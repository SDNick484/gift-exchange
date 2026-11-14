import json
import random
import time

import pytest

import draw
import pairings
from conftest import mk_edition, paired_edition, paired_ready_edition, put_roster, save_pairs, set_household


# ---------------------------------------------------------------- the plan's Task 10 tests
def test_draw_respects_every_constraint_over_many_seeds():
    people = list(range(1, 13)); forbidden = {(1, 2), (2, 1), (3, 4), (4, 3), (5, 6)}
    for seed in range(200):
        out = draw.draw(people, forbidden, single_loop=False, rng=random.Random(seed))
        assert sorted(out) == people and sorted(out.values()) == people
        assert all(g != r and (g, r) not in forbidden for g, r in out.items())


def test_single_loop_is_one_cycle():
    out = draw.draw(list(range(1, 9)), set(), single_loop=True, rng=random.Random(1))
    seen, cur = set(), 1
    while cur not in seen: seen.add(cur); cur = out[cur]
    assert len(seen) == 8


def test_impossible_names_the_person():
    with pytest.raises(draw.Impossible, match="3 has no one left"):
        draw.draw([1, 2, 3], {(3, 1), (3, 2)}, single_loop=False, rng=random.Random(0))


def test_preview_writes_nothing_and_publish_marks_paired(admin, con, x):
    e = paired_ready_edition(admin, x)
    prev = admin.post(f"/api/admin/editions/{e}/draw", json={"lookback": 1, "single_loop": False}).get_json()
    assert con.execute("SELECT COUNT(*) FROM pairing WHERE edition_id=?", (e,)).fetchone()[0] == 0
    assert admin.post(f"/api/admin/editions/{e}/draw/publish", json={"token": prev["token"]}).status_code == 200
    assert con.execute("SELECT status FROM edition WHERE id=?", (e,)).fetchone()[0] == "paired"


# ---------------------------------------------------------------- helpers
def add_people(con, x, *names):
    """More people in x's exchange; returns their ids in order."""
    return [con.execute("INSERT INTO person (exchange_id, name) VALUES (?, ?)", (x.id, n)).lastrowid for n in names]


def five(admin, con, x):
    """x plus Riley and Casey: (alex, sam, jordan, riley, casey)."""
    riley, casey = add_people(con, x, "Riley", "Casey")
    return x.alex, x.sam, x.jordan, riley, casey


def history(admin, x, year, ids, pairs):
    """An edition for `year` with roster `ids` and these (giver, recipient) rows, left open: the look-back takes
    earlier editions whatever their status."""
    e = mk_edition(admin, x.id, year)
    put_roster(admin, e, ids)
    save_pairs(admin, e, pairs)
    return e


def is_cycle(out):
    start = next(iter(out))
    seen, cur = set(), start
    while cur not in seen: seen.add(cur); cur = out[cur]
    return len(seen) == len(out) and cur == start


def do_draw(admin, e, lookback=1, single_loop=False):
    return admin.post(f"/api/admin/editions/{e}/draw", json={"lookback": lookback, "single_loop": single_loop})


def publish(admin, e, token):
    return admin.post(f"/api/admin/editions/{e}/draw/publish", json={"token": token})


def pairs_of(con, e):
    return {(r[0], r[1]) for r in con.execute("SELECT giver_id, recipient_id FROM pairing WHERE edition_id = ?", (e,))}


# ---------------------------------------------------------------- draw(): the algorithm
def test_single_loop_keeps_the_rules_over_many_seeds():
    people = list(range(1, 13)); forbidden = {(1, 2), (2, 1), (3, 4), (4, 3), (5, 6), (7, 8), (8, 7)}
    for seed in range(100):
        out = draw.draw(people, forbidden, single_loop=True, rng=random.Random(seed))
        assert sorted(out) == people and sorted(out.values()) == people and is_cycle(out)
        assert all(g != r and (g, r) not in forbidden for g, r in out.items())


def test_draws_vary_with_the_rng():
    seen = {tuple(sorted(draw.draw(list(range(1, 7)), set(), single_loop=False, rng=random.Random(s)).items()))
            for s in range(40)}
    assert len(seen) > 10
    loops = {tuple(sorted(draw.draw(list(range(1, 7)), set(), single_loop=True, rng=random.Random(s)).items()))
             for s in range(40)}
    assert len(loops) > 10


