"""Request-body helpers, the error type routes and modules raise, and the clock. No routes here."""
import re
import time
from datetime import date
from urllib.parse import urlsplit

from flask import request


class ApiError(Exception):
    """Raised anywhere while handling a request; app.py renders it as {"error": message} with this status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def json_body() -> dict:
    """The request's JSON object. Anything else (no body, bad JSON, a list, a string) is 400."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "Expected a JSON object.")
    return data


def text(data: dict, key: str, max_len: int, required: bool = False) -> str | None:
    """data[key] stripped. Missing, null or empty gives None, or 400 when required. Not a string, or longer than
    max_len, is 400."""
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise ApiError(400, f"{key} must be text.")
    value = (value or "").strip()
    if not value:
        if required:
            raise ApiError(400, f"{key} is required.")
        return None
    if len(value) > max_len:
        raise ApiError(400, f"{key} must be at most {max_len} characters.")
    return value


def now() -> int:
    """Seconds since the epoch. Every module asks here, so tests can monkeypatch time."""
    return int(time.time())


def today() -> str:
    """Today as YYYY-MM-DD. Every module asks here, so tests can monkeypatch the date."""
    return date.today().isoformat()


MAX_CENTS = 100_000_000
_MONEY = re.compile(r"\$?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.([0-9]{1,2}))?")
_PRICE_MSG = "Enter an amount such as 25 or 25.50."


def parse_cents(value) -> int | None:
    """Money as integer cents, never through a float. Takes a whole number of cents (int) or text such as "25",
    "25.5", "$25.00", "1,299". Empty text and None give None. Negative, non-numeric, more than 2 decimals, a float
    or bool, or more than MAX_CENTS is 400."""
    if value is None:
        return None
    if isinstance(value, (bool, float)):
        raise ApiError(400, _PRICE_MSG)
    if isinstance(value, int):
        cents = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        m = _MONEY.fullmatch(raw)
        if not m:
            raise ApiError(400, _PRICE_MSG)
        cents = int(m.group(1).replace(",", "")) * 100 + int((m.group(2) or "").ljust(2, "0"))
    else:
        raise ApiError(400, _PRICE_MSG)
    if not 0 <= cents <= MAX_CENTS:
        raise ApiError(400, "That amount is out of range.")
    return cents


MAX_URL = 2000
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_HOST_PORT = re.compile(r"[^/:]+:[0-9]+(?:/|$)")
_URL_MSG = "Enter a web address such as example.com/list."


def clean_url(value) -> str | None:
    """A web link a relative can paste as-is. Trims; empty gives None. http:// and https:// pass. With no scheme and
    no whitespace, when the part before the first "/" has a ".", https:// is prepended. Anything else (javascript:,
    ftp://, free text, longer than MAX_URL) is 400."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(400, _URL_MSG)
    url = value.strip()
    if not url:
        return None
    if len(url) > MAX_URL or re.search(r"\s", url):
        raise ApiError(400, _URL_MSG)
    if not re.match(r"https?://", url, re.I):
        if (_SCHEME.match(url) and not _HOST_PORT.match(url)) or "." not in url.split("/", 1)[0]:
            raise ApiError(400, _URL_MSG)
        url = "https://" + url
    try:
        host = urlsplit(url).hostname
    except ValueError:
        host = None
    if not host:
        raise ApiError(400, _URL_MSG)
    return url
