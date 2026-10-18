"""Slow status probes must not add school-network latency to browser input."""
import threading
from concurrent.futures import ThreadPoolExecutor

from app import pmss_connection_api as target


def test_probe_does_not_block_input_invalidation_or_duplicate_school_io(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, limit):
            return b'{"retCode":"T200"}'

    def slow_school(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return Response()

    monkeypatch.setattr(target, "urlopen", slow_school)
    monkeypatch.setattr(target, "_PROBE_CACHE", (0.0, "unknown"))
    monkeypatch.setattr(target, "_PROBE_RUNNING", False)
    monkeypatch.setattr(target, "_PROBE_REVISION", 0)
    with ThreadPoolExecutor(max_workers=3) as pool:
        probe = pool.submit(target._probe_bridge)
        try:
            assert entered.wait(1)
            # Would time out if the slow HTTP request still held the lock.
            pool.submit(target._invalidate_probe_cache).result(timeout=0.5)
            assert pool.submit(target._probe_bridge).result(timeout=0.5) == "unknown"
            assert calls == [1]
        finally:
            release.set()
        assert probe.result(timeout=1) == "authorized"
    # A probe started before the input must not repopulate its invalidated cache.
    assert target._PROBE_CACHE == (0.0, "unknown")
    assert target._PROBE_RUNNING is False
