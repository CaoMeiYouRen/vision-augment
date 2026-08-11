"""OpenAI-compatible vision channels.

Borrows luma-mcp's custom-provider design: each channel is a
base_url + api_key + model triple with its own timeout and extra headers.

Downgrade chain (fixes ds-vision P1-②, which had workers without timeouts):
configured channels in order → local Ollama VL probe as the final fallback.
A channel that times out or fails falls through to the next one; when every
channel fails, the last error is re-raised so the router can produce a
code-1/2 envelope.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import httpx

from ..config import Settings, VisionChannel
from ..envelope import ChannelFailedError, ChannelTimeoutError, VisionAugmentError
from ..input import Source
from .ollama import probe_ollama


@dataclass(slots=True)
class VisionResult:
    text: str
    confidence: float
    channel: VisionChannel
    latency_ms: int


def _channel_headers(channel: VisionChannel) -> dict[str, str]:
    headers = dict(channel.extra_headers)
    if channel.api_key:
        headers["Authorization"] = f"Bearer {channel.api_key}"
    return headers


def _call_channel(channel: VisionChannel, source: Source, task: str) -> VisionResult:
    started = time.perf_counter()
    url = f"{channel.base_url.rstrip('/')}/chat/completions"
    image_url = f"data:{source.mime or 'image/png'};base64,{base64.b64encode(source.data).decode('ascii')}"
    body = {
        "model": channel.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": task or "请描述这张图片的内容"},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
    }
    try:
        with httpx.Client(timeout=channel.timeout_seconds, headers=_channel_headers(channel)) as client:
            response = client.post(url, json=body)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not content:
                raise ChannelFailedError(f"channel {channel.name} returned empty content")
    except httpx.TimeoutException as exc:
        raise ChannelTimeoutError(
            f"channel {channel.name} timed out after {channel.timeout_seconds:.0f}s"
        ) from exc
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise ChannelFailedError(f"channel {channel.name} failed: {exc}") from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    return VisionResult(text=content, confidence=1.0, channel=channel, latency_ms=latency_ms)


def describe_image(
    channels: list[VisionChannel], source: Source, task: str, settings: Settings
) -> VisionResult:
    """Run the downgrade chain; raise the last channel error when all fail."""
    chain = [*channels]
    ollama_channel = probe_ollama(settings.ollama_url, settings.ollama_timeout_seconds)
    if ollama_channel is not None:
        chain.append(ollama_channel)

    last_error: VisionAugmentError | None = None
    for channel in chain:
        try:
            return _call_channel(channel, source, task)
        except VisionAugmentError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ChannelFailedError(
        "no vision channels available: set VISION_AUGMENT_CHANNELS "
        "(OpenAI-compatible endpoint) or run a local Ollama with a vision-language model"
    )
