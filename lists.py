"""A participant's page: details (about, Amazon link), profile values and wish items, with version checks.

Route-free: every function takes a sqlite3.Connection (autocommit, see db.py) and raises common.ApiError. Writers
open their own `transaction(con)`, so don't call them from inside one.

Rules kept here:
- Scoping: `edition_of`, `person_of`, `on_roster` and `item_of` turn every id that isn't in this exchange, and anyone
  off the edition's roster, into 404. Routes call them before any writer.
- Two phones never silently overwrite each other (review focus 3). Details and items carry `version`, and a save
  runs `UPDATE ... WHERE version = ?` and checks rowcount. Details are created on first save with version 1 (the page
  shows version 0 while there's no row). Profile values carry their `updated_at` instead, and a change moves
  updated_at on by at least one second, so two saves in the same second still conflict. A stale save is 409 STALE
  and saves nothing.
- Details and items of a closed edition are 423 CLOSED. Profile values belong to the person, carry into every
  edition, and stay editable when a year is closed.
- Links go through common.clean_url, so `amazon.com/x ` is stored as `https://amazon.com/x` (review focus 4)."""
import common
from common import ApiError, clean_url, text
from db import transaction

STALE = "Someone else just changed this list. Reload to see it."
CLOSED = "This year is closed."
PURGE_AFTER = 86400  # seconds a deleted item can still be restored
MAX_ABOUT, MAX_TITLE, MAX_NOTE, MAX_VALUE, MAX_UPDATED_BY = 4000, 200, 1000, 500, 60


def _stale():
    return ApiError(409, STALE)


def is_id(value) -> bool:
    """A whole number SQLite can store (a bigger one would raise OverflowError, a 500, when bound)."""
    return isinstance(value, int) and not isinstance(value, bool) and -2 ** 63 <= value < 2 ** 63


def _key(value) -> int:
    """value for a lookup by id, or -1 (matches nothing) when it isn't one SQLite can bind."""
    return value if is_id(value) else -1


def version_of(data: dict, key: str = "version") -> int:
    value = data.get(key)
    if not is_id(value) or value < 0:
        raise ApiError(400, f"{key} must be a whole number.")
    return value


def updated_by_of(data: dict) -> str:
    """The name from "Which one are you?", required on every write that records who made it."""
    return text(data, "updated_by", MAX_UPDATED_BY, required=True)


# ---------------------------------------------------------------- scoping (404 for anything outside the exchange)
def edition_of(con, exchange_id: int, edition_id):
    """The edition row, or 404 unless it is an edition of this exchange."""
    row = con.execute("SELECT * FROM edition WHERE id = ? AND exchange_id = ?",
                      (_key(edition_id), exchange_id)).fetchone()
    if row is None:
        raise ApiError(404, "No such edition.")
    return row


def person_of(con, exchange_id: int, person_id: int):
    row = con.execute("SELECT * FROM person WHERE id = ? AND exchange_id = ?", (_key(person_id), exchange_id)).fetchone()
    if row is None:
        raise ApiError(404, "No such person.")
    return row


def on_roster(con, edition_id: int, person_id: int) -> None:
    if not con.execute("SELECT 1 FROM edition_people WHERE edition_id = ? AND person_id = ?",
                       (edition_id, person_id)).fetchone():
        raise ApiError(404, "No such person.")


def item_of(con, exchange_id: int, item_id: int):
    """The item row, or 404 unless its edition is in this exchange and its person is on that edition's roster."""
    row = con.execute("SELECT i.* FROM wish_item i JOIN edition e ON e.id = i.edition_id "
                      "JOIN edition_people ep ON ep.edition_id = i.edition_id AND ep.person_id = i.person_id "
                      "WHERE i.id = ? AND e.exchange_id = ?", (_key(item_id), exchange_id)).fetchone()
    if row is None:
        raise ApiError(404, "No such item.")
    return row


def _open(con, edition_id: int) -> None:
    """423 unless the edition takes list writes. Call inside the writer's transaction."""
    if con.execute("SELECT status FROM edition WHERE id = ?", (edition_id,)).fetchone()[0] == "closed":
        raise ApiError(423, CLOSED)


