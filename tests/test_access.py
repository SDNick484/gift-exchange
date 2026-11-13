import os
import subprocess
import sys

import pytest
from itsdangerous import URLSafeTimedSerializer

import access
import settings
from conftest import _scrypt, mk_exchange, mut, token_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = 86400


def unlock(client, password, **headers):
    return client.post("/api/unlock", json={"password": password}, headers=mut(**headers))


def slugs(client):
    return [x["slug"] for x in client.get("/api/exchanges").get_json()]


# ---------------------------------------------------------------- the plan's Task 3 tests
def test_shared_password_unlocks_exactly_the_matches(client, con):
    mk_exchange(con, "adults", "pw-shared"); mk_exchange(con, "cousins", "pw-shared"); mk_exchange(con, "work", "pw-other")
    r = client.post("/api/unlock", json={"password": "pw-shared"}, headers=mut())
    assert sorted(x["slug"] for x in r.get_json()["exchanges"]) == ["adults", "cousins"]
    assert [x["slug"] for x in client.get("/api/exchanges").get_json()] == ["adults", "cousins"]
    assert client.get("/api/x/work").status_code == 403


def test_join_link_unlocks_only_its_exchange(client, con):
    mk_exchange(con, "adults", "pw"); b = mk_exchange(con, "cousins", "pw")
    r = client.get(f"/x/cousins/join/{token_of(con, b)}")
    assert r.status_code == 302 and r.headers["Location"].endswith("/#/x/cousins")
    assert [x["slug"] for x in client.get("/api/exchanges").get_json()] == ["cousins"]


def test_bad_join_token_sets_nothing(client, con):
    mk_exchange(con, "adults", "pw")
    client.get("/x/adults/join/nope")
    assert client.get("/api/exchanges").get_json() == []


def test_password_change_revokes_cookie(client, con):
    a = mk_exchange(con, "adults", "pw"); client.post("/api/unlock", json={"password": "pw"}, headers=mut())
    con.execute("UPDATE exchange SET password_version = password_version + 1 WHERE id=?", (a,)); con.commit()
    assert client.get("/api/x/adults").status_code == 403


def test_inactive_exchange_is_not_unlocked(client, con):
    mk_exchange(con, "adults", "pw", active=0)
    assert client.post("/api/unlock", json={"password": "pw"}, headers=mut()).status_code == 403


def test_throttle_after_ten_failures(client, con, clock):
    mk_exchange(con, "adults", "pw")
    for _ in range(10):
        assert client.post("/api/unlock", json={"password": "no"}, headers=mut()).status_code == 403
    assert client.post("/api/unlock", json={"password": "pw"}, headers=mut()).status_code == 429
    clock.advance(301)
    assert client.post("/api/unlock", json={"password": "pw"}, headers=mut()).status_code == 200


def test_admin_login_and_guard(client, clock):
    assert client.get("/api/admin/exchanges").status_code == 403
    assert client.post("/api/admin/login", json={"password": "admin-pass"}, headers=mut()).status_code == 200
    assert client.get("/api/admin/exchanges").status_code == 200
    clock.advance(12 * 3600 + 1)
    assert client.get("/api/admin/exchanges").status_code == 403


def test_exchange_cookie_is_not_admin(client, con):
    mk_exchange(con, "adults", "pw"); client.post("/api/unlock", json={"password": "pw"}, headers=mut())
    assert client.get("/api/admin/exchanges").status_code == 403


def test_cookie_flags(client, con):
    mk_exchange(con, "adults", "pw")
    sc = client.post("/api/unlock", json={"password": "pw"}, headers=mut()).headers["Set-Cookie"]
    assert "HttpOnly" in sc and "Secure" in sc and "SameSite=Lax" in sc


# ---------------------------------------------------------------- passwords
def test_hash_password_format_and_verify():
    stored = access.hash_password("correct horse")
    kind, salt, digest = stored.split("$")
    assert kind == "scrypt" and len(bytes.fromhex(salt)) == 16 and len(bytes.fromhex(digest)) == 64
    assert access.verify_password(stored, "correct horse")
    assert not access.verify_password(stored, "correct horse ")
    assert access.hash_password("correct horse") != stored                      # a fresh salt each time


def test_verify_reads_the_conftest_encoding():                                # what settings' admin hash uses
    assert access.verify_password(_scrypt("admin-pass"), "admin-pass")


