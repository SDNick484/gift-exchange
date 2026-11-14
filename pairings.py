"""Pairings: draft entry, the checks behind Mark paired, warnings, and who may see the names.

Route-free: every function takes a sqlite3.Connection (autocommit, see db.py) and raises common.ApiError for a bad
request, so app.py's routes stay thin. Functions that write open their own `transaction(con)`; their
`*_in_transaction` twins do the same work inside a transaction the caller already holds (draw.publish uses them).

Rules kept here:
- The admin types names in from the bowl, so a draft may be partial or wrong (a giver with no recipient, a recipient
  twice, someone giving to themselves). save_draft keeps it as typed; the problems say what is wrong, by roster name.
- Only mark_paired sets an edition to 'paired', and only when problems() is empty: a complete permutation of the roster.
- A household clash or a repeat of last year's pairing is a warning, never a problem. The bowl's result wins.
- The family sees names only once the edition is 'paired' or 'closed' (visible()); a draft is admin-only."""
from common import ApiError
from db import transaction

MIN_ROSTER = 2
_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _edition(con, edition_id):
    row = con.execute("SELECT * FROM edition WHERE id = ?", (edition_id,)).fetchone()
    if row is None:
        raise ApiError(404, "No such edition.")
    return row


def _roster(con, edition_id) -> dict[int, str]:
    """{person_id: name} of the edition's roster, in name order."""
    rows = con.execute("SELECT p.id, p.name FROM edition_people ep JOIN person p ON p.id = ep.person_id "
                       "WHERE ep.edition_id = ? ORDER BY p.name COLLATE NOCASE, p.id", (edition_id,))
    return {r["id"]: r["name"] for r in rows}


def _rows(con, edition_id) -> list[tuple[int, int | None]]:
    return [(r[0], r[1]) for r in con.execute("SELECT giver_id, recipient_id FROM pairing WHERE edition_id = ?",
                                              (edition_id,))]


def _list(names) -> str:
    """'Alex', 'Alex and Sam', 'Alex, Sam and Jordan'."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _not_open(status):
    if status == "paired":
        return ApiError(409, "The names are already marked paired. Unpair first to change them.")
    return ApiError(409, "This edition is closed.")


# ---------------------------------------------------------------- saving
def save_draft(con, edition_id: int, pairs: list[tuple[int, int | None]]) -> None:
    """Replace every pairing row of an open edition with `pairs` of (giver_id, recipient_id or None). A draft may be
    partial or wrong on purpose (see the module docstring). Givers and recipients must be on the roster and a giver
    may appear once (400); an edition that isn't open is 409. Nothing changes on an error."""
    with transaction(con):
        save_draft_in_transaction(con, edition_id, pairs)


def save_draft_in_transaction(con, edition_id: int, pairs: list[tuple[int, int | None]]) -> None:
    """save_draft for a caller that already holds a transaction (and rolls it back on an error)."""
    ed = _edition(con, edition_id)
    if ed["status"] != "open":
        raise _not_open(ed["status"])
    roster = _roster(con, edition_id)
    seen = set()
    for giver, recipient in pairs:
        for pid in (giver, recipient):
            if pid is not None and pid not in roster:
                name = con.execute("SELECT name FROM person WHERE id = ?", (pid,)).fetchone()
                raise ApiError(400, f"{name[0] if name else 'That person'} isn't on this edition's roster.")
        if giver in seen:
            raise ApiError(400, f"{roster[giver]} is listed twice as a giver.")
        seen.add(giver)
    con.execute("DELETE FROM pairing WHERE edition_id = ?", (edition_id,))
    con.executemany("INSERT INTO pairing (edition_id, giver_id, recipient_id) VALUES (?, ?, ?)",
                    [(edition_id, g, r) for g, r in pairs])


# ---------------------------------------------------------------- checking
def problems(con, edition_id: int) -> list[str]:
    """What stops Mark paired, as sentences built from roster names: everyone gives once, gets once, nobody gives to
    themselves. Givers first, then self-pairs, then doubled recipients, then people nobody gives to, each in name order.
    A roster of fewer than 2 is the only problem reported then."""
    roster = _roster(con, edition_id)
    if len(roster) < MIN_ROSTER:
        return [f"The roster needs at least {MIN_ROSTER} people."]
    given = dict(_rows(con, edition_id))                                   # giver -> recipient or None
    gets: dict[int, list[int]] = {}
    for giver, recipient in given.items():
        if recipient is not None:
            gets.setdefault(recipient, []).append(giver)
    out = [f"{name} isn't giving to anyone yet." for pid, name in roster.items() if given.get(pid) is None]
    out += [f"{name} can't give to themselves." for pid, name in roster.items() if given.get(pid) == pid]
    for pid, name in roster.items():
        givers = sorted((roster.get(g, "Someone") for g in gets.get(pid, [])), key=str.casefold)
        if len(givers) > 1:
            out.append(f"{name} is getting {_NUMBER_WORDS.get(len(givers), len(givers))} gifts "
                       f"(from {_list(givers)}).")
    out += [f"{name} isn't getting a gift." for pid, name in roster.items() if pid not in gets]
    return out


