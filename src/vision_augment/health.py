"""Environment probe: reports what is configured/available so agents can tell
the user exactly what setup is still missing (auto-configuration guidance).

Never includes secrets (api_key is omitted from channel info).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from .config import Settings
from .vision import ollama

_ENGINE_HINTS = {
    "rapidocr_onnxruntime": "uvx vision-augment[ocr]",
    "markitdown": "uvx vision-augment[document]",
}


def _pkg_version_or_default() -> str:
    try:
        return _pkg_version("vision-augment")
    except PackageNotFoundError:
        return "unknown"


def _engine_status(module: str) -> dict:
    try:
        __import__(module)
    except ImportError:
        return {"available": False, "hint": f"install extra: {_ENGINE_HINTS[module]}"}
    return {"available": True}


def check(settings: Settings) -> dict:
    """Probe the runtime environment and return a JSON-safe status report."""
    ollama_channel = ollama.probe_ollama(settings.ollama_url, settings.ollama_timeout_seconds)
    return {
        "version": _pkg_version_or_default(),
        "transport": settings.transport,
        "channels": [
            {"name": channel.name, "base_url": channel.base_url, "model": channel.model}
            for channel in settings.channels
        ],
        "ollama": {
            "reachable": ollama_channel is not None,
            "url": settings.ollama_url,
            "model": ollama_channel.model if ollama_channel is not None else None,
        },
        "ocr_engine": _engine_status("rapidocr_onnxruntime"),
        "document_engine": _engine_status("markitdown"),
        "cache": {"dir": str(settings.cache_dir), "ttl_seconds": settings.cache_ttl_seconds},
        "input_limits": {
            "max_input_mb": settings.max_input_mb,
            "max_output_chars": settings.max_output_chars,
        },
    }
