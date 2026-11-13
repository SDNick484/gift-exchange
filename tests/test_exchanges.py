import pytest

import exchanges
from conftest import mk_edition, put_roster, roster_ids


def pair(con, edition, giver, recipient):
    con.execute("INSERT INTO pairing VALUES (?,?,?)", (edition, giver, recipient))
    con.commit()


# ---------------------------------------------------------------- the plan's Task 4 tests
def test_new_exchange_gets_default_fields_in_order(admin, con):
    xid = admin.post("/api/admin/exchanges", json={"slug": "cousins", "name": "Cousins", "password": "pw12"}).get_json()["id"]
    labels = [f["label"] for f in admin.get(f"/api/admin/exchanges/{xid}/fields").get_json()]
    assert labels == [label for label, _ in exchanges.DEFAULT_FIELDS]


@pytest.mark.parametrize("slug", ["Admin", "admin", "x", "has space", "-lead", "a" * 41])
def test_bad_slug_is_400(admin, slug):
    assert admin.post("/api/admin/exchanges", json={"slug": slug, "name": "N", "password": "pw12"}).status_code == 400


def test_next_year_copies_active_roster_only(admin, con, x):        # x: exchange with people alex, sam, jordan
    e1 = mk_edition(admin, x.id, 2025); put_roster(admin, e1, [x.alex, x.sam, x.jordan])
    admin.patch(f"/api/admin/people/{x.jordan}", json={"active": False})
    e2 = admin.post(f"/api/admin/exchanges/{x.id}/editions", json={"year": 2026, "copy_roster": True}).get_json()["id"]
    assert roster_ids(con, e2) == {x.alex, x.sam}


def test_current_edition_prefers_newest_not_closed(con, x):
    e25 = exchanges.create_edition(con, x.id, 2025, None, False)
    e26 = exchanges.create_edition(con, x.id, 2026, None, False)
    con.execute("UPDATE edition SET status='closed' WHERE id=?", (e26,))
    assert exchanges.current_edition(con, x.id)["id"] == e25


def test_duplicate_year_is_409(admin, x):
    mk_edition(admin, x.id, 2026)
    assert admin.post(f"/api/admin/exchanges/{x.id}/editions", json={"year": 2026}).status_code == 409


def test_password_change_rotates_link_and_version(admin, con, x):
    before = con.execute("SELECT password_version, link_token FROM exchange WHERE id=?", (x.id,)).fetchone()
    admin.patch(f"/api/admin/exchanges/{x.id}", json={"password": "new-pass"})
    after = con.execute("SELECT password_version, link_token FROM exchange WHERE id=?", (x.id,)).fetchone()
    assert after[0] == before[0] + 1 and after[1] != before[1]


def test_roster_change_cannot_orphan_a_pairing(admin, con, x):
    e = mk_edition(admin, x.id, 2026); put_roster(admin, e, [x.alex, x.sam, x.jordan])
    con.execute("INSERT INTO pairing VALUES (?,?,?)", (e, x.alex, x.sam)); con.commit()
    r = admin.put(f"/api/admin/editions/{e}/roster", json={"person_ids": [x.alex, x.jordan]})
    assert r.status_code == 409 and "Sam" in r.get_json()["error"]
    assert admin.patch(f"/api/admin/people/{x.sam}", json={"active": False}).status_code == 409


def test_setting_paired_directly_is_400(admin, x):
    e = mk_edition(admin, x.id, 2026)
    assert admin.patch(f"/api/admin/editions/{e}", json={"status": "paired"}).status_code == 400


# ---------------------------------------------------------------- review focus 5 in full
def test_orphan_message_is_exact_and_nothing_changes(admin, con, x):
    e = mk_edition(admin, x.id, 2026); put_roster(admin, e, [x.alex, x.sam, x.jordan])
    pair(con, e, x.alex, x.sam)
    r = admin.put(f"/api/admin/editions/{e}/roster", json={"person_ids": [x.alex, x.jordan]})
    assert r.get_json() == {"error": "Remove their pairing first: Sam."}
    assert roster_ids(con, e) == {x.alex, x.sam, x.jordan}


def test_dropping_a_giver_with_a_draft_row_is_409(admin, con, x):
    e = mk_edition(admin, x.id, 2026); put_roster(admin, e, [x.alex, x.sam])
    con.execute("INSERT INTO pairing (edition_id, giver_id) VALUES (?, ?)", (e, x.alex)); con.commit()
    r = admin.put(f"/api/admin/editions/{e}/roster", json={"person_ids": [x.sam]})
    assert r.status_code == 409 and "Alex" in r.get_json()["error"]


