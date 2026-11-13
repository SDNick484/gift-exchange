// #/  The password box, or the exchanges this browser has unlocked (straight to the one when there is only one).
// Also the password box a locked exchange route shows in its place (lockedView), and the one that opens over a page
// when a save finds this phone signed out (askPassword), so a half-typed form is never thrown away.
import { get, send } from "./api.js";
import { esc } from "./core.js";

const renderPasswordForm = (heading, intro) => `
  <form class="card" data-form="unlock" novalidate>
    <h1>${esc(heading)}</h1>
    <p>${esc(intro)}</p>
    <label class="field"><span>Password</span>
      <input name="password" type="password" autocomplete="current-password" autocapitalize="none" spellcheck="false" required></label>
    <label class="check"><input name="show" type="checkbox"> Show the password as I type</label>
    <p class="msg error" role="alert" hidden></p>
    <button class="btn primary wide" type="submit">Open</button>
  </form>`;

const renderExchange = x => `<li class="link-row"><a href="#/x/${esc(x.slug)}"><span class="title">${esc(x.name)}</span><span class="go">Open</span></a></li>`;
const renderExchangeRows = list => list.map(renderExchange).join("");
const renderExchanges = list => `
  <section class="card">
    <h1>Your gift exchanges</h1>
    <ul class="rows">${renderExchangeRows(list)}</ul>
  </section>
  <details class="card"><summary>Have a password for another exchange?</summary><div data-slot="form"></div></details>`;

// Wires a password form: POST /api/unlock, then onUnlocked(exchanges) with the exchanges the password opened.
function wirePasswordForm(form, onUnlocked) {
  const box = form.querySelector(".msg");
  const input = form.elements.password;
  form.elements.show.addEventListener("change", () => { input.type = form.elements.show.checked ? "text" : "password"; });
  form.addEventListener("submit", async e => {
    e.preventDefault();
    box.hidden = true;
    if (!input.value.trim()) {
      box.textContent = "Type the password first.";
      box.hidden = false;
      return;
    }
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const res = await send("POST", "/api/unlock", { password: input.value });
      await onUnlocked(res.exchanges, box);
    } catch (err) {
      box.textContent = err.error ?? "Something went wrong. Try again.";
      box.hidden = false;
      input.select();
    } finally {
      button.disabled = false;
    }
  });
  return form;
}

const INTRO = "Type the password from the family message. You only need to do this once on this phone.";

export async function render(ctx) {
  const { view } = ctx;
  const list = await get("/api/exchanges");
  if (!ctx.alive()) return;
  if (list.length === 1) {
    location.replace(`#/x/${encodeURIComponent(list[0].slug)}`);
    return;
  }
  if (list.length === 0) {
    view.innerHTML = renderPasswordForm("Welcome", INTRO);
  } else {
    view.innerHTML = renderExchanges(list);
    view.querySelector("[data-slot=form]").innerHTML = renderPasswordForm("Another password", "It adds the exchanges it opens to the list above.");
  }
  wirePasswordForm(view.querySelector("form[data-form=unlock]"), () => ctx.rerender());
}

// In place of a screen whose exchange this browser hasn't unlocked (or whose password changed since).
export function lockedView(ctx, slug) {
  ctx.view.innerHTML = renderPasswordForm("This exchange needs its password", INTRO);
  const form = ctx.view.querySelector("form");
  wirePasswordForm(form, (opened, box) => {
    if (slug && !opened.some(x => x.slug === slug)) {
      box.textContent = "That password opens a different exchange, not this one. Check the family message for this one's password.";
      box.hidden = false;
      return;
    }
    ctx.rerender();
  });
  form.elements.password.focus();
}

const renderDialog = () => `<dialog class="unlock-dialog">${renderPasswordForm("Password, please", "This phone was signed out. Your typing is still on the page behind this box.")}
  <p><button class="btn quiet wide" type="button" data-act="later">Not now</button></p></dialog>`;

let open = null;
// Opens the password box over the page. Resolves true once a password unlocked something, false on "Not now".
export function askPassword() {
  if (open) return open;
  const holder = document.createElement("div");
  holder.innerHTML = renderDialog();
  const dialog = holder.firstElementChild;
  document.body.append(dialog);
  open = new Promise(resolve => {
    const done = value => {
      dialog.close();
      dialog.remove();
      open = null;
      resolve(value);
    };
    wirePasswordForm(dialog.querySelector("form"), () => done(true));
    dialog.querySelector("[data-act=later]").addEventListener("click", () => done(false));
    dialog.addEventListener("cancel", e => { e.preventDefault(); done(false); });
    dialog.showModal();
  });
  return open;
}
