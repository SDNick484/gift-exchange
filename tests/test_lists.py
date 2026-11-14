"""Participant pages, details, profile values and wish items, with version checks and scoping (Task 6)."""
import pytest

import app as exchange
from conftest import add_item, field_id, mk_edition, put_profile, put_roster, save_details

RELOAD = "Someone else just changed this list. Reload to see it."


# ---------------------------------------------------------------- the plan's tests
def test_two_phones_same_list_second_gets_409(family, fx):
    p = family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()
    ok = family.put(f"/api/x/{fx.slug}/people/{fx.sam}/details",
                    json={"edition_id": p["edition_id"], "about": "A", "version": p["version"], "updated_by": "Sam"})
    stale = family.put(f"/api/x/{fx.slug}/people/{fx.sam}/details",
                       json={"edition_id": p["edition_id"], "about": "B", "version": p["version"], "updated_by": "Alex"})
    assert (ok.status_code, stale.status_code) == (200, 409)
    assert stale.get_json()["error"] == "Someone else just changed this list. Reload to see it."


def test_profile_carries_across_editions_and_checks_versions(family, admin, fx, clock):
    f = field_id(fx, "Shoe size")
    assert put_profile(family, fx, fx.sam, {f: "9"}, {f: None}).status_code == 200
    e27 = admin.post(f"/api/admin/exchanges/{fx.id}/editions", json={"year": 2027, "copy_roster": True}).get_json()["id"]
    page = family.get(f"/api/x/{fx.slug}/people/{fx.sam}?edition={e27}").get_json()
    shoe = next(v for v in page["profile"] if v["field_id"] == f)
    assert shoe["value"] == "9"
    assert put_profile(family, fx, fx.sam, {f: "10"}, {f: None}).status_code == 409          # stale expectation


def test_amazon_url_without_scheme_is_fixed(family, fx):
    p = family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()
    family.put(f"/api/x/{fx.slug}/people/{fx.sam}/details", json={"edition_id": p["edition_id"], "about": None,
               "amazon_url": "amazon.example.com/hz/wishlist/ls/ABC123 ", "version": p["version"], "updated_by": "Sam"})
    assert family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()["amazon_url"] == "https://amazon.example.com/hz/wishlist/ls/ABC123"


def test_closed_year_refuses_item_writes_but_not_profile(family, admin, fx):
    admin.patch(f"/api/admin/editions/{fx.edition}", json={"status": "closed"})
    assert add_item(family, fx, fx.sam, "Socks", raw=True).status_code == 423
    f = field_id(fx, "Shirt size")
    assert put_profile(family, fx, fx.sam, {f: "M"}, {f: None}).status_code == 200


def test_cross_exchange_ids_are_404(family, fx, other):                          # other: second unlocked exchange
    assert family.get(f"/api/x/{fx.slug}/people/{other.alex}").status_code == 404
    assert family.get(f"/api/x/{fx.slug}?edition={other.edition}").status_code == 404


def test_reorder_and_delete_with_version(family, fx):
    a = add_item(family, fx, fx.sam, "A"); b = add_item(family, fx, fx.sam, "B")
    family.put(f"/api/x/{fx.slug}/people/{fx.sam}/items/order", json={"edition_id": fx.edition, "ids": [b, a]})
    assert [i["title"] for i in family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()["items"]] == ["B", "A"]
    assert family.delete(f"/api/x/{fx.slug}/items/{a}", json={"version": 99}).status_code == 409


# ---------------------------------------------------------------- the page
def test_page_shape_before_anything_is_saved(family, fx):
    p = family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()
    assert p["person"] == {"id": fx.sam, "name": "Sam"} and p["edition_id"] == fx.edition
    assert (p["about"], p["amazon_url"], p["version"], p["updated_at"], p["updated_by"], p["items"]) == \
           ("", None, 0, None, None, [])
    assert [v["label"] for v in p["profile"]][:3] == ["Shirt size", "Pants size", "Shoe size"]
    assert p["profile"][1] == {"field_id": field_id(fx, "Pants size"), "label": "Pants size",
                               "hint": "waist/length, or kids' size", "value": None, "updated_at": None,
                               "updated_by": None}


