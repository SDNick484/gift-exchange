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
app.py            Flask object, before/after hooks, every route (so far: /healthz, app.db(), init_db())
settings.py       environment config, read once at import (DATA_DIR, EXCHANGE_PORT, APP_NAME, ADMIN_PASSWORD_HASH, SECRET_KEY)
db.py             SCHEMA, SCHEMA_VERSION, connect(), transaction(), migrate()
common.py         ApiError, json_body, text, parse_cents, clean_url, now, today          (Task 2)
access.py         password hashing, unlock, share links, cookies, admin session, throttle (Task 3)
exchanges.py      exchanges, editions, people, roster, profile fields                     (Task 4)
pairings.py       draft save, validation, warnings, visibility                            (Task 5)
lists.py          participant details, profile values, wish items, versions               (Task 6)
static/           index.html, style.css, manifest.json, icon.svg, robots.txt; static/js/ (Task 7)
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
  the fixtures `client`, `con` and `seed` (one exchange, one edition, people a, b, c). Add shared helpers there.
