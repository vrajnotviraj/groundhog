"""The Mongo collections: cases, flows, runs, screenshots, users and sessions. Connects on first use."""

from pymongo import ASCENDING, DESCENDING, MongoClient

from groundhog import config

_client: MongoClient | None = None


def database():
    global _client
    if _client is None:
        _client = MongoClient(config.MONGO_URL, serverSelectionTimeoutMS=3000)
    return _client.get_default_database("groundhog")


def cases():
    return database()["cases"]


def flows():
    return database()["flows"]


def runs():
    return database()["runs"]


def shots():
    return database()["shots"]


def users():
    return database()["users"]


def sessions():
    return database()["sessions"]


def ping() -> bool:
    """True when Mongo answers."""
    try:
        database().command("ping")
        return True
    except Exception:
        return False


def ensure_indexes() -> None:
    runs().create_index([("created_at", DESCENDING)])
    runs().create_index([("target", ASCENDING), ("created_at", DESCENDING)])
    shots().create_index([("run_id", ASCENDING), ("seq", ASCENDING)], unique=True)
    users().create_index("email", unique=True)
    sessions().create_index("expires_at", expireAfterSeconds=0)
