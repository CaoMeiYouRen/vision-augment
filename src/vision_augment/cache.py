"""Disk-backed TTL cache for tool results.

Fixes ds-vision P1-③ (unbounded cache accumulation): entries older than the
TTL are treated as misses and purged lazily; ``ttl_seconds=0`` disables
caching entirely. Writes are atomic (scratch file + ``os.replace``) so
concurrent MCP requests cannot corrupt entries.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path


class TTLCache:
    def __init__(self, directory: Path, ttl_seconds: int) -> None:
        self.directory = directory
        self.ttl_seconds = ttl_seconds

    def get(self, key: str) -> str | None:
        if self.ttl_seconds <= 0:
            return None
        path = self._path(key)
        try:
            if time.time() - path.stat().st_mtime > self.ttl_seconds:
                path.unlink(missing_ok=True)
                return None
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def set(self, key: str, value: str) -> None:
        if self.ttl_seconds <= 0:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        scratch = self.directory / f".{os.getpid()}.{abs(hash(path.name))}.tmp"
        scratch.write_text(value, encoding="utf-8")
        os.replace(scratch, path)

    def clear(self) -> int:
        if not self.directory.exists():
            return 0
        count = 0
        for path in self.directory.glob("*.json"):
            path.unlink(missing_ok=True)
            count += 1
        for path in self.directory.glob(".*.tmp"):
            path.unlink(missing_ok=True)
            count += 1
        tmp_dir = self.directory / "tmp"
        if tmp_dir.exists():
            for path in tmp_dir.iterdir():
                path.unlink(missing_ok=True)
                count += 1
        return count

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self.directory / f"{digest}.json"