def test_every_dropped_person_is_named(admin, con, x):
    e = mk_edition(admin, x.id, 2026); put_roster(admin, e, [x.alex, x.sam, x.jordan])
    pair(con, e, x.alex, x.sam); pair(con, e, x.sam, x.jordan)
    r = admin.put(f"/api/admin/editions/{e}/roster", json={"person_ids": [x.alex]})
    assert r.get_json()["error"] == "Remove their pairing first: Jordan, Sam."


def test_roster_change_goes_through_once_the_pairing_is_gone(admin, con, x):
    e = mk_edition(admin, x.id, 2026); put_roster(admin, e, [x.alex, x.sam, x.jordan])
    pair(con, e, x.alex, x.sam)
    con.execute("DELETE FROM pairing WHERE edition_id = ?", (e,)); con.commit()
    put_roster(admin, e, [x.alex, x.jordan])
    assert roster_ids(con, e) == {x.alex, x.jordan}


def test_deactivating_a_receiver_is_409_and_leaves_them_active(admin, con, x):
    e = mk_edition(admin, x.id, 2026); put_roster(admin, e, [x.alex, x.sam])
    pair(con, e, x.alex, x.sam)
    r = admin.patch(f"/api/admin/people/{x.sam}", json={"active": False})
    assert r.get_json() == {"error": "Remove their pairing first: Sam."}
    assert con.execute("SELECT active FROM person WHERE id = ?", (x.sam,)).fetchone()[0] == 1


def test_deactivating_is_fine_when_the_only_pairing_is_in_a_closed_edition(admin, con, x):
    e = mk_edition(admin, x.id, 2025); put_roster(admin, e, [x.alex, x.sam])
    pair(con, e, x.alex, x.sam)
    admin.patch(f"/api/admin/editions/{e}", json={"status": "closed"})
    assert admin.patch(f"/api/admin/people/{x.sam}", json={"active": False}).status_code == 200


def test_deactivating_is_fine_without_a_pairing(admin, x):
    e = mk_edition(admin, x.id, 2026); put_roster(admin, e, [x.alex, x.sam])
    assert admin.patch(f"/api/admin/people/{x.sam}", json={"active": False}).status_code == 200
    assert admin.patch(f"/api/admin/people/{x.sam}", json={"active": True}).status_code == 200


def test_renaming_a_paired_person_is_fine(admin, con, x):
    e = mk_edition(admin, x.id, 2026); put_roster(admin, e, [x.alex, x.sam])
    pair(con, e, x.alex, x.sam)
    assert admin.patch(f"/api/admin/people/{x.sam}", json={"name": "Samantha", "household": "Casey's"}).status_code == 200


# ---------------------------------------------------------------- exchanges
def test_admin_only(client, x):
    assert client.get("/api/admin/exchanges").status_code == 403
    assert client.get(f"/api/admin/exchanges/{x.id}/people").status_code == 403


def test_create_and_list_exchange_never_leaks_secrets(admin, con):
    r = admin.post("/api/admin/exchanges", json={"slug": "cousins", "name": " Cousins ", "password": "pw12",
                                                 "accent_color": "#1A2b3C", "sort_order": 2})
    assert r.status_code == 201
    row = admin.get("/api/admin/exchanges").get_json()[0]
    assert row == {"id": r.get_json()["id"], "slug": "cousins", "name": "Cousins", "active": True, "sort_order": 2,
                   "accent_color": "#1A2b3C"}
    stored = con.execute("SELECT password_hash, link_token FROM exchange").fetchone()
    assert stored[0].startswith("scrypt$") and len(stored[1]) >= 20


def test_default_field_hints_match_the_spec(admin, x):
    xid = admin.post("/api/admin/exchanges", json={"slug": "adults", "name": "Adults", "password": "pw12"}).get_json()["id"]
    got = [(f["label"], f["hint"]) for f in admin.get(f"/api/admin/exchanges/{xid}/fields").get_json()]
    assert got == exchanges.DEFAULT_FIELDS and len(got) == 8
    assert got[1] == ("Pants size", "waist/length, or kids' size") and got[7][1] == "dislikes, allergies, scents"


def test_duplicate_slug_is_409(admin, x):
    assert admin.post("/api/admin/exchanges", json={"slug": "family", "name": "N", "password": "pw12"}).status_code == 409


