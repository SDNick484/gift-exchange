# Gift Exchange Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo each task is delivered as one Prompt issue run through issue-queue; PRs stack in task order.

**Goal:** A small self-hosted app where an extended family sees each exchange's pairings, budget, date and rules, and keeps per-person sizes, favorites and wishlists, behind one shared password.

**Architecture:** A new standalone Flask + SQLite app in its own public repo, `gift-exchange`. `app.py` holds the Flask object, hooks and routes. Route-free logic lives in sibling modules that take a `sqlite3.Connection`. The frontend is a small hash-routed SPA of native ES modules with no build step. Access is a signed cookie set by a shared exchange password or a share link. A separate admin password guards structure.

**Tech Stack:** Python 3.12, Flask 3 (with itsdangerous), gunicorn, SQLite (WAL), pytest, plain HTML/CSS/JS (ES modules), node --test, Alpine + OpenRC installer.

**Spec:** `docs/superpowers/specs/2026-11-13-gift-exchange-design.md` (committed with this plan before Task 1).

**Schedule:** Tasks 1 to 8 must be deployed by **Wed 2026-11-25** (bowl draw at Thanksgiving). Tasks 9 and 10 follow.

## Global Constraints

- Runtime dependencies are only Alpine packages `py3-flask py3-gunicorn`. Everything else is from the standard library. No PyJWT, no cryptography.
- No frontend framework, bundler or npm step. Native ES modules in `static/js/`, with `static/js/package.json` = `{"type": "module"}`.
- No personal data in the repo:
  - generic names (Alex, Sam, Jordan, Riley, Casey) and `example.com` hosts
  - RFC 5737 addresses
  - household values only in git-ignored `deploy/deploy.env`
- No Cloudflare Access. The app trusts no `Cf-*` or `X-Forwarded-*` header for identity or throttling.
- Every mutation (any non-GET under `/api/`) needs header `X-Exchange: 1`, a JSON object body, and an `Origin` equal to the request host's origin. Otherwise 400, or 403 for a foreign Origin.
- Bodies are read with `json_body()` and strings with `text(data, key, max_len)`. Bad shapes return 400. Money is integer cents parsed without `float`.
- Everything user-typed goes through `esc()` before `innerHTML`.
- CSP: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`.
- Every response has these headers:
  - `X-Robots-Tag: noindex, nofollow`
  - `Referrer-Policy: no-referrer`
  - `Cache-Control: no-store` on `/api/`
- `<title>` and the manifest use `APP_NAME` (default `Gift Exchange`), never a person's name.
- Schema changes go through idempotent `migrate()` and bump `SCHEMA_VERSION`. No manual DB step on the host.
- Commits: Conventional Commits, one logical change each, author `SDNick484 <SDNick484@users.noreply.github.com>`.
- Docs use OpenRC commands and say `vim`.
- Default port is `8770` (`EXCHANGE_PORT`). Gunicorn binds `127.0.0.1` only.

## Review Focus

1. **Shared passwords unlock exactly their matches.** Exchanges A and B share a password and C has another. Typing A's password unlocks A and B, never C. B's share link unlocks only B. (Task 3)
2. **Half-entered pairings survive and stay hidden.** The admin enters pairings halfway and closes the tab. The draft is there on return, and the family sees "Names not drawn yet." Mark paired with a duplicate recipient, a self-pair or a missing giver is refused with a message naming the person. (Task 5)
3. **Two phones save the same list.** The second save gets 409 with the reload message, and its typed text stays in the form. (Tasks 6, 7)
4. **A relative pastes `amazon.com/hz/wishlist/ls/ABC123 ` with no scheme and a trailing space.** It's stored as `https://amazon.com/hz/wishlist/ls/ABC123`. `javascript:alert(1)` and `see my list` are 400. (Task 6)
5. **A roster change can't orphan a pairing.** Removing someone from an edition, or deactivating them, while a pairing names them is 409 "Remove their pairing first." It never leaves a dangling pairing or makes the home page error. (Task 4)

## File structure

```
app.py            Flask object, before/after hooks, every route
settings.py       environment config, read once at import
db.py             SCHEMA, SCHEMA_VERSION, connect(), migrate()
common.py         ApiError, json_body, text, parse_cents, clean_url, now, today
access.py         password hashing, unlock (option C), share links, cookies, admin session, throttle
exchanges.py      exchanges, editions, people, roster, profile fields, current edition
pairings.py       draft save, validation, warnings, visibility
lists.py          participant details, profile values, wish items, versions
draw.py           in-app draw (Task 10)
static/           index.html, style.css, manifest.json, icon.svg, robots.txt
static/js/        main.js core.js api.js unlock.js whoami.js home.js person.js admin.js admin-pairings.js package.json
tests/            conftest.py + one test file per module, frontend.test.mjs
installer/        setup-head.sh, build.sh
deploy/           deploy.env.example
ops/              exchange-backup
docs/superpowers/ specs/, plans/
CLAUDE.md README.md requirements.txt requirements-dev.txt ruff.toml .gitignore .github/workflows/ci.yml
```

---

### Task 1: Scaffold, settings and schema

**Files:**
- Create: `settings.py`, `db.py`, `app.py`, `requirements.txt`, `requirements-dev.txt`, `ruff.toml`, `.gitignore`, `CLAUDE.md`, `README.md`, `.github/workflows/ci.yml`, (the spec and this plan are already under `docs/superpowers/`)
- Test: `tests/conftest.py`, `tests/test_db.py`, `tests/test_hygiene.py`

