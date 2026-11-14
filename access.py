"""Who may see what: exchange passwords (option C), share links, the access and admin cookies, and the throttle.

There are no accounts. This module is the whole access control; app.py holds the routes and decides when to set or
clear a cookie.

- Passwords: hashlib.scrypt (n=2**14, r=8, p=1) with a 16-byte random salt, stored as `scrypt$<salt hex>$<hash hex>`
  and compared in constant time.
- Option C: one typed password unlocks every active exchange whose hash matches it, so exchanges that share a
  password open together and exchanges with another password stay shut.
- Cookie `gx_access`: URLSafeTimedSerializer(SECRET_KEY, salt="access") over {"x": {str(exchange id): password_version}}.
  An entry counts only while its exchange is active and its password_version is unchanged, so changing a password
  revokes every cookie entry for that exchange. 400 days, re-issued on every response, so it slides with use.
- Cookie `gx_admin`: salt "admin", payload {"a": 1}, valid 12 hours and re-issued on each admin request.
- Throttle: per scope ("exchange" or "admin"), never per client IP (behind the tunnel every request comes from
  loopback and no client-supplied IP header is trusted). A scope is throttled while it has at least MAX_FAILURES
  failures in the last WINDOW seconds and the newest is under LOCKOUT seconds old. Success clears only "admin"
  (one password); "exchange" failures just age out, or one exchange's password could reset guesses at another's.

Both signers take their timestamp from common.now(), so tests move the clock. `settings` is imported inside the
functions that need it: importing settings creates DATA_DIR/secret.key, and `manage.py hash-password` must not."""
import hashlib
import hmac
import os
import re

from itsdangerous import BadSignature, TimestampSigner, URLSafeTimedSerializer

import common

ACCESS_COOKIE = "gx_access"
ADMIN_COOKIE = "gx_admin"
ACCESS_SALT = "access"      # itsdangerous salts: an access cookie never verifies as an admin cookie, or back
ADMIN_SALT = "admin"
ACCESS_MAX_AGE = 400 * 86400
ADMIN_MAX_AGE = 12 * 3600

SCRYPT = {"n": 2**14, "r": 8, "p": 1}
SALT_BYTES = 16
HASH_BYTES = 64              # hashlib.scrypt's default dklen

SCOPES = ("exchange", "admin")
MAX_FAILURES = 10
WINDOW = 600
LOCKOUT = 300

_ENTRY_ID = re.compile(r"[1-9][0-9]{0,18}")


# ---------------------------------------------------------------- passwords
def _scrypt(pw: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pw.encode(), salt=salt, dklen=HASH_BYTES, **SCRYPT)


def hash_password(pw: str) -> str:
    salt = os.urandom(SALT_BYTES)
    return f"scrypt${salt.hex()}${_scrypt(pw, salt).hex()}"


def verify_password(stored: str, pw: str) -> bool:
    """Whether pw is the password `stored` encodes. A missing or malformed hash is False, never an error."""
    if not isinstance(stored, str) or not isinstance(pw, str):
        return False
    parts = stored.split("$")
    if len(parts) != 3 or parts[0] != "scrypt":
        return False
    try:
        salt, digest = bytes.fromhex(parts[1]), bytes.fromhex(parts[2])
    except ValueError:
        return False
    if not salt or not digest:
        return False
    return hmac.compare_digest(hashlib.scrypt(pw.encode(), salt=salt, dklen=len(digest), **SCRYPT), digest)


# ---------------------------------------------------------------- signing
class _Signer(TimestampSigner):
    def get_timestamp(self) -> int:
        return common.now()


def _serializer(salt: str) -> URLSafeTimedSerializer:
    import settings
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt=salt, signer=_Signer)


def _load(request, cookie: str, salt: str, max_age: int):
    token = request.cookies.get(cookie)
    if not token:
        return None
    try:
        return _serializer(salt).loads(token, max_age=max_age)
    except BadSignature:  # includes SignatureExpired, and a timestamp from the future
        return None


# ---------------------------------------------------------------- the access cookie
def access_entries(request) -> dict[str, int] | None:
    """The {exchange id: password_version} entries of a valid gx_access cookie, or None when the request has no
    valid one. Entries are returned whether or not they still unlock anything; unlocked_ids() decides that."""
    data = _load(request, ACCESS_COOKIE, ACCESS_SALT, ACCESS_MAX_AGE)
    if not isinstance(data, dict) or not isinstance(data.get("x"), dict):
        return None
    return {k: v for k, v in data["x"].items()
            if isinstance(k, str) and _ENTRY_ID.fullmatch(k) and type(v) is int}


