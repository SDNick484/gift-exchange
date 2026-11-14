"""The SQLite schema, connections and migrate().

Connections run in autocommit mode (isolation_level=None): a single statement commits on its own, and anything
that must be atomic runs inside `with transaction(con):`. Every schema change adds a step to MIGRATIONS and bumps
SCHEMA_VERSION; migrate() is idempotent and runs at every start, so the host never needs a manual DB step.
Timestamps are integer epoch seconds; money is integer cents."""
import sqlite3
from contextlib import contextmanager

SCHEMA_VERSION = 2

# Version 1 (a deployed database was created from this text: never edit it, add a step to MIGRATIONS instead).
# Statements are separated by ";" and contain none themselves (no triggers): see _statements().
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS exchange (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE CHECK (slug <> '' AND slug NOT GLOB '*[^a-z0-9-]*'),
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  password_version INTEGER NOT NULL DEFAULT 1,
  link_token TEXT NOT NULL UNIQUE,
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0,
  accent_color TEXT);
CREATE TABLE IF NOT EXISTS edition (
  id INTEGER PRIMARY KEY,
  exchange_id INTEGER NOT NULL REFERENCES exchange(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  year INTEGER NOT NULL,
  budget_cents INTEGER,
  event_date TEXT,
  location TEXT,
  rules TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','paired','closed')),
  created_at INTEGER NOT NULL,
  UNIQUE (exchange_id, year));
CREATE TABLE IF NOT EXISTS person (
  id INTEGER PRIMARY KEY,
  exchange_id INTEGER NOT NULL REFERENCES exchange(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  household TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (exchange_id, name));
CREATE TABLE IF NOT EXISTS edition_people (
  edition_id INTEGER NOT NULL REFERENCES edition(id) ON DELETE CASCADE,
  person_id INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  PRIMARY KEY (edition_id, person_id));
CREATE TABLE IF NOT EXISTS participant (
  edition_id INTEGER NOT NULL REFERENCES edition(id) ON DELETE CASCADE,
  person_id INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  about TEXT NOT NULL DEFAULT '',
  amazon_url TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  updated_at INTEGER NOT NULL,
  updated_by TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (edition_id, person_id));
-- A draft may hold a doubled recipient or a self-pair so that pairings.problems can name it.
-- pairings.mark_paired is the guard: it refuses both, so a paired edition is a complete permutation.
CREATE TABLE IF NOT EXISTS pairing (
  edition_id INTEGER NOT NULL REFERENCES edition(id) ON DELETE CASCADE,
  giver_id INTEGER NOT NULL REFERENCES person(id),
  recipient_id INTEGER REFERENCES person(id),
  UNIQUE (edition_id, giver_id));
CREATE TABLE IF NOT EXISTS wish_item (
  id INTEGER PRIMARY KEY,
  edition_id INTEGER NOT NULL REFERENCES edition(id) ON DELETE CASCADE,
  person_id INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  url TEXT,
  note TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  updated_by TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS wish_item_person ON wish_item(edition_id, person_id);
CREATE TABLE IF NOT EXISTS profile_field (
  id INTEGER PRIMARY KEY,
  exchange_id INTEGER NOT NULL REFERENCES exchange(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  hint TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS profile_value (
  person_id INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  field_id INTEGER NOT NULL REFERENCES profile_field(id) ON DELETE CASCADE,
  value TEXT NOT NULL CHECK (length(value) <= 500),
  updated_at INTEGER NOT NULL,
  updated_by TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (person_id, field_id));
CREATE TABLE IF NOT EXISTS login_failure (
  scope TEXT NOT NULL CHECK (scope IN ('exchange','admin')),
  at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS login_failure_at ON login_failure(scope, at)
"""


def _statements(script):
    # Not executescript(): it commits any open transaction first, which would split a migration in two.
    return [s.strip() for s in script.split(";") if s.strip()]


def connect(path):
    con = sqlite3.connect(path, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 10000")
    con.execute("PRAGMA journal_mode = WAL")
    return con


@contextmanager
def transaction(con, mode="IMMEDIATE"):
    """BEGIN IMMEDIATE ... COMMIT, or ROLLBACK if the block raises."""
    con.execute(f"BEGIN {mode}")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def _version(con):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone():
        return 0
    row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row[0]) if row else 0


def _to_v1(con):
    for stmt in _statements(SCHEMA):
        con.execute(stmt)


def _to_v2(con):
    # Soft delete: set when an item is deleted, cleared by restore, purged a day later (lists.purge_deleted).
    # ALTER ... ADD COLUMN keeps every row as it is; a populated v1 database is never rebuilt or copied.
    con.execute("ALTER TABLE wish_item ADD COLUMN deleted_at INTEGER")


MIGRATIONS = {1: _to_v1, 2: _to_v2}  # version -> step that brings version-1 up to it


def migrate(con):
    """Bring the database up to SCHEMA_VERSION, one atomic step at a time. Safe to run at every start."""
    current = _version(con)
    for target in range(current + 1, SCHEMA_VERSION + 1):
        with transaction(con):
            MIGRATIONS[target](con)
            con.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(target),))