# ---------------------------------------------------------------- reading
def profile(con, person_id: int, exchange_id: int) -> list[dict]:
    """The exchange's active fields in order, each with this person's value (None when blank)."""
    rows = con.execute("SELECT f.id, f.label, f.hint, v.value, v.updated_at, v.updated_by FROM profile_field f "
                       "LEFT JOIN profile_value v ON v.field_id = f.id AND v.person_id = ? "
                       "WHERE f.exchange_id = ? AND f.active = 1 ORDER BY f.sort_order, f.id", (person_id, exchange_id))
    return [{"field_id": r["id"], "label": r["label"], "hint": r["hint"], "value": r["value"],
             "updated_at": r["updated_at"], "updated_by": r["updated_by"]} for r in rows]


def item_json(row) -> dict:
    return {"id": row["id"], "title": row["title"], "url": row["url"], "note": row["note"], "version": row["version"],
            "updated_at": row["updated_at"], "updated_by": row["updated_by"]}


def page(con, edition_id: int, person_id: int) -> dict:
    """Everything on a participant's page for one edition. The caller has checked scope and roster."""
    person = con.execute("SELECT p.id, p.name, e.exchange_id FROM person p JOIN edition e ON e.id = ? "
                         "WHERE p.id = ?", (edition_id, person_id)).fetchone()
    part = con.execute("SELECT * FROM participant WHERE edition_id = ? AND person_id = ?",
                       (edition_id, person_id)).fetchone()
    items = con.execute("SELECT * FROM wish_item WHERE edition_id = ? AND person_id = ? ORDER BY sort_order, id",
                        (edition_id, person_id))
    return {"person": {"id": person["id"], "name": person["name"]}, "edition_id": edition_id,
            "about": part["about"] if part else "", "amazon_url": part["amazon_url"] if part else None,
            "version": part["version"] if part else 0, "updated_at": part["updated_at"] if part else None,
            "updated_by": part["updated_by"] if part else None,
            "profile": profile(con, person_id, person["exchange_id"]), "items": [item_json(r) for r in items]}


def people(con, edition_id: int) -> list[dict]:
    """The edition's roster by name, each with their item count and whether they have an Amazon list."""
    rows = con.execute(
        "SELECT p.id, p.name, (SELECT COUNT(*) FROM wish_item i WHERE i.edition_id = ep.edition_id "
        "AND i.person_id = p.id) AS item_count, EXISTS (SELECT 1 FROM participant pa WHERE pa.edition_id = "
        "ep.edition_id AND pa.person_id = p.id AND pa.amazon_url IS NOT NULL) AS has_amazon "
        "FROM edition_people ep JOIN person p ON p.id = ep.person_id WHERE ep.edition_id = ? "
        "ORDER BY p.name COLLATE NOCASE, p.id", (edition_id,))
    return [{"id": r["id"], "name": r["name"], "item_count": r["item_count"], "has_amazon": bool(r["has_amazon"])}
            for r in rows]


# ---------------------------------------------------------------- details
def save_details(con, edition_id: int, person_id: int, about, amazon_url, version: int, updated_by: str) -> int:
    """Replace about and amazon_url (raw request values; validated here) and return the new version. version is the
    one the page loaded: 0 creates the row, anything else must match it."""
    about = text({"about": about}, "about", MAX_ABOUT) or ""
    amazon_url = clean_url(amazon_url)
    with transaction(con):
        _open(con, edition_id)
        if version == 0:
            cur = con.execute("INSERT INTO participant (edition_id, person_id, about, amazon_url, version, updated_at, "
                              "updated_by) VALUES (?, ?, ?, ?, 1, ?, ?) ON CONFLICT DO NOTHING",
                              (edition_id, person_id, about, amazon_url, common.now(), updated_by))
        else:
            cur = con.execute("UPDATE participant SET about = ?, amazon_url = ?, version = version + 1, updated_at = ?, "
                              "updated_by = ? WHERE edition_id = ? AND person_id = ? AND version = ?",
                              (about, amazon_url, common.now(), updated_by, edition_id, person_id, version))
        if cur.rowcount != 1:
            raise _stale()
    return version + 1