def big_family(n=40, seed=7):
    """n people in households of 2 to 4, plus three earlier years' pairings and last year's reverses: what a large
    exchange with lookback 3 forbids."""
    rng = random.Random(seed)
    people = list(range(1, n + 1))
    forbidden, i = set(), 0
    while i < n:
        size = rng.choice((2, 3, 4))
        house = people[i:i + size]
        forbidden |= {(a, b) for a in house for b in house if a != b}
        i += size
    for year in range(3):
        last = draw.draw(people, forbidden, single_loop=False, rng=rng)
        forbidden |= set(last.items())
        if year == 2:
            forbidden |= {(r, g) for g, r in last.items()}
    return people, forbidden


def test_a_large_constrained_family_resolves_fast():
    people, forbidden = big_family()
    started = time.monotonic()
    for seed in range(20):
        for loop in (False, True):
            out = draw.draw(people, forbidden, single_loop=loop, rng=random.Random(seed))
            assert sorted(out.values()) == people and not set(out.items()) & forbidden and all(g != r for g, r in out.items())
            assert not loop or is_cycle(out)
    assert time.monotonic() - started < 10


def test_nobody_may_draw_someone():
    with pytest.raises(draw.Impossible, match="^No one is allowed to draw 3.$"):
        draw.draw([1, 2, 3], {(1, 3), (2, 3)}, single_loop=False, rng=random.Random(0))


def test_no_complete_draw_still_names_the_person_with_fewest_choices():
    # 1, 2 and 3 may each draw only 4: everyone has someone, but no complete draw exists.
    forbidden = {(g, r) for g in (1, 2, 3) for r in (1, 2, 3)}
    with pytest.raises(draw.Impossible) as got:
        draw.draw([1, 2, 3, 4], forbidden, single_loop=False, rng=random.Random(0))
    assert got.value.person == 1 and str(got.value) == ("No draw keeps every rule. Start with 1, who is allowed to "
                                                        "draw only 1 person.")
    assert got.value.named({1: "Alex"}).startswith("No draw keeps every rule. Start with Alex,")


def test_single_loop_impossible_is_reported():
    # Two pairs that may only draw each other: a valid draw exists, but not one loop through everyone.
    forbidden = {(g, r) for g in (1, 2) for r in (3, 4)} | {(g, r) for g in (3, 4) for r in (1, 2)}
    assert draw.draw([1, 2, 3, 4], forbidden, single_loop=False, rng=random.Random(0)) in ({1: 2, 2: 1, 3: 4, 4: 3},)
    with pytest.raises(draw.Impossible, match="Start with 1"):
        draw.draw([1, 2, 3, 4], forbidden, single_loop=True, rng=random.Random(0))


def test_single_loop_through_two_closed_groups_is_reported_at_once():
    people = list(range(1, 31))
    halves = (set(range(1, 16)), set(range(16, 31)))
    forbidden = {(g, r) for g in halves[0] for r in halves[1]} | {(g, r) for g in halves[1] for r in halves[0]}
    started = time.monotonic()
    with pytest.raises(draw.Impossible, match="^No draw keeps every rule. Start with 1,"):
        draw.draw(people, forbidden, single_loop=True, rng=random.Random(0))
    assert time.monotonic() - started < 0.5
    assert len(draw.draw(people, forbidden, single_loop=False, rng=random.Random(0))) == 30


def test_step_cap_gives_up_with_the_person_named(monkeypatch):
    monkeypatch.setattr(draw, "MAX_STEPS", 1)
    with pytest.raises(draw.Impossible) as got:
        draw.draw(list(range(1, 9)), set(), single_loop=True, rng=random.Random(0))
    assert str(got.value).startswith("The draw gave up after 1 tries") and got.value.person == 1


def test_a_roster_under_two_is_impossible():
    for people in ([], [1]):
        with pytest.raises(draw.Impossible, match="at least 2 people"):
            draw.draw(people, set(), single_loop=False, rng=random.Random(0))


def test_two_people_draw_each_other():
    for loop in (False, True):
        assert draw.draw([5, 9], set(), single_loop=loop, rng=random.Random(0)) == {5: 9, 9: 5}


