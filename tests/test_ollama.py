import httpx
import pytest

from vision_augment.vision import ollama


@pytest.fixture(autouse=True)
def _reset_probe_cache():
    ollama._probe_cache = None
    yield
    ollama._probe_cache = None


def test_probe_failure_is_cached(monkeypatch):
    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(ollama.httpx, "get", boom)
    assert ollama.probe_ollama("http://127.0.0.1:1", 0.5) is None
    assert ollama.probe_ollama("http://127.0.0.1:1", 0.5) is None
    assert calls["n"] == 1


def test_probe_hit_is_cached(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "qwen3"}, {"name": "llava:latest"}]}

    calls = {"n": 0}

    def fake_get(*args, **kwargs):
        calls["n"] += 1
        return FakeResponse()

    monkeypatch.setattr(ollama.httpx, "get", fake_get)
    channel = ollama.probe_ollama("http://127.0.0.1:11434", 0.5)
    assert channel is not None
    assert channel.model == "llava:latest"
    ollama.probe_ollama("http://127.0.0.1:11434", 0.5)
    assert calls["n"] == 1


def test_probe_skips_non_vision_models(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "qwen3"}, {"name": "deepseek-r1"}]}

    monkeypatch.setattr(ollama.httpx, "get", lambda *a, **k: FakeResponse())
    assert ollama.probe_ollama("http://127.0.0.1:11434", 0.5) is None
