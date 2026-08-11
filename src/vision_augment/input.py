"""Source normalization: turn user input into bytes + mime + identity.

Accepted forms:

- local file path (absolute or relative to the server's working directory)
- ``file://`` URL
- ``http(s)://`` URL — opt-in via ``VISION_AUGMENT_ALLOW_URLS=true``
  (SSRF guard: fetching remote URLs is off by default, aligning with the
  project's local-first positioning)
- ``data:`` URL with a base64 payload

The sha256 identity feeds the result cache; the size limit guards the process
from huge inputs.
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from .config import Settings
from .envelope import InvalidInputError


@dataclass(slots=True)
class Source:
    data: bytes
    mime: str
    sha256: str
    origin: str
    local_path: Path | None = None


def resolve_source(source: str, settings: Settings) -> Source:
    """Resolve a user-supplied source into normalized bytes. Raises on any problem."""
    max_bytes = settings.max_input_mb * 1024 * 1024
    parsed = urlparse(source)

    if parsed.scheme == "data":
        header, _, payload = source.partition(",")
        mime = header.removeprefix("data:").split(";")[0] or "application/octet-stream"
        if len(payload) > max_bytes * 4 / 3 + 8:
            raise InvalidInputError(f"source exceeds the {settings.max_input_mb} MB limit")
        try:
            data = base64.b64decode(payload)
        except ValueError as exc:
            raise InvalidInputError("invalid data: URL payload") from exc
        origin = "data:url"

    elif parsed.scheme in {"http", "https"}:
        if not settings.allow_urls:
            raise InvalidInputError(
                "URL input is disabled by default; set VISION_AUGMENT_ALLOW_URLS=true or pass a local path"
            )
        try:
            with (
                httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True) as client,
                client.stream("GET", source) as response,
            ):
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise InvalidInputError(f"source exceeds the {settings.max_input_mb} MB limit")
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    mime = response.headers.get("content-type", "").split(";")[0] or "application/octet-stream"
        except httpx.HTTPError as exc:
            raise InvalidInputError(f"failed to fetch URL: {exc}") from exc
        origin = source

    else:
        # Local path: no scheme, file://, or a Windows drive letter (urlparse
        # would read "C:" as scheme, so accept single-letter schemes too).
        is_local = parsed.scheme in {"", "file"} or len(parsed.scheme) == 1
        if not is_local:
            raise InvalidInputError(
                f"unsupported source scheme {parsed.scheme!r}; expected local path, file://, http(s):// or data:"
            )
        path = Path(unquote(parsed.path)) if parsed.scheme == "file" else Path(source)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise InvalidInputError(f"cannot read file {path}: {exc}") from exc
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        origin = str(path)

    if not data:
        raise InvalidInputError("source is empty")
    if len(data) > max_bytes:
        raise InvalidInputError(f"source exceeds the {settings.max_input_mb} MB limit")

    return Source(
        data=data,
        mime=mime,
        sha256=hashlib.sha256(data).hexdigest(),
        origin=origin,
        local_path=path if parsed.scheme in {"", "file"} or len(parsed.scheme) == 1 else None,
    )


def ensure_local_file(source: Source, cache_dir: Path) -> Path:
    """Return a local path for engines that only accept files (OCR/document).

    Path-based sources are reused as-is; bytes-only sources (data:/URL) are
    materialized under ``<cache_dir>/tmp`` with a content-derived name.
    """
    if source.local_path is not None:
        return source.local_path

    tmp_dir = cache_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(source.origin).suffix or (mimetypes.guess_extension(source.mime) or ".bin")
    target = tmp_dir / f"{source.sha256}{ext}"
    if not target.exists():
        scratch = tmp_dir / f".{source.sha256}.{os.getpid()}.tmp"
        scratch.write_bytes(source.data)
        os.replace(scratch, target)
    return target