def test_page_lists_only_active_fields_in_order(admin, family, fx):
    shirt, shoe = field_id(fx, "Shirt size"), field_id(fx, "Shoe size")
    admin.patch(f"/api/admin/fields/{shirt}", json={"active": False})
    labels = [v["label"] for v in family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()["profile"]]
    assert "Shirt size" not in labels and labels[1] == "Shoe size" and shoe


def test_details_save_round_trip(family, fx, clock):
    assert save_details(family, fx, fx.sam, about="  Likes tea  ", amazon_url="https://amazon.com/l/1") == 1
    assert save_details(family, fx, fx.sam, about="Likes coffee") == 2
    p = family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()
    assert (p["about"], p["amazon_url"], p["version"], p["updated_at"], p["updated_by"]) == \
           ("Likes coffee", None, 2, clock.t, "Sam")


def test_first_save_from_two_phones_second_gets_409(family, fx):
    body = {"edition_id": fx.edition, "about": "A", "version": 0, "updated_by": "Sam"}
    assert family.put(f"/api/x/{fx.slug}/people/{fx.sam}/details", json=body).status_code == 200
    stale = family.put(f"/api/x/{fx.slug}/people/{fx.sam}/details", json={**body, "about": "B"})
    assert (stale.status_code, stale.get_json()["error"]) == (409, RELOAD)
    assert family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()["about"] == "A"


def test_details_version_ahead_of_a_missing_row_is_409(family, fx):
    r = family.put(f"/api/x/{fx.slug}/people/{fx.sam}/details",
                   json={"edition_id": fx.edition, "about": "A", "version": 3, "updated_by": "Sam"})
    assert r.status_code == 409


# ---------------------------------------------------------------- links (review focus 4)
def test_amazon_url_from_the_review_focus(family, fx):
    save_details(family, fx, fx.sam, amazon_url="amazon.com/hz/wishlist/ls/ABC123 ")
    assert family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()["amazon_url"] == \
           "https://amazon.com/hz/wishlist/ls/ABC123"


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "see my list", "ftp://example.com/x"])
def test_bad_links_are_400_and_change_nothing(family, fx, bad):
    assert save_details(family, fx, fx.sam, amazon_url=bad, raw=True).status_code == 400
    assert add_item(family, fx, fx.sam, "Socks", raw=True, url=bad).status_code == 400
    p = family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()
    assert (p["version"], p["items"]) == (0, [])


def test_item_url_without_scheme_is_fixed(family, fx):
    add_item(family, fx, fx.sam, "Socks", url=" example.com/socks", note="Blue")
    item = family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()["items"][0]
    assert (item["url"], item["note"], item["version"], item["updated_by"]) == \
           ("https://example.com/socks", "Blue", 1, "Sam")


# ---------------------------------------------------------------- lengths and updated_by
def test_lengths_are_enforced(family, fx):
    assert save_details(family, fx, fx.sam, about="x" * 4000, raw=True).status_code == 200
    assert save_details(family, fx, fx.sam, about="x" * 4001, raw=True).status_code == 400
    assert add_item(family, fx, fx.sam, "t" * 200, raw=True).status_code == 201
    assert add_item(family, fx, fx.sam, "t" * 201, raw=True).status_code == 400
    assert add_item(family, fx, fx.sam, "   ", raw=True).status_code == 400
    assert add_item(family, fx, fx.sam, "Socks", raw=True, note="n" * 1001).status_code == 400
    f = field_id(fx, "Interests and hobbies")
    assert put_profile(family, fx, fx.sam, {f: "v" * 501}, {f: None}).status_code == 400
    assert put_profile(family, fx, fx.sam, {f: "v" * 500}, {f: None}).status_code == 200


