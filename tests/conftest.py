"""Test setup. settings.py reads the environment once at import, so set it before importing the app,
and give every test a fresh database."""
import hashlib
import os
import secrets
import shutil
import sys
import tempfile
import types

import pytest

DATA = tempfile.mkdtemp(prefix="gift-exchange-test-")


def _scrypt(pw, salt=b"\x01" * 16):
    """The encoded form `scrypt$<salt hex>$<hash hex>` (n=2**14, r=8, p=1). access.hash_password (Task 3) writes the same."""
    return f"scrypt${salt.hex()}${hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1).hex()}"


os.environ.update(DATA_DIR=DATA, ADMIN_PASSWORD_HASH=_scrypt("admin-pass"))
for name in ("EXCHANGE_PORT", "APP_NAME", "SECRET_KEY"):
    os.environ.pop(name, None)  # test the defaults
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import access  # noqa: E402
import app as exchange  # noqa: E402
import common  # noqa: E402
import db  # noqa: E402
import settings  # noqa: E402

ORIGIN = "http://localhost"  # the Flask test client's host


def mut(**extra):
    """Headers a legitimate browser mutation carries: `client.post(url, json=..., headers=mut())`."""
    return {"X-Exchange": "1", "Origin": ORIGIN, **extra}


@pytest.fixture(autouse=True)
def fresh_db():
    """Every test starts from an empty, migrated database."""
    for name in os.listdir(DATA):
        path = os.path.join(DATA, name)
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    exchange.init_db()


@pytest.fixture
def client():
    return exchange.app.test_client()


@pytest.fixture
def con():
    c = db.connect(settings.DB_PATH)
    yield c
    c.close()


@pytest.fixture
def seed(con):
    """One exchange with one edition and three people: seed.ex, seed.ed, seed.a, seed.b, seed.c (all ids)."""
    ex = con.execute("INSERT INTO exchange (slug, name, password_hash, link_token) VALUES "
                     "('family', 'Family', 'x', 'tok')").lastrowid
    ed = con.execute("INSERT INTO edition (exchange_id, label, year, created_at) VALUES (?, '2026', 2026, 0)", (ex,)).lastrowid
    a, b, c = (con.execute("INSERT INTO person (exchange_id, name) VALUES (?, ?)", (ex, n)).lastrowid
               for n in ("Alex", "Sam", "Jordan"))
    return types.SimpleNamespace(ex=ex, ed=ed, a=a, b=b, c=c)


class Clock:
    """A frozen common.now() that tests move forward with advance(seconds). The cookie signers read it too."""

    def __init__(self, t=1_800_000_000):
        self.t = t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(common, "now", lambda: c.t)
    return c


def mk_exchange(con, slug, password, active=1, sort_order=0):
    """An exchange with this password (hashed by access.hash_password) and a fresh link token. Returns its id."""
    return con.execute("INSERT INTO exchange (slug, name, password_hash, link_token, active, sort_order) "
                       "VALUES (?, ?, ?, ?, ?, ?)",
                       (slug, slug.title(), access.hash_password(password), secrets.token_urlsafe(16), active,
                        sort_order)).lastrowid


def token_of(con, exchange_id):
    """The exchange's share-link token, for /x/<slug>/join/<token>."""
    return con.execute("SELECT link_token FROM exchange WHERE id = ?", (exchange_id,)).fetchone()[0]


@pytest.fixture
def admin(client):
    """The test client, logged in as admin, with `mut()`'s headers on every request it makes."""
    client.environ_base.update(HTTP_X_EXCHANGE="1", HTTP_ORIGIN=ORIGIN)
    assert client.post("/api/admin/login", json={"password": "admin-pass"}).status_code == 200
    return client


@pytest.fixture
def x(con):
    """An exchange 'family' with people x.alex, x.sam, x.jordan (ids) and no edition. x.id is the exchange id."""
    xid = mk_exchange(con, "family", "pw12")
    ids = {n: con.execute("INSERT INTO person (exchange_id, name) VALUES (?, ?)", (xid, n.title())).lastrowid
           for n in ("alex", "sam", "jordan")}
    return types.SimpleNamespace(id=xid, **ids)


def mk_edition(admin, exchange_id, year, **extra):
    """Creates an edition through the admin API and returns its id."""
    r = admin.post(f"/api/admin/exchanges/{exchange_id}/editions", json={"year": year, **extra})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def put_roster(admin, edition_id, person_ids):
    r = admin.put(f"/api/admin/editions/{edition_id}/roster", json={"person_ids": list(person_ids)})
    assert r.status_code == 200, r.get_json()
    return r


def roster_ids(con, edition_id):
    return {r[0] for r in con.execute("SELECT person_id FROM edition_people WHERE edition_id = ?", (edition_id,))}