@pytest.mark.parametrize("stored", ["", "x", "scrypt$zz$00", "scrypt$00", "bcrypt$00$00", "scrypt$$", None])
def test_verify_never_raises_on_a_bad_hash(stored):
    assert access.verify_password(stored, "pw") is False


# ---------------------------------------------------------------- unlock and the access cookie
def test_unlock_wrong_password_message(client, con):
    mk_exchange(con, "adults", "pw")
    r = unlock(client, "nope")
    assert r.status_code == 403 and r.get_json() == {"error": "That password didn't match."}
    assert "gx_access" not in r.headers.get("Set-Cookie", "")


def test_unlock_needs_a_password(client):
    assert client.post("/api/unlock", json={}, headers=mut()).status_code == 400
    assert client.post("/api/unlock", json={"password": 5}, headers=mut()).status_code == 400


def test_unlock_function_returns_active_matches(con):
    a = mk_exchange(con, "adults", "pw"); b = mk_exchange(con, "cousins", "pw")
    mk_exchange(con, "work", "other"); mk_exchange(con, "old", "pw", active=0)
    assert sorted(access.unlock(con, "pw")) == sorted([a, b])
    assert access.unlock(con, "missing") == []


def test_unlocking_a_second_password_merges(client, con):
    mk_exchange(con, "adults", "pw-a"); mk_exchange(con, "work", "pw-w")
    unlock(client, "pw-a"); unlock(client, "pw-w")
    assert slugs(client) == ["adults", "work"]


def test_exchanges_follow_sort_order(client, con):
    mk_exchange(con, "zed", "pw", sort_order=1); mk_exchange(con, "alpha", "pw", sort_order=2); mk_exchange(con, "mid", "pw", sort_order=0)
    unlock(client, "pw")
    assert slugs(client) == ["mid", "zed", "alpha"]
    assert client.get("/api/exchanges").get_json()[0] == {"slug": "mid", "name": "Mid"}


def test_access_cookie_lasts_400_days_and_slides(client, con, clock):
    mk_exchange(con, "adults", "pw")
    sc = unlock(client, "pw").headers["Set-Cookie"]
    assert f"Max-Age={400 * DAY}" in sc and "Path=/" in sc
    clock.advance(399 * DAY)
    r = client.get("/api/exchanges")                                           # a visit renews it
    assert [x["slug"] for x in r.get_json()] == ["adults"] and "gx_access=" in r.headers["Set-Cookie"]
    clock.advance(399 * DAY)
    assert slugs(client) == ["adults"]
    clock.advance(400 * DAY + 1)                                               # no visit for over 400 days
    assert slugs(client) == []


def test_no_cookie_means_no_set_cookie(client):
    assert "Set-Cookie" not in client.get("/api/exchanges").headers


def test_reissue_keeps_entries_on_every_response(client, con):
    mk_exchange(con, "adults", "pw"); unlock(client, "pw")
    for path in ("/healthz", "/api/nope", "/robots.txt"):
        assert "gx_access=" in client.get(path).headers.get("Set-Cookie", ""), path
    assert slugs(client) == ["adults"]


def test_forged_or_foreign_cookies_unlock_nothing(client, con):
    a = mk_exchange(con, "adults", "pw")
    wrong_key = URLSafeTimedSerializer(b"not the key", salt="access").dumps({"x": {str(a): 1}})
    client.set_cookie("gx_access", wrong_key)
    assert slugs(client) == []
    other_salt = URLSafeTimedSerializer(settings.SECRET_KEY, salt="admin").dumps({"x": {str(a): 1}})
    client.set_cookie("gx_access", other_salt)
    assert slugs(client) == []
    client.set_cookie("gx_access", "garbage")
    assert slugs(client) == [] and client.get("/api/x/adults").status_code == 403


def test_deactivating_hides_an_unlocked_exchange(client, con):
    a = mk_exchange(con, "adults", "pw"); unlock(client, "pw")
    con.execute("UPDATE exchange SET active = 0 WHERE id = ?", (a,))
    assert slugs(client) == [] and client.get("/api/x/adults").status_code == 404


def test_new_password_after_change_unlocks_again(client, con):
    a = mk_exchange(con, "adults", "pw"); unlock(client, "pw")
    con.execute("UPDATE exchange SET password_hash = ?, password_version = password_version + 1 WHERE id = ?",
                (access.hash_password("pw2"), a))
    assert slugs(client) == []
    assert unlock(client, "pw").status_code == 403 and unlock(client, "pw2").status_code == 200
    assert slugs(client) == ["adults"]