**Interfaces:**
- Produces:
  - Settings: `settings.DATA_DIR, DB_PATH, PORT, APP_NAME, ADMIN_PASSWORD_HASH: str, SECRET_KEY: bytes`. `SECRET_KEY` comes from the env if set, else `DATA_DIR/secret.key`, created with 32 random bytes and mode 0600 on first start.
  - `db.SCHEMA_VERSION = 1`, `db.connect(path) -> sqlite3.Connection` (Row factory, `foreign_keys=ON`, WAL), `db.migrate(con) -> None`.
  - `app.app`, `app.db()` (per request, in `flask.g`), and `GET /healthz -> {"ok": true}`.
  - Fixtures: `client` (fresh database per test) and `con`.

Schema v1, from the spec's data model with these exact decisions:

- `exchange.password_hash` holds the encoded `scrypt$<salt hex>$<hash hex>`, so there's no separate salt column.
- `participant` and `wish_item` each carry `version INTEGER NOT NULL DEFAULT 1`.
- Timestamps are integer epoch seconds.
- `pairing.recipient_id` is nullable (a draft row).
- `edition` has `UNIQUE(exchange_id, year)`.
- `person` has `UNIQUE(exchange_id, name)`.
- `edition_people (edition_id, person_id, PRIMARY KEY both)` is the per-year roster.
- `participant` rows are created lazily on first save.
- `profile_value` carries `updated_at` as its version.
- `login_failure (scope TEXT CHECK (scope IN ('exchange','admin')), at INTEGER)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_migrate_creates_every_table(con):
    names = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"meta","exchange","edition","person","edition_people","participant","pairing",
            "wish_item","profile_field","profile_value","login_failure"} <= names
    assert con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "1"

def test_migrate_is_idempotent(con):
    db.migrate(con); db.migrate(con)
    assert con.execute("SELECT COUNT(*) FROM meta WHERE key='schema_version'").fetchone()[0] == 1

def test_pairing_constraints(con, seed):                     # seed: one exchange, edition, people a, b, c
    con.execute("INSERT INTO pairing VALUES (?,?,?)", (seed.ed, seed.a, seed.b))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO pairing VALUES (?,?,?)", (seed.ed, seed.c, seed.b))   # recipient twice
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO pairing VALUES (?,?,?)", (seed.ed, seed.c, seed.c))   # self

def test_healthz_is_open_and_bare(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.get_json() == {"ok": True}

def test_secret_key_file_is_0600(tmp_path, monkeypatch): ...   # reload settings with DATA_DIR=tmp_path

# tests/test_hygiene.py: walk `git ls-files`; fail on any email or URL host not ending example.com
# (noreply.github.com, github.com, cloudflare docs exempt), and on lines in git-ignored tests/hygiene_denylist.txt.
```

- [ ] **Step 2: Run `python -m pytest -q`. Expect import errors.**
- [ ] **Step 3: Implement `settings.py`, `db.py` and the `app.py` skeleton.** `conftest.py` sets `DATA_DIR` to a temp dir and `ADMIN_PASSWORD_HASH` to the hash of `admin-pass` before importing `app`.
- [ ] **Step 4: Write `CLAUDE.md`** with the Global Constraints as "Rules that must keep holding", the file structure, and the commands `python -m pytest -q`, `node --test tests/`, `for f in static/js/*.js; do node --check "$f"; done`, `ruff check`.
- [ ] **Step 5: Add CI.** Run pytest on Python 3.12 and latest, an Alpine job that installs only `py3-*` packages, `ruff check`, and `node --check` plus `node --test`.
- [ ] **Step 6: Run `python -m pytest -q`. Expect all passed.**
- [ ] **Step 7: Commit** `chore: scaffold app, settings and schema v1`

### Task 2: Request guards and common helpers

**Files:**
- Create: `common.py`, `static/robots.txt`
- Modify: `app.py`
- Test: `tests/test_common.py`, `tests/test_guards.py`

**Interfaces:**
- Produces:
  - Errors and input helpers: `common.ApiError(status: int, message: str)`, `json_body() -> dict`, `text(data, key, max_len, required=False) -> str | None` (stripped; empty becomes `None` unless required, and required-and-empty is 400).
  - `common.parse_cents(value) -> int | None`
  - `common.clean_url(value) -> str | None`
  - Clock: `common.now() -> int`, `common.today() -> str` (tests monkeypatch both)
- Errors render as `{"error": message}` with their status.

Rules for the input helpers:

- `parse_cents` accepts an int or strings like `25`, `25.5`, `$25.00` and `1,299`. Empty or `None` gives `None`. Negative, non-numeric, more than 2 decimals, `NaN`/`inf`, a `bool` or `float` type, or more than 100,000,000 cents is 400. It never calls `float()`.
- `clean_url`:
  - trims whitespace; empty gives `None`
  - accepts `http://` or `https://`
  - with no scheme and no whitespace, when the part before the first `/` contains a `.`, prepends `https://`
  - anything else, or more than 2000 characters, is 400

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("raw,cents", [("25", 2500), ("25.5", 2550), ("$25.00", 2500), ("1,299", 129900),
                                        (5000, 5000), ("", None), (None, None)])
def test_parse_cents_accepts(raw, cents): assert common.parse_cents(raw) == cents

