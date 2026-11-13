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
                  link, admin login/logout, /api/session, /api/exchanges, the /api/admin/ structure and pairing routes;
                  stub GET /api/x/<slug> with pairings (Task 6 fills in the rest)), app.db(), init_db()
manage.py         host chores: `hash-password`
settings.py       environment config, read once at import (DATA_DIR, EXCHANGE_PORT, APP_NAME, ADMIN_PASSWORD_HASH, SECRET_KEY)
db.py             SCHEMA, SCHEMA_VERSION, connect(), transaction(), migrate()
common.py         ApiError, json_body, text, parse_cents, clean_url, now, today
access.py         password hashing, unlock (option C), share links, gx_access/gx_admin cookies, admin session, throttle
exchanges.py      exchanges, editions, people, roster, profile fields, current_edition
pairings.py       draft save, problems, warnings, Mark paired, Unpair, visibility
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
- The `pairing` table keeps only `UNIQUE(edition_id, giver_id)`: a draft can hold a doubled recipient or a self-pair so
  `pairings.problems` can name it, and `pairings.mark_paired` is the one guard that an edition is paired as a complete
  permutation. Schema is still v1 (no migrations before the family deadline).
- `SECRET_KEY` comes from the environment, else `DATA_DIR/secret.key` (32 random bytes, mode 0600, created on first start).
- Tests: `tests/conftest.py` sets the environment before importing `app`, gives every test a fresh database, and offers
  the fixtures `client`, `con`, `seed` (one exchange, one edition, people a, b, c) and `clock` (freezes `common.now`;
  `clock.advance(s)`), plus `mut(**extra)` for the headers every mutation needs (`X-Exchange: 1`, same-origin
  `Origin`), `mk_exchange(con, slug, password, active=1, sort_order=0) -> id` and `token_of(con, id)`. Add shared
  helpers there. Also: `admin` (logged-in client with `mut()` headers), `x` (exchange `x.slug` 'family', password
  `pw12`, people `x.alex/sam/jordan`), `family` (a second client that has typed `pw12`), and the helpers `mk_edition`,
  `put_roster`, `roster_ids`, `paired_ready_edition(admin, x, year=2026)`, `save_pairs`, `full_cycle(admin, e, ids)`,
  `paired_edition(admin, x, year, pairs)` and `set_household(admin, ids, label)`.
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
- Admin structure (`exchanges.py`; every `/api/admin/` route is `@admin_required`): creates return 201 `{"id"}`,
  PATCH returns the row, PUT returns `{"ok": true}`. A new exchange is seeded with `DEFAULT_FIELDS`. Slugs match
  `[a-z0-9][a-z0-9-]{0,39}` and `admin`, `api`, `x`, `static` are reserved. An edition can't be set to `paired`
  through PATCH (Mark paired, Task 5, is the only way in). Text over its limit is 400, never cut. A roster change or
  a deactivation that would orphan a pairing is 409 `Remove their pairing first: <names>.`, where a pairing names a
  person as giver or recipient, draft rows included; deactivation only checks editions that aren't `closed`. The
  share link comes back from `POST /api/admin/exchanges/<id>/link` (regenerates), built from the request's Origin.
- Pairings (`pairings.py`; admin routes `GET/PUT /api/admin/editions/<id>/pairings`, `POST .../mark-paired`,
  `POST .../unpair`, all `@admin_required`; mutations still need a JSON body, `{}` for the two POSTs):
  - Save keeps the draft as typed, even a doubled recipient or a self-pair (the `pairing` table allows both); the PUT replaces every row,
    needs an `open` edition (409 otherwise) and roster members only (400). A giver listed twice is 400.
  - `problems()` are blocking and name people from the roster (givers first, then self-pairs, doubled recipients,
    people nobody gives to; a roster under 2 is the only problem then). Mark paired is 400 with all of them joined by
    `; `, and 409 unless the edition is `open`. Unpair is `paired` to `open` and keeps the rows.
  - `warnings()` never block: same household label (case-insensitive, one note per pair) and a repeat of the newest
    earlier edition of the exchange ("last year", by year, whatever its status).
  - `visible(admin=False)` is `None` unless the edition is `paired` or `closed`. `GET /api/x/<slug>` returns
    `pairings` for the current edition with `admin=False` always: the family page never shows a draft, even to the
    admin. The front end shows "Names not drawn yet." for `null`.
