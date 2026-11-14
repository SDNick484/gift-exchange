"""The in-app draw: who may not draw whom, a random draw that keeps every rule, a preview, and Publish.

Route-free like pairings.py: every function takes a sqlite3.Connection and raises common.ApiError for a bad request.
It reuses pairings' edition, roster and "not open" helpers so the messages match the pairings page.

Forbidden (forbidden_pairs), as directed (giver, recipient) pairs between people on the edition's roster:
- the same household label (trimmed, case-insensitive, non-empty: pairings.warnings' test), both ways;
- every pair of the last `lookback` (1 to 3) editions of the same exchange: the newest editions with an earlier year,
  whatever their status ("last year" is the newest one, as in pairings.warnings); draft rows with no recipient skip;
- the owner's rule, whatever the look-back: the reverse of every pair of the newest earlier edition. Alex had Sam last
  year, so Sam can't draw Alex this year. Only last year's reverses: a pair from two years back may be reversed;
- the edition's manual exclusions (draw_exclusion, stored once as a_id < b_id), both ways.
Nobody draws themselves, and nobody off the roster counts. The warnings in pairings.py are untouched by these rules: a
typed-in bowl result that reverses last year's pairs gets no warning.

draw() never relaxes a rule. When no draw exists it raises Impossible naming one person by id (the route puts the name
in): someone with no one left to draw, someone nobody may draw, or else the person with the fewest allowed recipients
as the place to start loosening. The search is randomized backtracking, most-constrained giver first, capped at
MAX_STEPS tries.

Preview and publish: preview() writes nothing to pairing or edition. It stores the result in draw_preview under a random
token (secrets.token_urlsafe(32)) with the look-back it used, in the database because gunicorn's two workers share
nothing else. A token is good for PREVIEW_SECONDS, for its own edition only (another edition's token is 400 and stays
good for its own), and once: publish() deletes it. A new draw for the edition replaces its older previews, and every
draw deletes expired ones. publish() re-checks in one transaction that the edition is still open with no pairing rows,
that the roster is still exactly the preview's givers and that no pair has become forbidden (each 409), then writes
through pairings' save_draft and mark_paired."""
import json
import secrets

import common
import pairings
from common import ApiError
from db import transaction

MAX_STEPS = 200_000
LOOKBACKS = (1, 2, 3)
PREVIEW_SECONDS = 600

NONE_LEFT = "{name} has no one left they're allowed to draw."
NO_GIVER = "No one is allowed to draw {name}."
NO_DRAW = "No draw keeps every rule. Start with {name}, who is allowed to draw only {count} {people}."
GAVE_UP = ("The draw gave up after {steps:,} tries without finding one that keeps every rule. Start with {name}, who "
           "is allowed to draw only {count} {people}.")
ALREADY_ENTERED = ("Names are already entered for this year. To draw instead, set everyone back to Not entered yet "
                   "on the pairings page and save.")
STALE_TOKEN = "This draw is no longer good (a draw lasts 10 minutes, and a new one replaces it). Draw again."


class Impossible(Exception):
    """No draw keeps every rule. The reason names `person` by id; named() puts their name in instead."""

    def __init__(self, reason: str, person: int | None = None, template: str | None = None, **values):
        super().__init__(reason)
        self.reason, self.person, self._template, self._values = reason, person, template, values

    def named(self, names: dict[int, str]) -> str:
        if self._template is None or self.person is None:
            return self.reason
        return self._template.format(name=names.get(self.person, "Someone"), **self._values)


def _impossible(template, person, **values):
    return Impossible(template.format(name=person, **values), person, template, **values)


class _GaveUp(Exception):
    pass


# ---------------------------------------------------------------- the algorithm
def _bits(mask):
    """Indexes of the set bits, lowest first."""
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def _matching_exists(out_mask, n):
    """Whether everyone can be given a different allowed recipient at all (Kuhn's augmenting paths). A draw is exactly
    such a matching, so without one the search would only burn its steps."""
    owner = [-1] * n

    def augment(i, seen):
        for j in _bits(out_mask[i]):
            if seen[0] >> j & 1:
                continue
            seen[0] |= 1 << j
            if owner[j] < 0 or augment(owner[j], seen):
                owner[j] = i
                return True
        return False

    return all(augment(i, [0]) for i in range(n))