def test_never_relaxes_a_rule():
    forbidden = {(1, 2), (2, 1)}                                    # 3 people, 1 and 2 may not draw each other
    with pytest.raises(draw.Impossible):
        draw.draw([1, 2, 3], forbidden, single_loop=False, rng=random.Random(0))


# ---------------------------------------------------------------- forbidden_pairs()
def test_household_is_forbidden_both_ways(admin, con, x):
    set_household(admin, [x.alex, x.sam], "  The Smiths ")
    admin.patch(f"/api/admin/people/{x.jordan}", json={"household": "the smiths"})
    e = paired_ready_edition(admin, x)
    a, s, j = x.alex, x.sam, x.jordan
    assert draw.forbidden_pairs(con, e, 1) == {(a, s), (s, a), (a, j), (j, a), (s, j), (j, s)}


def test_blank_household_forbids_nothing(admin, con, x):
    set_household(admin, [x.alex, x.sam], "   ")
    assert draw.forbidden_pairs(con, paired_ready_edition(admin, x), 1) == set()


def test_lookback_takes_the_newest_earlier_editions(admin, con, x):
    a, s, j, r, c = five(admin, con, x)
    everyone = [a, s, j, r, c]
    history(admin, x, 2022, everyone, [(a, j)])
    history(admin, x, 2023, everyone, [(a, r), (s, None)])          # a draft row with no recipient is skipped
    history(admin, x, 2024, everyone, [(a, c)])
    history(admin, x, 2025, everyone, [(a, s), (j, r)])
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, everyone)
    last_year = {(a, s), (j, r)}
    reverse = {(s, a), (r, j)}                                       # the reverse of last year's pairs
    assert draw.forbidden_pairs(con, e, 1) == last_year | reverse
    assert draw.forbidden_pairs(con, e, 2) == last_year | reverse | {(a, c)}
    assert draw.forbidden_pairs(con, e, 3) == last_year | reverse | {(a, c), (a, r)}
    assert (c, a) not in draw.forbidden_pairs(con, e, 3)           # the reverse of two years back is allowed


def test_reverse_of_last_year_is_blocked_whatever_the_lookback(admin, con, x):
    paired_edition(admin, x, 2025, [(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)])
    e = paired_ready_edition(admin, x, 2026)
    for lookback in (1, 3):
        f = draw.forbidden_pairs(con, e, lookback)
        assert (x.sam, x.alex) in f and (x.jordan, x.sam) in f and (x.alex, x.jordan) in f
    # With three people every complete draw repeats or reverses last year's.
    with pytest.raises(draw.Impossible):
        draw.draw([x.alex, x.sam, x.jordan], draw.forbidden_pairs(con, e, 1), single_loop=False, rng=random.Random(0))


def test_reverse_of_two_years_back_is_not_blocked(admin, con, x):
    a, s, j, r, c = five(admin, con, x)
    everyone = [a, s, j, r, c]
    history(admin, x, 2024, everyone, [(a, s)])
    history(admin, x, 2025, everyone, [(j, r)])
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, everyone)
    for lookback in (1, 2, 3):
        f = draw.forbidden_pairs(con, e, lookback)
        assert (s, a) not in f and (r, j) in f
    assert (a, s) in draw.forbidden_pairs(con, e, 2) and (a, s) not in draw.forbidden_pairs(con, e, 1)


def test_later_editions_are_not_history(admin, con, x):
    e25 = paired_ready_edition(admin, x, 2025)
    paired_edition(admin, x, 2026, [(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)])
    assert draw.forbidden_pairs(con, e25, 3) == set()


def test_reverse_rule_leaves_the_warnings_alone(admin, con, x):
    paired_edition(admin, x, 2025, [(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)])
    e = paired_ready_edition(admin, x, 2026)
    save_pairs(admin, e, [(x.sam, x.alex), (x.alex, x.jordan), (x.jordan, x.sam)])  # every pair reversed
    assert pairings.warnings(con, e) == []


def test_manual_exclusions_both_ways(admin, con, x):
    e = paired_ready_edition(admin, x)
    assert admin.put(f"/api/admin/editions/{e}/exclusions", json={"pairs": [[x.jordan, x.alex]]}).status_code == 200
    assert draw.forbidden_pairs(con, e, 1) == {(x.alex, x.jordan), (x.jordan, x.alex)}


