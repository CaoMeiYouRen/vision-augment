"""Task routing: task_type (reasoning | ocr | document) → provider chain → envelope.

Fixes ds-vision P1-① (task routing breaks): routing happens on task_type at the
entry, each task maps to exactly one provider chain, and the envelope always
carries task_type + tool_used so callers know what actually ran.
"""

from __future__ import annotations

import json
from typing import Any

from .cache import TTLCache
from .config import Settings
from .document import markitdown as document_provider
from .envelope import (
    InternalError,
    InvalidInputError,
    VisionAugmentError,
    err,
    ok,
)
from .input import resolve_source
from .ocr import rapidocr as ocr_provider
from .vision import client as vision_client

TASK_TYPES = ("reasoning", "ocr", "document")


class Router:
    def __init__(self, settings: Settings, cache: TTLCache) -> None:
        self.settings = settings
        self.cache = cache

    def run(self, task_type: str, source: str, task: str = "", language: str = "ch") -> dict[str, Any]:
        if task_type not in TASK_TYPES:
            return err(task_type, InvalidInputError(
                f"unknown task_type {task_type!r}; expected one of {TASK_TYPES}"
            ))
        try:
            if task_type == "reasoning":
                return self._reasoning(source, task)
            if task_type == "ocr":
                return self._ocr(source, language)
            return self._document(source)
        except VisionAugmentError as exc:
            return err(task_type, exc)
        except Exception as exc:  # noqa: BLE001 -- never leak raw exceptions to the client
            return err(task_type, InternalError(f"{type(exc).__name__}: {exc}"))

    def _reasoning(self, source: str, task: str) -> dict[str, Any]:
        src = resolve_source(source, self.settings)
        cache_key = f"reasoning:{src.sha256}:{task}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return self._from_cache(json.loads(cached))
        result = vision_client.describe_image(self.settings.channels, src, task, self.settings)
        text, truncated = self._cap(result.text)
        body = ok(
            task_type="reasoning",
            tool_used=f"vision:{result.channel.name}",
            result=text,
            confidence=result.confidence,
            metadata={
                "channel": result.channel.name,
                "model": result.channel.model,
                "latency_ms": result.latency_ms,
                "cache_hit": False,
                "truncated": truncated,
            },
        )
        self._store(cache_key, body)
        return body

    def _ocr(self, source: str, language: str) -> dict[str, Any]:
        src = resolve_source(source, self.settings)
        cache_key = f"ocr:{src.sha256}:{language}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return self._from_cache(json.loads(cached))
        text, confidence = ocr_provider.run(src, language, self.settings)
        body = ok(
            task_type="ocr",
            tool_used=f"local:{ocr_provider.NAME}",
            result=text,
            confidence=confidence,
            metadata={"cache_hit": False},
        )
        self._store(cache_key, body)
        return body

    def _document(self, source: str) -> dict[str, Any]:
        src = resolve_source(source, self.settings)
        cache_key = f"document:{src.sha256}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return self._from_cache(json.loads(cached))
        text, confidence = document_provider.run(src, self.settings)
        text, truncated = self._cap(text)
        body = ok(
            task_type="document",
            tool_used=f"local:{document_provider.NAME}",
            result=text,
            confidence=confidence,
            metadata={"cache_hit": False, "truncated": truncated},
        )
        self._store(cache_key, body)
        return body

    def _cap(self, text: str) -> tuple[str, bool]:
        if len(text) > self.settings.max_output_chars:
            return text[: self.settings.max_output_chars], True
        return text, False

    def _store(self, cache_key: str, body: dict[str, Any]) -> None:
        self.cache.set(cache_key, json.dumps(body, ensure_ascii=False))

    @staticmethod
    def _from_cache(body: dict[str, Any]) -> dict[str, Any]:
        body["metadata"] = dict(body.get("metadata", {}))
        body["metadata"]["cache_hit"] = True
        body["metadata"]["latency_ms"] = 0
        return body