def _reaches_everyone(masks, n):
    """Whether every person can be reached from person 0 along `masks` edges."""
    seen = frontier = 1
    while frontier:
        nxt = 0
        for i in _bits(frontier):
            nxt |= masks[i]
        frontier = nxt & ~seen
        seen |= frontier
    return seen == (1 << n) - 1


class _Search:
    """Randomized backtracking over bitmasks of allowed recipients (out) and allowed givers (into)."""

    def __init__(self, out_mask, into_mask, rng):
        self.out, self.into, self.rng, self.n = out_mask, into_mask, rng, len(out_mask)
        self.tie = [rng.random() for _ in range(self.n)]  # random tie-break among equally constrained people
        self.steps, self.limit = 0, MAX_STEPS

    def _step(self):
        self.steps += 1
        if self.steps > self.limit:
            raise _GaveUp

    def assign(self) -> dict[int, int] | None:
        """Any draw: the giver with the fewest recipients left goes next; recipients in random order. A choice stands
        only while every giver left still has someone and every recipient left still has a giver."""
        out, every = {}, (1 << self.n) - 1

        def solve(givers, free):
            if not givers:
                return True
            g = min(_bits(givers), key=lambda i: ((self.out[i] & free).bit_count(), self.tie[i]))
            options = list(_bits(self.out[g] & free))
            self.rng.shuffle(options)
            rest = givers & ~(1 << g)
            for r in options:
                self._step()
                left = free & ~(1 << r)
                if all(self.out[i] & left for i in _bits(rest)) and all(self.into[j] & rest for j in _bits(left)):
                    out[g] = r
                    if solve(rest, left):
                        return True
            out.pop(g, None)
            return False

        return out if solve(every, every) else None

    def loop(self) -> dict[int, int] | None:
        """One cycle through everyone: a path from the most constrained person, next steps in random order with the
        fewest onward choices first, kept only while everyone unvisited still has a way in and a way on."""
        start = min(range(self.n), key=lambda i: (self.out[i].bit_count(), self.tie[i]))
        home = 1 << start
        path = {}

        def extend(cur, unvisited):
            if not unvisited:
                path[cur] = start
                return True
            options = list(_bits(self.out[cur] & unvisited))
            self.rng.shuffle(options)
            options.sort(key=lambda j: (self.out[j] & unvisited).bit_count())  # stable: ties stay shuffled
            for nxt in options:
                self._step()
                rest = unvisited & ~(1 << nxt)
                if rest:
                    ok = bool(self.into[start] & rest) and all(
                        self.into[v] & (rest | 1 << nxt) & ~(1 << v) and self.out[v] & (rest | home) & ~(1 << v)
                        for v in _bits(rest))
                else:
                    ok = bool(self.out[nxt] & home)
                if ok:
                    path[cur] = nxt
                    if extend(nxt, rest):
                        return True
            path.pop(cur, None)
            return False

        return path if extend(start, ((1 << self.n) - 1) & ~home) else None