def test_updated_by_is_required_on_writes_that_record_it(family, fx):
    url = f"/api/x/{fx.slug}/people/{fx.sam}"
    assert family.put(f"{url}/details", json={"edition_id": fx.edition, "version": 0}).status_code == 400
    assert add_item(family, fx, fx.sam, "Socks", raw=True, updated_by="").status_code == 400
    f = field_id(fx, "Shoe size")
    assert put_profile(family, fx, fx.sam, {f: "9"}, {f: None}, updated_by=None).status_code == 400
    assert put_profile(family, fx, fx.sam, {f: "9"}, {f: None}, updated_by="x" * 61).status_code == 400
    a = add_item(family, fx, fx.sam, "Socks")
    assert family.patch(f"/api/x/{fx.slug}/items/{a}", json={"title": "Mug", "version": 1}).status_code == 400


@pytest.mark.parametrize("version", [None, "1", True, -1, 1.0])
def test_version_must_be_a_whole_number(family, fx, version):
    r = family.put(f"/api/x/{fx.slug}/people/{fx.sam}/details",
                   json={"edition_id": fx.edition, "about": "A", "version": version, "updated_by": "Sam"})
    assert r.status_code == 400


# ---------------------------------------------------------------- profile values
def test_profile_value_round_trip_and_empty_deletes(family, fx, clock):
    f = field_id(fx, "Favorite colors")
    r = put_profile(family, fx, fx.sam, {f: "  green  "}, {f: None})
    v = next(v for v in r.get_json()["profile"] if v["field_id"] == f)
    assert (v["value"], v["updated_at"], v["updated_by"]) == ("green", clock.t, "Sam")
    clock.advance(60)
    assert put_profile(family, fx, fx.sam, {f: ""}, {f: v["updated_at"]}).status_code == 200
    assert fx.con.execute("SELECT COUNT(*) FROM profile_value WHERE person_id = ?", (fx.sam,)).fetchone()[0] == 0


def test_profile_same_second_saves_still_conflict(family, fx, clock):
    """Two phones load the same value; the first saves in the same second it was loaded. The second must still get
    409, so updated_at moves on at every change even while the clock stands still."""
    f = field_id(fx, "Shoe size")
    loaded = put_profile(family, fx, fx.sam, {f: "9"}, {f: None}).get_json()
    seen = next(v for v in loaded["profile"] if v["field_id"] == f)["updated_at"]
    assert put_profile(family, fx, fx.sam, {f: "10"}, {f: seen}).status_code == 200
    stale = put_profile(family, fx, fx.sam, {f: "11"}, {f: seen}, updated_by="Alex")
    assert (stale.status_code, stale.get_json()["error"]) == (409, RELOAD)
    page = family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()
    assert next(v for v in page["profile"] if v["field_id"] == f)["value"] == "10"


def test_profile_unchanged_fields_are_skipped_and_a_conflict_saves_nothing(family, fx):
    shoe, shirt = field_id(fx, "Shoe size"), field_id(fx, "Shirt size")
    put_profile(family, fx, fx.sam, {shoe: "9", shirt: "M"}, {})
    # shoe is unchanged, so its (wrong) expectation is not checked
    assert put_profile(family, fx, fx.sam, {shoe: "9"}, {shoe: 12345}).status_code == 200
    # shirt is stale: nothing in the request is saved, not even the new field
    colors = field_id(fx, "Favorite colors")
    assert put_profile(family, fx, fx.sam, {shirt: "L", colors: "red"}, {shirt: None, colors: None}).status_code == 409
    values = dict(fx.con.execute("SELECT field_id, value FROM profile_value WHERE person_id = ?", (fx.sam,)).fetchall())
    assert values == {shoe: "9", shirt: "M"}


@pytest.mark.parametrize("body", [
    {"values": [], "expected": {}},
    {"values": {"abc": "x"}, "expected": {}},
    {"values": {"1": 9}, "expected": {}},
    {"values": {}, "expected": []},
    {"values": {}, "expected": {"1": "today"}},
])
def test_profile_bad_shapes_are_400(family, fx, body):
    r = family.put(f"/api/x/{fx.slug}/people/{fx.sam}/profile", json={**body, "updated_by": "Sam"})
    assert r.status_code == 400