def test_people_off_the_roster_are_ignored(admin, con, x):
    riley, = add_people(con, x, "Riley")
    set_household(admin, [x.alex, riley], "Home")
    history(admin, x, 2025, [x.alex, x.sam, riley], [(x.alex, riley), (riley, x.sam)])
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, [x.alex, x.sam, x.jordan])
    assert draw.forbidden_pairs(con, e, 1) == set()


# ---------------------------------------------------------------- the draw route
def test_preview_lists_names_sorted_by_giver_and_keeps_the_rules(admin, con, x):
    a, s, j, r, c = five(admin, con, x)
    set_household(admin, [a, s], "One")
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, [a, s, j, r, c])
    admin.put(f"/api/admin/editions/{e}/exclusions", json={"pairs": [[j, r]]})
    for _ in range(10):
        got = do_draw(admin, e).get_json()
        assert [p["giver"] for p in got["preview"]] == ["Alex", "Casey", "Jordan", "Riley", "Sam"]
        assert all(set(p) == {"giver_id", "giver", "recipient_id", "recipient"} for p in got["preview"])
        out = {p["giver_id"]: p["recipient_id"] for p in got["preview"]}
        assert sorted(out.values()) == sorted(out) and not set(out.items()) & {(a, s), (s, a), (j, r), (r, j)}
        assert isinstance(got["token"], str) and len(got["token"]) >= 40
    assert pairs_of(con, e) == set()
    assert con.execute("SELECT status FROM edition WHERE id = ?", (e,)).fetchone()[0] == "open"


def test_single_loop_route(admin, con, x):
    a, s, j, r, c = five(admin, con, x)
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, [a, s, j, r, c])
    got = do_draw(admin, e, single_loop=True).get_json()
    assert is_cycle({p["giver_id"]: p["recipient_id"] for p in got["preview"]})


def test_publish_writes_what_was_previewed(admin, family, con, x):
    e = paired_ready_edition(admin, x)
    got = do_draw(admin, e).get_json()
    assert publish(admin, e, got["token"]).get_json() == {"ok": True}
    assert pairs_of(con, e) == {(p["giver_id"], p["recipient_id"]) for p in got["preview"]}
    seen = family.get(f"/api/x/{x.slug}").get_json()["pairings"]
    assert [(p["giver"], p["recipient"]) for p in seen] == [(p["giver"], p["recipient"]) for p in got["preview"]]


def test_draw_is_409_unless_open_with_no_rows(admin, con, x):
    e = paired_ready_edition(admin, x)
    save_pairs(admin, e, [(x.alex, None)])                          # even a draft row with no recipient
    r = do_draw(admin, e)
    assert r.status_code == 409 and "already" in r.get_json()["error"]
    save_pairs(admin, e, [])
    assert do_draw(admin, e).status_code == 200
    e2 = paired_edition(admin, x, 2027, [(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)])
    assert do_draw(admin, e2).status_code == 409
    admin.post(f"/api/admin/editions/{e2}/unpair", json={})
    admin.put(f"/api/admin/editions/{e2}/pairings", json={"pairs": []})
    admin.patch(f"/api/admin/editions/{e2}", json={"status": "closed"})
    assert do_draw(admin, e2).status_code == 409


def test_draw_impossible_is_400_with_the_name(admin, con, x):
    e = paired_ready_edition(admin, x)
    admin.put(f"/api/admin/editions/{e}/exclusions", json={"pairs": [[x.jordan, x.alex], [x.sam, x.jordan]]})
    r = do_draw(admin, e)
    assert r.status_code == 400 and r.get_json() == {"error": "Jordan has no one left they're allowed to draw."}
    assert con.execute("SELECT COUNT(*) FROM draw_preview").fetchone()[0] == 0


def test_draw_impossible_search_names_the_first_most_constrained(admin, x):
    set_household(admin, [x.alex, x.sam], "Alex & Sam")
    e = paired_ready_edition(admin, x)
    r = do_draw(admin, e)
    assert r.status_code == 400 and r.get_json()["error"] == ("No draw keeps every rule. Start with Alex, who is "
                                                             "allowed to draw only 1 person.")


def test_draw_needs_two_people(admin, x):
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, [x.alex])
    r = do_draw(admin, e)
    assert r.status_code == 400 and r.get_json()["error"] == "The roster needs at least 2 people."


