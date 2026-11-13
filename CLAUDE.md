# Gift Exchange

A small self-hosted Flask + SQLite app. An extended family sees each exchange's pairings, budget, date and rules, and
keeps per-person sizes, favorites and wishlists, behind one shared password. Spec:
`docs/superpowers/specs/2026-11-13-gift-exchange-design.md`. Plan: `docs/superpowers/plans/2026-11-13-gift-exchange.md`
(each task is delivered as one PR; the plan's task block is the contract for names, signatures and messages).

## Commands

```
python -m pytest -q
node --test tests/                                  # once tests/*.test.mjs exist
for f in static/js/*.js; do node --check "$f"; done
ruff check
python3 app.py                                      # dev server on 127.0.0.1:8770
echo 'a-password' | python3 manage.py hash-password # scrypt hash for ADMIN_PASSWORD_HASH (no DATA_DIR touched)
```

Run the whole gate before every commit. `tests/test_hygiene.py` walks `git ls-files`, so new files must be added to git
before it sees them.

## Rules that must keep holding

- Runtime dependencies are only Alpine packages `py3-flask py3-gunicorn`. Everything else is from the standard library.
  No PyJWT, no cryptography.
- No frontend framework, bundler or npm step. Native ES modules in `static/js/`, with `static/js/package.json` =
  `{"type": "module"}`.
- No personal data in the repo:
  - generic names (Alex, Sam, Jordan, Riley, Casey) and `example.com` hosts
  - RFC 5737 addresses
  - household values only in git-ignored `deploy/deploy.env`
- No Cloudflare Access. The app trusts no `Cf-*` or `X-Forwarded-*` header for identity or throttling.
- Every mutation (any non-GET under `/api/`) needs header `X-Exchange: 1`, a JSON object body, and an `Origin` equal to
  the request host's origin. Otherwise 400, or 403 for a foreign Origin.
- Bodies are read with `json_body()` and strings with `text(data, key, max_len)`. Bad shapes return 400. Money is
  integer cents parsed without `float`.
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

## Layout

```
app.py            Flask object, before/after hooks (mutation guard, security headers, cookie sliding), error handlers, the
                  exchange_required/admin_required decorators, every route (so far: /healthz, /robots.txt, unlock, join
                  link, admin login/logout, /api/session, /api/exchanges; stubs GET /api/admin/exchanges (Task 4) and
                  GET /api/x/<slug> (Tasks 5, 6)), app.db(), init_db()
manage.py         host chores: `hash-password`
settings.py       environment config, read once at import (DATA_DIR, EXCHANGE_PORT, APP_NAME, ADMIN_PASSWORD_HASH, SECRET_KEY)
db.py             SCHEMA, SCHEMA_VERSION, connect(), transaction(), migrate()
common.py         ApiError, json_body, text, parse_cents, clean_url, now, today
access.py         password hashing, unlock (option C), share links, gx_access/gx_admin cookies, admin session, throttle
exchanges.py      exchanges, editions, people, roster, profile fields                     (Task 4)
pairings.py       draft save, validation, warnings, visibility                            (Task 5)
lists.py          participant details, profile values, wish items, versions               (Task 6)
static/           robots.txt (Task 2); index.html, style.css, manifest.json, icon.svg, static/js/ (Task 7)
tests/            conftest.py + one test file per module
installer/ deploy/ ops/                                                                   (Task 8)
```

Later modules are listed so the layout is known; add each to this file when it lands.

## Conventions

- Route-free logic lives in sibling modules that take a `sqlite3.Connection`; routes in `app.py` call `db()`.
- Schema v1 decisions: `exchange.password_hash` is the encoded `scrypt$<salt hex>$<hash hex>` (no salt column);
  `participant` and `wish_item` carry `version`; `pairing.recipient_id` is nullable (a draft row); `edition_people` is
  the per-year roster; timestamps are integer epoch seconds; `participant` rows are created lazily on first save.
- `SECRET_KEY` comes from the environment, else `DATA_DIR/secret.key` (32 random bytes, mode 0600, created on first start).
- Tests: `tests/conftest.py` sets the environment before importing `app`, gives every test a fresh database, and offers
  the fixtures `client`, `con`, `seed` (one exchange, one edition, people a, b, c) and `clock` (freezes `common.now`;
  `clock.advance(s)`), plus `mut(**extra)` for the headers every mutation needs (`X-Exchange: 1`, same-origin
  `Origin`), `mk_exchange(con, slug, password, active=1, sort_order=0) -> id` and `token_of(con, id)`. Add shared
  helpers there.
- Access (`access.py` docstring has the details): one typed password unlocks every active exchange whose hash matches
  (option C); a share link `/x/<slug>/join/<token>` opens only its own exchange, and a bad token sets nothing but still
  redirects. `gx_access` (salt `access`, `{"x": {id: password_version}}`, 400 days, `SameSite=Lax`) is re-issued on every
  response to a request carrying a valid one; `gx_admin` (salt `admin`, `{"a": 1}`, 12 h, `SameSite=Strict`) is
  re-issued by `admin_required`. Both `HttpOnly`, `Secure`, path `/`, timestamped by `common.now()`. Changing a
  password must bump `password_version` (revokes cookie entries) and regenerate `link_token`.
- Throttle: scopes `exchange` (password box and join links) and `admin`, never per IP. Throttled while ≥10 failures in
  the last 600 s and the newest is under 300 s old; throttled attempts get 429 and aren't recorded; success clears.
- Routes for an exchange use `@exchange_required` (view gets `slug`; the row is `g.exchange`); admin routes use
  `@admin_required`. Both sit under the `@app.get/post` line.
