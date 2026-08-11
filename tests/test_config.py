import pytest

from vision_augment.config import load_settings


def test_transport_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("VISION_AUGMENT_CACHE_DIR", str(tmp_path))
    settings = load_settings()
    assert settings.transport == "stdio"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000


def test_transport_http_env(monkeypatch, tmp_path):
    monkeypatch.setenv("VISION_AUGMENT_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("VISION_AUGMENT_TRANSPORT", "streamable-http")
    monkeypatch.setenv("VISION_AUGMENT_HOST", "0.0.0.0")
    monkeypatch.setenv("VISION_AUGMENT_PORT", "9001")
    settings = load_settings()
    assert settings.transport == "streamable-http"
    assert settings.host == "0.0.0.0"
    assert settings.port == 9001


def test_transport_invalid(monkeypatch, tmp_path):
    monkeypatch.setenv("VISION_AUGMENT_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("VISION_AUGMENT_TRANSPORT", "webrtc")
    with pytest.raises(ValueError, match="VISION_AUGMENT_TRANSPORT"):
        load_settings()