@pytest.mark.parametrize("raw", ["abc", "-5", "NaN", "inf", "1.999", "1e5", 12.5, True, 100_000_001])
def test_parse_cents_rejects(raw):
    with pytest.raises(common.ApiError): common.parse_cents(raw)

@pytest.mark.parametrize("raw,out", [(" https://a.example.com/x ", "https://a.example.com/x"),
                                      ("amazon.example.com/hz/wishlist/ls/ABC123 ", "https://amazon.example.com/hz/wishlist/ls/ABC123"),
                                      ("", None)])
def test_clean_url_accepts(raw, out): assert common.clean_url(raw) == out

@pytest.mark.parametrize("raw", ["javascript:alert(1)", "see my list", "ftp://x.example.com", "x" * 2001, "//x.example.com"])
def test_clean_url_rejects(raw):
    with pytest.raises(common.ApiError): common.clean_url(raw)

def test_mutation_needs_header_json_and_origin(client):
    assert client.post("/api/unlock", json={"password": "x"}).status_code == 400                     # no X-Exchange
    assert client.post("/api/unlock", data="password=x", headers={"X-Exchange": "1"}).status_code == 400
    assert client.post("/api/unlock", json={"password": "x"},
                       headers={"X-Exchange": "1", "Origin": "https://evil.example.com"}).status_code == 403

def test_security_headers(client):
    r = client.get("/healthz")
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Robots-Tag"] == "noindex, nofollow" and r.headers["Referrer-Policy"] == "no-referrer"

def test_robots_disallows_all(client):
    assert "Disallow: /" in client.get("/robots.txt").get_data(as_text=True)
```

- [ ] **Step 2: Run. Expect failures.**
- [ ] **Step 3: Implement `common.py`, the `before_request` mutation guard, the `after_request` headers and the `ApiError` handler.** `POST /api/unlock` may be a stub returning 403 until Task 3. Test helper `mut(**extra)` returns `{"X-Exchange": "1", "Origin": "http://localhost"}`.
- [ ] **Step 4: Run. Expect passed.**
- [ ] **Step 5: Commit** `feat: request guards, security headers and input helpers`

### Task 3: Access (passwords, option C unlock, share links, admin, throttle)

**Files:**
- Create: `access.py`, `manage.py`
- Modify: `app.py`
- Test: `tests/test_access.py`

**Interfaces:**
- Produces:
  - Passwords: `access.hash_password(pw: str) -> str` (scrypt n=2**14, r=8, p=1, 16-byte salt, encoded `scrypt$salt$hash`) and `access.verify_password(stored: str, pw: str) -> bool` (constant-time compare).
  - Unlock: `access.unlock(con, pw) -> list[int]` (ids of active exchanges whose hash matches) and `access.unlocked_ids(con, request) -> set[int]` (cookie entries whose `password_version` still matches and whose exchange is active).
  - Throttle: `access.throttled(con, scope) -> bool`, `access.record_failure(con, scope)`, `access.clear_failures(con, scope)`.
  - Admin: `access.is_admin(request) -> bool`.
  - Route decorators `exchange_required` (resolves `<slug>`, 404 when unknown or inactive, 403 `{"error":"Locked","locked":true}` when not unlocked) and `admin_required` (403 `{"error":"Admin only"}`).
  - Routes:
    - `POST /api/unlock {password}` → 200 `{"exchanges":[{"slug","name"}]}`, 403 `{"error":"That password didn't match."}`, or 429
    - `GET /api/exchanges` (unlocked only, by `sort_order`)
    - `GET /x/<slug>/join/<token>` → sets cookie for that exchange only, then 302 to `/#/x/<slug>`; a bad token gives 302 to `/#/x/<slug>` without a cookie
    - `POST /api/admin/login {password}` and `POST /api/admin/logout`
    - `GET /api/session` → `{"app_name","admin": bool}`
  - `manage.py hash-password` reads a password from stdin and prints `hash_password()`.

Rules:

- Access cookie `gx_access`: `URLSafeTimedSerializer(SECRET_KEY, salt="access").dumps({"x": {str(id): password_version}})`.
  - Flags: `HttpOnly`, `Secure`, `SameSite=Lax`, path `/`, `max_age` 400 days.
  - Unlocking merges new ids into the existing entries.
  - Every response to a request carrying a valid cookie re-issues it.
- Admin cookie `gx_admin`: separate salt `"admin"`, payload `{"a": 1}`, `SameSite=Strict`, valid for 12 h and re-issued on each admin request.
- Throttle: a scope is throttled when it has ≥10 failures with `at > now-600` and its newest failure is `> now-300`.
  - While throttled, attempts answer 429 `{"error":"Too many tries. Wait a few minutes."}` and aren't recorded.
  - Success clears the scope.
  - Exchange unlock and the join link share scope `exchange`. Admin uses scope `admin`.
- Changing an exchange's password (Task 4) bumps `password_version` and regenerates `link_token`.

- [ ] **Step 1: Write the failing tests**

```python
def test_shared_password_unlocks_exactly_the_matches(client, con):
    a = mk_exchange(con, "adults", "pw-shared"); b = mk_exchange(con, "cousins", "pw-shared"); c = mk_exchange(con, "work", "pw-other")
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
    a = mk_exchange(con, "adults", "pw", active=0)
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
```

(`mk_exchange` and `token_of` are conftest helpers that use `access.hash_password`. `clock` monkeypatches `common.now`. `GET /api/admin/exchanges` and `GET /api/x/<slug>` may be stubs until Tasks 4 and 6.)