@pytest.mark.parametrize("password", ["abc", "a" * 129, "", None, 1234])
def test_bad_password_is_400(admin, password):
    assert admin.post("/api/admin/exchanges", json={"slug": "cousins", "name": "N", "password": password}).status_code == 400


def test_password_limits_are_inclusive(admin):
    for slug, pw in (("a", "abcd"), ("b", "a" * 128)):
        assert admin.post("/api/admin/exchanges", json={"slug": slug, "name": "N", "password": pw}).status_code == 201


def test_name_is_required(admin):
    assert admin.post("/api/admin/exchanges", json={"slug": "cousins", "name": "  ", "password": "pw12"}).status_code == 400


@pytest.mark.parametrize("color", ["red", "#12345", "#1234567", "123456", "#12345g"])
def test_bad_accent_color_is_400(admin, x, color):
    assert admin.patch(f"/api/admin/exchanges/{x.id}", json={"accent_color": color}).status_code == 400


def test_accent_color_can_be_set_and_cleared(admin, con, x):
    admin.patch(f"/api/admin/exchanges/{x.id}", json={"accent_color": "#0a0B0c"})
    assert con.execute("SELECT accent_color FROM exchange WHERE id=?", (x.id,)).fetchone()[0] == "#0a0B0c"
    admin.patch(f"/api/admin/exchanges/{x.id}", json={"accent_color": None})
    assert con.execute("SELECT accent_color FROM exchange WHERE id=?", (x.id,)).fetchone()[0] is None


def test_patch_exchange_fields(admin, x):
    r = admin.patch(f"/api/admin/exchanges/{x.id}", json={"name": "Family 2", "slug": "fam", "active": False, "sort_order": 3})
    assert r.status_code == 200
    assert r.get_json() == {"id": x.id, "slug": "fam", "name": "Family 2", "active": False, "sort_order": 3,
                            "accent_color": None}


def test_patch_slug_rules(admin, con, x):
    mk_other = admin.post("/api/admin/exchanges", json={"slug": "other", "name": "O", "password": "pw12"})
    assert mk_other.status_code == 201
    assert admin.patch(f"/api/admin/exchanges/{x.id}", json={"slug": "other"}).status_code == 409
    assert admin.patch(f"/api/admin/exchanges/{x.id}", json={"slug": "api"}).status_code == 400
    assert admin.patch(f"/api/admin/exchanges/{x.id}", json={"slug": "family"}).status_code == 200


def test_patch_bad_shapes_are_400(admin, x):
    url = f"/api/admin/exchanges/{x.id}"
    assert admin.patch(url, json={}).status_code == 400
    assert admin.patch(url, json={"active": "yes"}).status_code == 400
    assert admin.patch(url, json={"sort_order": True}).status_code == 400
    assert admin.patch(url, json={"name": 5}).status_code == 400
    assert admin.patch(url, json={"password": "abc"}).status_code == 400


def test_other_patches_leave_the_password_and_link_alone(admin, con, x):
    before = con.execute("SELECT password_version, link_token, password_hash FROM exchange WHERE id=?", (x.id,)).fetchone()
    admin.patch(f"/api/admin/exchanges/{x.id}", json={"name": "Renamed", "active": False})
    assert tuple(con.execute("SELECT password_version, link_token, password_hash FROM exchange WHERE id=?",
                             (x.id,)).fetchone()) == tuple(before)


def test_changed_password_unlocks_and_the_old_one_does_not(admin, con, x):
    admin.patch(f"/api/admin/exchanges/{x.id}", json={"password": "new-pass"})
    fresh = admin.application.test_client()
    h = {"X-Exchange": "1", "Origin": "http://localhost"}
    assert fresh.post("/api/unlock", json={"password": "pw12"}, headers=h).status_code == 403
    assert fresh.post("/api/unlock", json={"password": "new-pass"}, headers=h).status_code == 200


def test_link_route_regenerates_and_builds_the_url_from_origin(admin, con, x):
    old = con.execute("SELECT link_token FROM exchange WHERE id=?", (x.id,)).fetchone()[0]
    r = admin.post(f"/api/admin/exchanges/{x.id}/link", json={}, headers={"Origin": "http://localhost"})
    new = con.execute("SELECT link_token FROM exchange WHERE id=?", (x.id,)).fetchone()[0]
    assert new != old and r.get_json() == {"url": f"http://localhost/x/family/join/{new}"}
    assert admin.get(f"/x/family/join/{old}").status_code == 302
    assert admin.get("/api/exchanges").get_json() == []         # the old token set nothing