def test_profile_of_someone_off_every_roster_still_saves(admin, family, fx):
    """Profile values belong to the person, not to an edition."""
    put_roster(admin, fx.edition, [fx.alex, fx.jordan])
    f = field_id(fx, "Shoe size")
    assert put_profile(family, fx, fx.sam, {f: "9"}, {f: None}).status_code == 200


# ---------------------------------------------------------------- items
def test_item_edit_with_version(family, fx):
    a = add_item(family, fx, fx.sam, "Socks")
    r = family.patch(f"/api/x/{fx.slug}/items/{a}", json={"note": "wool", "version": 1, "updated_by": "Alex"})
    assert (r.status_code, r.get_json()["version"]) == (200, 2)
    stale = family.patch(f"/api/x/{fx.slug}/items/{a}", json={"title": "Mug", "version": 1, "updated_by": "Sam"})
    assert (stale.status_code, stale.get_json()["error"]) == (409, RELOAD)
    item = family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()["items"][0]
    assert (item["title"], item["note"], item["version"], item["updated_by"]) == ("Socks", "wool", 2, "Alex")


def test_item_edit_rejects_an_empty_title_and_bad_shapes(family, fx):
    a = add_item(family, fx, fx.sam, "Socks")
    assert family.patch(f"/api/x/{fx.slug}/items/{a}",
                        json={"title": "", "version": 1, "updated_by": "Sam"}).status_code == 400
    assert family.patch(f"/api/x/{fx.slug}/items/{a}", json={"version": 1, "updated_by": "Sam"}).status_code == 400


def test_delete_with_the_right_version(family, fx):
    a = add_item(family, fx, fx.sam, "Socks")
    assert family.delete(f"/api/x/{fx.slug}/items/{a}", json={"version": 1}).status_code == 200
    assert family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()["items"] == []
    assert family.delete(f"/api/x/{fx.slug}/items/{a}", json={"version": 1}).status_code == 404


def test_new_items_go_last(family, fx):
    a = add_item(family, fx, fx.sam, "A"); b = add_item(family, fx, fx.sam, "B")
    family.put(f"/api/x/{fx.slug}/people/{fx.sam}/items/order", json={"edition_id": fx.edition, "ids": [b, a]})
    add_item(family, fx, fx.sam, "C")
    assert [i["title"] for i in family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()["items"]] == ["B", "A", "C"]


def test_reorder_needs_exactly_this_lists_items(family, fx):
    a = add_item(family, fx, fx.sam, "A"); b = add_item(family, fx, fx.sam, "B")
    j = add_item(family, fx, fx.jordan, "J")
    url = f"/api/x/{fx.slug}/people/{fx.sam}/items/order"
    assert family.put(url, json={"edition_id": fx.edition, "ids": [a, a]}).status_code == 400
    assert family.put(url, json={"edition_id": fx.edition, "ids": "ab"}).status_code == 400
    stale = family.put(url, json={"edition_id": fx.edition, "ids": [a]})          # B was added on another phone
    assert (stale.status_code, stale.get_json()["error"]) == (409, RELOAD)
    assert family.put(url, json={"edition_id": fx.edition, "ids": [b, a, j]}).status_code == 409
    assert [i["title"] for i in family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()["items"]] == ["A", "B"]


def test_reorder_does_not_bump_versions(family, fx):
    a = add_item(family, fx, fx.sam, "A"); b = add_item(family, fx, fx.sam, "B")
    family.put(f"/api/x/{fx.slug}/people/{fx.sam}/items/order", json={"edition_id": fx.edition, "ids": [b, a]})
    assert family.patch(f"/api/x/{fx.slug}/items/{a}",
                        json={"note": "x", "version": 1, "updated_by": "Sam"}).status_code == 200