def test_draw_bad_bodies_are_400(admin, con, x):
    e = paired_ready_edition(admin, x)
    for body in ({"lookback": 0}, {"lookback": 4}, {"lookback": True}, {"lookback": "1"}, {"lookback": 1.0},
                 {"lookback": None}, {"single_loop": 1}, {"single_loop": "yes"}, {"single_loop": None}):
        assert admin.post(f"/api/admin/editions/{e}/draw", json=body).status_code == 400, body
    assert con.execute("SELECT COUNT(*) FROM draw_preview").fetchone()[0] == 0


def test_draw_defaults_to_lookback_1_any_draw(admin, x):
    e = paired_ready_edition(admin, x)
    assert admin.post(f"/api/admin/editions/{e}/draw", json={}).status_code == 200


def test_draw_routes_are_admin_only_and_guarded(admin, family, client, x):
    e = paired_ready_edition(admin, x)
    tok = do_draw(admin, e).get_json()["token"]
    assert family.post(f"/api/admin/editions/{e}/draw", json={}).status_code == 403
    assert family.post(f"/api/admin/editions/{e}/draw/publish", json={"token": tok}).status_code == 403
    assert family.get(f"/api/admin/editions/{e}/exclusions").status_code == 403
    assert family.put(f"/api/admin/editions/{e}/exclusions", json={"pairs": []}).status_code == 403
    for url in (f"/api/admin/editions/{e}/draw", f"/api/admin/editions/{e}/draw/publish"):
        assert admin.post(url, json={"token": tok}, headers={"X-Exchange": ""}).status_code == 400
        assert admin.post(url, json={"token": tok}, headers={"Origin": "https://evil.example.com"}).status_code == 403
        assert admin.post(url, data="[]", content_type="application/json").status_code == 400
    assert admin.put(f"/api/admin/editions/{e}/exclusions", json={"pairs": []}, headers={"X-Exchange": ""}).status_code == 400
    assert admin.get("/api/admin/editions/999/exclusions").status_code == 404
    assert admin.post("/api/admin/editions/999/draw", json={}).status_code == 404
    assert admin.post("/api/admin/editions/999/draw/publish", json={"token": tok}).status_code == 404
    assert publish(admin, e, tok).status_code == 200                # none of the refused calls used it up


# ---------------------------------------------------------------- publish and the token
def test_token_lasts_ten_minutes(admin, con, x, clock):
    e = paired_ready_edition(admin, x)
    tok = do_draw(admin, e).get_json()["token"]
    clock.advance(599)
    assert publish(admin, e, tok).status_code == 200


def test_token_expires_at_ten_minutes(admin, con, x, clock):
    e = paired_ready_edition(admin, x)
    tok = do_draw(admin, e).get_json()["token"]
    clock.advance(600)
    r = publish(admin, e, tok)
    assert r.status_code == 400 and "Draw again" in r.get_json()["error"]
    assert pairs_of(con, e) == set()


def test_expired_previews_are_purged_on_the_next_draw(admin, con, x, clock):
    e1 = paired_ready_edition(admin, x, 2026)
    e2 = paired_ready_edition(admin, x, 2027)
    do_draw(admin, e1)
    clock.advance(600)
    do_draw(admin, e2)
    assert [r[0] for r in con.execute("SELECT edition_id FROM draw_preview")] == [e2]


def test_token_is_only_for_its_edition(admin, con, x):
    e1 = paired_ready_edition(admin, x, 2026)
    e2 = paired_ready_edition(admin, x, 2027)
    tok1 = do_draw(admin, e1).get_json()["token"]
    r = publish(admin, e2, tok1)
    assert r.status_code == 400 and pairs_of(con, e2) == set()
    assert publish(admin, e1, tok1).status_code == 200              # still good for its own edition


def test_token_is_single_use(admin, con, x):
    e = paired_ready_edition(admin, x)
    tok = do_draw(admin, e).get_json()["token"]
    assert publish(admin, e, tok).status_code == 200
    admin.post(f"/api/admin/editions/{e}/unpair", json={})
    admin.put(f"/api/admin/editions/{e}/pairings", json={"pairs": []})
    assert publish(admin, e, tok).status_code == 400
    assert con.execute("SELECT COUNT(*) FROM draw_preview").fetchone()[0] == 0


