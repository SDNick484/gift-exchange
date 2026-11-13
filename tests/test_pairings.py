import pytest

import pairings
from common import ApiError
from conftest import (full_cycle, mk_edition, paired_edition, paired_ready_edition, put_roster, save_pairs,
                      set_household)


# ---------------------------------------------------------------- the plan's Task 5 tests
def test_draft_survives_and_is_hidden_from_family(admin, family, con, x):     # family: unlocked non-admin client
    e = paired_ready_edition(admin, x)                                          # roster alex, sam, jordan; status open
    admin.put(f"/api/admin/editions/{e}/pairings", json={"pairs": [{"giver_id": x.alex, "recipient_id": x.sam},
                                                                   {"giver_id": x.sam, "recipient_id": None}]})
    got = admin.get(f"/api/admin/editions/{e}/pairings").get_json()
    assert {(p["giver_id"], p["recipient_id"]) for p in got["pairs"]} == {(x.alex, x.sam), (x.sam, None)}
    assert family.get(f"/api/x/{x.slug}").get_json()["pairings"] is None


def test_mark_paired_names_each_problem(admin, x):
    e = paired_ready_edition(admin, x)
    admin.put(f"/api/admin/editions/{e}/pairings", json={"pairs": [{"giver_id": x.alex, "recipient_id": x.sam},
                                                                   {"giver_id": x.jordan, "recipient_id": x.sam}]})
    r = admin.post(f"/api/admin/editions/{e}/mark-paired", json={})
    msg = r.get_json()["error"]
    assert r.status_code == 400 and "Sam isn't giving" in msg and "Sam is getting two gifts" in msg and "Alex isn't getting" in msg


def test_mark_paired_then_family_sees_sorted_list(admin, family, x):
    e = paired_ready_edition(admin, x)
    full_cycle(admin, e, [x.alex, x.sam, x.jordan])
    assert admin.post(f"/api/admin/editions/{e}/mark-paired", json={}).status_code == 200
    names = [(p["giver"], p["recipient"]) for p in family.get(f"/api/x/{x.slug}").get_json()["pairings"]]
    assert names == [("Alex", "Sam"), ("Jordan", "Alex"), ("Sam", "Jordan")]


def test_household_and_repeat_are_warnings_not_problems(admin, con, x):
    set_household(admin, [x.alex, x.sam], "Alex & Sam")
    paired_edition(admin, x, 2025, [(x.alex, x.jordan), (x.jordan, x.sam), (x.sam, x.alex)])
    e26 = paired_ready_edition(admin, x, 2026)
    full_cycle(admin, e26, [x.alex, x.jordan, x.sam])                       # alex→jordan again, sam→alex same household
    got = admin.get(f"/api/admin/editions/{e26}/pairings").get_json()
    assert got["problems"] == [] and any("same household" in w for w in got["warnings"]) and any("last year" in w for w in got["warnings"])
    assert admin.post(f"/api/admin/editions/{e26}/mark-paired", json={}).status_code == 200


def test_cannot_edit_pairs_once_paired(admin, x):
    e = paired_edition(admin, x, 2026, [(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)])
    assert admin.put(f"/api/admin/editions/{e}/pairings", json={"pairs": []}).status_code == 409
    assert admin.post(f"/api/admin/editions/{e}/unpair", json={}).status_code == 200


# ---------------------------------------------------------------- exact messages
def test_problem_messages_are_worded_from_roster_names(admin, con, x):
    e = paired_ready_edition(admin, x)
    assert pairings.problems(con, e) == ["Alex isn't giving to anyone yet.", "Jordan isn't giving to anyone yet.",
                                         "Sam isn't giving to anyone yet.", "Alex isn't getting a gift.",
                                         "Jordan isn't getting a gift.", "Sam isn't getting a gift."]
    save_pairs(admin, e, [(x.alex, x.sam), (x.sam, x.sam), (x.jordan, x.sam)])
    assert pairings.problems(con, e) == ["Sam can't give to themselves.",
                                         "Sam is getting three gifts (from Alex, Jordan and Sam).",
                                         "Alex isn't getting a gift.", "Jordan isn't getting a gift."]
    save_pairs(admin, e, [(x.alex, x.sam), (x.jordan, x.sam), (x.sam, x.alex)])
    assert pairings.problems(con, e) == ["Sam is getting two gifts (from Alex and Jordan).",
                                         "Jordan isn't getting a gift."]


def test_a_roster_of_fewer_than_two_is_a_problem(admin, con, x):
    e = mk_edition(admin, x.id, 2026)
    assert pairings.problems(con, e) == ["The roster needs at least 2 people."]
    put_roster(admin, e, [x.alex])
    assert pairings.problems(con, e) == ["The roster needs at least 2 people."]
    r = admin.post(f"/api/admin/editions/{e}/mark-paired", json={})
    assert r.status_code == 400 and r.get_json()["error"] == "The roster needs at least 2 people."


