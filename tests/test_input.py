import base64
from pathlib import Path

import pytest

from vision_augment.config import Settings
from vision_augment.envelope import InvalidInputError
from vision_augment.input import ensure_local_file, resolve_source


def make_settings(**overrides) -> Settings:
    defaults = {
        "channels": [],
        "ollama_url": "http://127.0.0.1:11434",
        "ollama_timeout_seconds": 1.0,
        "cache_dir": Path("."),
        "cache_ttl_seconds": 60,
        "request_timeout_seconds": 5.0,
        "max_input_mb": 10,
        "max_output_chars": 1000,
        "allow_urls": False,
        "debug": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_data_url(tmp_path):
    payload = base64.b64encode(b"\x89PNG").decode()
    src = resolve_source(f"data:image/png;base64,{payload}", make_settings(cache_dir=tmp_path))
    assert src.data == b"\x89PNG"
    assert src.mime == "image/png"
    assert src.local_path is None


def test_local_path(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"abc")
    src = resolve_source(str(f), make_settings(cache_dir=tmp_path))
    assert src.data == b"abc"
    assert src.mime == "image/png"
    assert src.local_path == f


def test_missing_file():
    with pytest.raises(InvalidInputError, match="cannot read file"):
        resolve_source("C:/no/such/file.png", make_settings())


def test_url_disabled_by_default(tmp_path):
    with pytest.raises(InvalidInputError, match="disabled by default"):
        resolve_source("http://example.com/a.png", make_settings(cache_dir=tmp_path))


def test_url_fetch_failure(tmp_path):
    with pytest.raises(InvalidInputError, match="failed to fetch"):
        resolve_source("http://127.0.0.1:1/x.png", make_settings(allow_urls=True, cache_dir=tmp_path))


def test_size_limit(tmp_path):
    settings = make_settings(max_input_mb=1, cache_dir=tmp_path)
    payload = base64.b64encode(b"x" * (1024 * 1024 + 1)).decode()
    with pytest.raises(InvalidInputError, match="MB limit"):
        resolve_source(f"data:application/octet-stream;base64,{payload}", settings)


def test_unsupported_scheme(tmp_path):
    with pytest.raises(InvalidInputError, match="unsupported source scheme"):
        resolve_source("ftp://example.com/a.png", make_settings(cache_dir=tmp_path))


def test_ensure_local_file_reuses_path(tmp_path):
    f = tmp_path / "doc.docx"
    f.write_bytes(b"x")
    src = resolve_source(str(f), make_settings(cache_dir=tmp_path))
    assert ensure_local_file(src, tmp_path) == f


def test_ensure_local_file_materializes_bytes(tmp_path):
    src = resolve_source(f"data:image/png;base64,{base64.b64encode(b'x').decode()}", make_settings(cache_dir=tmp_path))
    path = ensure_local_file(src, tmp_path)
    assert path.exists()
    assert path.read_bytes() == b"x"
    assert ensure_local_file(src, tmp_path) == path