def test_a_redraw_replaces_the_older_preview(admin, x):
    e = paired_ready_edition(admin, x)
    old = do_draw(admin, e).get_json()["token"]
    new = do_draw(admin, e).get_json()["token"]
    assert publish(admin, e, old).status_code == 400
    assert publish(admin, e, new).status_code == 200


def test_publish_after_a_draft_was_typed_is_409(admin, con, x):
    e = paired_ready_edition(admin, x)
    tok = do_draw(admin, e).get_json()["token"]
    save_pairs(admin, e, [(x.alex, x.sam)])
    r = publish(admin, e, tok)
    assert r.status_code == 409 and pairs_of(con, e) == {(x.alex, x.sam)}
    assert con.execute("SELECT status FROM edition WHERE id = ?", (e,)).fetchone()[0] == "open"


def test_publish_after_mark_paired_elsewhere_is_409(admin, con, x):
    e = paired_ready_edition(admin, x)
    tok = do_draw(admin, e).get_json()["token"]
    save_pairs(admin, e, [(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)])
    admin.post(f"/api/admin/editions/{e}/mark-paired", json={})
    r = publish(admin, e, tok)
    assert r.status_code == 409 and pairs_of(con, e) == {(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)}


def test_publish_after_a_roster_change_is_409(admin, con, x):
    riley, = add_people(con, x, "Riley")
    e = paired_ready_edition(admin, x)
    tok = do_draw(admin, e).get_json()["token"]
    put_roster(admin, e, [x.alex, x.sam, x.jordan, riley])
    r = publish(admin, e, tok)
    assert r.status_code == 409 and "roster" in r.get_json()["error"] and pairs_of(con, e) == set()


def test_publish_after_the_rules_changed_is_409(admin, con, x):
    a, s, j, r, c = five(admin, con, x)
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, [a, s, j, r, c])
    got = do_draw(admin, e).get_json()
    first = got["preview"][0]
    admin.put(f"/api/admin/editions/{e}/exclusions", json={"pairs": [[first["giver_id"], first["recipient_id"]]]})
    resp = publish(admin, e, got["token"])
    assert resp.status_code == 409 and "rules" in resp.get_json()["error"] and pairs_of(con, e) == set()


def test_publish_rechecks_against_the_preview_lookback(admin, con, x):
    a, s, j, r, c = five(admin, con, x)
    everyone = [a, s, j, r, c]
    history(admin, x, 2024, everyone, [(a, s)])
    history(admin, x, 2025, everyone, [])
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, everyone)
    for _ in range(30):                                             # lookback 1 only looks at 2025
        got = do_draw(admin, e, lookback=1).get_json()
        if any((p["giver_id"], p["recipient_id"]) == (a, s) for p in got["preview"]):
            assert publish(admin, e, got["token"]).status_code == 200
            break
    else:
        pytest.fail("no draw gave Alex Sam in 30 tries")


def test_publish_bad_tokens_are_400(admin, con, x):
    e = paired_ready_edition(admin, x)
    do_draw(admin, e)
    for body in ({}, {"token": 5}, {"token": ""}, {"token": None}, {"token": "nope"}, {"token": "x" * 101}):
        assert admin.post(f"/api/admin/editions/{e}/draw/publish", json=body).status_code == 400, body
    assert pairs_of(con, e) == set()


def test_preview_row_holds_the_draw(admin, con, x, clock):
    e = paired_ready_edition(admin, x)
    got = do_draw(admin, e, lookback=2).get_json()
    row = con.execute("SELECT * FROM draw_preview").fetchone()
    assert (row["token"], row["edition_id"], row["lookback"], row["created_at"]) == (got["token"], e, 2, clock.t)
    assert {tuple(p) for p in json.loads(row["pairs"])} == {(p["giver_id"], p["recipient_id"]) for p in got["preview"]}