- [ ] **Step 2: Run. Expect failures.**
- [ ] **Step 3: Implement `access.py`, `manage.py` and the routes.**
- [ ] **Step 4: Run. Expect passed.**
- [ ] **Step 5: Commit** `feat(access): shared exchange passwords, share links, admin session, throttle`

### Task 4: Admin structure (exchanges, editions, people, roster, profile fields)

**Files:**
- Create: `exchanges.py`
- Modify: `app.py`
- Test: `tests/test_exchanges.py`

**Interfaces:**
- Consumes: `access.hash_password`, `admin_required`
- Produces:
  - `exchanges.DEFAULT_FIELDS: list[tuple[str, str | None]]`, the spec's eight `(label, hint)` pairs in order:
    - `("Shirt size", None)`
    - `("Pants size", "waist/length, or kids' size")`
    - `("Shoe size", None)`
    - `("Favorite colors", None)`
    - `("Interests and hobbies", None)`
    - `("Favorite stores", None)`
    - `("Already have / don't need", None)`
    - `("Please avoid", "dislikes, allergies, scents")`
  - `exchanges.create_exchange(con, slug, name, password) -> int` (seeds `DEFAULT_FIELDS` and a `secrets.token_urlsafe(16)` link token)
  - `exchanges.create_edition(con, exchange_id, year: int, label: str | None, copy_roster: bool) -> int` (label defaults to `str(year)`; `copy_roster` copies `edition_people` from the newest earlier edition, keeping only active people)
  - `exchanges.current_edition(con, exchange_id) -> sqlite3.Row | None` (newest `year` not `closed`, else newest)
  - `exchanges.set_roster(con, edition_id, person_ids: list[int]) -> None`
  - Admin routes:
    - `GET/POST /api/admin/exchanges`
    - `PATCH /api/admin/exchanges/<id>` `{name?, slug?, active?, accent_color?, sort_order?, password?}`
    - `POST /api/admin/exchanges/<id>/link` → `{"url": "<host>/x/<slug>/join/<token>"}` (regenerates)
    - `GET/POST /api/admin/exchanges/<id>/people`
    - `PATCH /api/admin/people/<id>` `{name?, household?, active?}`
    - `GET/POST /api/admin/exchanges/<id>/editions`
    - `PATCH /api/admin/editions/<id>` `{label?, budget?, event_date?, location?, rules?, status?}`
    - `PUT /api/admin/editions/<id>/roster` `{person_ids}`
    - `GET/POST /api/admin/exchanges/<id>/fields`
    - `PATCH /api/admin/fields/<id>` `{label?, hint?, active?}`
    - `PUT /api/admin/exchanges/<id>/fields/order` `{ids}`

Rules:

- Field formats:
  - `slug` matches `^[a-z0-9][a-z0-9-]{0,39}$`; `admin`, `api`, `x` and `static` are reserved (400).
  - `accent_color` matches `^#[0-9a-fA-F]{6}$` or is null.
  - `event_date` is `YYYY-MM-DD` or null; `year` is between 2000 and 2100.
  - `budget` goes through `parse_cents`.
  - `status` is `open`, `paired` or `closed`; setting `paired` here is 400 (use Mark paired, Task 5). `closed → open` is allowed. Changing `rules` keeps up to 2000 characters.
  - Passwords are 4 to 128 characters. Changing one bumps `password_version` and regenerates `link_token`.
- Duplicates: a second edition with the same `(exchange, year)` is 409, and so is a duplicate person name in one exchange.
- **Review focus 5:** `set_roster` that drops a person named in any pairing of that edition is 409 `{"error":"Remove their pairing first: <name>."}`. Deactivating a person who is on the roster of an edition that isn't `closed` and has a pairing naming them gets the same 409.
- Past editions (an earlier `year`) can be created at any time.

- [ ] **Step 1: Write the failing tests**

```python
def test_new_exchange_gets_default_fields_in_order(admin, con):
    xid = admin.post("/api/admin/exchanges", json={"slug": "cousins", "name": "Cousins", "password": "pw12"}).get_json()["id"]
    labels = [f["label"] for f in admin.get(f"/api/admin/exchanges/{xid}/fields").get_json()]
    assert labels == [l for l, _ in exchanges.DEFAULT_FIELDS]

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
```

(`admin` is a client fixture already logged in as admin with `mut()` headers applied.)

- [ ] **Step 2: Run. Expect failures.**
- [ ] **Step 3: Implement `exchanges.py` and the routes.**
- [ ] **Step 4: Run. Expect passed.**
- [ ] **Step 5: Commit** `feat(admin): exchanges, editions, roster, people and profile fields`

### Task 5: Pairings (draft, Mark paired, warnings, visibility)

**Files:**
- Create: `pairings.py`
- Modify: `app.py`
- Test: `tests/test_pairings.py`