def test_mark_paired_joins_every_problem_with_semicolons(admin, con, x):
    e = paired_ready_edition(admin, x)
    msg = admin.post(f"/api/admin/editions/{e}/mark-paired", json={}).get_json()["error"]
    assert msg == "; ".join(pairings.problems(con, e)) and msg.count("; ") == 5
    assert con.execute("SELECT status FROM edition WHERE id = ?", (e,)).fetchone()[0] == "open"


def test_warning_messages_and_pair_dedupe(admin, con, x):
    set_household(admin, [x.alex, x.sam], "Same")
    paired_edition(admin, x, 2025, [(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)])
    e = paired_ready_edition(admin, x, 2026)
    save_pairs(admin, e, [(x.alex, x.sam), (x.sam, x.alex), (x.jordan, None)])
    assert pairings.warnings(con, e) == ["Alex and Sam are in the same household.", "Alex had Sam last year too."]


def test_last_year_means_the_newest_earlier_edition(admin, con, x):
    paired_edition(admin, x, 2024, [(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)])
    paired_edition(admin, x, 2025, [(x.alex, x.jordan), (x.jordan, x.sam), (x.sam, x.alex)])
    e = paired_ready_edition(admin, x, 2026)
    full_cycle(admin, e, [x.alex, x.sam, x.jordan])            # 2024's pairs again, not 2025's
    assert pairings.warnings(con, e) == []
    e23 = paired_ready_edition(admin, x, 2023)                 # nothing before it
    full_cycle(admin, e23, [x.alex, x.sam, x.jordan])
    assert pairings.warnings(con, e23) == []


def test_household_warning_needs_a_label_on_both(admin, con, x):
    set_household(admin, [x.alex], "Alex & Sam")
    e = paired_ready_edition(admin, x)
    full_cycle(admin, e, [x.alex, x.sam, x.jordan])
    assert pairings.warnings(con, e) == []


# ---------------------------------------------------------------- save and validate
def test_save_replaces_every_row(admin, con, x):
    e = paired_ready_edition(admin, x)
    save_pairs(admin, e, [(x.alex, x.sam), (x.sam, None)])
    save_pairs(admin, e, [(x.jordan, x.alex)])
    rows = con.execute("SELECT giver_id, recipient_id FROM pairing WHERE edition_id = ?", (e,)).fetchall()
    assert [tuple(r) for r in rows] == [(x.jordan, x.alex)]
    save_pairs(admin, e, [])
    assert con.execute("SELECT COUNT(*) FROM pairing WHERE edition_id = ?", (e,)).fetchone()[0] == 0


def test_people_off_the_roster_are_400_and_nothing_changes(admin, con, x):
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, [x.alex, x.sam])
    save_pairs(admin, e, [(x.alex, x.sam)])
    for pairs in ([{"giver_id": x.jordan, "recipient_id": x.sam}], [{"giver_id": x.alex, "recipient_id": x.jordan}],
                  [{"giver_id": 99999, "recipient_id": x.sam}]):
        r = admin.put(f"/api/admin/editions/{e}/pairings", json={"pairs": pairs})
        assert r.status_code == 400, pairs
    assert admin.put(f"/api/admin/editions/{e}/pairings",
                     json={"pairs": [{"giver_id": x.jordan, "recipient_id": x.sam}]}).get_json()["error"] == \
        "Jordan isn't on this edition's roster."
    assert [tuple(r) for r in con.execute("SELECT giver_id, recipient_id FROM pairing WHERE edition_id = ?", (e,))] \
        == [(x.alex, x.sam)]


def test_a_giver_twice_is_400(admin, x):
    e = paired_ready_edition(admin, x)
    r = admin.put(f"/api/admin/editions/{e}/pairings", json={"pairs": [{"giver_id": x.alex, "recipient_id": x.sam},
                                                                       {"giver_id": x.alex, "recipient_id": x.jordan}]})
    assert r.status_code == 400 and r.get_json()["error"] == "Alex is listed twice as a giver."


@pytest.mark.parametrize("body", [{}, {"pairs": "x"}, {"pairs": [1]}, {"pairs": [{"giver_id": "1", "recipient_id": None}]},
                                  {"pairs": [{"giver_id": True, "recipient_id": None}]},
                                  {"pairs": [{"giver_id": 1, "recipient_id": "2"}]},
                                  {"pairs": [{"giver_id": None, "recipient_id": 1}]}, {"pairs": [{"recipient_id": 1}]}])
def test_bad_shapes_are_400(admin, x, body):
    e = paired_ready_edition(admin, x)
    assert admin.put(f"/api/admin/editions/{e}/pairings", json=body).status_code == 400


def test_a_missing_recipient_key_is_a_draft_row(admin, con, x):
    e = paired_ready_edition(admin, x)
    assert admin.put(f"/api/admin/editions/{e}/pairings", json={"pairs": [{"giver_id": x.alex}]}).status_code == 200
    assert [tuple(r) for r in con.execute("SELECT giver_id, recipient_id FROM pairing WHERE edition_id = ?", (e,))] \
        == [(x.alex, None)]


