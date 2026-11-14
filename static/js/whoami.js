// "Who are you?": who is holding this phone, per exchange, in a plain cookie gx_me_<slug> (400 days,
// SameSite=Lax). It is a convenience, not a security boundary: it shows "You're getting ...", puts your own list
// first, and fills in updated_by on every save. "Just looking (parent, etc.)" stores { person_id: null, name }.
// The cookie helpers are DOM-free so node --test can load this file.
import { esc } from "./core.js";

export const MAX_NAME = 60; // the server's limit on updated_by
const MAX_AGE = 400 * 86400;
const cookieName = slug => `gx_me_${slug}`;

// A stored value is { person_id: whole number or null, name: 1 to 60 characters }; anything else is null.
export function cleanMe(value) {
  if (!value || typeof value !== "object") return null;
  const pid = value.person_id;
  if (pid !== null && !(Number.isInteger(pid) && pid > 0)) return null;
  const name = typeof value.name === "string" ? value.name.trim().slice(0, MAX_NAME) : "";
  return name ? { person_id: pid, name } : null;
}

// The value for `slug` out of a document.cookie string, or null.
export function parseMe(cookies, slug) {
  const prefix = `${cookieName(slug)}=`;
  const raw = String(cookies ?? "").split(/;\s*/).find(c => c.startsWith(prefix));
  if (!raw) return null;
  try {
    return cleanMe(JSON.parse(decodeURIComponent(raw.slice(prefix.length))));
  } catch {
    return null;
  }
}

// The document.cookie assignment that stores (or, for null, clears) the value.
export function meCookie(slug, value, secure) {
  const clean = cleanMe(value);
  const body = clean ? encodeURIComponent(JSON.stringify(clean)) : "";
  return `${cookieName(slug)}=${body}; Path=/; Max-Age=${clean ? MAX_AGE : 0}; SameSite=Lax${secure ? "; Secure" : ""}`;
}

export function me(slug) {
  return parseMe(globalThis.document?.cookie, slug);
}

export function setMe(slug, value) {
  globalThis.document.cookie = meCookie(slug, value, globalThis.location?.protocol === "https:");
}

// ---------------------------------------------------------------- the picker
const renderPerson = p => `<button class="btn" type="button" data-pid="${esc(p.id)}">${esc(p.name)}</button>`;
const renderPeople = people => people.map(renderPerson).join("");
const renderPicker = (people, current) => `
  <dialog class="picker-dialog" aria-labelledby="pickerTitle">
    <div class="picker">
      <h1 id="pickerTitle">Who are you?</h1>
      <p>Tap your name. The page then shows who you're shopping for and allows you to update your own wishlist/ideas/sizes/etc.</p>
      ${renderPeople(people)}
      <button class="btn" type="button" data-act="looking">Just looking (parent, etc.)</button>
      <form data-form="looking" hidden novalidate>
        <label class="field"><span>Your name</span>
          <span class="hint">Shown as "updated by" on anything you change.</span>
          <input name="name" type="text" maxlength="60" autocomplete="given-name" value="${esc(current)}"></label>
        <p class="msg error" role="alert" hidden></p>
        <button class="btn primary wide" type="submit">Continue</button>
      </form>
    </div>
  </dialog>`;

// Asks who this is, stores the answer with setMe and resolves with it; resolves null when the picker is closed
// without an answer (Esc or the phone's back gesture), leaving what was stored before.
export function showPicker(slug, people) {
  const current = me(slug);
  const holder = document.createElement("div");
  holder.innerHTML = renderPicker(people, current?.person_id === null ? current.name : "");
  const dialog = holder.firstElementChild;
  document.body.append(dialog);
  return new Promise(resolve => {
    const done = value => {
      if (value) setMe(slug, value);
      dialog.close();
      dialog.remove();
      resolve(value ? cleanMe(value) : null);
    };
    const form = dialog.querySelector("form");
    dialog.addEventListener("click", e => {
      const btn = e.target.closest("button[data-pid], button[data-act=looking]");
      if (!btn) return;
      if (btn.dataset.act === "looking") {
        form.hidden = false;
        form.elements.name.focus();
        return;
      }
      const person = people.find(p => String(p.id) === btn.dataset.pid);
      if (person) done({ person_id: person.id, name: person.name });
    });
    form.addEventListener("submit", e => {
      e.preventDefault();
      const name = form.elements.name.value.trim();
      if (!name) {
        const box = form.querySelector(".msg");
        box.textContent = "Type your name, so people know who changed what.";
        box.hidden = false;
        return;
      }
      done({ person_id: null, name });
    });
    dialog.addEventListener("cancel", () => done(null));
    dialog.showModal();
  });
}
