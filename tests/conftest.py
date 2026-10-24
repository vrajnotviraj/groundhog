import mongomock
import pytest

from groundhog import db, events


@pytest.fixture(autouse=True)
def in_memory_mongo(monkeypatch):
    """Every test gets its own empty in-memory database; nothing reaches a real Mongo."""
    monkeypatch.setattr(db, "_client", mongomock.MongoClient("mongodb://localhost:27017/groundhog-test"))
    monkeypatch.setattr(events, "_run_id", None)