def draw(people: list[int], forbidden: set[tuple[int, int]], *, single_loop: bool, rng) -> dict[int, int]:
    """{giver: recipient} for everyone in `people`, a permutation with no self-pair and no pair in `forbidden`, chosen
    with `rng` (the route passes secrets.SystemRandom()). single_loop: one cycle through everyone. Raises Impossible
    rather than drop a rule; ties for "fewest" go to the earliest in `people` (the route passes name order)."""
    people = list(dict.fromkeys(people))
    n = len(people)
    if n < pairings.MIN_ROSTER:
        raise Impossible(f"The roster needs at least {pairings.MIN_ROSTER} people.")
    out_mask, into_mask = [0] * n, [0] * n
    for i, g in enumerate(people):
        for j, r in enumerate(people):
            if i != j and (g, r) not in forbidden:
                out_mask[i] |= 1 << j
                into_mask[j] |= 1 << i
    counts = [m.bit_count() for m in out_mask]
    fewest = min(range(n), key=counts.__getitem__)
    if counts[fewest] == 0:
        raise _impossible(NONE_LEFT, people[fewest])
    for j in range(n):
        if not into_mask[j]:
            raise _impossible(NO_GIVER, people[j])
    why = {"count": counts[fewest], "people": "person" if counts[fewest] == 1 else "people"}
    if not _matching_exists(out_mask, n):
        raise _impossible(NO_DRAW, people[fewest], **why)
    if single_loop and not (_reaches_everyone(out_mask, n) and _reaches_everyone(into_mask, n)):
        raise _impossible(NO_DRAW, people[fewest], **why)           # one loop needs everyone to lead to everyone
    search = _Search(out_mask, into_mask, rng)
    try:
        found = search.loop() if single_loop else search.assign()
    except _GaveUp:
        raise _impossible(GAVE_UP, people[fewest], steps=search.limit, **why) from None
    if found is None:
        raise _impossible(NO_DRAW, people[fewest], **why)
    return {people[i]: people[j] for i, j in found.items()}


# ---------------------------------------------------------------- the rules
def forbidden_pairs(con, edition_id: int, lookback: int) -> set[tuple[int, int]]:
    """Directed (giver, recipient) pairs the draw may not make for this edition (the rules in the module docstring)."""
    ed = pairings._edition(con, edition_id)
    homes = {r["id"]: (r["household"] or "").strip().casefold() for r in con.execute(
        "SELECT p.id, p.household FROM edition_people ep JOIN person p ON p.id = ep.person_id WHERE ep.edition_id = ?",
        (edition_id,))}
    out = {(a, b) for a in homes for b in homes if homes[a] and homes[a] == homes[b]}
    earlier = [r[0] for r in con.execute("SELECT id FROM edition WHERE exchange_id = ? AND year < ? "
                                         "ORDER BY year DESC LIMIT ?", (ed["exchange_id"], ed["year"], lookback))]
    for i, eid in enumerate(earlier):
        rows = {(r[0], r[1]) for r in con.execute("SELECT giver_id, recipient_id FROM pairing WHERE edition_id = ? "
                                                  "AND recipient_id IS NOT NULL", (eid,))}
        out |= rows
        if i == 0:                                                   # last year: no drawing back your giver
            out |= {(r, g) for g, r in rows}
    for a, b in con.execute("SELECT a_id, b_id FROM draw_exclusion WHERE edition_id = ?", (edition_id,)):
        out |= {(a, b), (b, a)}
    return {(g, r) for g, r in out if g != r and g in homes and r in homes}


# ---------------------------------------------------------------- preview and publish
def _has_rows(con, edition_id):
    return con.execute("SELECT 1 FROM pairing WHERE edition_id = ? LIMIT 1", (edition_id,)).fetchone() is not None


def preview(con, edition_id: int, lookback: int, single_loop: bool, rng) -> dict:
    """Draw for an open edition with no pairing rows (409 otherwise) and keep the result for publish(). Returns
    {"preview": [{"giver_id","giver","recipient_id","recipient"}] in giver-name order, "token", "expires_in"}.
    Impossible is 400 with the person's name; so is a roster under 2."""
    ed = pairings._edition(con, edition_id)
    if ed["status"] != "open":
        raise pairings._not_open(ed["status"])
    if _has_rows(con, edition_id):
        raise ApiError(409, ALREADY_ENTERED)
    roster = pairings._roster(con, edition_id)
    try:
        out = draw(list(roster), forbidden_pairs(con, edition_id, lookback), single_loop=single_loop, rng=rng)
    except Impossible as e:
        raise ApiError(400, e.named(roster)) from None
    pairs = [(g, out[g]) for g in roster]
    token = secrets.token_urlsafe(32)
    with transaction(con):
        con.execute("DELETE FROM draw_preview WHERE edition_id = ? OR created_at <= ?",
                    (edition_id, common.now() - PREVIEW_SECONDS))
        con.execute("INSERT INTO draw_preview (token, edition_id, lookback, pairs, created_at) VALUES (?, ?, ?, ?, ?)",
                    (token, edition_id, lookback, json.dumps(pairs), common.now()))
    return {"preview": [{"giver_id": g, "giver": roster[g], "recipient_id": r, "recipient": roster[r]} for g, r in pairs],
            "token": token, "expires_in": PREVIEW_SECONDS}


