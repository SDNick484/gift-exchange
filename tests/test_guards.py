import json

from conftest import mut


def test_mutation_needs_header_json_and_origin(client):
    assert client.post("/api/unlock", json={"password": "x"}).status_code == 400                     # no X-Exchange
    assert client.post("/api/unlock", data="password=x", headers={"X-Exchange": "1"}).status_code == 400
    assert client.post("/api/unlock", json={"password": "x"},
                       headers={"X-Exchange": "1", "Origin": "https://evil.example.com"}).status_code == 403


def test_mutation_rejections_are_json_errors(client):
    r = client.post("/api/unlock", json={"password": "x"})
    assert r.status_code == 400 and r.get_json()["error"]
    r = client.post("/api/unlock", json={"password": "x"}, headers={"X-Exchange": "1"})  # no Origin at all
    assert r.status_code == 403


def test_mutation_body_must_be_object(client):
    for body in ("[]", '"x"', "not json", "null"):
        r = client.post("/api/unlock", data=body, headers=mut(**{"Content-Type": "application/json"}))
        assert r.status_code == 400, body


def test_same_origin_mutation_reaches_the_route(client):
    r = client.post("/api/unlock", json={"password": "x"}, headers=mut())
    assert r.status_code == 403 and r.get_json() == {"error": "That password didn't match."}       # past the guard


def test_origin_scheme_may_differ_behind_a_proxy(client):
    r = client.post("/api/unlock", json={"password": "x"}, headers=mut(Origin="https://localhost"))
    assert r.status_code == 403 and r.get_json() == {"error": "That password didn't match."}


def test_guard_covers_every_mutating_method_under_api(client):
    for method in (client.put, client.patch, client.delete):
        assert method("/api/anything", json={}).status_code == 400
        assert method("/api/anything", json={}, headers=mut(Origin="https://evil.example.com")).status_code == 403


def test_guard_ignores_gets_and_non_api_paths(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/anything").status_code == 404
    assert client.post("/healthz").status_code == 405                      # not under /api/: no guard, just no POST route


def test_errors_render_as_json(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and "error" in json.loads(r.data)


def test_security_headers(client):
    r = client.get("/healthz")
    assert r.headers["Content-Security-Policy"] == (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'")
    assert r.headers["X-Robots-Tag"] == "noindex, nofollow" and r.headers["Referrer-Policy"] == "no-referrer"
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]


def test_api_responses_are_not_cached_others_are_untouched(client):
    assert client.get("/api/nope").headers["Cache-Control"] == "no-store"
    assert client.post("/api/unlock", json={}).headers["Cache-Control"] == "no-store"
    assert "no-store" not in client.get("/healthz").headers.get("Cache-Control", "")


def test_robots_disallows_all(client):
    r = client.get("/robots.txt")
    assert "Disallow: /" in r.get_data(as_text=True)
    assert r.headers["X-Robots-Tag"] == "noindex, nofollow"
