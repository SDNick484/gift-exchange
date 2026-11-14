"""Admin structure: exchanges, yearly editions, people, the per-edition roster and the profile fields.

Route-free: every function takes a sqlite3.Connection (autocommit, see db.py) and raises common.ApiError for a bad
request, so app.py's routes stay thin. Functions that write more than one row open their own `transaction(con)`, so
don't call them from inside one.

Rules kept here:
- A roster change or a deactivation never orphans a pairing: it is 409 "Remove their pairing first: <names>."
  while a pairing (a giver or a recipient, even a half-entered draft row) names the person.
- An edition can't be set to 'paired' here (Mark paired in pairings.py is the only way in).
- Changing an exchange's password bumps password_version and regenerates link_token."""
import re
import secrets
import sqlite3
from datetime import date

import access
import common
from common import ApiError, parse_cents, text
from db import transaction

DEFAULT_FIELDS = [
    ("Shirt size", None),
    ("Pants size", "waist/length, or kids' size"),
    ("Shoe size", None),
    ("Favorite colors", None),
    ("Interests and hobbies", None),
    ("Favorite stores", None),
    ("Already have / don't need", None),
    ("Please avoid", "dislikes, allergies, scents"),
]

SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
RESERVED_SLUGS = ("admin", "api", "x", "static")
COLOR = re.compile(r"#[0-9a-fA-F]{6}")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
MIN_PASSWORD, MAX_PASSWORD = 4, 128
MIN_YEAR, MAX_YEAR = 2000, 2100
MAX_NAME, MAX_HOUSEHOLD, MAX_LABEL, MAX_HINT, MAX_LOCATION, MAX_RULES = 80, 80, 60, 200, 200, 2000
MAX_EDITION_LABEL = 40
MAX_SORT = 100_000
EDITION_STATUSES = ("open", "paired", "closed")


# ---------------------------------------------------------------- small validators
def _get(con, table, row_id, message):
    row = con.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        raise ApiError(404, message)
    return row


def _flag(value, key):
    if not isinstance(value, bool):
        raise ApiError(400, f"{key} must be true or false.")
    return int(value)


def _int_id(value):
    return isinstance(value, int) and not isinstance(value, bool)


def check_slug(slug) -> str:
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise ApiError(400, "The address must be 1 to 40 lowercase letters, digits or dashes, starting with a "
                            "letter or digit.")
    if slug in RESERVED_SLUGS:
        raise ApiError(400, "That address is reserved.")
    return slug


def check_password(pw) -> str:
    if not isinstance(pw, str) or not MIN_PASSWORD <= len(pw) <= MAX_PASSWORD:
        raise ApiError(400, f"The password must be {MIN_PASSWORD} to {MAX_PASSWORD} characters.")
    return pw


def _color(value):
    if value is None:
        return None
    if not isinstance(value, str) or (value.strip() and not COLOR.fullmatch(value.strip())):
        raise ApiError(400, "The color must look like #1a2b3c.")
    return value.strip() or None


def _sort_order(value):
    if not _int_id(value) or abs(value) > MAX_SORT:
        raise ApiError(400, "sort_order must be a whole number.")
    return value


