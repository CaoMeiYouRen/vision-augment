"""Local Ollama probing — the no-key default vision channel.

Probe results are cached for a short TTL so a stopped Ollama does not add a
timeout penalty to every reasoning call (default probe timeout is 5s).
"""

from __future__ import annotations

import time

import httpx

from ..config import VisionChannel

# Substrings used to detect vision-language models in `ollama list`.
_VL_MARKERS = ("llava", "vision", "-vl", "minicpm", "moondream", "gemma3")

# Cache probe result for this long; a benign race may re-probe concurrently.
_PROBE_CACHE_TTL_SECONDS = 30.0

_probe_cache: tuple[float, VisionChannel | None] | None = None


def probe_ollama(base_url: str, timeout_seconds: float) -> VisionChannel | None:
    """Return a channel for the first vision-capable model on a running Ollama.

    Returns None when Ollama is unreachable or has no vision model — callers
    treat that as "no fallback", never as an error.
    """
    global _probe_cache
    now = time.time()
    if _probe_cache is not None and now - _probe_cache[0] < _PROBE_CACHE_TTL_SECONDS:
        return _probe_cache[1]

    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=timeout_seconds)
        response.raise_for_status()
        names = [model.get("name", "") for model in response.json().get("models", [])]
    except (httpx.HTTPError, ValueError, KeyError):
        channel = None
    else:
        channel = next(
            (
                VisionChannel(base_url=base_url, model=name)
                for name in names
                if any(marker in name.lower() for marker in _VL_MARKERS)
            ),
            None,
        )
    _probe_cache = (now, channel)
    return channel
