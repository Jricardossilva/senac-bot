"""MySQLStorage com conexão falsa (sem servidor MySQL): SQL parametrizado, cache, falha do banco e EventStore sobre ele."""
import pytest

from backend.eventkb import EventStore, EventStoreError
from backend.eventkb.storage import MySQLStorage, StorageError


class FakeDB:
    def __init__(self):
        self.rows: dict[str, tuple[str, str]] = {}
        self.down = False
        self.queries: list[tuple[str, tuple]] = []

    def connect(self):
        if self.down:
            raise OSError("host=secreto.exemplo senha=abc")
        return FakeConn(self)


class FakeConn:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        return FakeCursor(self.db)

    def close(self):
        pass


class FakeCursor:
    def __init__(self, db):
        self.db, self.result = db, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=()):
        self.db.queries.append((sql, args))
        if sql.startswith("INSERT"):
            key, event_id, body = args
            self.db.rows[key] = (event_id, body)
        elif sql.startswith("SELECT body"):
            self.result = [(self.db.rows[args[0]][1],)] if args[0] in self.db.rows else []
        elif sql.startswith("SELECT event_id"):
            self.result = [(e,) for k, (e, _) in sorted(self.db.rows.items()) if k == f"{e}/event.json"]

    def fetchall(self):
        return self.result


@pytest.fixture
def db():
    return FakeDB()


def make(db, cache=0.0):
    return MySQLStorage("h", 3306, "d", "u", "p", cache_seconds=cache, connect=db.connect)


def test_event_store_roundtrip_in_mysql(db, tmp_path):
    store = EventStore(tmp_path / "x", make(db))
    event = store.create({"name": "Feira Teste", "area": "tec", "description": "d", "start_date": "2026-01-01", "end_date": "2026-01-02"})
    assert [e.id for e in store.list_events()] == [event.id]
    store.set_active_id(event.id)
    assert store.active_id() == event.id
    again = EventStore(tmp_path / "y", make(db))  # nova instância (reinício do Render): dados continuam
    assert again.get(event.id).name == "Feira Teste" and again.active_id() == event.id
    assert not (tmp_path / "x" / event.id).exists()  # nada foi gravado em disco


def test_unique_ids_and_unicode(db, tmp_path):
    store = EventStore(tmp_path, make(db))
    data = {"name": "Feira", "area": "á", "description": "ção ✓", "start_date": "2026-01-01", "end_date": "2026-01-01"}
    a, b = store.create(data), store.create(data)
    assert a.id != b.id and store.get(a.id).description == "ção ✓"


def test_queries_are_parameterized(db):
    storage = make(db)
    storage.write("e/event.json", {"id": "e"})
    storage.read("e/event.json'; DROP TABLE x;--")
    for sql, args in db.queries:
        assert "DROP" not in sql and "e/event.json" not in sql


def test_read_uses_stale_cache_when_db_down(db):
    storage = make(db, cache=0.0)
    storage.write("a/event.json", {"id": "a"})
    db.down = True
    assert storage.read("a/event.json") == {"id": "a"}  # último valor conhecido
    with pytest.raises(StorageError):
        storage.read("outro/event.json")


def test_write_fails_loudly_and_hides_credentials(db, tmp_path):
    storage = make(db)
    db.down = True
    with pytest.raises(StorageError) as info:
        storage.write("a/event.json", {})
    assert "secreto" not in str(info.value) and "abc" not in str(info.value)
    store = EventStore(tmp_path, storage)
    with pytest.raises(EventStoreError) as err:
        store.set_active_id("a")
    assert err.value.status == 503


def test_cache_avoids_repeated_queries(db):
    storage = make(db, cache=60)
    storage.write("a/event.json", {"id": "a"})
    n = len(db.queries)
    for _ in range(5):
        storage.read("a/event.json")
    assert len(db.queries) == n
