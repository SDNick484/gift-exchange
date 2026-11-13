"""Configuration, read once from the environment at import. Nothing here has a household value as its default.

  DATA_DIR             where exchange.db and secret.key live (default ./data)
  EXCHANGE_PORT        port for `python3 app.py` and the installer's gunicorn bind (default 8770)
  APP_NAME             page title and home-screen name (default Gift Exchange)
  ADMIN_PASSWORD_HASH  the admin password, encoded `scrypt$<salt hex>$<hash hex>`; empty means no admin sign-in
  SECRET_KEY           signs cookies. Unset: 32 random bytes in DATA_DIR/secret.key, created 0600 on first start
"""
import os
import re
import secrets

BASE = os.path.dirname(os.path.abspath(__file__))


def _int(name, default, minimum):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if not re.fullmatch(r"\d+", raw) or int(raw) < minimum:
        raise ValueError(f"{name} must be a whole number of at least {minimum}")
    return int(raw)


def _secret_key(data_dir):
    raw = os.environ.get("SECRET_KEY", "")
    if raw:
        return raw.encode()
    path = os.path.join(data_dir, "secret.key")
    os.makedirs(data_dir, exist_ok=True)
    try:
        # O_EXCL: two workers starting together cannot both create it; the loser reads the winner's file.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(path, "rb") as f:
            return f.read()
    key = secrets.token_bytes(32)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


DATA_DIR = os.environ.get("DATA_DIR", "").strip() or os.path.join(BASE, "data")
DB_PATH = os.path.join(DATA_DIR, "exchange.db")
PORT = _int("EXCHANGE_PORT", 8770, 1)
APP_NAME = os.environ.get("APP_NAME", "").strip() or "Gift Exchange"
ADMIN_PASSWORD_HASH: str = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()
SECRET_KEY: bytes = _secret_key(DATA_DIR)