**Interfaces:**
- Consumes: `exchanges.current_edition`
- Produces:
  - `pairings.save_draft(con, edition_id, pairs: list[tuple[int, int | None]]) -> None` (replaces all rows; edition must be `open`, else 409)
  - `pairings.problems(con, edition_id) -> list[str]` (blocking)
  - `pairings.warnings(con, edition_id) -> list[str]` (non-blocking)
  - `pairings.mark_paired(con, edition_id) -> None` (raises `ApiError(400, "; ".join(problems))`)
  - `pairings.visible(con, edition_id, *, admin: bool) -> list[dict] | None` → `[{"giver_id","giver","recipient_id","recipient"}]` sorted by giver name, or `None` when hidden
  - Routes:
    - `GET /api/admin/editions/<id>/pairings` → `{"pairs", "problems", "warnings", "status"}`
    - `PUT /api/admin/editions/<id>/pairings` `{pairs: [{giver_id, recipient_id|null}]}`
    - `POST /api/admin/editions/<id>/mark-paired`
    - `POST /api/admin/editions/<id>/unpair` (sets `paired → open`, keeps rows)

Rules:

- Givers and recipients must be on the edition's roster (400 otherwise).
- `problems` are messages built from roster names:
  - "Alex isn't giving to anyone yet."
  - "Sam is getting two gifts (from Alex and Jordan)."
  - "Riley isn't getting a gift."
  - "Casey can't give to themselves."
  - a roster of fewer than 2 people
- `warnings`:
  - "Alex and Sam are in the same household."
  - "Alex had Sam last year too." ("last year" is the newest earlier edition of the same exchange)
- `visible` returns `None` unless the status is `paired` or `closed`, or `admin` is true.

- [ ] **Step 1: Write the failing tests**

```python
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
    r = admin.post(f"/api/admin/editions/{e}/mark-paired")
    msg = r.get_json()["error"]
    assert r.status_code == 400 and "Sam isn't giving" in msg and "Sam is getting two gifts" in msg and "Alex isn't getting" in msg

def test_mark_paired_then_family_sees_sorted_list(admin, family, x):
    e = paired_ready_edition(admin, x)
    full_cycle(admin, e, [x.alex, x.sam, x.jordan])
    assert admin.post(f"/api/admin/editions/{e}/mark-paired").status_code == 200
    names = [(p["giver"], p["recipient"]) for p in family.get(f"/api/x/{x.slug}").get_json()["pairings"]]
    assert names == [("Alex", "Sam"), ("Jordan", "Alex"), ("Sam", "Jordan")]

def test_household_and_repeat_are_warnings_not_problems(admin, con, x):
    set_household(admin, [x.alex, x.sam], "Alex & Sam")
    e25 = paired_edition(admin, x, 2025, [(x.alex, x.jordan), (x.jordan, x.sam), (x.sam, x.alex)])
    e26 = paired_ready_edition(admin, x, 2026)
    full_cycle(admin, e26, [x.alex, x.jordan, x.sam])                       # alex→jordan again, sam→alex same household
    got = admin.get(f"/api/admin/editions/{e26}/pairings").get_json()
    assert got["problems"] == [] and any("same household" in w for w in got["warnings"]) and any("last year" in w for w in got["warnings"])
    assert admin.post(f"/api/admin/editions/{e26}/mark-paired").status_code == 200

def test_cannot_edit_pairs_once_paired(admin, x):
    e = paired_edition(admin, x, 2026, [(x.alex, x.sam), (x.sam, x.jordan), (x.jordan, x.alex)])
    assert admin.put(f"/api/admin/editions/{e}/pairings", json={"pairs": []}).status_code == 409
    assert admin.post(f"/api/admin/editions/{e}/unpair").status_code == 200
```

- [ ] **Step 2: Run. Expect failures.**
- [ ] **Step 3: Implement.** `GET /api/x/<slug>` gains `pairings` here. A minimal version of its Task 6 shape is fine.
- [ ] **Step 4: Run. Expect passed.**
- [ ] **Step 5: Commit** `feat(pairings): draft entry, Mark paired with named problems, warnings`

### Task 6: Family API (home, participant pages, profile, items, versions)

**Files:**
- Create: `lists.py`
- Modify: `app.py`
- Test: `tests/test_lists.py`, `tests/test_home.py`

**Interfaces:**
- Consumes: `exchanges.current_edition`, `pairings.visible`, `common.clean_url`, `exchange_required`
- Produces:
  - `lists.page(con, edition_id, person_id) -> dict` → `{"person": {"id","name"}, "edition_id", "about", "amazon_url", "version", "updated_at", "updated_by", "profile": [{"field_id","label","hint","value","updated_at","updated_by"}], "items": [{"id","title","url","note","version","updated_at","updated_by"}]}`. Profile lists active fields in order, including blank ones (the client hides them in read mode).
  - Writers, each raising `ApiError(409, "Someone else just changed this list. Reload to see it.")` on a stale version:
    - `lists.save_details(con, edition_id, person_id, about, amazon_url, version, updated_by) -> int` (new version)
    - `lists.save_profile(con, person_id, exchange_id, values: dict[int, str | None], expected: dict[int, int | None], updated_by) -> None`
    - `lists.add_item(...) -> int`, `lists.update_item(con, item_id, data, version, updated_by) -> int`, `lists.delete_item(con, item_id, version) -> None`, `lists.reorder(con, edition_id, person_id, ids: list[int]) -> None`
  - Routes, all `exchange_required`:
    - `GET /api/x/<slug>?edition=<id>` → `{"exchange": {"slug","name","accent_color"}, "edition": {...,"days_until"}, "editions": [{"id","label","status"}], "people": [{"id","name","item_count","has_amazon"}], "pairings": [...]|null}`
    - `GET /api/x/<slug>/people/<pid>?edition=<id>`
    - `PUT /api/x/<slug>/people/<pid>/details`
    - `PUT /api/x/<slug>/people/<pid>/profile` `{values: {field_id: value}, expected: {field_id: updated_at|null}, updated_by}`
    - `POST /api/x/<slug>/people/<pid>/items`
    - `PATCH/DELETE /api/x/<slug>/items/<id>` (DELETE body `{version}`)
    - `PUT /api/x/<slug>/people/<pid>/items/order` `{edition_id, ids}`

