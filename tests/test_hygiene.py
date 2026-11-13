"""No personal data in tracked files. Walks `git ls-files` and fails on any email address whose domain is not
example.com (GitHub noreply addresses are exempt, for commit authors in docs), on any URL host outside the allowed
list, and on any string listed in tests/hygiene_denylist.txt. That file is git-ignored and optional: keep the
household's real names, emails and hostnames in it locally, one per line, so they never enter the repo."""
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DENYLIST = os.path.join(ROOT, "tests", "hygiene_denylist.txt")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
URL = re.compile(r"https?://(?:[^\s/@:]*@)?([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)", re.I)
# amazon.com: public wishlist URLs in the docs and tests. 127.0.0.1 and the RFC 5737 documentation ranges are not hosts of anyone.
ALLOWED = ("example.com", "noreply.github.com", "github.com", "cloudflare.com", "amazon.com", "127.0.0.1")
DOC_IPS = ("192.0.2.", "198.51.100.", "203.0.113.")
# Only used when git is unavailable (a source tarball): mirrors .gitignore closely enough for a test.
SKIP_DIRS = {".git", ".venv", "venv", "data", "dist", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
SKIP_FILES = {DENYLIST, os.path.join(ROOT, "deploy", "deploy.env"), os.path.join(ROOT, ".env")}


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
        return [os.path.join(ROOT, p) for p in out.decode().split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            files += [p for p in (os.path.join(dirpath, f) for f in filenames) if p not in SKIP_FILES]
        return files


def allowed_domain(domain):
    domain = domain.lower()
    return domain.startswith(DOC_IPS) or any(domain == d or domain.endswith("." + d) for d in ALLOWED)


def denied_strings():
    if not os.path.exists(DENYLIST):
        return []
    with open(DENYLIST, encoding="utf-8") as f:
        return [s.strip().lower() for s in f if s.strip() and not s.lstrip().startswith("#")]


def find_problems(rel, body, denied=()):
    problems = [f"{rel}: email {m.group(0)}" for m in EMAIL.finditer(body) if not allowed_domain(m.group(1))]
    problems += [f"{rel}: url host {m.group(1)}" for m in URL.finditer(body) if not allowed_domain(m.group(1))]
    low = body.lower()
    return problems + [f"{rel}: a denylisted string" for s in denied if s in low]


def test_no_personal_data_in_tracked_files():
    files = tracked_files()
    assert files, "found no files to check"
    denied = denied_strings()
    problems = []
    for path in files:
        if not os.path.isfile(path):
            continue  # deleted in the working tree but still in the index
        with open(path, "rb") as f:
            body = f.read().decode("utf-8", errors="ignore")
        problems += find_problems(os.path.relpath(path, ROOT), body, denied)
    assert not problems, "\n".join(problems)


def test_the_check_catches_what_it_should():
    bad = "family" + ".org"  # built from parts so this file does not trip the check it tests
    assert find_problems("x", "mail jo@" + bad) and find_problems("x", "see https://nas." + bad + "/x")
    assert find_problems("x", "Alex lives here", denied=["alex"])
    assert find_problems("x", "http:" + "//10.0" + ".0.5:8080/") and not find_problems("x", "http://192.0.2.10:8090 http://127.0.0.1:8770")
    assert not find_problems("x", "a@example.com https://docs.example.com/ https://github.com/o/r a@users.noreply.github.com")
