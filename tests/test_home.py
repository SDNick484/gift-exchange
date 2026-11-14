"""GET /api/x/<slug>: the exchange home payload (Task 6)."""
import common
from conftest import add_item, mk_edition, put_roster, save_details


def test_home_shape_and_counts(family, fx):                                     # fx: unlocked exchange, edition 2026 open
    add_item(family, fx, fx.sam, "Socks"); save_details(family, fx, fx.sam, amazon_url="https://amazon.example.com/l/1")
    h = family.get(f"/api/x/{fx.slug}").get_json()
    sam = next(p for p in h["people"] if p["id"] == fx.sam)
    assert (sam["item_count"], sam["has_amazon"]) == (1, True) and h["pairings"] is None


def test_home_payload_fields(admin, family, fx, monkeypatch):
    admin.patch(f"/api/admin/editions/{fx.edition}",
                json={"budget": "50", "event_date": "2026-12-24", "location": "Riley's house", "rules": "One gift"})
    monkeypatch.setattr(common, "today", lambda: "2026-11-13")
    h = family.get(f"/api/x/{fx.slug}").get_json()
    assert h["exchange"] == {"slug": "family", "name": "Family", "accent_color": None}
    assert h["edition"] == {"id": fx.edition, "label": "2026", "year": 2026, "budget_cents": 5000,
                            "event_date": "2026-12-24", "location": "Riley's house", "rules": "One gift",
                            "status": "open", "days_until": 41}
    assert h["editions"] == [{"id": fx.edition, "label": "2026", "status": "open"}]
    assert [p["name"] for p in h["people"]] == ["Alex", "Jordan", "Sam"]
    assert h["people"][0] == {"id": fx.alex, "name": "Alex", "item_count": 0, "has_amazon": False}


def test_days_until_is_null_without_a_date_and_negative_after_it(admin, family, fx, monkeypatch):
    assert family.get(f"/api/x/{fx.slug}").get_json()["edition"]["days_until"] is None
    admin.patch(f"/api/admin/editions/{fx.edition}", json={"event_date": "2026-12-24"})
    monkeypatch.setattr(common, "today", lambda: "2026-12-26")
    assert family.get(f"/api/x/{fx.slug}").get_json()["edition"]["days_until"] == -2


def test_home_without_an_edition(family, x):
    h = family.get(f"/api/x/{x.slug}").get_json()
    assert (h["edition"], h["editions"], h["people"], h["pairings"]) == (None, [], [], None)


def test_edition_param_picks_a_past_year_and_its_roster(admin, family, fx):
    e25 = mk_edition(admin, fx.id, 2025)
    put_roster(admin, e25, [fx.alex])
    add_item(family, fx, fx.alex, "Old thing", edition=e25)
    h = family.get(f"/api/x/{fx.slug}?edition={e25}").get_json()
    assert h["edition"]["id"] == e25 and [(p["name"], p["item_count"]) for p in h["people"]] == [("Alex", 1)]
    assert [e["id"] for e in h["editions"]] == [fx.edition, e25]                  # newest year first
    assert next(p for p in family.get(f"/api/x/{fx.slug}").get_json()["people"]
                if p["id"] == fx.alex)["item_count"] == 0                       # items belong to one edition


def test_edition_param_must_be_an_id_of_this_exchange(family, fx, other):
    assert family.get(f"/api/x/{fx.slug}?edition={other.edition}").status_code == 404
    assert family.get(f"/api/x/{fx.slug}?edition=999").status_code == 404
    assert family.get(f"/api/x/{fx.slug}?edition=abc").status_code == 400