def _date(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not DATE.fullmatch(value.strip()):
        raise ApiError(400, "The date must look like 2026-12-24.")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise ApiError(400, "That date doesn't exist.") from None


def _year(value):
    if not _int_id(value) or not MIN_YEAR <= value <= MAX_YEAR:
        raise ApiError(400, f"The year must be a whole number from {MIN_YEAR} to {MAX_YEAR}.")
    return value


def _update(con, table, row_id, sets):
    """UPDATE one row from {column: value}. sets is built by this module from fixed column names, never from input."""
    cols = ", ".join(f"{c} = ?" for c in sets)
    con.execute(f"UPDATE {table} SET {cols} WHERE id = ?", (*sets.values(), row_id))


# ---------------------------------------------------------------- exchanges
def exchange_json(row) -> dict:
    return {"id": row["id"], "slug": row["slug"], "name": row["name"], "active": bool(row["active"]),
            "sort_order": row["sort_order"], "accent_color": row["accent_color"]}


def list_exchanges(con) -> list[dict]:
    return [exchange_json(r) for r in con.execute("SELECT * FROM exchange ORDER BY sort_order, id")]


def create_exchange(con, slug, name, password, *, accent_color=None, sort_order=0) -> int:
    """A new exchange with its password hashed, a fresh share-link token and the DEFAULT_FIELDS seeded in order."""
    check_slug(slug)
    check_password(password)
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_NAME:
        raise ApiError(400, f"The name is required, at most {MAX_NAME} characters.")
    color, order = _color(accent_color), _sort_order(sort_order)
    with transaction(con):
        if con.execute("SELECT 1 FROM exchange WHERE slug = ?", (slug,)).fetchone():
            raise ApiError(409, "That address is already used by another exchange.")
        xid = con.execute("INSERT INTO exchange (slug, name, password_hash, link_token, sort_order, accent_color) "
                          "VALUES (?, ?, ?, ?, ?, ?)",
                          (slug, name.strip(), access.hash_password(password), secrets.token_urlsafe(16), order,
                           color)).lastrowid
        con.executemany("INSERT INTO profile_field (exchange_id, label, hint, sort_order) VALUES (?, ?, ?, ?)",
                        [(xid, label, hint, i) for i, (label, hint) in enumerate(DEFAULT_FIELDS)])
    return xid


def update_exchange(con, exchange_id: int, data: dict) -> dict:
    """PATCH {name?, slug?, active?, accent_color?, sort_order?, password?}. A new password bumps password_version
    (revoking every cookie entry for the exchange) and regenerates link_token (revoking old links)."""
    _get(con, "exchange", exchange_id, "No such exchange.")
    sets = {}
    if "name" in data:
        sets["name"] = text(data, "name", MAX_NAME, required=True)
    if "slug" in data:
        sets["slug"] = check_slug(text(data, "slug", 40, required=True))
    if "active" in data:
        sets["active"] = _flag(data["active"], "active")
    if "accent_color" in data:
        sets["accent_color"] = _color(data["accent_color"])
    if "sort_order" in data:
        sets["sort_order"] = _sort_order(data["sort_order"])
    if "password" in data:
        sets["password_hash"] = access.hash_password(check_password(text(data, "password", MAX_PASSWORD, required=True)))
        sets["link_token"] = secrets.token_urlsafe(16)
    if not sets:
        raise ApiError(400, "Nothing to change.")
    cols = ", ".join(f"{c} = ?" for c in sets)
    bump = ", password_version = password_version + 1" if "password_hash" in sets else ""
    try:
        con.execute(f"UPDATE exchange SET {cols}{bump} WHERE id = ?", (*sets.values(), exchange_id))
    except sqlite3.IntegrityError:
        raise ApiError(409, "That address is already used by another exchange.") from None
    return exchange_json(_get(con, "exchange", exchange_id, "No such exchange."))


def regenerate_link(con, exchange_id: int) -> tuple[str, str]:
    """A new share-link token (old links stop working; cookies already set keep working). Returns (slug, token)."""
    row = _get(con, "exchange", exchange_id, "No such exchange.")
    token = secrets.token_urlsafe(16)
    con.execute("UPDATE exchange SET link_token = ? WHERE id = ?", (token, exchange_id))
    return row["slug"], token


# ---------------------------------------------------------------- people
def person_json(row) -> dict:
    return {"id": row["id"], "name": row["name"], "household": row["household"], "active": bool(row["active"])}


def list_people(con, exchange_id: int) -> list[dict]:
    _get(con, "exchange", exchange_id, "No such exchange.")
    return [person_json(r) for r in con.execute("SELECT * FROM person WHERE exchange_id = ? "
                                                "ORDER BY name COLLATE NOCASE, id", (exchange_id,))]


def _duplicate_name(name):
    return ApiError(409, f"{name} is already in this exchange.")


def add_person(con, exchange_id: int, data: dict) -> int:
    _get(con, "exchange", exchange_id, "No such exchange.")
    name = text(data, "name", MAX_NAME, required=True)
    household = text(data, "household", MAX_HOUSEHOLD)
    try:
        return con.execute("INSERT INTO person (exchange_id, name, household) VALUES (?, ?, ?)",
                           (exchange_id, name, household)).lastrowid
    except sqlite3.IntegrityError:
        raise _duplicate_name(name) from None


def _paired_people(con, edition_id):
    """Rows (id, name) of people named by a pairing of the edition, as giver or recipient (draft rows included)."""
    return con.execute("SELECT DISTINCT p.id, p.name FROM person p JOIN pairing r ON r.edition_id = ? "
                       "AND (r.giver_id = p.id OR r.recipient_id = p.id) ORDER BY p.name COLLATE NOCASE, p.id",
                       (edition_id,)).fetchall()


def _remove_pairing_first(names):
    return ApiError(409, f"Remove their pairing first: {', '.join(names)}.")


def update_person(con, person_id: int, data: dict) -> dict:
    """PATCH {name?, household?, active?}. Deactivating is 409 while a pairing in an edition that isn't closed names
    the person (review focus 5)."""
    with transaction(con):
        row = _get(con, "person", person_id, "No such person.")
        sets = {}
        if "name" in data:
            sets["name"] = text(data, "name", MAX_NAME, required=True)
        if "household" in data:
            sets["household"] = text(data, "household", MAX_HOUSEHOLD)
        if "active" in data:
            sets["active"] = _flag(data["active"], "active")
        if not sets:
            raise ApiError(400, "Nothing to change.")
        if sets.get("active") == 0 and row["active"] and con.execute(
                "SELECT 1 FROM pairing r JOIN edition e ON e.id = r.edition_id WHERE e.status <> 'closed' "
                "AND (r.giver_id = ? OR r.recipient_id = ?) LIMIT 1", (person_id, person_id)).fetchone():
            raise _remove_pairing_first([row["name"]])
        try:
            _update(con, "person", person_id, sets)
        except sqlite3.IntegrityError:
            raise _duplicate_name(sets["name"]) from None
        return person_json(_get(con, "person", person_id, "No such person."))


# ---------------------------------------------------------------- editions and the roster
def edition_json(con, row) -> dict:
    ids = [r[0] for r in con.execute("SELECT person_id FROM edition_people WHERE edition_id = ? ORDER BY person_id",
                                     (row["id"],))]
    return {"id": row["id"], "year": row["year"], "label": row["label"], "budget_cents": row["budget_cents"],
            "event_date": row["event_date"], "location": row["location"], "rules": row["rules"],
            "status": row["status"], "person_ids": ids}


def list_editions(con, exchange_id: int) -> list[dict]:
    _get(con, "exchange", exchange_id, "No such exchange.")
    return [edition_json(con, r) for r in con.execute("SELECT * FROM edition WHERE exchange_id = ? ORDER BY year DESC",
                                                      (exchange_id,))]


def create_edition(con, exchange_id: int, year: int, label: str | None, copy_roster: bool) -> int:
    """A new open edition; label defaults to str(year). Any year may be added at any time (past editions feed the
    repeat-pairing warning). copy_roster copies the roster of the newest edition with an earlier year, keeping
    only people who are still active. A second edition for the same year is 409."""
    _get(con, "exchange", exchange_id, "No such exchange.")
    _year(year)
    if label is not None and (not isinstance(label, str) or len(label.strip()) > MAX_EDITION_LABEL):
        raise ApiError(400, f"The label must be at most {MAX_EDITION_LABEL} characters.")
    label = (label or "").strip() or str(year)
    with transaction(con):
        if con.execute("SELECT 1 FROM edition WHERE exchange_id = ? AND year = ?", (exchange_id, year)).fetchone():
            raise ApiError(409, f"There is already an edition for {year}.")
        eid = con.execute("INSERT INTO edition (exchange_id, label, year, created_at) VALUES (?, ?, ?, ?)",
                          (exchange_id, label, year, common.now())).lastrowid
        if copy_roster:
            con.execute("INSERT INTO edition_people (edition_id, person_id) "
                        "SELECT ?, ep.person_id FROM edition_people ep JOIN person p ON p.id = ep.person_id "
                        "WHERE p.active = 1 AND ep.edition_id = (SELECT id FROM edition WHERE exchange_id = ? "
                        "AND year < ? ORDER BY year DESC LIMIT 1)", (eid, exchange_id, year))
    return eid


def current_edition(con, exchange_id: int):
    """The newest edition (by year) that isn't closed, else the newest one, else None."""
    return con.execute("SELECT * FROM edition WHERE exchange_id = ? ORDER BY status = 'closed', year DESC LIMIT 1",
                       (exchange_id,)).fetchone()


def update_edition(con, edition_id: int, data: dict) -> dict:
    """PATCH {label?, budget?, event_date?, location?, rules?, status?}. status is open or closed; 'paired' is 400
    (Mark paired is the only way in). Text over its limit is 400 rather than cut, so typed rules are never lost."""
    _get(con, "edition", edition_id, "No such edition.")
    sets = {}
    if "label" in data:
        sets["label"] = text(data, "label", MAX_EDITION_LABEL, required=True)
    if "budget" in data:
        sets["budget_cents"] = parse_cents(data["budget"])
    if "event_date" in data:
        sets["event_date"] = _date(data["event_date"])
    if "location" in data:
        sets["location"] = text(data, "location", MAX_LOCATION)
    if "rules" in data:
        sets["rules"] = text(data, "rules", MAX_RULES) or ""
    if "status" in data:
        status = data["status"]
        if status == "paired":
            raise ApiError(400, "Use Mark paired to set an edition to paired.")
        if status not in ("open", "closed"):
            raise ApiError(400, "The status must be open or closed.")
        sets["status"] = status
    if not sets:
        raise ApiError(400, "Nothing to change.")
    _update(con, "edition", edition_id, sets)
    return edition_json(con, _get(con, "edition", edition_id, "No such edition."))


def set_roster(con, edition_id: int, person_ids: list[int]) -> None:
    """Replace the edition's roster. Everyone must belong to the edition's exchange (400). Dropping someone a pairing
    of this edition names, as giver or recipient, is 409 "Remove their pairing first: <names>." and changes nothing.
    The edition's draw exclusions that name someone dropped are deleted."""
    ed = _get(con, "edition", edition_id, "No such edition.")
    if not isinstance(person_ids, list) or not all(_int_id(i) for i in person_ids):
        raise ApiError(400, "person_ids must be a list of ids.")
    keep = list(dict.fromkeys(person_ids))
    with transaction(con):
        valid = {r[0] for r in con.execute("SELECT id FROM person WHERE exchange_id = ?", (ed["exchange_id"],))}
        if not valid.issuperset(keep):
            raise ApiError(400, "Everyone on the roster must belong to this exchange.")
        dropped = [r["name"] for r in _paired_people(con, edition_id) if r["id"] not in keep]
        if dropped:
            raise _remove_pairing_first(dropped)
        con.execute("DELETE FROM edition_people WHERE edition_id = ?", (edition_id,))
        con.executemany("INSERT INTO edition_people (edition_id, person_id) VALUES (?, ?)",
                        [(edition_id, pid) for pid in keep])
        # A draw exclusion naming someone who left the roster goes with them (it never blocks a roster change, and
        # coming back doesn't bring it back).
        con.execute("DELETE FROM draw_exclusion WHERE edition_id = ?1 AND (a_id NOT IN (SELECT person_id FROM "
                    "edition_people WHERE edition_id = ?1) OR b_id NOT IN (SELECT person_id FROM edition_people "
                    "WHERE edition_id = ?1))", (edition_id,))


# ---------------------------------------------------------------- profile fields
def field_json(row) -> dict:
    return {"id": row["id"], "label": row["label"], "hint": row["hint"], "sort_order": row["sort_order"],
            "active": bool(row["active"])}


def list_fields(con, exchange_id: int) -> list[dict]:
    _get(con, "exchange", exchange_id, "No such exchange.")
    return [field_json(r) for r in con.execute("SELECT * FROM profile_field WHERE exchange_id = ? "
                                               "ORDER BY sort_order, id", (exchange_id,))]


def add_field(con, exchange_id: int, data: dict) -> int:
    _get(con, "exchange", exchange_id, "No such exchange.")
    label = text(data, "label", MAX_LABEL, required=True)
    hint = text(data, "hint", MAX_HINT)
    with transaction(con):
        return con.execute("INSERT INTO profile_field (exchange_id, label, hint, sort_order) VALUES (?, ?, ?, "
                           "(SELECT COALESCE(MAX(sort_order), -1) + 1 FROM profile_field WHERE exchange_id = ?))",
                           (exchange_id, label, hint, exchange_id)).lastrowid


def update_field(con, field_id: int, data: dict) -> dict:
    """PATCH {label?, hint?, active?}. Hiding a field (active false) keeps its values."""
    _get(con, "profile_field", field_id, "No such field.")
    sets = {}
    if "label" in data:
        sets["label"] = text(data, "label", MAX_LABEL, required=True)
    if "hint" in data:
        sets["hint"] = text(data, "hint", MAX_HINT)
    if "active" in data:
        sets["active"] = _flag(data["active"], "active")
    if not sets:
        raise ApiError(400, "Nothing to change.")
    _update(con, "profile_field", field_id, sets)
    return field_json(_get(con, "profile_field", field_id, "No such field."))


def order_fields(con, exchange_id: int, ids) -> None:
    """Renumber the exchange's fields (hidden ones too) in the given order. ids must list every one exactly once."""
    _get(con, "exchange", exchange_id, "No such exchange.")
    with transaction(con):
        have = {r[0] for r in con.execute("SELECT id FROM profile_field WHERE exchange_id = ?", (exchange_id,))}
        if (not isinstance(ids, list) or not all(_int_id(i) for i in ids) or len(set(ids)) != len(ids)
                or set(ids) != have):
            raise ApiError(400, "ids must list every field of this exchange exactly once.")
        con.executemany("UPDATE profile_field SET sort_order = ? WHERE id = ?", [(n, fid) for n, fid in enumerate(ids)])