def publish(con, edition_id: int, token: str) -> None:
    """Write the previewed draw and mark the edition paired, all in one transaction. 404 for no such edition; 400 for
    a token that is unknown, used, replaced, expired or another edition's; 409 when the edition is no longer open,
    has pairing rows, has a different roster, or one of the pairs is now forbidden. Nothing changes on an error."""
    with transaction(con):
        ed = pairings._edition(con, edition_id)
        row = con.execute("SELECT * FROM draw_preview WHERE token = ?", (token,)).fetchone()
        if row is None or row["edition_id"] != edition_id or common.now() - row["created_at"] >= PREVIEW_SECONDS:
            raise ApiError(400, STALE_TOKEN)
        if ed["status"] != "open":
            raise pairings._not_open(ed["status"])
        if _has_rows(con, edition_id):
            raise ApiError(409, "Names were entered for this year after the draw. Draw again once they're cleared.")
        pairs = [(g, r) for g, r in json.loads(row["pairs"])]
        if {g for g, _ in pairs} != set(pairings._roster(con, edition_id)):
            raise ApiError(409, "The roster changed since the draw. Draw again.")
        if set(pairs) & forbidden_pairs(con, edition_id, row["lookback"]):
            raise ApiError(409, "The rules changed since the draw. Draw again.")
        con.execute("DELETE FROM draw_preview WHERE token = ?", (token,))
        pairings.save_draft_in_transaction(con, edition_id, pairs)
        pairings.mark_paired_in_transaction(con, edition_id)


# ---------------------------------------------------------------- manual exclusions
def exclusions(con, edition_id: int) -> list[dict]:
    """[{"a_id","a","b_id","b"}]: each pair once, the name that sorts first as a, in name order."""
    pairings._edition(con, edition_id)
    rows = con.execute("SELECT x.a_id, a.name AS a, x.b_id, b.name AS b FROM draw_exclusion x "
                       "JOIN person a ON a.id = x.a_id JOIN person b ON b.id = x.b_id WHERE x.edition_id = ?",
                       (edition_id,))
    out = []
    for r in rows:
        first, second = sorted([(r["a"], r["a_id"]), (r["b"], r["b_id"])], key=lambda p: (p[0].casefold(), p[1]))
        out.append({"a_id": first[1], "a": first[0], "b_id": second[1], "b": second[0]})
    return sorted(out, key=lambda p: (p["a"].casefold(), p["b"].casefold(), p["a_id"], p["b_id"]))


def set_exclusions(con, edition_id: int, pairs: list[tuple[int, int]]) -> None:
    """Replace the edition's manual exclusions. Both people must be on the roster and different (400); duplicates and
    reversed duplicates collapse. Nothing changes on an error."""
    with transaction(con):
        pairings._edition(con, edition_id)
        roster = pairings._roster(con, edition_id)
        keep = set()
        for a, b in pairs:
            if a == b:
                raise ApiError(400, "A pair needs two different people.")
            for pid in (a, b):
                if pid not in roster:
                    name = con.execute("SELECT name FROM person WHERE id = ?", (pid,)).fetchone()
                    raise ApiError(400, f"{name[0] if name else 'That person'} isn't on this edition's roster.")
            keep.add((min(a, b), max(a, b)))
        con.execute("DELETE FROM draw_exclusion WHERE edition_id = ?", (edition_id,))
        con.executemany("INSERT INTO draw_exclusion (edition_id, a_id, b_id) VALUES (?, ?, ?)",
                        [(edition_id, a, b) for a, b in sorted(keep)])