# ---------------------------------------------------------------- closed years
def test_closed_year_refuses_every_list_write(family, admin, fx):
    a = add_item(family, fx, fx.sam, "Socks")
    admin.patch(f"/api/admin/editions/{fx.edition}", json={"status": "closed"})
    base = f"/api/x/{fx.slug}"
    responses = [
        save_details(family, fx, fx.sam, about="A", raw=True),
        family.patch(f"{base}/items/{a}", json={"title": "Mug", "version": 1, "updated_by": "Sam"}),
        family.delete(f"{base}/items/{a}", json={"version": 1}),
        family.put(f"{base}/people/{fx.sam}/items/order", json={"edition_id": fx.edition, "ids": [a]}),
    ]
    assert [(r.status_code, r.get_json()) for r in responses] == [(423, {"error": "This year is closed."})] * 4
    assert family.get(f"{base}/people/{fx.sam}").status_code == 200              # still readable


def test_reopened_year_takes_writes_again(family, admin, fx):
    admin.patch(f"/api/admin/editions/{fx.edition}", json={"status": "closed"})
    admin.patch(f"/api/admin/editions/{fx.edition}", json={"status": "open"})
    assert add_item(family, fx, fx.sam, "Socks", raw=True).status_code == 201


# ---------------------------------------------------------------- scoping: other exchanges and the roster
def test_every_id_from_another_exchange_is_404(family, fx, other):
    theirs = add_item(family, other, other.alex, "Theirs", updated_by="Alex")
    mine = f"/api/x/{fx.slug}"
    responses = [
        family.get(f"{mine}/people/{fx.sam}?edition={other.edition}"),
        family.put(f"{mine}/people/{other.alex}/details",
                   json={"edition_id": fx.edition, "about": "A", "version": 0, "updated_by": "Sam"}),
        family.put(f"{mine}/people/{fx.sam}/details",
                   json={"edition_id": other.edition, "about": "A", "version": 0, "updated_by": "Sam"}),
        put_profile(family, fx, other.alex, {field_id(fx, "Shoe size"): "9"}, {}),
        put_profile(family, fx, fx.sam, {other.field: "9"}, {}),
        add_item(family, fx, other.alex, "Socks", raw=True),
        add_item(family, fx, fx.sam, "Socks", raw=True, edition=other.edition),
        family.patch(f"{mine}/items/{theirs}", json={"title": "Mine now", "version": 1, "updated_by": "Sam"}),
        family.delete(f"{mine}/items/{theirs}", json={"version": 1}),
        family.put(f"{mine}/people/{other.alex}/items/order", json={"edition_id": other.edition, "ids": [theirs]}),
        family.put(f"{mine}/people/{fx.sam}/items/order", json={"edition_id": other.edition, "ids": [theirs]}),
        family.put(f"{mine}/people/{fx.sam}/items/order", json={"edition_id": fx.edition, "ids": [theirs]}),
    ]
    assert [r.status_code for r in responses] == [404] * len(responses)
    item = family.get(f"/api/x/{other.slug}/people/{other.alex}").get_json()["items"][0]
    assert (item["title"], item["version"]) == ("Theirs", 1)
    assert fx.con.execute("SELECT COUNT(*) FROM profile_value").fetchone()[0] == 0
    assert fx.con.execute("SELECT COUNT(*) FROM participant").fetchone()[0] == 0


def test_someone_off_the_editions_roster_is_404_for_it(admin, family, fx):
    a = add_item(family, fx, fx.sam, "Socks")
    e25 = mk_edition(admin, fx.id, 2025)
    put_roster(admin, e25, [fx.alex])
    assert family.get(f"/api/x/{fx.slug}/people/{fx.sam}?edition={e25}").status_code == 404
    assert add_item(family, fx, fx.sam, "Socks", raw=True, edition=e25).status_code == 404
    assert save_details(family, fx, fx.alex, about="ok", edition=e25) == 1
    put_roster(admin, fx.edition, [fx.alex, fx.jordan])                            # Sam leaves 2026
    base = f"/api/x/{fx.slug}"
    assert family.get(f"{base}/people/{fx.sam}").status_code == 404
    assert family.patch(f"{base}/items/{a}", json={"title": "Mug", "version": 1, "updated_by": "Sam"}).status_code == 404
    assert family.delete(f"{base}/items/{a}", json={"version": 1}).status_code == 404
    assert family.put(f"{base}/people/{fx.sam}/details", json={"edition_id": fx.edition, "about": "A", "version": 0,
                                                              "updated_by": "Sam"}).status_code == 404
    assert fx.sam not in [p["id"] for p in family.get(base).get_json()["people"]]