# ---------------------------------------------------------------- exclusions
def test_exclusions_round_trip_with_names(admin, con, x):
    a, s, j, r, c = five(admin, con, x)
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, [a, s, j, r, c])
    body = {"pairs": [[s, a], [a, s], [r, j], [j, r], [c, a]]}     # duplicates and reversed duplicates collapse
    assert admin.put(f"/api/admin/editions/{e}/exclusions", json=body).get_json() == {"ok": True}
    got = admin.get(f"/api/admin/editions/{e}/exclusions").get_json()
    assert got == {"pairs": [{"a_id": a, "a": "Alex", "b_id": c, "b": "Casey"},
                             {"a_id": a, "a": "Alex", "b_id": s, "b": "Sam"},
                             {"a_id": j, "a": "Jordan", "b_id": r, "b": "Riley"}]}
    assert {(row[0], row[1]) for row in con.execute("SELECT a_id, b_id FROM draw_exclusion")} == \
        {(min(a, s), max(a, s)), (min(j, r), max(j, r)), (min(a, c), max(a, c))}
    admin.put(f"/api/admin/editions/{e}/exclusions", json={"pairs": [[j, r]]})   # replaces the set
    assert [(p["a"], p["b"]) for p in admin.get(f"/api/admin/editions/{e}/exclusions").get_json()["pairs"]] == [("Jordan", "Riley")]


def test_exclusions_are_per_edition(admin, con, x):
    e1 = paired_ready_edition(admin, x, 2026)
    e2 = paired_ready_edition(admin, x, 2027)
    admin.put(f"/api/admin/editions/{e1}/exclusions", json={"pairs": [[x.alex, x.sam]]})
    assert admin.get(f"/api/admin/editions/{e2}/exclusions").get_json() == {"pairs": []}
    assert draw.forbidden_pairs(con, e2, 1) == set()


def test_exclusions_bad_shapes_are_400(admin, x):
    e = paired_ready_edition(admin, x)
    for pairs in ("x", [[1]], [[1, 2, 3]], [1, 2], [["1", "2"]], [[True, 2]], [[1.0, 2]], [{"a": 1}], None,
                  [[x.alex, x.sam]] * 1001):
        assert admin.put(f"/api/admin/editions/{e}/exclusions", json={"pairs": pairs}).status_code == 400, pairs
    assert admin.put(f"/api/admin/editions/{e}/exclusions", json={}).status_code == 400


def test_exclusions_must_be_two_people_on_the_roster(admin, con, x, other):
    riley, = add_people(con, x, "Riley")
    e = paired_ready_edition(admin, x)
    put = lambda pairs: admin.put(f"/api/admin/editions/{e}/exclusions", json={"pairs": pairs})  # noqa: E731
    r = put([[x.alex, x.alex]])
    assert r.status_code == 400 and r.get_json()["error"] == "A pair needs two different people."
    r = put([[x.alex, riley]])
    assert r.status_code == 400 and r.get_json()["error"] == "Riley isn't on this edition's roster."
    assert put([[x.alex, other.alex]]).status_code == 400
    assert put([[x.alex, 99999]]).status_code == 400
    put([[x.alex, x.sam]])
    assert put([[x.alex, x.alex]]).status_code == 400
    assert admin.get(f"/api/admin/editions/{e}/exclusions").get_json()["pairs"][0]["b"] == "Sam"  # unchanged


def test_dropping_someone_from_the_roster_drops_their_exclusions(admin, con, x):
    riley, = add_people(con, x, "Riley")
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, [x.alex, x.sam, x.jordan, riley])
    admin.put(f"/api/admin/editions/{e}/exclusions", json={"pairs": [[x.alex, riley], [x.sam, x.jordan]]})
    put_roster(admin, e, [x.alex, x.sam, x.jordan])
    assert [(p["a"], p["b"]) for p in admin.get(f"/api/admin/editions/{e}/exclusions").get_json()["pairs"]] == \
        [("Jordan", "Sam")]
    put_roster(admin, e, [x.alex, x.sam, x.jordan, riley])         # coming back doesn't bring the rule back
    assert len(admin.get(f"/api/admin/editions/{e}/exclusions").get_json()["pairs"]) == 1


def test_exclusion_rows_cascade(con, seed):
    con.execute("INSERT INTO draw_exclusion VALUES (?, ?, ?)", (seed.ed, min(seed.a, seed.b), max(seed.a, seed.b)))
    con.execute("DELETE FROM edition WHERE id = ?", (seed.ed,))
    assert con.execute("SELECT COUNT(*) FROM draw_exclusion").fetchone()[0] == 0
