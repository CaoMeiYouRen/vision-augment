import builtins
from pathlib import Path

from vision_augment import health
from vision_augment.config import Settings
from vision_augment.vision import ollama


def make_settings(**overrides) -> Settings:
    defaults = {
        "channels": [],
        "ollama_url": "http://127.0.0.1:11434",
        "ollama_timeout_seconds": 1.0,
        "cache_dir": Path("."),
        "cache_ttl_seconds": 86400,
        "request_timeout_seconds": 5.0,
        "max_input_mb": 50,
        "max_output_chars": 20000,
        "allow_urls": False,
        "debug": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_health_shape_with_ollama(monkeypatch):
    channel = ollama.VisionChannel(base_url="http://127.0.0.1:11434", model="llava:latest")
    monkeypatch.setattr(ollama, "probe_ollama", lambda *a, **k: channel)
    report = health.check(make_settings())
    assert report["version"]
    assert report["transport"] == "stdio"
    assert report["channels"] == []
    assert report["ollama"]["reachable"] is True
    assert report["ollama"]["model"] == "llava:latest"
    assert report["ocr_engine"]["available"] is False
    assert "uvx vision-augment[ocr]" in report["ocr_engine"]["hint"]
    assert report["document_engine"]["available"] is False
    assert "uvx vision-augment[document]" in report["document_engine"]["hint"]
    assert report["cache"]["ttl_seconds"] == 86400
    assert report["input_limits"]["max_input_mb"] == 50


def test_health_channels_without_keys(monkeypatch):
    monkeypatch.setattr(ollama, "probe_ollama", lambda *a, **k: None)
    settings = make_settings(
        channels=[
            ollama.VisionChannel(
                base_url="https://api.example.com/v1", model="qwen3.7-plus", api_key="sk-secret"
            )
        ]
    )
    report = health.check(settings)
    assert report["ollama"]["reachable"] is False
    assert report["ollama"]["model"] is None
    assert report["channels"][0]["model"] == "qwen3.7-plus"
    assert "sk-secret" not in str(report)


def test_engine_status_available(monkeypatch):
    original_import = builtins.__import__
    fake_module = type("FakeModule", (), {})()

    def fake_import(name, *args, **kwargs):
        if name in health._ENGINE_HINTS:
            return fake_module
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    for module in health._ENGINE_HINTS:
        status = health._engine_status(module)
        assert status == {"available": True}
