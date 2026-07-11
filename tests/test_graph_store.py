import neo4j as neo4j_module
import pytest


class _FakeDriver:
    def __init__(self):
        self.verify_calls = 0
        self.closed = False

    def verify_connectivity(self):
        self.verify_calls += 1

    def close(self):
        self.closed = True


def _reset(monkeypatch):
    from groundhog.graph import store

    monkeypatch.setattr(store, "_driver", None)
    monkeypatch.setattr(store, "_unavailable", None)


def test_driver_failure_is_cached_and_reraised_without_reconnecting(monkeypatch):
    from groundhog.graph import store

    _reset(monkeypatch)
    calls = []

    class FakeGraphDatabase:
        @staticmethod
        def driver(uri, **kwargs):
            calls.append(kwargs)
            raise ConnectionError("refused")

    monkeypatch.setattr(neo4j_module, "GraphDatabase", FakeGraphDatabase)

    with pytest.raises(ConnectionError):
        store.driver()
    with pytest.raises(ConnectionError):
        store.driver()

    assert len(calls) == 1  # second call didn't re-attempt the connection


def test_successful_driver_is_reused_not_reconnected(monkeypatch):
    from groundhog.graph import store

    _reset(monkeypatch)
    calls = []
    fake = _FakeDriver()

    class FakeGraphDatabase:
        @staticmethod
        def driver(uri, **kwargs):
            calls.append(kwargs)
            return fake

    monkeypatch.setattr(neo4j_module, "GraphDatabase", FakeGraphDatabase)

    d1 = store.driver()
    d2 = store.driver()

    assert d1 is d2 is fake
    assert len(calls) == 1
    assert fake.verify_calls == 1


def test_driver_construction_passes_bounded_timeouts_and_silences_notifications(monkeypatch):
    from groundhog.graph import store

    _reset(monkeypatch)
    captured = {}

    class FakeGraphDatabase:
        @staticmethod
        def driver(uri, **kwargs):
            captured.update(kwargs)
            return _FakeDriver()

    monkeypatch.setattr(neo4j_module, "GraphDatabase", FakeGraphDatabase)

    store.driver()

    # library defaults are ~30s; a down/hung Neo4j must fail in a few seconds
    assert 0 < captured.get("connection_timeout", 999) <= 10
    assert 0 < captured.get("max_transaction_retry_time", 999) <= 10
    # coverage gaps (no Feature nodes yet) are normal — server shouldn't emit
    # notifications that land as warnings in the CLI
    assert captured.get("notifications_min_severity") == "OFF"