def test_missing_exchange_is_404(admin):
    assert admin.patch("/api/admin/exchanges/999", json={"name": "N"}).status_code == 404
    assert admin.post("/api/admin/exchanges/999/link", json={}).status_code == 404
    assert admin.get("/api/admin/exchanges/999/people").status_code == 404
    assert admin.get("/api/admin/exchanges/999/editions").status_code == 404
    assert admin.get("/api/admin/exchanges/999/fields").status_code == 404


# ---------------------------------------------------------------- people
def test_people_add_list_patch(admin, x):
    r = admin.post(f"/api/admin/exchanges/{x.id}/people", json={"name": " Riley ", "household": "Casey's house"})
    assert r.status_code == 201
    people = admin.get(f"/api/admin/exchanges/{x.id}/people").get_json()
    assert [p["name"] for p in people] == ["Alex", "Jordan", "Riley", "Sam"]
    riley = next(p for p in people if p["name"] == "Riley")
    assert riley == {"id": r.get_json()["id"], "name": "Riley", "household": "Casey's house", "active": True}
    assert admin.patch(f"/api/admin/people/{riley['id']}", json={"household": None}).status_code == 200
    assert admin.patch("/api/admin/people/999", json={"name": "N"}).status_code == 404


def test_duplicate_person_name_is_409(admin, x):
    assert admin.post(f"/api/admin/exchanges/{x.id}/people", json={"name": "Alex"}).status_code == 409
    assert admin.patch(f"/api/admin/people/{x.sam}", json={"name": "Alex"}).status_code == 409


def test_same_name_in_two_exchanges_is_fine(admin, x):
    other = admin.post("/api/admin/exchanges", json={"slug": "cousins", "name": "C", "password": "pw12"}).get_json()["id"]
    assert admin.post(f"/api/admin/exchanges/{other}/people", json={"name": "Alex"}).status_code == 201


def test_person_needs_a_name(admin, x):
    assert admin.post(f"/api/admin/exchanges/{x.id}/people", json={"name": " "}).status_code == 400


# ---------------------------------------------------------------- editions
def test_edition_defaults_and_listing(admin, con, x):
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, [x.sam, x.alex])
    row = admin.get(f"/api/admin/exchanges/{x.id}/editions").get_json()[0]
    assert row == {"id": e, "year": 2026, "label": "2026", "budget_cents": None, "event_date": None, "location": None,
                   "rules": "", "status": "open", "person_ids": sorted([x.alex, x.sam])}


def test_editions_list_newest_year_first_and_label_defaults(admin, x):
    mk_edition(admin, x.id, 2025, label="Last year"); mk_edition(admin, x.id, 2026)
    got = admin.get(f"/api/admin/exchanges/{x.id}/editions").get_json()
    assert [(e["year"], e["label"]) for e in got] == [(2026, "2026"), (2025, "Last year")]


@pytest.mark.parametrize("year", [1999, 2101, "2026", 2026.5, True, None])
def test_bad_year_is_400(admin, x, year):
    assert admin.post(f"/api/admin/exchanges/{x.id}/editions", json={"year": year}).status_code == 400


def test_year_limits_are_inclusive(admin, x):
    assert admin.post(f"/api/admin/exchanges/{x.id}/editions", json={"year": 2000}).status_code == 201
    assert admin.post(f"/api/admin/exchanges/{x.id}/editions", json={"year": 2100}).status_code == 201


def test_past_edition_can_be_created_after_a_newer_one(admin, con, x):
    e26 = mk_edition(admin, x.id, 2026)
    e25 = mk_edition(admin, x.id, 2025)
    assert exchanges.current_edition(con, x.id)["id"] == e26 and e25 != e26


def test_copy_roster_takes_the_newest_earlier_edition_not_the_newest(admin, con, x):
    e24 = mk_edition(admin, x.id, 2024); put_roster(admin, e24, [x.alex])
    e26 = mk_edition(admin, x.id, 2026); put_roster(admin, e26, [x.sam, x.jordan])
    e25 = mk_edition(admin, x.id, 2025, copy_roster=True)
    assert roster_ids(con, e25) == {x.alex}


def test_copy_roster_with_no_earlier_edition_is_empty(admin, con, x):
    assert roster_ids(con, mk_edition(admin, x.id, 2026, copy_roster=True)) == set()


