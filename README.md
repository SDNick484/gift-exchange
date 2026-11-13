# Gift Exchange

A small self-hosted app where an extended family sees each exchange's pairings, budget, date and rules, and keeps
per-person sizes, favorites and wishlists, behind one shared password. Flask and SQLite, no build step.

Work in progress: the design is in `docs/superpowers/specs/` and the build plan in `docs/superpowers/plans/`.
Installer and deployment notes arrive with the installer task.

## Development

```
python -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
ruff check
python3 app.py        # http://127.0.0.1:8770/healthz
```