Rules:

- **Scoping:**
  - A person or item that isn't in this exchange is 404.
  - Someone who isn't on the edition's roster is 404 for that edition.
  - An `edition` query param from another exchange is 404.
- **Closed editions:** writes to `details` and `items` are 423 `{"error":"This year is closed."}`. Profile values are person-level and stay editable.
- **Lengths:** `about` is up to 4000 characters. Item `title` is required, up to 200. `note` is up to 1000. Profile values are up to 500; an empty value deletes the row.
- **Profile staleness check:** `expected[field_id]` must equal the stored `updated_at`, or `None` when no value exists yet. Fields whose value didn't change are skipped and not checked.
- **`updated_by`:** text up to 60 characters, required on every write. The client sends the name from "Which one are you?"
- **`days_until`:** `event_date − today` in days, or `null`.

- [ ] **Step 1: Write the failing tests**

```python
def test_home_shape_and_counts(family, fx):                                     # fx: unlocked exchange, edition 2026 open
    add_item(family, fx, fx.sam, "Socks"); save_details(family, fx, fx.sam, amazon_url="https://amazon.example.com/l/1")
    h = family.get(f"/api/x/{fx.slug}").get_json()
    sam = next(p for p in h["people"] if p["id"] == fx.sam)
    assert (sam["item_count"], sam["has_amazon"]) == (1, True) and h["pairings"] is None

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
```

- [ ] **Step 2: Run. Expect failures.**
- [ ] **Step 3: Implement `lists.py` and the routes.** Version checks use `UPDATE ... WHERE id=? AND version=?` and test `rowcount`. The details row is created on first save with `version` 1 (the GET returns `version: 0` when absent).
- [ ] **Step 4: Run the whole suite. Expect all passed.**
- [ ] **Step 5: Commit** `feat(lists): home, participant pages, profile details, items with version checks`

### Task 7: Frontend

**Files:**
- Create: `static/index.html`, `static/style.css`, `static/manifest.json`, `static/icon.svg`, `static/js/{package.json,main,core,api,unlock,whoami,home,person,admin,admin-pairings}.js`
- Modify: `app.py` (`GET /` serves `index.html` with `APP_NAME`, and `GET /manifest.json` is generated from it)
- Test: `tests/test_frontend.py`, `tests/frontend.test.mjs`

**Interfaces:**
- Consumes: every route above
- Produces:
  - `core.js` exports: `esc(s)`, `money(cents)`, `daysLabel(n)`, `hostLabel(url)` (e.g. `"amazon.com"`, with a leading `www.` dropped), `isStale(updatedAtSec, nowSec)` (true when older than 182 days), `monthLabel(sec)` (e.g. `"Nov 2025"`)
  - `api.js` exports `get(path)` and `send(method, path, body)` (adds `X-Exchange: 1`). It throws `{status, error}`, and a 403 with `locked` routes to the unlock screen.
  - `whoami.js` exports `me(slug) -> {person_id: number|null, name: string}|null`, `setMe(slug, value)` (a plain cookie `gx_me_<slug>`, 400 days, `SameSite=Lax`) and `showPicker(slug, people) -> Promise<value>`

Screens (hash routes):