def test_unknown_ids_are_404(family, fx):
    base = f"/api/x/{fx.slug}"
    assert family.get(f"{base}/people/99999").status_code == 404
    assert family.patch(f"{base}/items/99999", json={"title": "X", "version": 1, "updated_by": "Sam"}).status_code == 404
    assert add_item(family, fx, fx.sam, "Socks", raw=True, edition=99999).status_code == 404


def test_page_without_any_edition_is_404(family, x):
    assert family.get(f"/api/x/{x.slug}/people/{x.sam}").status_code == 404


def test_list_routes_are_locked_without_the_password(fx):
    client = exchange.app.test_client()                                          # a phone that never typed pw12
    assert client.get(f"/api/x/{fx.slug}/people/{fx.sam}").status_code == 403
    r = client.post(f"/api/x/{fx.slug}/people/{fx.sam}/items", json={"edition_id": fx.edition, "title": "Socks",
                                                                     "updated_by": "Sam"},
                    headers={"X-Exchange": "1", "Origin": "http://localhost"})
    assert r.status_code == 403 and r.get_json()["locked"] is True


def test_out_of_range_and_odd_ids_are_404_or_400_never_500(family, fx):
    base, huge = f"/api/x/{fx.slug}", 2 ** 70
    assert family.get(f"{base}/people/{huge}").status_code == 404
    assert family.get(f"{base}/people/{fx.sam}?edition={huge}").status_code == 400
    assert family.get(f"{base}/people/{fx.sam}?edition=²").status_code == 400
    assert family.patch(f"{base}/items/{huge}", json={"title": "X", "version": 1, "updated_by": "Sam"}).status_code == 404
    assert add_item(family, fx, fx.sam, "Socks", raw=True, edition=huge).status_code == 400
    assert save_details(family, fx, fx.sam, about="A", raw=True).status_code == 200
    r = family.put(f"{base}/people/{fx.sam}/details",
                   json={"edition_id": fx.edition, "about": "B", "version": huge, "updated_by": "Sam"})
    assert r.status_code == 400
    assert put_profile(family, fx, fx.sam, {huge: "9"}, {}).status_code == 400
    assert put_profile(family, fx, fx.sam, {"²": "9"}, {}).status_code == 400
    a = add_item(family, fx, fx.sam, "A")
    assert family.put(f"{base}/people/{fx.sam}/items/order",
                      json={"edition_id": fx.edition, "ids": [a, huge]}).status_code == 400


# ---------------------------------------------------------------- schema v2: soft-deleted items


def test_start_up_purges(family, fx, clock):
    import app as a_
    import common
    i = add_item(family, fx, fx.sam, "Old")
    fx.con.execute("UPDATE wish_item SET deleted_at = ? WHERE id = ?", (common.now(), i))
    clock.advance(86401)
    a_.init_db()
    assert fx.con.execute("SELECT COUNT(*) FROM wish_item").fetchone()[0] == 0

# ---------------------------------------------------------------- bring over last year's items
def _bring(client, fx, edition, pid=None, **extra):
    return client.post(f"/api/x/{fx.slug}/people/{pid or fx.sam}/bring-over",
                       json={"edition_id": edition, "updated_by": "Sam", **extra})


def _titles(client, fx, pid=None, edition=None):
    q = f"?edition={edition}" if edition else ""
    return [i["title"] for i in client.get(f"/api/x/{fx.slug}/people/{pid or fx.sam}{q}").get_json()["items"]]