# ---------------------------------------------------------------- exchange_required
def test_exchange_required_answers(client, con):
    mk_exchange(con, "adults", "pw"); mk_exchange(con, "old", "pw", active=0)
    r = client.get("/api/x/adults")
    assert r.status_code == 403 and r.get_json() == {"error": "Locked", "locked": True}
    assert client.get("/api/x/nobody").status_code == 404
    assert client.get("/api/x/old").status_code == 404
    unlock(client, "pw")
    assert client.get("/api/x/adults").status_code == 200


# ---------------------------------------------------------------- share links
def test_join_sets_a_lax_cookie_and_no_store(client, con):
    a = mk_exchange(con, "adults", "pw")
    r = client.get(f"/x/adults/join/{token_of(con, a)}")
    sc = r.headers["Set-Cookie"]
    assert "gx_access=" in sc and "HttpOnly" in sc and "Secure" in sc and "SameSite=Lax" in sc
    assert r.headers["Cache-Control"] == "no-store"


def test_join_merges_with_an_existing_cookie(client, con):
    mk_exchange(con, "adults", "pw"); w = mk_exchange(con, "work", "other")
    unlock(client, "pw"); client.get(f"/x/work/join/{token_of(con, w)}")
    assert slugs(client) == ["adults", "work"]


def test_bad_join_token_redirects_without_a_cookie(client, con):
    a = mk_exchange(con, "adults", "pw")
    for path in ("/x/adults/join/nope", f"/x/nobody/join/{token_of(con, a)}"):
        r = client.get(path)
        assert r.status_code == 302 and "Set-Cookie" not in r.headers, path
    assert client.get("/x/nobody/join/nope").headers["Location"].endswith("/#/x/nobody")


def test_another_exchanges_token_does_not_open_this_one(client, con):
    mk_exchange(con, "adults", "pw"); b = mk_exchange(con, "cousins", "pw")
    client.get(f"/x/adults/join/{token_of(con, b)}")
    assert slugs(client) == []


def test_join_to_an_inactive_exchange_sets_nothing(client, con):
    a = mk_exchange(con, "adults", "pw", active=0)
    r = client.get(f"/x/adults/join/{token_of(con, a)}")
    assert r.status_code == 302 and "Set-Cookie" not in r.headers


def test_join_with_an_odd_slug_redirects_home(client):
    r = client.get("/x/Bad%20Slug/join/nope")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")


# ---------------------------------------------------------------- throttle
def test_throttled_attempts_are_not_recorded(client, con, clock):
    mk_exchange(con, "adults", "pw")
    for _ in range(10): unlock(client, "no")
    for _ in range(5):
        r = unlock(client, "no")
        assert r.status_code == 429 and r.get_json() == {"error": "Too many tries. Wait a few minutes."}
        clock.advance(60)                                                      # 300 s of 429s, none recorded
    clock.advance(1)
    assert unlock(client, "pw").status_code == 200


def test_throttle_lasts_while_the_newest_failure_is_recent(client, con, clock):
    mk_exchange(con, "adults", "pw")
    for _ in range(10): unlock(client, "no")
    clock.advance(299)
    assert unlock(client, "pw").status_code == 429                             # newest failure is 299 s old
    clock.advance(1)
    assert unlock(client, "pw").status_code == 200                             # 300 s: no longer "> now-300"


def test_failures_older_than_ten_minutes_do_not_count(client, con, clock):
    mk_exchange(con, "adults", "pw")
    for _ in range(9): unlock(client, "no")
    clock.advance(600)
    assert unlock(client, "no").status_code == 403                             # the nine are now 600 s old
    assert unlock(client, "pw").status_code == 200


def test_success_clears_the_scope(client, con, clock):
    mk_exchange(con, "adults", "pw")
    for _ in range(9): unlock(client, "no")
    assert unlock(client, "pw").status_code == 200
    for _ in range(9): unlock(client, "no")
    assert unlock(client, "pw").status_code == 200


def test_join_link_shares_the_exchange_scope(client, con, clock):
    a = mk_exchange(con, "adults", "pw")
    for _ in range(10): client.get("/x/adults/join/nope")
    assert unlock(client, "pw").status_code == 429
    r = client.get(f"/x/adults/join/{token_of(con, a)}")                      # even a good link waits
    assert r.status_code == 429 and "Set-Cookie" not in r.headers
    clock.advance(301)
    assert client.get(f"/x/adults/join/{token_of(con, a)}").status_code == 302 and slugs(client) == ["adults"]