def test_copy_roster_is_off_by_default(admin, con, x):
    put_roster(admin, mk_edition(admin, x.id, 2025), [x.alex])
    assert roster_ids(con, mk_edition(admin, x.id, 2026)) == set()


def test_copy_roster_must_be_boolean(admin, x):
    assert admin.post(f"/api/admin/exchanges/{x.id}/editions", json={"year": 2026, "copy_roster": "yes"}).status_code == 400


def test_edition_patch_settings(admin, con, x):
    e = mk_edition(admin, x.id, 2026)
    r = admin.patch(f"/api/admin/editions/{e}", json={"label": "Christmas 2026", "budget": "$25.50", "event_date": "2026-12-24",
                                                    "location": "Riley's house", "rules": "One gift, wrapped."})
    assert r.status_code == 200
    row = con.execute("SELECT label, budget_cents, event_date, location, rules FROM edition WHERE id=?", (e,)).fetchone()
    assert tuple(row) == ("Christmas 2026", 2550, "2026-12-24", "Riley's house", "One gift, wrapped.")
    admin.patch(f"/api/admin/editions/{e}", json={"budget": None, "event_date": None, "location": "", "rules": ""})
    row = con.execute("SELECT budget_cents, event_date, location, rules FROM edition WHERE id=?", (e,)).fetchone()
    assert tuple(row) == (None, None, None, "")


@pytest.mark.parametrize("patch", [
    {"budget": "free"}, {"budget": -5}, {"budget": 2.5}, {"event_date": "2026-13-01"}, {"event_date": "12/24/2026"},
    {"event_date": "2026-2-3"}, {"event_date": 20261224}, {"rules": "x" * 2001}, {"label": " "}, {"status": "bogus"},
    {"status": 1}, {"location": "x" * 201},
])
def test_bad_edition_patch_is_400(admin, x, patch):
    e = mk_edition(admin, x.id, 2026)
    assert admin.patch(f"/api/admin/editions/{e}", json=patch).status_code == 400


def test_rules_keep_up_to_2000_characters(admin, con, x):
    e = mk_edition(admin, x.id, 2026)
    assert admin.patch(f"/api/admin/editions/{e}", json={"rules": "x" * 2000}).status_code == 200
    assert len(con.execute("SELECT rules FROM edition WHERE id=?", (e,)).fetchone()[0]) == 2000


def test_status_transitions(admin, con, x):
    e = mk_edition(admin, x.id, 2026)
    for status in ("closed", "open", "closed"):
        assert admin.patch(f"/api/admin/editions/{e}", json={"status": status}).status_code == 200
        assert con.execute("SELECT status FROM edition WHERE id=?", (e,)).fetchone()[0] == status
    assert admin.patch(f"/api/admin/editions/{e}", json={"status": "paired"}).status_code == 400
    assert con.execute("SELECT status FROM edition WHERE id=?", (e,)).fetchone()[0] == "closed"


def test_paired_cannot_be_set_even_alongside_other_changes(admin, con, x):
    e = mk_edition(admin, x.id, 2026)
    assert admin.patch(f"/api/admin/editions/{e}", json={"label": "New", "status": "paired"}).status_code == 400
    assert con.execute("SELECT label FROM edition WHERE id=?", (e,)).fetchone()[0] == "2026"


def test_edition_patch_404(admin):
    assert admin.patch("/api/admin/editions/999", json={"label": "N"}).status_code == 404
    assert admin.put("/api/admin/editions/999/roster", json={"person_ids": []}).status_code == 404


# ---------------------------------------------------------------- roster
def test_roster_put_replaces(admin, con, x):
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, [x.alex, x.sam]); put_roster(admin, e, [x.jordan, x.sam])
    assert roster_ids(con, e) == {x.jordan, x.sam}
    put_roster(admin, e, [])
    assert roster_ids(con, e) == set()


@pytest.mark.parametrize("ids", ["1", [1, "2"], [True], [1.5], [999999], None])
def test_bad_roster_is_400(admin, con, x, ids):
    e = mk_edition(admin, x.id, 2026); put_roster(admin, e, [x.alex])
    assert admin.put(f"/api/admin/editions/{e}/roster", json={"person_ids": ids}).status_code == 400
    assert roster_ids(con, e) == {x.alex}


def test_roster_rejects_a_person_from_another_exchange(admin, con, x):
    other = admin.post("/api/admin/exchanges", json={"slug": "cousins", "name": "C", "password": "pw12"}).get_json()["id"]
    stranger = admin.post(f"/api/admin/exchanges/{other}/people", json={"name": "Casey"}).get_json()["id"]
    e = mk_edition(admin, x.id, 2026)
    assert admin.put(f"/api/admin/editions/{e}/roster", json={"person_ids": [x.alex, stranger]}).status_code == 400
    assert roster_ids(con, e) == set()