def test_bring_over_copies_last_years_items_once(family, admin, fx):
    add_item(family, fx, fx.sam, "Socks"); add_item(family, fx, fx.sam, "Mug")
    e27 = admin.post(f"/api/admin/exchanges/{fx.id}/editions", json={"year": 2027, "copy_roster": True}).get_json()["id"]
    add_item(family, fx, fx.sam, "socks", edition=e27)
    r = family.post(f"/api/x/{fx.slug}/people/{fx.sam}/bring-over", json={"edition_id": e27, "updated_by": "Sam"})
    assert r.get_json()["copied"] == 1
    assert family.post(f"/api/x/{fx.slug}/people/{fx.sam}/bring-over", json={"edition_id": e27, "updated_by": "Sam"}).status_code == 400


def test_bring_over_copies_fields_in_order_to_the_end(family, admin, fx):
    add_item(family, fx, fx.sam, "Socks", url="amazon.com/s", note="blue"); add_item(family, fx, fx.sam, "Mug")
    e27 = mk_edition(admin, fx.id, 2027); put_roster(admin, e27, [fx.sam])
    add_item(family, fx, fx.sam, "Book", edition=e27)
    assert _bring(family, fx, e27).get_json() == {"copied": 2}
    page = family.get(f"/api/x/{fx.slug}/people/{fx.sam}?edition={e27}").get_json()
    assert [i["title"] for i in page["items"]] == ["Book", "Socks", "Mug"]
    socks = page["items"][1]
    assert (socks["url"], socks["note"], socks["version"], socks["updated_by"]) == ("https://amazon.com/s", "blue", 1, "Sam")
    assert _titles(family, fx, edition=fx.edition) == ["Socks", "Mug"]  # last year's list is untouched


def test_bring_over_uses_the_newest_earlier_edition_the_person_was_on(family, admin, fx):
    add_item(family, fx, fx.sam, "From 2026")
    e27 = mk_edition(admin, fx.id, 2027); put_roster(admin, e27, [fx.alex])          # Sam not on 2027
    e28 = mk_edition(admin, fx.id, 2028); put_roster(admin, e28, [fx.sam])
    add_item(family, fx, fx.alex, "Alex 2027", edition=e27)
    e29 = mk_edition(admin, fx.id, 2029); put_roster(admin, e29, [fx.sam])
    assert _bring(family, fx, e29).status_code == 400                                 # 2028 had Sam but no items
    add_item(family, fx, fx.sam, "From 2028", edition=e28)
    assert _bring(family, fx, e29).get_json() == {"copied": 1}
    assert _titles(family, fx, edition=e29) == ["From 2028"]
    assert _bring(family, fx, e28).get_json() == {"copied": 1}                        # only earlier years count
    assert _titles(family, fx, edition=e28) == ["From 2028", "From 2026"]


def test_bring_over_with_no_earlier_edition_is_400(family, fx):
    r = _bring(family, fx, fx.edition)
    assert r.status_code == 400 and r.get_json()["error"] == "Nothing to bring over."


def test_bring_over_scoping_closed_and_shape(family, admin, fx, other):
    add_item(family, fx, fx.sam, "Socks")
    e27 = mk_edition(admin, fx.id, 2027); put_roster(admin, e27, [fx.alex])
    assert _bring(family, fx, e27).status_code == 404                                 # Sam isn't on 2027
    assert _bring(family, fx, other.edition).status_code == 404                       # another exchange's edition
    assert _bring(family, fx, e27, pid=other.alex).status_code == 404
    put_roster(admin, e27, [fx.sam])
    assert family.post(f"/api/x/{fx.slug}/people/{fx.sam}/bring-over", json={"edition_id": e27}).status_code == 400
    assert family.post(f"/api/x/{fx.slug}/people/{fx.sam}/bring-over", json={"updated_by": "Sam"}).status_code == 400
    admin.patch(f"/api/admin/editions/{e27}", json={"status": "closed"})
    r = _bring(family, fx, e27)
    assert (r.status_code, r.get_json()["error"]) == (423, "This year is closed.")
    assert _titles(family, fx, edition=e27) == []
