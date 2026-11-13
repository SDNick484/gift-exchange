# Gift Exchange: design

Status: draft for approval, 2026-11-13
Repo: `SDNick484/gift-exchange`, public
Delivery: Prompt issues in the repo, run with the issue-queue skill

## Intent and why

The owner's extended family runs two gift exchanges each Christmas: one for the adults and one for the
cousins, about 15 people or fewer in each. Today names are drawn from a bowl, the pairings get
posted in a group text, and everything after that (budget, date, "what do you want?") happens
one-to-one by phone, text and email. Nothing is in one place, so people go back through the
thread or ask each other again.

This app is that one place. For each exchange and year, anyone in the family can see:

- who has whom
- the budget, the date and any rules
- each person's wishlist, including a link to their Amazon list

The family is old-fashioned, so the app has to work for someone who taps a link in a text,
types one password once, and never thinks about it again. It doesn't replace the bowl. The bowl
stays the default, and the app records its result. An in-app draw is an optional extra.

The code is generic and public on GitHub. The owner's family is one deployment of it.

## Goals

1. One deployment hosts several exchanges at once (adults, cousins, and others later), each at
   its own URL path.
2. Each exchange has a yearly edition with its own roster, budget, date, rules and pairings.
   Past editions stay readable as history, and the roster carries forward to the next year.
3. Pairings are shown openly to everyone in the exchange.
4. Each participant has a page with self-reported details, so givers aren't relying only on
   specific wishlist items:
   - structured fields: shirt, pants and shoe size, favorite colors, interests, and so on
   - a free-text "anything else" box
   - an optional Amazon list link
   - wishlist items (title, optional link, optional note)
5. Anyone with the exchange password can edit any participant's page. That covers parents
   editing their kids' lists and the owner fixing a grandparent's list.
6. Phone-first. It can be installed to the home screen and is readable at large text sizes.
7. Optional, later phase: an in-app draw with exclusion rules, as an alternative to typing in
   the bowl's result.

## Non-goals

- Per-person accounts, email sign-in, or Cloudflare Access in front of the app.
- Reservations or "purchased" tracking. Each recipient has exactly one giver, so there is no
  one to coordinate with.
- Secret pairings. The family posts them openly. (This could be a later per-exchange setting
  for other users of the public repo, but it isn't in this design.)
- Fetching, scraping or previewing Amazon or any other linked page. Links are stored and shown
  as given.
- Email, SMS or push notifications.
- Tracking money spent or gifts given.

## Anti-goals (a failure even if it works)

- Asking a relative for more than one password, or for an account, a code or an app-store
  install.
- Making the app required to take part. The bowl and the group text must keep working, with the
  app as a convenience.
- Any real family name, email, URL or password in the public repo.
- Something someone enters from a phone being lost without warning, whether that's a wishlist
  item or a pairing.

## Constraints

- Same pattern as the owner's other self-hosted apps (Dinner Log, Cookbooks, Roasted, Matinee,
  Family Wishlist, Gift Tracker):
  - Python 3.12 and Flask 3 with SQLite in WAL mode, served by gunicorn bound to 127.0.0.1.
  - Plain HTML/CSS and native ES modules, with no framework, bundler or npm step.
  - Alpine LXC on Proxmox with an OpenRC service and a single idempotent installer script.
  - Cloudflare Tunnel to a subdomain of the owner's domain, with `cloudflared` in the same
    container.
- Runtime dependencies must exist as Alpine `py3-*` packages. Prefer the standard library.
  `itsdangerous` comes with Flask.
- Household values live in a git-ignored `deploy/deploy.env`: admin password hash, secret key,
  subdomain. Exchange passwords are set in the app and stored hashed in the database.
- Tests and docs use generic names (Alex, Sam, Jordan, Riley, Casey), `example.com` and RFC 5737
  addresses.
- The repo gets a `CLAUDE.md` listing the rules that must keep holding, plus test commands and
  Conventional Commits. Author: `SDNick484 <SDNick484@users.noreply.github.com>`.
- Docs use OpenRC commands and say `vim`.

## Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| A | One deployment that hosts many exchanges, each with yearly editions | Slightly bigger data model. One container, backup and upgrade. More useful as a public project. | **Chosen by the owner** |
| B | One exchange per deployment | Simplest code, but two (or more) containers, subdomains and backups to run every year | Rejected |
| C | An "exchange mode" inside `family-wishlist` | That app is built around reservations and spoiler protection, which this app doesn't need. The extended family would also share access with the owner's own lists. | Rejected |

## What the owner decided

- Pairings come from the bowl and are typed in. The in-app draw is a later, optional phase:
  "cool, but may or may not be used."
- Access is one shared password per exchange. People pick themselves from the list and manage
  their own space.
- Pairings are visible to everyone in the exchange.
- No reservations or purchase tracking.
- Amazon support is a link only. There is no Amazon API.
- A generic public repo, with a family-specific deployment of it.
- Approach A.
- Password option C: per-exchange passwords that may be shared, with one entry unlocking every
  match. The family shares one across both exchanges.
- The bowl draw is at Thanksgiving, so the Christmas-critical slice ships before it.
- The build goes through Prompt issues and issue-queue.

## The design

### Data model

```
exchange      id, slug (unique, [a-z0-9-]), name, password_hash, password_salt,
              password_version, link_token, active, sort_order, accent_color
edition       id, exchange_id, label ("2026"), year, budget_cents (nullable),
              event_date (YYYY-MM-DD, nullable), location (text, nullable),
              rules (text), status ('open' | 'paired' | 'closed'), created_at
person        id, exchange_id, name, household (text label, nullable), active
participant   edition_id, person_id, about (text), amazon_url (nullable), version,
              updated_at, updated_by (free-text name), PRIMARY KEY (edition_id, person_id)
pairing       edition_id, giver_id, recipient_id (rows may be partial while status is 'open'),
              UNIQUE (edition_id, giver_id), UNIQUE (edition_id, recipient_id),
              CHECK (giver_id <> recipient_id)
wish_item     id, edition_id, person_id, title, url (nullable), note (nullable),
              sort_order, created_at, updated_at, updated_by
profile_field id, exchange_id, label, hint (nullable), sort_order, active
profile_value person_id, field_id, value (text, max 500), updated_at, updated_by,
              PRIMARY KEY (person_id, field_id)
login_failure scope ('exchange' | 'admin'), at
meta          key, value (schema_version)
```

- People belong to one exchange. Someone in both exchanges is two rows. This is simpler and
  matches reality, since the adults and the cousins are mostly different people.
- Wishlist items belong to a participant in one edition, so each year starts clean. A "bring
  over last year's items" action copies the person's previous-edition items into the new one.
- **Profile details (sizes, favorites, interests).**
  - Each exchange has a list of fields the admin can edit. New exchanges start with this
    default set:

    | Field | Hint |
    |---|---|
    | Shirt size | |
    | Pants size | waist/length, or kids' size |
    | Shoe size | |
    | Favorite colors | |
    | Interests and hobbies | |
    | Favorite stores | |
    | Already have / don't need | |
    | Please avoid | dislikes, allergies, scents |

  - Values belong to the **person**, not the yearly edition, so they carry forward
    automatically. Nobody re-enters their shoe size each year.
  - Each value shows "updated Nov 2025". A value older than 6 months is shown dimmed with
    "may be out of date", because kids' sizes go stale fast.
  - Blank fields are hidden on the read view and shown in edit mode.
  - The participant's free-text `about` stays as an "Anything else" box under the fields.
- Money is integer cents. Prices are typed like `$25` or `25.00` and parsed without going
  through a float, the same way as gift-tracker's `parse_cents`.
- Every schema change goes through an idempotent `migrate()` that bumps `SCHEMA_VERSION`, with
  no manual database step on the host.

### Access