| Route | Module | Shows |
|---|---|---|
| `#/` | `unlock.js` | A password box, or the list of unlocked exchanges (redirects when there's exactly one) |
| `#/x/<slug>` | `home.js` | Header (name, year picker, date, location, budget, days), rules, the "You're getting X" banner, Who has whom (or "Names not drawn yet."), Everyone's lists |
| `#/x/<slug>/p/<pid>` | `person.js` | The basics (non-empty fields with "updated Nov 2025", dimmed with "may be out of date" when stale), Anything else, the Amazon list button, Ideas. Edit mode for all of it. |
| `#/admin` | `admin.js` | Login, exchanges (password, share link with copy button), editions, roster, households, fields |
| `#/admin/e/<id>/pairings` | `admin-pairings.js` | One dropdown per giver, problems and warnings, Save draft, Mark paired, Unpair |

Rules:

- **Layout:**
  - Phone-first single column, with a 16px minimum body font and tap targets at least 44px.
  - The exchange `accent_color` is a CSS variable.
  - Links are `target="_blank" rel="noopener noreferrer"`, with the text `Open link · <hostLabel>`.
- **Who am I:** the picker appears on the first visit to an exchange. "Just looking (parent, etc.)" asks for a name and stores `{person_id: null, name}`. "Not you?" in the header reopens it. Every write sends `updated_by: me.name`.
- **On 409** (review focus 3): the edit form stays open with the user's text intact. The server message shows above it, alongside a **Reload** button that refetches without discarding the form until the user confirms.
- **Delete** uses a confirm step (`window.confirm` is not allowed; use an inline "Delete? Yes / No"). Undo comes in Task 9.
- `document.title` is only ever set from `APP_NAME` in `main.js`.

- [ ] **Step 1: Write the failing tests**

```python
def test_index_title_and_manifest_use_app_name(client):
    assert "<title>Gift Exchange</title>" in client.get("/").get_data(as_text=True)
    assert client.get("/manifest.json").get_json()["name"] == "Gift Exchange"

def test_no_inline_script_or_handlers():
    html = open("static/index.html").read()
    assert "<script>" not in html and "onclick=" not in html

def test_every_innerhtml_interpolation_is_escaped():
    """For each static/js/*.js, every `${...}` inside a template literal assigned to innerHTML is
    esc(...), money(...), daysLabel(...), monthLabel(...) or a call to a local function whose name starts with `render`."""

def test_no_window_confirm_or_alert():
    for f in glob("static/js/*.js"):
        src = open(f).read(); assert "confirm(" not in src and "alert(" not in src
```

```js
test("esc", () => assert.equal(esc(`<a href="x">'&`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;"));
test("money", () => { assert.equal(money(5000), "$50"); assert.equal(money(2999), "$29.99"); assert.equal(money(null), ""); });
test("daysLabel", () => { assert.equal(daysLabel(41), "41 days"); assert.equal(daysLabel(1), "1 day"); assert.equal(daysLabel(0), "today"); assert.equal(daysLabel(-2), "2 days ago"); });
test("hostLabel", () => { assert.equal(hostLabel("https://www.amazon.com/hz/x"), "amazon.com"); assert.equal(hostLabel("bad"), ""); });
test("isStale", () => { const now = 1_800_000_000; assert.equal(isStale(now - 183 * 86400, now), true); assert.equal(isStale(now - 30 * 86400, now), false); });
```

- [ ] **Step 2: Run `python -m pytest -q tests/test_frontend.py` and `node --test tests/`. Expect failures.**
- [ ] **Step 3: Build `core.js`, `api.js`, `index.html` and `style.css`, then one screen per commit in the table's order.**
- [ ] **Step 4: Run `python -m pytest -q`, `node --test tests/` and `node --check` on every module. Expect clean.**
- [ ] **Step 5: Manual check** with `DATA_DIR=/tmp/gx ADMIN_PASSWORD_HASH=$(echo admin-pass | python3 manage.py hash-password) python3 app.py`:
  - Create exchanges Adults and Cousins with the same password, and add four people to each.
  - Unlock both with one password, pick "Just looking", and fill in a size and two items.
  - Open the same page in two browsers and confirm the second save shows the reload message and keeps its text.
  - Enter half the pairings, reload, finish them, and Mark paired.
- [ ] **Step 6: Commit** per screen: `feat(ui): <screen>`

### Task 8: Installer, backup and deployment notes

**Files:**
- Create: `installer/setup-head.sh`, `installer/build.sh`, `deploy/deploy.env.example`, `ops/exchange-backup`, `.env.example`
- Modify: `README.md`
- Test: `tests/test_installer_static.py`

**Interfaces:**
- Produces: `sh installer/build.sh` → `dist/setup-exchange.sh`, a single idempotent installer for Alpine + OpenRC

Rules:

- The installer:
  - `apk add`s `py3-flask py3-gunicorn` and replaces `/opt/exchange`.
  - Writes `/etc/init.d/exchange`, running gunicorn as an unprivileged `exchange` user on `127.0.0.1:${EXCHANGE_PORT}`.
  - Keeps `/var/lib/exchange` and `/etc/conf.d/exchange`, and adds missing settings without overwriting existing ones. Settings: `EXCHANGE_PORT`, `APP_NAME`, `ADMIN_PASSWORD_HASH`.
  - Installs `ops/exchange-backup` to `/etc/periodic/daily/`. It uses `sqlite3 ... ".backup"` into `/var/backups/exchange` with mode 0600 and keeps 14 days.
- `README.md`, using `exchange.example.com`, documents:
  - the Cloudflare Tunnel public hostname pointing to `http://127.0.0.1:8770`
  - that there is **no** Access application, because the password is the gate
  - running `cloudflared` in the same container
  - `manage.py hash-password`
  - first-run admin steps: create exchanges, set the shared password, add people, copy the share link
  - that backups contain password hashes

- [ ] **Step 1: Write the failing tests**

```python
def test_build_produces_a_valid_installer():
    subprocess.run(["sh", "installer/build.sh"], check=True)
    subprocess.run(["sh", "-n", "dist/setup-exchange.sh"], check=True)

def test_installer_binds_loopback():
    head = open("installer/setup-head.sh").read()
    assert "127.0.0.1:" in head and "0.0.0.0" not in head

def test_every_module_and_setting_is_shipped():
    """Each top-level *.py is in build.sh's copy list; each env name read in settings.py except DATA_DIR
    and SECRET_KEY appears in .env.example and the installer's settings list."""
```

- [ ] **Step 2: Run. Expect failures.**
- [ ] **Step 3: Implement**, following `gift-tracker/installer/` and `family-wishlist/deploy/`.
- [ ] **Step 4: Run `python -m pytest -q` and `shellcheck -s sh installer/*.sh ops/exchange-backup`. Expect clean.**
- [ ] **Step 5: Commit** `chore(installer): Alpine installer, daily backup and deployment notes`
- [ ] **Step 6 (the owner, on the host):**
  - Deploy and add the tunnel hostname.
  - Dry run with two fake exchanges from a phone on cellular data.
  - Then create Adults and Cousins and enter 2025's pairings as a past edition.

**Christmas-critical slice ends here (by Wed 2026-11-25).**

### Task 9: Polish (bring-over, undo, PWA, large text)

**Files:**
- Modify: `lists.py`, `app.py`, `static/js/person.js`, `static/style.css`, `static/manifest.json`
- Test: `tests/test_lists.py`, `tests/frontend.test.mjs`

**Interfaces:**
- Produces:
  - `lists.bring_over(con, edition_id, person_id, updated_by) -> int` (count copied)
  - `lists.restore_item(con, item_id) -> None`
  - Routes: `POST /api/x/<slug>/people/<pid>/bring-over` `{edition_id, updated_by}` and `POST /api/x/<slug>/items/<id>/restore`
  - Schema v2: `wish_item.deleted_at INTEGER` (soft delete). Items deleted more than 1 day ago are purged at start-up.

Rules:

- **Bring-over** copies title, url and note from the person's items in the newest earlier edition they were on the roster for. It skips titles already present, compared case-insensitively. It's 400 when there's nothing to bring.
- **Delete becomes soft.** The client shows "Deleted · Undo" for 8 seconds. Restore works only while `deleted_at` is set.
- **PWA:** a 192 and a 512 icon (PNG or SVG `purpose: any`), plus `display: standalone`.
- **Large text:** the layout holds at 200% browser zoom with no horizontal scroll.

- [ ] **Step 1: Write the failing tests**

```python
def test_bring_over_copies_last_years_items_once(family, admin, fx):
    add_item(family, fx, fx.sam, "Socks"); add_item(family, fx, fx.sam, "Mug")
    e27 = admin.post(f"/api/admin/exchanges/{fx.id}/editions", json={"year": 2027, "copy_roster": True}).get_json()["id"]
    add_item(family, fx, fx.sam, "socks", edition=e27)
    r = family.post(f"/api/x/{fx.slug}/people/{fx.sam}/bring-over", json={"edition_id": e27, "updated_by": "Sam"})
    assert r.get_json()["copied"] == 1
    assert family.post(f"/api/x/{fx.slug}/people/{fx.sam}/bring-over", json={"edition_id": e27, "updated_by": "Sam"}).status_code == 400

def test_delete_then_restore(family, fx):
    a = add_item(family, fx, fx.sam, "Socks")
    family.delete(f"/api/x/{fx.slug}/items/{a}", json={"version": 1})
    assert family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()["items"] == []
    family.post(f"/api/x/{fx.slug}/items/{a}/restore", json={})
    assert [i["title"] for i in family.get(f"/api/x/{fx.slug}/people/{fx.sam}").get_json()["items"]] == ["Socks"]
```

- [ ] **Step 2: Run. Expect failures.**
- [ ] **Step 3: Implement**, including the v2 migration.
- [ ] **Step 4: Run all suites. Expect clean.**
- [ ] **Step 5: Commit** per feature: `feat(lists): bring over last year's items`, `feat(lists): undo delete`, `feat(ui): installable app and large-text pass`

### Task 10: In-app draw

**Files:**
- Create: `draw.py`, `static/js/admin-draw.js`
- Modify: `app.py`, `db.py` (schema v3), `static/js/admin-pairings.js`
- Test: `tests/test_draw.py`

**Interfaces:**
- Consumes: `pairings.save_draft`, `pairings.mark_paired`
- Produces:
  - `draw.draw(people: list[int], forbidden: set[tuple[int, int]], *, single_loop: bool, rng) -> dict[int, int]`, raising `draw.Impossible(reason: str)`
  - `draw.forbidden_pairs(con, edition_id, lookback: int) -> set[tuple[int, int]]`
  - Schema v3: `draw_exclusion (edition_id, a_id, b_id)`, symmetric
  - Routes:
    - `POST /api/admin/editions/<id>/draw` `{lookback: 1..3, single_loop: bool}` → `{"preview": [{"giver","recipient"}], "token"}` (stored server-side, nothing written)
    - `POST /api/admin/editions/<id>/draw/publish` `{token}` → writes the pairings and marks paired
    - `GET/PUT /api/admin/editions/<id>/exclusions`

Rules:

- **Allowed:** the edition must be `open` with no pairing rows, else 409.
- **Forbidden pairs:**
  - same household, both directions
  - (giver, recipient) from the last `lookback` editions
  - manual exclusions, both directions
- **Algorithm:** randomized backtracking with `secrets.SystemRandom`, and a hard cap of 200,000 steps. `single_loop` requires one cycle through everyone.
- **Impossible:** the reason names the person with the fewest allowed recipients, e.g. "Riley has no one left they're allowed to draw." It's 400 with that message.
- The preview token is valid for 10 minutes and only for that edition.

- [ ] **Step 1: Write the failing tests**

```python
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
```

(`draw` reports an impossible person by id. The route maps the id to the person's name.)

- [ ] **Step 2: Run. Expect failures.**
- [ ] **Step 3: Implement `draw.py`, the v3 migration, the routes and the admin screen** (Draw button, look-back select, single-loop checkbox, exclusions editor, preview with Redraw and Publish).
- [ ] **Step 4: Run all suites. Expect clean.**
- [ ] **Step 5: Commit** `feat(draw): in-app draw with exclusions, preview and publish`

---

## Done when

- `python -m pytest -q`, `node --test tests/`, `node --check` on every module, `ruff check` and `shellcheck` are clean, and CI is green.
- On the container, LAN port 8770 refuses connections from other hosts. A phone on cellular data opens the share link, lands on the cousins exchange, and can switch to adults without typing a password. Pairings appear only after Mark paired.