def test_admin_has_its_own_scope(client, con, clock):
    mk_exchange(con, "adults", "pw")
    for _ in range(10):
        assert client.post("/api/admin/login", json={"password": "no"}, headers=mut()).status_code == 403
    assert client.post("/api/admin/login", json={"password": "admin-pass"}, headers=mut()).status_code == 429
    assert unlock(client, "pw").status_code == 200
    clock.advance(301)
    assert client.post("/api/admin/login", json={"password": "admin-pass"}, headers=mut()).status_code == 200


def test_throttle_ignores_client_ip_headers(client, con, clock):
    mk_exchange(con, "adults", "pw")
    for i in range(10): unlock(client, "no", **{"X-Forwarded-For": f"203.0.113.{i}", "Cf-Connecting-Ip": f"198.51.100.{i}"})
    assert unlock(client, "pw", **{"X-Forwarded-For": "192.0.2.1"}).status_code == 429


def test_throttle_functions(con, clock):
    assert not access.throttled(con, "admin")
    for _ in range(10): access.record_failure(con, "admin")
    assert access.throttled(con, "admin") and not access.throttled(con, "exchange")
    access.clear_failures(con, "admin")
    assert not access.throttled(con, "admin")


# ---------------------------------------------------------------- admin session
def test_admin_cookie_flags(client):
    sc = client.post("/api/admin/login", json={"password": "admin-pass"}, headers=mut()).headers["Set-Cookie"]
    assert sc.startswith("gx_admin=") and "HttpOnly" in sc and "Secure" in sc and "SameSite=Strict" in sc
    assert f"Max-Age={12 * 3600}" in sc and "Path=/" in sc


def test_admin_wrong_password(client):
    r = client.post("/api/admin/login", json={"password": "nope"}, headers=mut())
    assert r.status_code == 403 and r.get_json() == {"error": "That password didn't match."}
    assert "Set-Cookie" not in r.headers


def test_admin_guard_message(client):
    r = client.get("/api/admin/exchanges")
    assert r.status_code == 403 and r.get_json() == {"error": "Admin only"}


def test_admin_session_slides_with_use(client, clock):
    client.post("/api/admin/login", json={"password": "admin-pass"}, headers=mut())
    clock.advance(11 * 3600)
    r = client.get("/api/admin/exchanges")
    assert r.status_code == 200 and "gx_admin=" in r.headers["Set-Cookie"]
    clock.advance(11 * 3600)
    assert client.get("/api/admin/exchanges").status_code == 200


def test_admin_logout(client):
    client.post("/api/admin/login", json={"password": "admin-pass"}, headers=mut())
    assert client.get("/api/session").get_json()["admin"] is True
    r = client.post("/api/admin/logout", json={}, headers=mut())
    assert r.status_code == 200 and "gx_admin=;" in r.headers["Set-Cookie"]
    assert client.get("/api/admin/exchanges").status_code == 403


def test_access_cookie_value_is_not_an_admin_cookie(client, con):
    mk_exchange(con, "adults", "pw"); unlock(client, "pw")
    client.set_cookie("gx_admin", client.get_cookie("gx_access").value)
    assert client.get("/api/admin/exchanges").status_code == 403


def test_no_admin_hash_means_no_admin(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", "")
    assert client.post("/api/admin/login", json={"password": ""}, headers=mut()).status_code == 400
    assert client.post("/api/admin/login", json={"password": "admin-pass"}, headers=mut()).status_code == 403


def test_session(client):
    assert client.get("/api/session").get_json() == {"app_name": "Gift Exchange", "admin": False}
    client.post("/api/admin/login", json={"password": "admin-pass"}, headers=mut())
    assert client.get("/api/session").get_json() == {"app_name": "Gift Exchange", "admin": True}


# ---------------------------------------------------------------- manage.py
def test_manage_hash_password(tmp_path):
    env = {**os.environ, "DATA_DIR": str(tmp_path / "data")}
    out = subprocess.run([sys.executable, os.path.join(ROOT, "manage.py"), "hash-password"], input="admin-pass\n",
                         capture_output=True, text=True, env=env, check=True).stdout.strip()
    assert access.verify_password(out, "admin-pass")
    assert not os.path.exists(tmp_path / "data")                              # hashing touches no data


def test_manage_rejects_an_empty_password(tmp_path):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "manage.py"), "hash-password"], input="\n",
                       capture_output=True, text=True)
    assert r.returncode != 0 and not r.stdout