def test_closed_and_missing_editions(admin, con, x):
    e = paired_ready_edition(admin, x)
    admin.patch(f"/api/admin/editions/{e}", json={"status": "closed"})
    assert admin.put(f"/api/admin/editions/{e}/pairings", json={"pairs": []}).status_code == 409
    assert admin.post(f"/api/admin/editions/{e}/mark-paired", json={}).status_code == 409
    assert admin.post(f"/api/admin/editions/{e}/unpair", json={}).status_code == 409
    assert admin.get(f"/api/admin/editions/{e}/pairings").status_code == 200
    for r in (admin.get("/api/admin/editions/9999/pairings"),
              admin.put("/api/admin/editions/9999/pairings", json={"pairs": []}),
              admin.post("/api/admin/editions/9999/mark-paired", json={}), admin.post("/api/admin/editions/9999/unpair", json={})):
        assert r.status_code == 404


def test_save_draft_checks_status_in_the_module(admin, con, x):
    e = paired_edition(admin, x, 2026, [(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)])
    with pytest.raises(ApiError) as err:
        pairings.save_draft(con, e, [])
    assert err.value.status == 409


def test_mark_paired_twice_is_409(admin, x):
    e = paired_edition(admin, x, 2026, [(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)])
    assert admin.post(f"/api/admin/editions/{e}/mark-paired", json={}).status_code == 409


# ---------------------------------------------------------------- visibility
def test_unpair_hides_again_and_keeps_rows(admin, family, con, x):
    e = paired_edition(admin, x, 2026, [(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)])
    assert family.get(f"/api/x/{x.slug}").get_json()["pairings"] is not None
    assert admin.post(f"/api/admin/editions/{e}/unpair", json={}).status_code == 200
    assert family.get(f"/api/x/{x.slug}").get_json()["pairings"] is None
    assert con.execute("SELECT COUNT(*) FROM pairing WHERE edition_id = ?", (e,)).fetchone()[0] == 3
    got = admin.get(f"/api/admin/editions/{e}/pairings").get_json()
    assert got["status"] == "open" and len(got["pairs"]) == 3 and got["problems"] == []


def test_visible_rules(admin, con, x):
    e = paired_ready_edition(admin, x)
    save_pairs(admin, e, [(x.sam, x.alex), (x.alex, None)])
    assert pairings.visible(con, e, admin=False) is None
    assert pairings.visible(con, e, admin=True) == [
        {"giver_id": x.alex, "giver": "Alex", "recipient_id": None, "recipient": None},
        {"giver_id": x.sam, "giver": "Sam", "recipient_id": x.alex, "recipient": "Alex"}]
    full_cycle(admin, e, [x.alex, x.sam, x.jordan])
    admin.post(f"/api/admin/editions/{e}/mark-paired", json={})
    assert len(pairings.visible(con, e, admin=False)) == 3
    admin.patch(f"/api/admin/editions/{e}", json={"status": "closed"})       # closed still shows them
    assert len(pairings.visible(con, e, admin=False)) == 3


def test_an_admin_cookie_does_not_change_the_family_page(admin, x):
    e = paired_ready_edition(admin, x)
    save_pairs(admin, e, [(x.alex, x.sam)])
    assert admin.post("/api/unlock", json={"password": "pw12"}).status_code == 200   # the admin browses as family too
    assert admin.get(f"/api/x/{x.slug}").get_json()["pairings"] is None


def test_home_pairings_is_null_without_an_edition_and_for_the_current_one_only(admin, family, x):
    assert family.get(f"/api/x/{x.slug}").get_json()["pairings"] is None
    paired_edition(admin, x, 2025, [(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)])
    e = paired_ready_edition(admin, x, 2026)
    # 2025 is paired but 2026 is the current edition and is still open: the family sees no names
    assert family.get(f"/api/x/{x.slug}").get_json()["pairings"] is None
    full_cycle(admin, e, [x.alex, x.jordan, x.sam])
    admin.post(f"/api/admin/editions/{e}/mark-paired", json={})
    got = family.get(f"/api/x/{x.slug}").get_json()["pairings"]
    assert [(p["giver"], p["recipient"]) for p in got] == [("Alex", "Jordan"), ("Jordan", "Sam"), ("Sam", "Alex")]


def test_admin_pairings_routes_are_admin_only_and_guarded(admin, family, x):
    e = paired_ready_edition(admin, x)
    assert family.get(f"/api/admin/editions/{e}/pairings").status_code == 403
    assert family.post(f"/api/admin/editions/{e}/mark-paired", json={}, headers={"X-Exchange": "1", "Origin": "http://localhost"}).status_code == 403
    assert admin.post(f"/api/admin/editions/{e}/unpair", json={}, headers={"Origin": "http://evil.example.com"}).status_code == 403
