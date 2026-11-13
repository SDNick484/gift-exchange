// Shared helpers. No top-level DOM access, so Node can import this file (tests/frontend.test.mjs).
//
// The escaping rule: everything a person typed reaches innerHTML only through esc(). Markup is built in template
// literals whose every ${...} is one call to esc, money, daysLabel, monthLabel or a render* function (each of which
// returns markup it escaped itself). tests/test_frontend.py scans every module for this.

// ---------------------------------------------------------------- escaping
// The regex spells the two quote characters as hex escapes so the scanner in tests/test_frontend.py, which does
// not parse regex literals, never mistakes one for the start of a string.
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export function esc(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>\x22\x27]/g, c => ESC[c]);
}

// ---------------------------------------------------------------- formatting
// 5000 -> "$50", 2999 -> "$29.99", 100000 -> "$1,000". Anything but a whole number of cents -> "".
export function money(cents) {
  if (!Number.isInteger(cents)) return "";
  const abs = Math.abs(cents);
  const dollars = String(Math.floor(abs / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const rest = abs % 100 ? `.${String(abs % 100).padStart(2, "0")}` : "";
  return `${cents < 0 ? "-" : ""}$${dollars}${rest}`;
}

// 41 -> "41 days", 1 -> "1 day", 0 -> "today", -2 -> "2 days ago".
export function daysLabel(n) {
  if (n === 0) return "today";
  const d = Math.abs(n);
  return `${d} ${d === 1 ? "day" : "days"}${n < 0 ? " ago" : ""}`;
}

// The host of a web link, without a leading "www.": "https://www.amazon.com/hz/x" -> "amazon.com". "" otherwise.
export function hostLabel(url) {
  try {
    const u = new URL(String(url ?? ""));
    if (u.protocol !== "http:" && u.protocol !== "https:") return "";
    return u.hostname.replace(/^www\./i, "");
  } catch {
    return "";
  }
}

export const STALE_DAYS = 182;
// A profile value older than about six months is shown dimmed with "may be out of date" (kids' sizes go stale).
export function isStale(updatedAtSec, nowSec) {
  if (!Number.isFinite(updatedAtSec) || !Number.isFinite(nowSec)) return false;
  return nowSec - updatedAtSec > STALE_DAYS * 86400;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// Epoch seconds -> "Nov 2025" in the phone's own time zone. "" without a time.
export function monthLabel(sec) {
  if (!Number.isFinite(sec)) return "";
  const d = new Date(sec * 1000);
  return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

// Epoch seconds -> "Nov 20".
export function dayLabel(sec) {
  if (!Number.isFinite(sec)) return "";
  const d = new Date(sec * 1000);
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
}

// "2026-12-24" -> "Thu, Dec 24". The date is a calendar day, so it is read as such, never through a time zone.
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
export function eventDateLabel(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
  if (!m) return "";
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return `${WEEKDAYS[d.getUTCDay()]}, ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

export const nowSec = () => Math.floor(Date.now() / 1000);

// ---------------------------------------------------------------- routing
// "#/x/cousins/p/3?e=7" -> { parts: ["x", "cousins", "p", "3"], query: { e: "7" } }
export function parseHash(hash) {
  const [path, qs = ""] = (hash || "").replace(/^#\/?/, "").split("?");
  const query = {};
  for (const [k, v] of new URLSearchParams(qs)) query[k] = v;
  return { parts: path.split("/").filter(Boolean), query };
}

// ---------------------------------------------------------------- the exchange's accent colour
const HEX = /^#[0-9a-fA-F]{6}$/;
export function validAccent(color) {
  return typeof color === "string" && HEX.test(color) ? color : null;
}

// Black or white, whichever reads better on this #rrggbb background (WCAG relative luminance).
export function inkFor(color) {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(color.slice(i, i + 2), 16) / 255)
    .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.179 ? "#15191a" : "#ffffff";
}

// Sets --accent (and the text colour that goes on it) from an exchange's accent_color, data the admin typed, only
// when it is #rrggbb. Through the CSSOM: the Content-Security-Policy forbids style attributes in markup. Anything
// else, null included, puts the default back.
export function applyAccent(color) {
  const root = globalThis.document?.documentElement;
  if (!root) return;
  if (typeof color === "string" && HEX.test(color)) {
    root.style.setProperty("--accent", color);
    root.style.setProperty("--accent-ink", inkFor(color));
  } else {
    root.style.removeProperty("--accent");
    root.style.removeProperty("--accent-ink");
  }
}

// ---------------------------------------------------------------- small markup helpers (each returns escaped markup)
export const renderChecked = on => (on ? " checked" : "");
export const renderSelected = on => (on ? " selected" : "");
export const renderDisabled = on => (on ? " disabled" : "");

// <option>s from [{ value, label }]; `selected` is compared as text.
export function renderOptions(items, selected) {
  return items.map(i => `<option value="${esc(i.value)}"${renderSelected(String(i.value) === String(selected ?? ""))}>${esc(i.label)}</option>`).join("");
}

// A link to somewhere else on the web: a new tab, no referrer, and text that says where it goes.
export function renderLink(url, cls = "btn") {
  const host = hostLabel(url);
  if (!host) return "";
  return `<a class="${esc(cls)}" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open link · ${esc(host)}</a>`;
}

// A message box above a form: role=alert so a screen reader says it. Empty text renders nothing.
export const renderError = message => (message ? `<p class="msg error" role="alert">${esc(message)}</p>` : "");

// One element from the markup a render* function returns: fromHtml(renderItem, item).
export function fromHtml(renderFn, ...args) {
  const t = globalThis.document.createElement("template");
  t.innerHTML = renderFn(...args);
  return t.content.firstElementChild;
}

// A short-lived "Saved" note at the bottom of the screen.
export function toast(message) {
  const el = globalThis.document.createElement("div");
  el.className = "toast";
  el.setAttribute("role", "status");
  el.textContent = message;
  globalThis.document.body.append(el);
  setTimeout(() => el.remove(), 2600);
}
