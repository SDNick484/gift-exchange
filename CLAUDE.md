# Gift Exchange

A small self-hosted Flask + SQLite app. An extended family sees each exchange's pairings, budget, date and rules, and
keeps per-person sizes, favorites and wishlists, behind one shared password. Spec:
`docs/superpowers/specs/2026-11-13-gift-exchange-design.md`. Plan: `docs/superpowers/plans/2026-11-13-gift-exchange.md`
(each task is delivered as one PR; the plan's task block is the contract for names, signatures and messages).

## Commands

```
python -m pytest -q
node --test tests/*.test.mjs                        # tests/frontend.test.mjs: the DOM-free helpers in static/js/
for f in static/js/*.js; do node --check "$f"; done
ruff check
shellcheck -s sh installer/setup-head.sh installer/build.sh ops/exchange-backup
sh installer/build.sh                               # writes dist/setup-exchange.sh (git-ignored)
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
                  exchange_required/admin_required decorators, every route (so far: /, /manifest.json, /healthz, /robots.txt, unlock, join
                  link, admin login/logout, /api/session, /api/exchanges, the /api/admin/ structure, pairing and draw
                  routes, the family routes under /api/x/<slug>), app.db(), init_db()
manage.py         host chores: `hash-password`
settings.py       environment config, read once at import (DATA_DIR, EXCHANGE_PORT, APP_NAME, ADMIN_PASSWORD_HASH, SECRET_KEY)
db.py             SCHEMA, SCHEMA_VERSION, connect(), transaction(), migrate()
common.py         ApiError, json_body, text, parse_cents, clean_url, now, today
access.py         password hashing, unlock (option C), share links, gx_access/gx_admin cookies, admin session, throttle
exchanges.py      exchanges, editions, people, roster, profile fields, current_edition
pairings.py       draft save, problems, warnings, Mark paired, Unpair, visibility
draw.py           in-app draw: forbidden_pairs, draw (randomized backtracking), preview tokens, publish, exclusions
lists.py          participant pages, details, profile values, wish items, version checks, scoping helpers
static/           index.html (the shell; GET / fills in __APP_NAME__), style.css, manifest.json (GET /manifest.json sets
                  name and short_name), icon.svg, robots.txt
static/js/        hash-routed ES modules, no build step: main.js (router, header), core.js (esc and formatting, no DOM
                  at import), api.js (get/send; a 403 `locked` fires the unlock box), unlock.js (#/, the password box),
                  whoami.js (gx_me_<slug> cookie and the "Which one are you?" picker), home.js (#/x/<slug>),
                  person.js (#/x/<slug>/p/<pid>), admin.js (#/admin, #/admin/x/<id>),
                  admin-pairings.js (#/admin/e/<id>/pairings)
tests/            conftest.py + one test file per module; test_frontend.py (shell, CSP and escaping scans over static/),
                  frontend.test.mjs (node --test)
installer/        setup-head.sh (the installer's text, with a __DEPLOY_DEFAULTS__ marker), build.sh (head + base64 tarball of
                  every top-level *.py, static/ and ops/exchange-backup -> dist/setup-exchange.sh)
deploy/           deploy.env.example (deploy.env is git-ignored; only APP_NAME and EXCHANGE_PORT are baked in)
ops/              exchange-backup (nightly `sqlite3 .backup`, 0600 in /var/backups/exchange, keeps 14 days)
.env.example      development settings
```

Later modules are listed so the layout is known; add each to this file when it lands.

## Conventions

- Route-free logic lives in sibling modules that take a `sqlite3.Connection`; routes in `app.py` call `db()`.
- Schema v1 decisions: `exchange.password_hash` is the encoded `scrypt$<salt hex>$<hash hex>` (no salt column);
  `participant` and `wish_item` carry `version`; `pairing.recipient_id` is nullable (a draft row); `edition_people` is
  the per-year roster; timestamps are integer epoch seconds; `participant` rows are created lazily on first save.
- The `pairing` table keeps only `UNIQUE(edition_id, giver_id)`: a draft can hold a doubled recipient or a self-pair so
  `pairings.problems` can name it, and `pairings.mark_paired` is the one guard that an edition is paired as a complete
  permutation. Schema is v3 (see "Schema v2" and "Schema v3" below).
- Schema v2: `wish_item.deleted_at INTEGER` (nullable), added by `db._to_v2` with `ALTER TABLE ... ADD COLUMN` inside
  the migrate transaction. The v1 `SCHEMA` text is never edited (a deployed v1 database was made from it); a fresh
  database runs v1 then v2. `tests/test_db.py` upgrades a populated v1 database and checks the rows survive.
- Schema v3 (`db._to_v3`, new tables only): `draw_exclusion (edition_id, a_id, b_id)` with `CHECK (a_id < b_id)` and
  primary key on all three (one row per unordered pair, read both ways; every reference `ON DELETE CASCADE`), and
  `draw_preview (token PRIMARY KEY, edition_id ON DELETE CASCADE, lookback, pairs /* JSON [[giver, recipient], ...] */,
  created_at)`. `tests/test_db.py` upgrades a populated v2 database (every old row and table definition unchanged, a
  second migrate a no-op) and a v1 database straight to v3.
- `SECRET_KEY` comes from the environment, else `DATA_DIR/secret.key` (32 random bytes, mode 0600, created on first start).
- Tests: `tests/conftest.py` sets the environment before importing `app`, gives every test a fresh database, and offers
  the fixtures `client`, `con`, `seed` (one exchange, one edition, people a, b, c) and `clock` (freezes `common.now`
  at the real current second, so cookies set by earlier fixtures stay valid; `clock.advance(s)`), plus `mut(**extra)` for the headers every mutation needs (`X-Exchange: 1`, same-origin
  `Origin`), `mk_exchange(con, slug, password, active=1, sort_order=0) -> id` and `token_of(con, id)`. Add shared
  helpers there. Also: `admin` (logged-in client with `mut()` headers), `x` (exchange `x.slug` 'family', password
  `pw12`, people `x.alex/sam/jordan`), `family` (a second client that has typed `pw12`, with `mut()`'s headers on every
  request), `fx` (x plus the default fields and an open edition 2026, `fx.edition`, roster alex, sam, jordan; `fx.con`),
  `other` (a second exchange `other`, password `pw34`, `other.alex` on `other.edition`, one field `other.field`, also
  unlocked by `family`), and the helpers `mk_edition`, `put_roster`, `roster_ids`,
  `paired_ready_edition(admin, x, year=2026)`, `save_pairs`, `full_cycle(admin, e, ids)`,
  `paired_edition(admin, x, year, pairs)`, `set_household(admin, ids, label)`, `add_item(client, fx, pid, title,
  raw=False, edition=None, **extra) -> id`, `save_details(client, fx, pid, about=None, amazon_url=None, raw=False,
  edition=None) -> version`, `put_profile(client, fx, pid, values, expected, updated_by="Sam")` and `field_id(fx, label)`.
- Access (`access.py` docstring has the details): one typed password unlocks every active exchange whose hash matches
  (option C); a share link `/x/<slug>/join/<token>` opens only its own exchange, and a bad token sets nothing but still
  redirects. `gx_access` (salt `access`, `{"x": {id: password_version}}`, 400 days, `SameSite=Lax`) is re-issued on every
  response to a request carrying a valid one; `gx_admin` (salt `admin`, `{"a": 1}`, 12 h, `SameSite=Strict`) is
  re-issued by `admin_required`. Both `HttpOnly`, `Secure`, path `/`, timestamped by `common.now()`. Changing a
  password must bump `password_version` (revokes cookie entries) and regenerate `link_token`.
- Throttle: scopes `exchange` (password box and join links) and `admin`, never per IP. Throttled while ≥10 failures in
  the last 600 s and the newest is under 300 s old; throttled attempts get 429 and aren't recorded. A good password or link never clears `exchange` (one counter
  covers every exchange, so clearing would let one exchange's password reset guesses at another's); admin success
  clears `admin`, which has a single password.
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
- Draw (`draw.py`; admin routes `POST /api/admin/editions/<id>/draw` `{lookback: 1..3 = 1, single_loop: bool = false}`,
  `POST .../draw/publish` `{token}`, `GET/PUT .../exclusions` `{pairs: [[a, b], ...]}`, all `@admin_required`):
  - Forbidden (`forbidden_pairs(con, edition_id, lookback)`, directed, roster members only): same household label
    (trimmed, case-insensitive, non-empty), both ways; every pair of the newest `lookback` editions with an earlier
    year (same exchange, any status, draft rows with no recipient skipped); **the reverse of every pair of the newest
    earlier edition, whatever the look-back** (Alex had Sam last year, so Sam can't draw Alex; older reverses are
    allowed); manual exclusions, both ways. `pairings.warnings()` is untouched by the reverse rule.
  - `draw(people, forbidden, *, single_loop, rng)` never relaxes a rule. `Impossible` names a person by id
    ("<id> has no one left they're allowed to draw.", "No one is allowed to draw <id>.", else "No draw keeps every
    rule. Start with <id>, ..." for the person with the fewest allowed recipients, ties to the earliest in `people`);
    the route swaps in the name via `Impossible.named(roster)` and returns 400. A bipartite-matching check (and, for
    one loop, a reachability check) runs first; then MRV backtracking (loop: Warnsdorff order) capped at `MAX_STEPS`
    (200,000). Ties and choices come from `rng`: the route passes `secrets.SystemRandom()`.
  - Draw is 409 unless the edition is `open` with no `pairing` rows (a draft row with no recipient counts). A preview
    writes nothing to `pairing` or `edition`; it goes in `draw_preview` (in the database, not memory: gunicorn has two
    workers) with a `secrets.token_urlsafe(32)` token, good for `PREVIEW_SECONDS` (600) by `common.now()`, for its
    edition only, and once. A new draw deletes the edition's older previews and every expired one. Publish: 404 no
    edition; 400 a token unknown, used, replaced, expired or another edition's (that one stays good); then in the
    same transaction 409 if the edition isn't open, has rows, its roster isn't the preview's givers, or a pair is now
    forbidden (with the preview's look-back); then `pairings.save_draft_in_transaction` and
    `mark_paired_in_transaction` (the `*_in_transaction` twins assume the caller's transaction).
  - Exclusions: PUT replaces the set; both people on the roster (400 `<name> isn't on this edition's roster.`) and
    different (400 `A pair needs two different people.`); duplicates either way round collapse. GET returns
    `{"pairs": [{"a_id","a","b_id","b"}]}`, the name that sorts first as `a`, in name order. A roster change deletes
    exclusions naming anyone dropped (it never blocks; coming back doesn't restore them).
- Family lists (`lists.py`; routes under `/api/x/<slug>`, all `@exchange_required`):
  - Scoping: every person, item, edition or field id that isn't in this exchange is 404, and so is someone off the
    edition's roster for that edition (page, details, items, reorder). Routes call `lists.edition_of`, `person_of`,
    `on_roster` and `item_of` before any writer. `?edition=` defaults to the current edition. A malformed id (not
    ASCII digits, or past SQLite's 64-bit range) is 400.
  - Versions (review focus 3): a stale save is 409 `Someone else just changed this list. Reload to see it.` and saves
    nothing. Details and items use `UPDATE ... WHERE version = ?` and rowcount; the details row is created on first
    save with version 1 (the page shows 0). Profile values check `expected[field_id]` against the stored `updated_at`
    (None when blank), skip unchanged fields, and move `updated_at` on by at least 1 s per change. Reorder takes no
    version and bumps none, but a list that doesn't match the stored items is 409.
  - Closed editions: details and items are 423 `This year is closed.`; profile values are person-level and stay
    editable. Links go through `clean_url` (review focus 4). `updated_by` (60) is required on details, profile and
    item add/edit; delete (`{version}`) and reorder (`{edition_id, ids}`) take none.
  - Soft delete and undo: `DELETE /items/<id>` `{version}` sets `deleted_at` and bumps `version`. Every `wish_item` read
    and write ignores rows with `deleted_at` set (page, home item count, `item_of`, edit, reorder's list check,
    bring-over), so a deleted item is 404, and `item_of(..., deleted=True)` finds only deleted ones. `POST
    /items/<id>/restore` `{}` clears the mark: 404 unless it is set now, 423 in a closed year, no version. `init_db`
    runs `lists.purge_deleted` after `migrate`: rows deleted over 86400 s ago go for good.
  - Bring-over: `POST /people/<pid>/bring-over` `{edition_id, updated_by}` -> `{"copied": n}`. Source is the newest
    earlier edition (by year, same exchange) whose roster had the person; live items are copied to the end of the
    target list, skipping titles already live there (case-insensitive). 400 `Nothing to bring over.` when none; the
    target needs the person on its roster (404) and is 423 when closed.
- Frontend (`static/js/`, Task 7): native ES modules, hash routes, `static/js/package.json` is `{"type": "module"}`.
  - Escaping: markup is built in template literals whose every `${...}` is exactly one call to `esc`, `money`,
    `daysLabel`, `monthLabel` or a `render*` function, never in an unquoted attribute; `innerHTML` is only ever
    assigned a template literal, `""` or a `render*` call. `tests/test_frontend.py` scans every module for this, and
    it doesn't parse regex literals: keep quote characters and backticks out of them (`\x22`, `\x27`).
  - CSP holds by construction: no inline `<script>`/`<style>`, no `style="..."` or `on*=` in markup strings, no
    `.onclick =` (use `addEventListener`). The exchange's `accent_color` reaches CSS only through
    `core.applyAccent`, which checks `^#[0-9a-fA-F]{6}$` first (CSSOM `setProperty` is allowed by the CSP).
  - No `window.confirm` or `alert` (the test greps for `confirm(` and `alert(`): deletes use an inline "Delete? Yes / No".
  - `core.js` touches no `document`/`window` at import so `node --test` can load it.
  - `document.title` is set only in `main.js`, from `/api/session`'s `app_name`.
  - Links out are `target="_blank" rel="noopener noreferrer"` with the text `Open link · <hostLabel>` (`core.renderLink`).
  - Undo and bring-over (`person.js`): a delete shows "Deleted · Undo" in its own `[data-slot=undo]` for `UNDO_MS` (8 s),
    one line and timer per idea; "Bring over last year's items" sits under Add an idea and is hidden in a closed year.
  - Large text: `style.css` has no `nowrap` and no fixed wide boxes, children of grids/flex may shrink (`min-width: 0`)
    and long words and addresses wrap, so 200% zoom has no sideways scroll (`tests/test_frontend.py` guards the rules).
  - PWA: `manifest.json` is `display: standalone` with `static/icon.svg` listed at 192x192, 512x512 and `any`
    (`purpose: any`); no PNG files.
  - Nothing typed is lost (review focus 3, `person.js`): each part of a person's page is a unit with its own form, and
    a save or Reload redraws only units not being edited. On 409 the form stays as typed under the server's message
    and a Reload button; Reload refetches, shows what's saved, and moves untouched fields to the fresh values while
    keeping typed ones, until the person picks "Save mine instead" or "Use what's saved". A profile save sends only
    the fields that were typed in. Never re-render a whole screen after a save.
- Installer (`installer/`, Task 8): Alpine + OpenRC, service `exchange` (gunicorn on `127.0.0.1:${EXCHANGE_PORT}`, default 8770,
  as the `exchange` user), `/opt/exchange` replaced on each run, `/var/lib/exchange` and `/etc/conf.d/exchange` kept.
  `add_setting` only adds missing keys, single-quoted because `ADMIN_PASSWORD_HASH` holds `$`. A new setting read in
  `settings.py` needs `.env.example` and an `add_setting` line (`tests/test_installer_static.py` checks both). Never bake
  `ADMIN_PASSWORD_HASH` or set `SECRET_KEY`: the app makes `secret.key` itself. apk packages: `py3-flask py3-gunicorn`
  plus `sqlite` (the backup's `sqlite3` command only).
