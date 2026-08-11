import time

from vision_augment.cache import TTLCache


def test_roundtrip(tmp_path):
    cache = TTLCache(tmp_path, ttl_seconds=60)
    assert cache.get("k") is None
    cache.set("k", "v")
    assert cache.get("k") == "v"


def test_disabled_when_ttl_zero(tmp_path):
    cache = TTLCache(tmp_path, ttl_seconds=0)
    cache.set("k", "v")
    assert cache.get("k") is None


def test_expiry(tmp_path, monkeypatch):
    cache = TTLCache(tmp_path, ttl_seconds=10)
    cache.set("k", "v")
    original = time.time
    monkeypatch.setattr(time, "time", lambda: original() + 11)
    assert cache.get("k") is None


def test_clear(tmp_path):
    cache = TTLCache(tmp_path, ttl_seconds=60)
    cache.set("a", "1")
    cache.set("b", "2")
    scratch = tmp_path / ".123.456.tmp"
    scratch.write_text("x")
    materialized_dir = tmp_path / "tmp"
    materialized_dir.mkdir()
    materialized = materialized_dir / "materialized.png"
    materialized.write_bytes(b"x")
    assert cache.clear() == 4
    assert cache.clear() == 0
    assert not scratch.exists()
    assert not materialized.exists()