def warnings(con, edition_id: int) -> list[str]:
    """Non-blocking notes on the rows that name both people: two people with the same household label, and a pairing
    that repeats the newest earlier edition of the same exchange ("last year"). In giver-name order, one note per
    household pair even when they give to each other."""
    ed = _edition(con, edition_id)
    people = {r["id"]: r for r in con.execute("SELECT id, name, household FROM person WHERE exchange_id = ?",
                                              (ed["exchange_id"],))}
    prev = con.execute("SELECT id FROM edition WHERE exchange_id = ? AND year < ? ORDER BY year DESC LIMIT 1",
                       (ed["exchange_id"], ed["year"])).fetchone()
    before = set(_rows(con, prev["id"])) if prev else set()
    rows = sorted(((g, r) for g, r in _rows(con, edition_id) if r is not None and g != r and g in people
                   and r in people), key=lambda p: (people[p[0]]["name"].casefold(), p[0]))
    out, seen = [], set()
    for giver, recipient in rows:
        a, b = people[giver], people[recipient]
        household = (a["household"] or "").strip().casefold()
        key = frozenset((giver, recipient))
        if household and household == (b["household"] or "").strip().casefold() and key not in seen:
            seen.add(key)
            out.append(f"{a['name']} and {b['name']} are in the same household.")
    for giver, recipient in rows:
        if (giver, recipient) in before:
            out.append(f"{people[giver]['name']} had {people[recipient]['name']} last year too.")
    return out


# ---------------------------------------------------------------- status changes
def mark_paired(con, edition_id: int) -> None:
    """Open to paired, when problems() is empty; otherwise 400 with every problem joined by '; '. Not open is 409."""
    with transaction(con):
        mark_paired_in_transaction(con, edition_id)


def mark_paired_in_transaction(con, edition_id: int) -> None:
    """mark_paired for a caller that already holds a transaction (and rolls it back on an error)."""
    ed = _edition(con, edition_id)
    if ed["status"] != "open":
        raise _not_open(ed["status"])
    found = problems(con, edition_id)
    if found:
        raise ApiError(400, "; ".join(found))
    con.execute("UPDATE edition SET status = 'paired' WHERE id = ?", (edition_id,))


def unpair(con, edition_id: int) -> None:
    """Paired back to open so the draft can be edited; the rows stay. Any other status is 409."""
    with transaction(con):
        ed = _edition(con, edition_id)
        if ed["status"] != "paired":
            raise ApiError(409, "Only a paired edition can be unpaired.")
        con.execute("UPDATE edition SET status = 'open' WHERE id = ?", (edition_id,))


# ---------------------------------------------------------------- reading
def overview(con, edition_id: int) -> dict:
    """What the admin's pairing page shows: {"pairs", "problems", "warnings", "status"}, the draft included."""
    status = _edition(con, edition_id)["status"]
    return {"pairs": visible(con, edition_id, admin=True), "problems": problems(con, edition_id),
            "warnings": warnings(con, edition_id), "status": status}


def visible(con, edition_id: int, *, admin: bool) -> list[dict] | None:
    """[{"giver_id","giver","recipient_id","recipient"}] sorted by giver name, or None while the family may not see
    them: the edition is open and the viewer is not the admin. A draft row has recipient_id and recipient None."""
    ed = _edition(con, edition_id)
    if ed["status"] not in ("paired", "closed") and not admin:
        return None
    rows = con.execute("SELECT r.giver_id, g.name AS giver, r.recipient_id, t.name AS recipient FROM pairing r "
                       "JOIN person g ON g.id = r.giver_id LEFT JOIN person t ON t.id = r.recipient_id "
                       "WHERE r.edition_id = ? ORDER BY g.name COLLATE NOCASE, g.id", (edition_id,))
    return [dict(r) for r in rows]