# ---------------------------------------------------------------- profile values
def save_profile(con, person_id: int, exchange_id: int, values: dict[int, str | None],
                 expected: dict[int, int | None], updated_by: str) -> None:
    """Set the person's values {field_id: text or None}; empty text deletes the value. expected[field_id] is the
    updated_at the page loaded, or None when the value was blank. Fields whose value didn't change are skipped and
    not checked. Every field must belong to this exchange (404). Any stale field is 409 and nothing is saved."""
    clean = {}
    for fid, value in values.items():
        if value is not None and not isinstance(value, str):
            raise ApiError(400, "Each value must be text.")
        clean[fid] = text({"value": value}, "value", MAX_VALUE)
    with transaction(con):
        if clean:
            ids = list(clean)
            found = con.execute(f"SELECT COUNT(*) FROM profile_field WHERE exchange_id = ? AND id IN "
                                f"({','.join('?' * len(ids))})", (exchange_id, *ids)).fetchone()[0]
            if found != len(ids):
                raise ApiError(404, "No such field.")
        changes = []
        for fid, value in clean.items():
            row = con.execute("SELECT value, updated_at FROM profile_value WHERE person_id = ? AND field_id = ?",
                              (person_id, fid)).fetchone()
            if value == (row["value"] if row else None):
                continue
            if expected.get(fid) != (row["updated_at"] if row else None):
                raise _stale()
            changes.append((fid, value, row))
        now = common.now()
        for fid, value, row in changes:
            if value is None:
                con.execute("DELETE FROM profile_value WHERE person_id = ? AND field_id = ?", (person_id, fid))
            else:
                # Strictly later than the value it replaces, so a page loaded in the same second is still stale.
                at = max(now, row["updated_at"] + 1) if row else now
                con.execute("INSERT INTO profile_value (person_id, field_id, value, updated_at, updated_by) "
                            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (person_id, field_id) DO UPDATE SET "
                            "value = excluded.value, updated_at = excluded.updated_at, "
                            "updated_by = excluded.updated_by", (person_id, fid, value, at, updated_by))


# ---------------------------------------------------------------- wish items
def _item_fields(data: dict, partial: bool) -> dict:
    """title/url/note from a request body. With partial, only the keys present (at least one)."""
    out = {}
    if not partial or "title" in data:
        out["title"] = text(data, "title", MAX_TITLE, required=True)
    if not partial or "url" in data:
        out["url"] = clean_url(data.get("url"))
    if not partial or "note" in data:
        out["note"] = text(data, "note", MAX_NOTE)
    if not out:
        raise ApiError(400, "Nothing to change.")
    return out


