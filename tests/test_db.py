import importlib
import os
import sqlite3
import stat

import pytest

import db
import settings


def test_migrate_creates_every_table(con):
    names = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"meta","exchange","edition","person","edition_people","participant","pairing",
            "wish_item","profile_field","profile_value","login_failure"} <= names
    assert con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"


def test_migrate_is_idempotent(con):
    db.migrate(con); db.migrate(con)
    assert con.execute("SELECT COUNT(*) FROM meta WHERE key='schema_version'").fetchone()[0] == 1


def test_v1_database_upgrades_to_v2_keeping_its_rows(tmp_path):
    path = str(tmp_path / "v1.db")
    c = db.connect(path)
    with db.transaction(c):                       # a database as the v1 release made it
        db.MIGRATIONS[1](c)
        c.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '1')")
    c.execute("INSERT INTO exchange (id, slug, name, password_hash, link_token) VALUES (1, 'family', 'Family', 'h', 't')")
    c.execute("INSERT INTO edition (id, exchange_id, label, year, created_at) VALUES (1, 1, '2026', 2026, 5)")
    c.execute("INSERT INTO person (id, exchange_id, name) VALUES (1, 1, 'Sam')")
    c.execute("INSERT INTO wish_item (id, edition_id, person_id, title, url, note, sort_order, version, created_at, "
              "updated_at, updated_by) VALUES (7, 1, 1, 'Socks', 'https://example.com/s', 'blue', 3, 4, 5, 6, 'Alex')")
    assert "deleted_at" not in {r["name"] for r in c.execute("PRAGMA table_info(wish_item)")}
    db.migrate(c)
    assert c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(db.SCHEMA_VERSION) == "2"
    row = c.execute("SELECT * FROM wish_item").fetchone()
    assert dict(row) == {"id": 7, "edition_id": 1, "person_id": 1, "title": "Socks", "url": "https://example.com/s",
                         "note": "blue", "sort_order": 3, "version": 4, "created_at": 5, "updated_at": 6,
                         "updated_by": "Alex", "deleted_at": None}
    before = [tuple(r) for r in c.execute("SELECT * FROM sqlite_master ORDER BY name")]
    db.migrate(c)                                 # a second start changes nothing
    assert [tuple(r) for r in c.execute("SELECT * FROM sqlite_master ORDER BY name")] == before
    assert c.execute("SELECT COUNT(*) FROM wish_item").fetchone()[0] == 1
    c.close()


def test_fresh_database_has_deleted_at(con):
    assert "deleted_at" in {r["name"] for r in con.execute("PRAGMA table_info(wish_item)")}


def test_pairing_constraints(con, seed):                     # seed: one exchange, edition, people a, b, c
    ins = "INSERT INTO pairing VALUES (?,?,?)"
    con.execute(ins, (seed.ed, seed.a, seed.b))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(ins, (seed.ed, seed.a, seed.c))      # a giver twice
    # A draft may hold what Mark paired refuses (pairings.problems names it).
    con.execute(ins, (seed.ed, seed.c, seed.b))          # recipient twice
    con.execute(ins, (seed.ed, seed.b, seed.b))          # self


def test_healthz_is_open_and_bare(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.get_json() == {"ok": True}


def test_secret_key_file_is_0600(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SECRET_KEY", raising=False)
    try:
        s = importlib.reload(settings)
        path = tmp_path / "secret.key"
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert len(s.SECRET_KEY) == 32 and path.read_bytes() == s.SECRET_KEY
        assert importlib.reload(settings).SECRET_KEY == s.SECRET_KEY  # a second start keeps the key
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


def test_secret_key_from_env_writes_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "from-the-env")
    try:
        assert importlib.reload(settings).SECRET_KEY == b"from-the-env"
        assert not (tmp_path / "secret.key").exists()
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


def test_connect_sets_pragmas(con):
    assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_schema_decisions(con, seed):
    def cols(t):
        return {r["name"]: r for r in con.execute(f"PRAGMA table_info({t})")}
    assert "password_salt" not in cols("exchange")
    assert cols("participant")["version"]["dflt_value"] == "1" and cols("wish_item")["version"]["dflt_value"] == "1"
    assert cols("pairing")["recipient_id"]["notnull"] == 0
    con.execute("INSERT INTO pairing VALUES (?,?,NULL)", (seed.ed, seed.a))           # a draft row
    con.execute("INSERT INTO pairing VALUES (?,?,NULL)", (seed.ed, seed.b))           # NULLs never collide
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO edition (exchange_id, label, year, created_at) VALUES (?, 'x', 2026, 0)", (seed.ex,))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO person (exchange_id, name) VALUES (?, 'Alex')", (seed.ex,))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO login_failure VALUES ('other', 0)")
