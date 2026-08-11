import base64
from pathlib import Path

from vision_augment import router as router_module
from vision_augment.cache import TTLCache
from vision_augment.config import Settings
from vision_augment.envelope import ChannelFailedError, DependencyMissingError
from vision_augment.router import Router
from vision_augment.vision.client import VisionResult

DATA_URL = f"data:image/png;base64,{base64.b64encode(b'fake-png').decode()}"


def make_settings(**overrides) -> Settings:
    defaults = {
        "channels": [],
        "ollama_url": "http://127.0.0.1:1",
        "ollama_timeout_seconds": 0.5,
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


def make_router(tmp_path: Path, **overrides) -> Router:
    settings = make_settings(**overrides)
    return Router(settings, TTLCache(tmp_path, settings.cache_ttl_seconds))


def test_unknown_task_type(tmp_path):
    body = make_router(tmp_path).run("hack", DATA_URL)
    assert body["code"] == 3
    assert body["task_type"] == "hack"
    assert "unknown task_type" in body["error"]


def test_invalid_source_is_invalid_input(tmp_path):
    body = make_router(tmp_path).run("ocr", "C:/no/such/file.png")
    assert body["code"] == 3
    assert body["metadata"]["error_type"] == "invalid_input"


def test_reasoning_all_channels_failed(monkeypatch, tmp_path):
    def boom(channels, source, task, settings):
        raise ChannelFailedError("no vision channels available")

    monkeypatch.setattr(router_module.vision_client, "describe_image", boom)
    body = make_router(tmp_path).run("reasoning", DATA_URL, "describe")
    assert body["code"] == 1
    assert "no vision channels" in body["error"]


def test_reasoning_success_and_cache(monkeypatch, tmp_path):
    class FakeChannel:
        name = "fake@x"
        model = "fake"

    def fake(channels, source, task, settings):
        return VisionResult(text="A cat", confidence=1.0, channel=FakeChannel(), latency_ms=5)

    monkeypatch.setattr(router_module.vision_client, "describe_image", fake)
    router = make_router(tmp_path)
    body = router.run("reasoning", DATA_URL, "describe")
    assert body["code"] == 0
    assert body["result"] == "A cat"
    assert body["tool_used"] == "vision:fake@x"
    assert body["metadata"]["cache_hit"] is False

    body2 = router.run("reasoning", DATA_URL, "describe")
    assert body2["code"] == 0
    assert body2["metadata"]["cache_hit"] is True
    assert body2["metadata"]["latency_ms"] == 0


def test_ocr_dependency_missing(monkeypatch, tmp_path):
    def boom(source, language, settings):
        raise DependencyMissingError("rapidocr-onnxruntime is not installed")

    monkeypatch.setattr(router_module.ocr_provider, "run", boom)
    body = make_router(tmp_path).run("ocr", DATA_URL, "ch")
    assert body["code"] == 4
    assert body["metadata"]["error_type"] == "dependency_missing"


def test_ocr_success(monkeypatch, tmp_path):
    def fake(source, language, settings):
        return "hello\nworld", 0.95

    monkeypatch.setattr(router_module.ocr_provider, "run", fake)
    body = make_router(tmp_path).run("ocr", DATA_URL, "ch")
    assert body["code"] == 0
    assert body["result"] == "hello\nworld"
    assert body["confidence"] == 0.95
    assert body["tool_used"] == "local:rapidocr"


def test_document_truncated(monkeypatch, tmp_path):
    def fake(source, settings):
        return "x" * 5000, 1.0

    monkeypatch.setattr(router_module.document_provider, "run", fake)
    router = make_router(tmp_path, max_output_chars=100)
    body = router.run("document", DATA_URL)
    assert body["code"] == 0
    assert len(body["result"]) == 100
    assert body["metadata"]["truncated"] is True


def test_internal_error_wrapped(monkeypatch, tmp_path):
    def boom(source, language, settings):
        raise RuntimeError("onnx crashed")

    monkeypatch.setattr(router_module.ocr_provider, "run", boom)
    body = make_router(tmp_path).run("ocr", DATA_URL, "ch")
    assert body["code"] == 5
    assert "RuntimeError" in body["error"]
