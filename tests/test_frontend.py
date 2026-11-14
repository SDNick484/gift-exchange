"""The shell around the frontend (GET / and GET /manifest.json) and static checks over static/ that keep the
Content-Security-Policy (no inline script, no inline style, no inline handlers) and the escaping rule true as screens
are added. The JavaScript's own unit tests are tests/frontend.test.mjs (`node --test tests/*.test.mjs`)."""
import glob
import json
import os
import re

import pytest

import settings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
JS_FILES = sorted(glob.glob(os.path.join(STATIC, "js", "*.js")))

# The only things a template-literal interpolation that builds markup may be: one call to one of these.
SAFE_CALL = re.compile(r"(esc|money|daysLabel|monthLabel|render[A-Za-z0-9_]*)\(")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- what the server renders
def test_index_title_and_manifest_use_app_name(client):
    assert "<title>Gift Exchange</title>" in client.get("/").get_data(as_text=True)
    assert client.get("/manifest.json").get_json()["name"] == "Gift Exchange"


def test_app_name_reaches_title_and_manifest_escaped(client, monkeypatch):
    monkeypatch.setattr(settings, "APP_NAME", 'Tab <b>"&</b>')
    html = client.get("/").get_data(as_text=True)
    assert "<title>Tab &lt;b&gt;&quot;&amp;&lt;/b&gt;</title>" in html
    assert "<b>" not in html and "__APP_NAME__" not in html
    m = client.get("/manifest.json").get_json()
    assert (m["name"], m["short_name"]) == ('Tab <b>"&</b>', 'Tab <b>"&</b>')


def test_manifest_is_a_manifest(client):
    r = client.get("/manifest.json")
    assert r.mimetype == "application/manifest+json"
    m = r.get_json()
    assert m["start_url"] == "/" and m["display"] == "standalone" and m["icons"]
    sizes = {i["sizes"] for i in m["icons"] if i["purpose"] == "any"}
    assert {"192x192", "512x512"} <= sizes and all(i["src"] == "/static/icon.svg" for i in m["icons"])
    assert '<link rel="manifest" href="/manifest.json">' in client.get("/").get_data(as_text=True)


def test_shell_and_modules_are_served_with_the_csp(client):
    paths = ["/", "/manifest.json", "/static/style.css", "/static/icon.svg"]
    paths += [f"/static/js/{os.path.basename(p)}" for p in JS_FILES]
    for path in paths:
        r = client.get(path)
        assert r.status_code == 200, path
        csp = r.headers["Content-Security-Policy"]
        assert "script-src 'self'" in csp and "style-src 'self'" in csp and "unsafe" not in csp, path
        assert r.headers["X-Robots-Tag"] == "noindex, nofollow", path
        if path.endswith(".js"):
            assert r.mimetype in ("text/javascript", "application/javascript"), path


def test_modules_are_es_modules():
    assert json.loads(read(os.path.join(STATIC, "js", "package.json"))) == {"type": "module"}
    names = {os.path.basename(p) for p in JS_FILES}
    assert {"main.js", "core.js", "api.js"} <= names


# ---------------------------------------------------------------- the CSP, held by construction
def test_no_inline_script_or_handlers():
    html = read(os.path.join(STATIC, "index.html"))
    assert "<script>" not in html and "onclick=" not in html
    assert not re.search(r"<script(?![^>]*\ssrc=)", html), "an inline <script>"
    assert not re.search(r"<[^>]+\son[a-z]+\s*=", html, re.I), "an inline event handler"
    assert not re.search(r"<[^>]+\sstyle\s*=", html, re.I) and "<style" not in html, "inline style"
    assert 'type="module"' in html and "/static/js/main.js" in html


@pytest.mark.parametrize("path", JS_FILES, ids=os.path.basename)
def test_scripts_never_write_inline_style_or_handlers_or_raw_html(path):
    src = read(path)
    assert not re.search(r"""\bstyle\s*=\s*["'\\]""", src), "a style attribute in a string"
    assert "<style" not in src, "a <style> block"
    for banned in ("cssText", 'setAttribute("style"', "setAttribute('style'", "insertAdjacentHTML", "outerHTML",
                   "document.write", "eval(", "new Function", "<script"):
        assert banned not in src, banned
    assert not re.search(r"""\bon[a-z]+\s*=\s*["'\\]""", src), "an inline event handler attribute in a string"
    assert not re.search(r"""\.on[a-z]+\s*=[^=]""", src), "assign handlers with addEventListener"


def test_no_window_confirm_or_alert():
    for f in glob.glob(os.path.join(STATIC, "js", "*.js")):
        src = open(f).read(); assert "confirm(" not in src and "alert(" not in src


@pytest.mark.parametrize("path", JS_FILES, ids=os.path.basename)
def test_accent_is_set_only_after_the_colour_check(path):
    """The exchange's accent_color is data: it reaches CSS only through core.applyAccent, which checks it first."""
    src = read(path)
    if os.path.basename(path) == "core.js":
        body = src[src.index("export function applyAccent"):]
        body = body[:body.index("\n}\n")]
        assert body.index("HEX.test(") < body.index("setProperty(")
    else:
        assert "setProperty(" not in src


# ---------------------------------------------------------------- escaping
def _skip_string(src, i):
    quote = src[i]
    i += 1
    while src[i] != quote:
        i += 2 if src[i] == "\\" else 1
    return i + 1


def _skip_comment(src, i):
    """i is at a "/": index after the comment starting here, or i when it does not start one."""
    if src.startswith("//", i):
        j = src.find("\n", i)
        return len(src) if j < 0 else j
    if src.startswith("/*", i):
        return src.index("*/", i) + 2
    return i