def _open_item(con, item_id: int) -> None:
    """423 when the item's edition is closed; 404 when the item went (deleted on another phone after the route's
    item_of check). Call inside the writer's transaction."""
    row = con.execute("SELECT edition_id FROM wish_item WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise ApiError(404, "No such item.")
    _open(con, row[0])


def add_item(con, edition_id: int, person_id: int, data: dict, updated_by: str) -> int:
    """A new item at the end of the person's list for the edition, version 1. Returns its id."""
    f = _item_fields(data, partial=False)
    with transaction(con):
        _open(con, edition_id)
        now = common.now()
        return con.execute(
            "INSERT INTO wish_item (edition_id, person_id, title, url, note, sort_order, created_at, updated_at, "
            "updated_by) VALUES (?, ?, ?, ?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM wish_item "
            "WHERE edition_id = ? AND person_id = ?), ?, ?, ?)",
            (edition_id, person_id, f["title"], f["url"], f["note"], edition_id, person_id, now, now,
             updated_by)).lastrowid


def update_item(con, item_id: int, data: dict, version: int, updated_by: str) -> int:
    """PATCH {title?, url?, note?} at the version the page loaded. Returns the new version."""
    sets = _item_fields(data, partial=True)
    cols = ", ".join(f"{c} = ?" for c in sets)  # fixed column names from _item_fields, never from input
    with transaction(con):
        _open_item(con, item_id)
        cur = con.execute(f"UPDATE wish_item SET {cols}, version = version + 1, updated_at = ?, updated_by = ? "
                          "WHERE id = ? AND version = ?", (*sets.values(), common.now(), updated_by, item_id, version))
        if cur.rowcount != 1:
            raise _stale()
    return version + 1


def delete_item(con, item_id: int, version: int) -> None:
    with transaction(con):
        _open_item(con, item_id)
        if con.execute("DELETE FROM wish_item WHERE id = ? AND version = ?", (item_id, version)).rowcount != 1:
            raise _stale()


def purge_deleted(con) -> int:
    """Drop items soft-deleted more than PURGE_AFTER seconds ago (they can no longer be restored). Run at start-up."""
    with transaction(con):
        return con.execute("DELETE FROM wish_item WHERE deleted_at IS NOT NULL AND deleted_at <= ?",
                           (common.now() - PURGE_AFTER,)).rowcount


def bring_over(con, edition_id: int, person_id: int, updated_by: str) -> int:
    """Copy title, url and note of the person's items from the newest earlier edition (by year, same exchange) whose
    roster had them, to the end of their list for edition_id. Skips titles already on the list, case-insensitively.
    400 when nothing is left to bring. The caller has checked scope and roster. Returns the number copied."""
    with transaction(con):
        _open(con, edition_id)
        src = con.execute("SELECT e.id FROM edition e JOIN edition t ON t.id = ? AND t.exchange_id = e.exchange_id "
                          "AND e.year < t.year JOIN edition_people ep ON ep.edition_id = e.id AND ep.person_id = ? "
                          "ORDER BY e.year DESC LIMIT 1", (edition_id, person_id)).fetchone()
        mine = {r[0].casefold() for r in con.execute(
            "SELECT title FROM wish_item WHERE edition_id = ? AND person_id = ? AND deleted_at IS NULL",
            (edition_id, person_id))}
        fresh = []
        if src is not None:
            for r in con.execute("SELECT title, url, note FROM wish_item WHERE edition_id = ? AND person_id = ? "
                                 "AND deleted_at IS NULL ORDER BY sort_order, id", (src[0], person_id)):
                if r["title"].casefold() not in mine:
                    mine.add(r["title"].casefold())  # a title repeated last year is brought once
                    fresh.append(r)
        if not fresh:
            raise ApiError(400, "Nothing to bring over.")
        now = common.now()
        last = con.execute("SELECT COALESCE(MAX(sort_order), -1) FROM wish_item WHERE edition_id = ? AND person_id = ? "
                           "AND deleted_at IS NULL", (edition_id, person_id)).fetchone()[0]
        con.executemany(
            "INSERT INTO wish_item (edition_id, person_id, title, url, note, sort_order, created_at, updated_at, "
            "updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(edition_id, person_id, r["title"], r["url"], r["note"], last + 1 + n, now, now, updated_by)
             for n, r in enumerate(fresh)])
    return len(fresh)


def reorder(con, edition_id: int, person_id: int, ids: list[int]) -> None:
    """Renumber the person's items for the edition in this order. ids must name each of them exactly once. An id
    that isn't an item of this exchange is 404; a list that otherwise doesn't match what is stored (an item added
    or deleted on another phone) is 409. Versions don't change, so an edit open on another phone still saves."""
    if not isinstance(ids, list) or not all(is_id(i) for i in ids) or len(set(ids)) != len(ids):
        raise ApiError(400, "ids must list each item once.")
    with transaction(con):
        _open(con, edition_id)
        have = {r[0] for r in con.execute("SELECT id FROM wish_item WHERE edition_id = ? AND person_id = ?",
                                          (edition_id, person_id))}
        if set(ids) != have:
            exchange_id = con.execute("SELECT exchange_id FROM edition WHERE id = ?", (edition_id,)).fetchone()[0]
            for i in set(ids) - have:
                if not con.execute("SELECT 1 FROM wish_item i JOIN edition e ON e.id = i.edition_id "
                                   "WHERE i.id = ? AND e.exchange_id = ?", (i, exchange_id)).fetchone():
                    raise ApiError(404, "No such item.")
            raise _stale()
        con.executemany("UPDATE wish_item SET sort_order = ? WHERE id = ?", [(n, i) for n, i in enumerate(ids)])