def unlocked_ids(con, request) -> set[int]:
    """Ids of the active exchanges this request's cookie unlocks: entries whose password_version still matches."""
    entries = access_entries(request)
    if not entries:
        return set()
    ids = [int(k) for k in entries]
    marks = ",".join("?" * len(ids))
    rows = con.execute(f"SELECT id, password_version FROM exchange WHERE active = 1 AND id IN ({marks})", ids)
    return {r["id"] for r in rows if entries[str(r["id"])] == r["password_version"]}


def unlock(con, pw) -> list[int]:
    """Option C: ids of every active exchange whose password is pw, in sort order. Checks every exchange, so the
    time taken does not depend on which one matches."""
    rows = con.execute("SELECT id, password_hash FROM exchange WHERE active = 1 ORDER BY sort_order, id").fetchall()
    return [r["id"] for r in rows if verify_password(r["password_hash"], pw)]


def join(con, slug: str, token: str) -> int | None:
    """The id of the active exchange `slug` when token is its link_token, else None."""
    row = con.execute("SELECT id, link_token FROM exchange WHERE slug = ? AND active = 1", (slug,)).fetchone()
    if row is None or not isinstance(token, str):
        return None
    return row["id"] if hmac.compare_digest(row["link_token"].encode(), token.encode()) else None


def grant(con, entries: dict[str, int] | None, ids) -> dict[str, int]:
    """The cookie entries after unlocking `ids`: the existing entries with each id set to its current version."""
    merged = dict(entries or {})
    for i in ids:
        row = con.execute("SELECT password_version FROM exchange WHERE id = ?", (i,)).fetchone()
        if row is not None:
            merged[str(i)] = row["password_version"]
    return merged


def set_access_cookie(resp, entries: dict[str, int]) -> None:
    resp.set_cookie(ACCESS_COOKIE, _serializer(ACCESS_SALT).dumps({"x": entries}), max_age=ACCESS_MAX_AGE, path="/",
                    secure=True, httponly=True, samesite="Lax")


# ---------------------------------------------------------------- the admin cookie
def admin_password_ok(pw) -> bool:
    import settings
    return bool(settings.ADMIN_PASSWORD_HASH) and verify_password(settings.ADMIN_PASSWORD_HASH, pw)


def is_admin(request) -> bool:
    return _load(request, ADMIN_COOKIE, ADMIN_SALT, ADMIN_MAX_AGE) == {"a": 1}


def set_admin_cookie(resp) -> None:
    resp.set_cookie(ADMIN_COOKIE, _serializer(ADMIN_SALT).dumps({"a": 1}), max_age=ADMIN_MAX_AGE, path="/",
                    secure=True, httponly=True, samesite="Strict")


def clear_admin_cookie(resp) -> None:
    resp.delete_cookie(ADMIN_COOKIE, path="/", secure=True, httponly=True, samesite="Strict")


# ---------------------------------------------------------------- the throttle
def _scope(scope: str) -> str:
    if scope not in SCOPES:
        raise ValueError(f"unknown throttle scope {scope!r}")
    return scope


def throttled(con, scope: str) -> bool:
    """At least MAX_FAILURES failures newer than WINDOW seconds, the newest under LOCKOUT seconds old."""
    now = common.now()
    count, newest = con.execute("SELECT COUNT(*), MAX(at) FROM login_failure WHERE scope = ? AND at > ?",
                                (_scope(scope), now - WINDOW)).fetchone()
    return count >= MAX_FAILURES and newest > now - LOCKOUT


def record_failure(con, scope: str) -> None:
    """Count one failed attempt, and drop this scope's failures too old to matter."""
    now = common.now()
    con.execute("DELETE FROM login_failure WHERE scope = ? AND at <= ?", (_scope(scope), now - WINDOW))
    con.execute("INSERT INTO login_failure (scope, at) VALUES (?, ?)", (scope, now))


def clear_failures(con, scope: str) -> None:
    con.execute("DELETE FROM login_failure WHERE scope = ?", (_scope(scope),))