def test_duplicate_ids_in_a_roster_are_collapsed(admin, con, x):
    e = mk_edition(admin, x.id, 2026)
    put_roster(admin, e, [x.alex, x.alex, x.sam])
    assert roster_ids(con, e) == {x.alex, x.sam}


def test_set_roster_directly(con, x):
    e = exchanges.create_edition(con, x.id, 2026, None, False)
    exchanges.set_roster(con, e, [x.alex, x.sam])
    assert roster_ids(con, e) == {x.alex, x.sam}


# ---------------------------------------------------------------- profile fields
def fields(admin, xid):
    return admin.get(f"/api/admin/exchanges/{xid}/fields").get_json()


def test_field_add_patch_and_hide(admin, x):
    r = admin.post(f"/api/admin/exchanges/{x.id}/fields", json={"label": "Ring size", "hint": "US"})
    assert r.status_code == 201
    fid = r.get_json()["id"]
    assert fields(admin, x.id) == [{"id": fid, "label": "Ring size", "hint": "US", "sort_order": 0, "active": True}]
    admin.post(f"/api/admin/exchanges/{x.id}/fields", json={"label": "Scent"})
    assert [f["label"] for f in fields(admin, x.id)] == ["Ring size", "Scent"]
    assert admin.patch(f"/api/admin/fields/{fid}", json={"label": "Ring", "hint": None, "active": False}).status_code == 200
    assert fields(admin, x.id)[0] == {"id": fid, "label": "Ring", "hint": None, "sort_order": 0, "active": False}


def test_field_needs_a_label(admin, x):
    assert admin.post(f"/api/admin/exchanges/{x.id}/fields", json={"label": ""}).status_code == 400
    assert admin.post(f"/api/admin/exchanges/{x.id}/fields", json={"label": "L", "hint": "h" * 201}).status_code == 400
    f = admin.post(f"/api/admin/exchanges/{x.id}/fields", json={"label": "L"}).get_json()["id"]
    assert admin.patch(f"/api/admin/fields/{f}", json={"label": " "}).status_code == 400
    assert admin.patch(f"/api/admin/fields/{f}", json={"active": 1}).status_code == 400
    assert admin.patch("/api/admin/fields/999", json={"label": "L"}).status_code == 404


def test_hiding_a_field_keeps_its_values(admin, con, x):
    f = admin.post(f"/api/admin/exchanges/{x.id}/fields", json={"label": "Shirt"}).get_json()["id"]
    con.execute("INSERT INTO profile_value (person_id, field_id, value, updated_at) VALUES (?, ?, 'M', 0)", (x.alex, f))
    admin.patch(f"/api/admin/fields/{f}", json={"active": False})
    assert con.execute("SELECT value FROM profile_value WHERE field_id=?", (f,)).fetchone()[0] == "M"


def test_field_order(admin, x):
    ids = [f["id"] for f in (admin.post(f"/api/admin/exchanges/{x.id}/fields", json={"label": n}).get_json() for n in "abc")]
    r = admin.put(f"/api/admin/exchanges/{x.id}/fields/order", json={"ids": [ids[2], ids[0], ids[1]]})
    assert r.status_code == 200
    assert [f["label"] for f in fields(admin, x.id)] == ["c", "a", "b"]


@pytest.mark.parametrize("pick", ["missing", "extra", "duplicate", "not-a-list", "other-exchange"])
def test_bad_field_order_is_400(admin, x, pick):
    ids = [admin.post(f"/api/admin/exchanges/{x.id}/fields", json={"label": n}).get_json()["id"] for n in "ab"]
    foreign = admin.post("/api/admin/exchanges", json={"slug": "other", "name": "O", "password": "pw12"}).get_json()["id"]
    foreign_field = fields(admin, foreign)[0]["id"]
    body = {"missing": ids[:1], "extra": ids + [ids[0] + 1000], "duplicate": [ids[0], ids[0]], "not-a-list": "ab",
            "other-exchange": [ids[0], foreign_field]}[pick]
    assert admin.put(f"/api/admin/exchanges/{x.id}/fields/order", json={"ids": body}).status_code == 400
    assert [f["label"] for f in fields(admin, x.id)] == ["a", "b"]