def _template(src, i, found):
    """src[i] is a backtick. Parse the template literal (and any nested in its ${} expressions); every one is
    appended to `found` as (pieces, exprs): the raw text segments and the ${} expression sources. Returns the
    index after the closing backtick."""
    i += 1
    pieces, exprs, buf = [], [], []
    while src[i] != "`":
        if src[i] == "\\":
            buf.append(src[i:i + 2])
            i += 2
        elif src.startswith("${", i):
            pieces.append("".join(buf))
            buf = []
            start, depth, i = i + 2, 1, i + 2
            while depth:
                c = src[i]
                if c in "'\"":
                    i = _skip_string(src, i)
                elif c == "`":
                    i = _template(src, i, found)
                elif c == "/" and (j := _skip_comment(src, i)) != i:
                    i = j
                else:
                    depth += (c == "{") - (c == "}")
                    i += 1
            exprs.append(src[start:i - 1])
        else:
            buf.append(src[i])
            i += 1
    pieces.append("".join(buf))
    found.append((pieces, exprs))
    return i + 1


def template_literals(src):
    """Every template literal in src as (pieces, exprs). Regex literals are not parsed, so the modules keep quote
    characters and backticks out of them (core.js writes them as hex escapes)."""
    found, i = [], 0
    while i < len(src):
        c = src[i]
        if c in "'\"":
            i = _skip_string(src, i)
        elif c == "`":
            i = _template(src, i, found)
        elif c == "/" and (j := _skip_comment(src, i)) != i:
            i = j
        else:
            i += 1
    return found


def is_single_safe_call(expr):
    """`esc(...)`, `money(...)`, `daysLabel(...)`, `monthLabel(...)` or `renderXxx(...)` and nothing after the
    closing parenthesis."""
    expr = expr.strip()
    m = SAFE_CALL.match(expr)
    if not m:
        return False
    depth, i = 1, m.end()
    while i < len(expr):
        c = expr[i]
        if c in "'\"":
            i = _skip_string(expr, i)
            continue
        if c == "`":
            return False  # a template literal as an argument is built elsewhere, by a render function
        depth += (c == "(") - (c == ")")
        i += 1
        if depth == 0:
            return i == len(expr)
    return False


def test_the_scanner_itself():
    src = 'a = `<b>${esc(x)}</b> ${items.map(i => `<i>${i}</i>`).join("")} // not a comment`; // `x`\nb = "`"'
    found = template_literals(src)
    assert len(found) == 2
    outer = next(f for f in found if len(f[1]) == 2)
    assert [e.strip() for e in outer[1]] == ["esc(x)", 'items.map(i => `<i>${i}</i>`).join("")']
    assert is_single_safe_call("esc(a, b(c))") and is_single_safe_call(" renderRow(x) ")
    assert is_single_safe_call("monthLabel(v.updated_at)")
    assert not is_single_safe_call("esc(a) + b") and not is_single_safe_call("x ? esc(a) : ''")
    assert not is_single_safe_call("escape(a)") and not is_single_safe_call("esc(a)(b)")
    assert not is_single_safe_call("esc(a) || `<x>`") and not is_single_safe_call("hostLabel(u)")


@pytest.mark.parametrize("path", JS_FILES, ids=os.path.basename)
def test_every_innerhtml_interpolation_is_escaped(path):
    """For each static/js/*.js, every `${...}` inside a template literal that holds markup is esc(...), money(...),
    daysLabel(...), monthLabel(...) or a call to a local function whose name starts with `render`, and never sits in
    an unquoted attribute. Every innerHTML assignment is a template literal, an empty string or a render* call."""
    src = read(path)
    for pieces, exprs in template_literals(src):
        if not re.search(r"</?[A-Za-z]", "".join(pieces)):
            continue  # not markup: a URL path, a message
        for before, expr in zip(pieces, exprs):
            assert is_single_safe_call(expr), f"{os.path.basename(path)}: unescaped interpolation ${{{expr.strip()}}}"
            assert not re.search(r"\s[A-Za-z_:][\w:.-]*=\s*$", before), \
                f"{os.path.basename(path)}: unquoted attribute before ${{{expr.strip()}}}"
    for m in re.finditer(r"innerHTML\s*\+?=\s*(?P<rhs>[^;\n]*)", src):
        rhs = m.group("rhs").strip()
        assert rhs.startswith(("`", "render")) or rhs in ('""', "''"), f"{os.path.basename(path)}: innerHTML = {rhs}"


def test_every_innerhtml_check_has_something_to_check():
    """Guards the guard: once screens exist, the scanner must be finding template literals in them."""
    if len(JS_FILES) > 3:
        assert sum(len(template_literals(read(p))) for p in JS_FILES) > 3


# ---------------------------------------------------------------- titles
def test_document_title_is_set_only_in_main_from_app_name():
    for f in JS_FILES:
        src = read(f)
        if f.endswith("main.js"):
            for m in re.finditer(r"document\.title\s*=\s*([^;\n]+)", src):
                assert m.group(1).strip() == "session.app_name", m.group(1)  # APP_NAME, from /api/session
        else:
            assert "document.title" not in src, f


def test_stylesheet_holds_at_large_text():
    css = read(os.path.join(STATIC, "style.css"))
    assert "nowrap" not in css                                   # nothing refuses to wrap at 200% zoom
    assert "overflow-wrap: break-word" in css and "min-width: 0" in css
    assert not re.search(r"(?<![-\w])(width|min-width):\s*[2-9]\d\dpx", css)   # no fixed wide boxes
