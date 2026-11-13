"""Test setup. settings.py reads the environment once at import, so set it before importing the app,
and give every test a fresh database."""
import hashlib
import os
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

import app as exchange  # noqa: E402
import db  # noqa: E402
import settings  # noqa: E402

ORIGIN = "http://localhost"  # the Flask test client's host


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