- **Exchange password (owner's choice: option C).** Each exchange has its own password, but
  several exchanges may share one.
  - Typing a password at `/` or `/<slug>` unlocks **every active exchange whose password
    matches**. The owner's family sets the same password on Adults and Cousins, so a parent types
    it once and gets both. Another user of the public repo can keep groups apart by giving them
    different passwords.
  - Seeing the other exchange's pairings and lists is fine for this family, since the pairings
    are posted openly anyway.
  - `/` lists the exchanges this browser has unlocked. With exactly one, it redirects there.
  - An unauthenticated visitor sees only a password box, plus the exchange name when they're on
    a `/<slug>` URL.
  - A correct password sets a signed, `HttpOnly`, `Secure`, `SameSite=Lax` cookie mapping each
    unlocked exchange id to its `password_version`. It lasts 400 days, and every visit renews
    it, so a relative signs in once per device.
  - Passwords are hashed with `hashlib.scrypt` and a per-exchange salt. Changing an exchange's
    password bumps `password_version`, which invalidates every cookie entry for it.
- **Share link.** Each exchange has a `link_token`. `/<slug>/join/<token>` sets the same cookie
  and redirects to the exchange, so a link texted to the family works without typing anything.
  The admin can regenerate the token, which revokes old links but not cookies already set.
  Changing the password does both. A forwarded link gives the same access as a forwarded
  password, which is acceptable for this audience.
- **Admin password.** One per deployment, stored as a hash in config. It unlocks
  `/admin`: create exchanges, set passwords, manage editions, roster and households, enter or
  draw pairings, and close editions. The admin session uses its own signed cookie with a 12-hour
  sliding expiry.
- **Who am I.** After unlocking, the page asks "Which one are you?" and stores the answer in a
  plain cookie per exchange. It's only for convenience: it highlights "You're getting
  <name>", opens your own page first, and fills in `updated_by`. It isn't a security boundary.
  "Not you?" switches it. The list ends with **"Just looking (parent, etc.)"**, which asks for a
  name to show in `updated_by` and doesn't show any "You're getting" banner. Parents use this
  to edit their kids' lists in the cousins exchange.
- **Throttling.** After 10 failed exchange passwords within 10 minutes, exchange login answers
  429 for 5 minutes. Admin login has its own counter with the same rule. Exchange attempts
  share one counter for the whole deployment, because one attempt is checked against every
  exchange. The throttle isn't per IP: behind the tunnel every request arrives from loopback,
  and the app doesn't trust client-supplied IP headers.
- **Non-admin users can't edit structure.** People with the exchange password edit only
  participant pages and wish items. The roster, edition settings and pairings are admin-only.
  That keeps a stray tap from breaking the pairings, which is the part the whole family relies
  on.

### Pages (hash routes or server paths, builder's call)

**`/<slug>`: exchange home (current edition)**

```
Cousins Exchange · 2026                    [2025 ▾]
Dec 24 · Riley's house · $50 limit · 41 days
Rules: one gift, wrap it, no gift cards
───────────────────────────────────────────
You're getting  RILEY  →  see Riley's list
───────────────────────────────────────────
Who has whom
  Alex   → Riley
  Jordan → Casey
  ...
Everyone's lists
  Alex   · 4 items · Amazon list
  Casey  · 0 items
```

- Before pairings are entered, the "Who has whom" block says "Names not drawn yet."
- The edition picker shows past years read-only.

**`/<slug>/p/<person_id>`: a participant's page**

- Name, then **The basics**: the profile fields that have values, each with its "updated"
  date. Then "Anything else" (`about`) and an **Amazon list** button when `amazon_url` is set.
- Wish items come below that, under **Ideas**.
- Items, each showing the title, an "Open link" button showing the link's hostname, and the
  note.
- An edit mode for about me, the Amazon URL and the items (add, edit, delete, reorder). Delete
  asks for confirmation, then shows an undo for a few seconds.
- "Last updated by Sam, Nov 20" is shown at the bottom.

**`/admin`**

- Exchanges: create, rename, slug, password, share link (copy button), active.
- Editions: start next year, which copies the active roster and leaves pairings and items
  empty. Also budget, date, location, rules and status.
- Roster: add, rename or deactivate people. Household label.
- Profile fields: add, rename, reorder or hide the exchange's fields. Hiding a field keeps its
  values.
- Pairings: one dropdown per giver.
  - **Save** keeps a partial draft, so nothing typed in is lost.
  - **Mark paired** checks that the pairings form a complete permutation of the roster:
    everyone gives once and receives once, and nobody gets themselves. Only then does it set
    the status to `paired` and show the pairings to the family.
  - A household clash or a repeat of last year's pairing is a warning, not an error. The bowl's
    result wins.
- The admin can create a past edition (for example 2025) and enter its pairings, so the
  repeat-pairing warning and the draw's look-back have data from day one.
- Draw (later phase, below).

### Links

- `amazon_url` and item `url` must start with `https://` or `http://`, with a 2,000-character
  maximum.
- Links are shown with `rel="noopener noreferrer"` and `target="_blank"`, labelled with the
  hostname (`amazon.com`, `target.com`).
- Nothing is fetched server-side.

### In-app draw (later phase)

- Admin-only, on an `open` edition with no pairings.
- Exclusions:
  - same household
  - last year's pairing (configurable look-back of 1 to 3 editions)
  - manual "never pair A with B" pairs, set per edition
- The algorithm is randomized backtracking over the roster. With 15 or fewer people that's
  trivial. It uses `secrets.SystemRandom`. If no valid assignment exists, the app says which
  constraint makes it impossible rather than silently relaxing it.
- Option: one big loop (A→B→C→…→A) or any valid assignment. The default is any valid
  assignment.
- The result is shown to the admin as a preview, with **Redraw** and **Publish**. Publish
  writes the pairings and sets the status to `paired`.

### Security and privacy

- Every mutation needs a custom header (`X-Exchange: 1`), a JSON body and a same-origin
  `Origin`. Bad shapes return 400.
- CSP: no inline scripts, and images only from this origin. Everything user-typed goes through
  `esc()` before `innerHTML`.
- `X-Robots-Tag: noindex, nofollow`, a `robots.txt` that disallows everything, and
  `Referrer-Policy: no-referrer`.
- Page titles and the manifest use the exchange or app name, never a person's name.
- `/healthz` is open and returns `{"ok": true}` only.
- An `ops/exchange-backup` script runs a SQLite `.backup` with mode 0600 and keeps 14 days.

### Rules settled while writing (builder may rely on these)

- **Current edition:** the newest by `year` that isn't `closed`. If all are closed, the newest
  one.
- **Closed:** the edition becomes read-only for everyone except the admin, who can reopen it.
- **Concurrent edits:** participant, profile and item saves carry the `version` they loaded
  (for profile values, their `updated_at`). A stale
  save gets 409 and the message "Someone else just changed this list. Reload to see it," and
  the typed text stays in the form. Two phones can't silently overwrite each other.
- **Showing pairings:** only an edition in `paired` or `closed` status shows its pairings to
  non-admins.

### Timeline and phases

The family draws names from the bowl on **Thanksgiving, Thursday Nov 26, 2026**. Links go out
with the pairings that weekend, so the Christmas-critical slice must be deployed by
**Wed Nov 25**. The phases are ordered for that.

**Before Thanksgiving (Christmas-critical):**

1. Scaffold: settings, schema, migrations, `/healthz`, CI, `CLAUDE.md`, hygiene test.
2. Access: admin password, exchange passwords with option C unlock, share link, cookies,
   throttling, CSRF and security headers.
3. Admin: exchanges, editions (including past ones), roster, households, and pairing entry
   with draft save and Mark paired.
4. Family pages:
   - the exchange home
   - "Which one are you?" with Just looking
   - participant pages: profile fields with the default set and staleness dimming, anything
     else, Amazon link, and items (add, edit, delete, reorder)
   - version checks on every save
   - admin editing of the profile fields
5. The Alpine installer, backups, and a README with Cloudflare Tunnel setup. Then deploy and do
   a dry run with two fake exchanges.

**After Thanksgiving:**

6. Polish: "bring over last year's items", undo after delete, PWA manifest and icon, and a
   large-text and accessibility pass.
7. In-app draw.
8. Later and not committed: a read-only JSON feed per edition, so the gift tracker's Exchanges
   plan (Plan 6) can show the owners' pairing and budget without re-entry. Also an
   optional "secret pairings" setting for other users of the public repo.

## Left to the builder

- Server-rendered pages vs a small SPA with hash routes. Either way: no build step, no inline
  scripts.
- Module layout, test structure, and exact route names under the shapes above.
- Visual style. It should be plain, high-contrast and large-tap-target, with one accent color
  per exchange stored as data.
- Port. Pick one not used by the owner's other apps (gift-tracker uses 8767), and make it
  configurable.
