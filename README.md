# Gift Exchange

A small self-hosted app where an extended family sees each exchange's pairings, budget, date and rules, and keeps
per-person sizes, favorites and wishlists, behind one shared password. Flask and SQLite, no build step.

Work in progress: the design is in `docs/superpowers/specs/` and the build plan in `docs/superpowers/plans/`.

## Development

```
python -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
ruff check
shellcheck -s sh installer/setup-head.sh installer/build.sh ops/exchange-backup
python3 app.py        # http://127.0.0.1:8770/healthz
```

## Deployment

The app runs in an Alpine container under OpenRC, listens on `127.0.0.1:8770` only, and is reached through a Cloudflare
Tunnel. Gunicorn runs as the unprivileged `exchange` user.

Build and install:

```
cp deploy/deploy.env.example deploy/deploy.env   # git-ignored; vim deploy/deploy.env
sh installer/build.sh                            # writes dist/setup-exchange.sh
# copy dist/setup-exchange.sh to the container, then as root:
sh setup-exchange.sh
```

`deploy/deploy.env` holds household defaults (`APP_NAME`, `EXCHANGE_PORT`), used on the first install only; never commit
it. The installer is safe to re-run: it installs `py3-flask` and `py3-gunicorn` (and `sqlite`, for the backup's
`sqlite3` command) with `apk`, replaces `/opt/exchange`, and keeps `/var/lib/exchange` and `/etc/conf.d/exchange`. It
adds settings that are missing from the config and never overwrites existing ones. It never writes `SECRET_KEY`: the
app creates `/var/lib/exchange/secret.key` (mode 0600, owned by `exchange`) on its first start.

Settings live in `/etc/conf.d/exchange` (`EXCHANGE_PORT`, `APP_NAME`, `ADMIN_PASSWORD_HASH`). Edit with `vim`, then:

```
vim /etc/conf.d/exchange
rc-service exchange restart
rc-service exchange status
tail -n 40 /var/log/exchange.log
```

`sh setup-exchange.sh --uninstall` removes the app and service and keeps data, config and backups.

### Admin password

```
echo 'a-password' | python3 /opt/exchange/manage.py hash-password
```

Put the output in `/etc/conf.d/exchange` as `ADMIN_PASSWORD_HASH='scrypt$...'` (single quotes, because the hash contains
`$`), then `rc-service exchange restart`. The same command works in a development checkout.

### Tunnel

Run `cloudflared` in the same container, so the origin is `http://127.0.0.1:8770` and nothing has to listen on a LAN
address. In the Cloudflare Tunnel, add the public hostname `exchange.example.com` pointing at `http://127.0.0.1:8770`.

There is **no** Cloudflare Access application for it. The shared password is the gate: relatives open the link on a phone
and type it, and an Access login in front would lock them out. The app trusts no `Cf-*` or `X-Forwarded-*` header.

### First run

1. Open `https://exchange.example.com/#/admin` and sign in with the admin password.
2. Create each exchange and set its shared password (exchanges can share one password; one typed password unlocks every
   exchange it matches).
3. Add the people and each edition's roster.
4. Copy each exchange's share link and send it to the family; the link opens only that exchange.

### Backups

`ops/exchange-backup` is installed as `/etc/periodic/daily/exchange-backup`. It uses `sqlite3 ... ".backup"` to write
`/var/backups/exchange/exchange-<date>.db` with mode 0600 (directory 0700), checks integrity, keeps 14 days, and logs
to `/var/log/exchange-backup.log`. The installer takes a first backup.

The backups contain the exchanges' password hashes, share-link tokens and who draws whom. Keep them private and treat them like
the live database.

To restore, `rc-service exchange stop`, copy a backup over `/var/lib/exchange/exchange.db` (owner `exchange`, mode 0600),
remove any `exchange.db-wal` and `exchange.db-shm` beside it, then `rc-service exchange start`.
