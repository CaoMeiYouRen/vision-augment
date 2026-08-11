"""Configuration for vision-augment.

All settings come from environment variables (VISION_AUGMENT_* prefix) so the
server stays 12-factor friendly: no config files, no secrets in code.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env_str(name)
    if not raw:
        return default
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_str(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class VisionChannel:
    """One OpenAI-compatible vision endpoint.

    Borrowed from luma-mcp's custom-provider design: base_url + api_key + model
    triple, with optional per-channel timeout and extra headers. Any number of
    channels may be configured; they are tried in order (downgrade chain).
    """

    base_url: str
    model: str
    api_key: str = ""
    timeout_seconds: float = 60.0
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"{self.model}@{self.base_url}"


@dataclass(slots=True)
class Settings:
    channels: list[VisionChannel]
    ollama_url: str
    ollama_timeout_seconds: float
    cache_dir: Path
    cache_ttl_seconds: int
    request_timeout_seconds: float
    max_input_mb: int
    max_output_chars: int
    allow_urls: bool
    debug: bool
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000


_TRANSPORTS = ("stdio", "streamable-http")


def load_settings() -> Settings:
    """Build Settings from the environment. Fails fast on malformed input."""
    channels: list[VisionChannel] = []
    raw_channels = _env_str("VISION_AUGMENT_CHANNELS")
    if raw_channels:
        try:
            items = json.loads(raw_channels)
        except json.JSONDecodeError as exc:
            raise ValueError("VISION_AUGMENT_CHANNELS must be a JSON array") from exc
        if not isinstance(items, list):
            raise ValueError("VISION_AUGMENT_CHANNELS must be a JSON array")
        for item in items:
            channels.append(VisionChannel(**item))

    transport = _env_str("VISION_AUGMENT_TRANSPORT", "stdio")
    if transport not in _TRANSPORTS:
        raise ValueError(f"VISION_AUGMENT_TRANSPORT must be one of {_TRANSPORTS}")

    return Settings(
        channels=channels,
        ollama_url=_env_str("VISION_AUGMENT_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        ollama_timeout_seconds=float(_env_int("VISION_AUGMENT_OLLAMA_TIMEOUT_SECONDS", 5)),
        cache_dir=Path(
            _env_str("VISION_AUGMENT_CACHE_DIR", str(Path.home() / ".cache" / "vision-augment"))
        ),
        cache_ttl_seconds=_env_int("VISION_AUGMENT_CACHE_TTL_SECONDS", 86400),
        request_timeout_seconds=float(_env_int("VISION_AUGMENT_TIMEOUT_SECONDS", 60)),
        max_input_mb=_env_int("VISION_AUGMENT_MAX_INPUT_MB", 50),
        max_output_chars=_env_int("VISION_AUGMENT_MAX_OUTPUT_CHARS", 20000),
        allow_urls=_env_bool("VISION_AUGMENT_ALLOW_URLS", False),
        debug=_env_bool("VISION_AUGMENT_DEBUG", False),
        transport=transport,
        host=_env_str("VISION_AUGMENT_HOST", "127.0.0.1"),
        port=_env_int("VISION_AUGMENT_PORT", 8000),
    )
