// #/admin          Sign in, the exchanges, and a new exchange.
// #/admin/x/<id>   One exchange: name, address, colour and order; password and share link (with a copy button);
//                  people and households; years (details, roster, link to pairings); profile fields.
// Each section saves and redraws on its own, so typing in one section is never cleared by a save in another.
import { get, send } from "./api.js";
import { esc, money, renderChecked, renderError, renderOptions, toast, validAccent } from "./core.js";

const q = s => encodeURIComponent(s);

// ---------------------------------------------------------------- DOM-free helpers (tests/frontend.test.mjs)
// Integer cents -> the text for a budget box: 5000 -> "50", 2999 -> "29.99", null -> "".
export function centsToText(cents) {
  if (!Number.isInteger(cents)) return "";
  const rest = cents % 100 ? `.${String(cents % 100).padStart(2, "0")}` : "";
  return `${Math.floor(cents / 100)}${rest}`;
}

// The year a new edition most likely is: the year after the newest, or this year when there are none.
export function nextYear(editions, today = new Date()) {
  return editions.length ? Math.max(...editions.map(e => e.year)) + 1 : today.getFullYear();
}

// Roster choices: active people, plus anyone inactive who is still on this year's roster.
export function rosterChoices(people, edition) {
  return people.filter(p => p.active || edition.person_ids.includes(p.id));
}

// The field ids in a new order after moving one up (-1) or down (+1); null when it can't move.
export function moved(ids, id, step) {
  const at = ids.indexOf(id);
  if (at < 0 || at + step < 0 || at + step >= ids.length) return null;
  const out = ids.slice();
  [out[at], out[at + step]] = [out[at + step], out[at]];
  return out;
}

// ---------------------------------------------------------------- markup
const renderSlot = () => `<div data-slot="msg"></div>`;
const renderSaveRow = label => `<div class="btn-row"><button class="btn primary" type="submit">${esc(label)}</button></div>`;
const renderInactive = (on, word = "hidden") => (on ? "" : ` (${esc(word)})`);

// Same input settings as the family's password box: a phone keyboard must not capitalize or "correct" a password.
export const renderLogin = () => `
  <form class="card" data-form="login" novalidate>
    <h1>Admin</h1>
    <p>For the organizer only. Family members don't need this.</p>
    <label class="field"><span>Admin password</span>
      <input name="password" type="password" autocomplete="current-password" autocapitalize="none" spellcheck="false" required></label>
    <label class="check"><input name="show" type="checkbox"> Show the password as I type</label>
    ${renderSlot()}
    <button class="btn primary wide" type="submit">Sign in</button>
  </form>`;

const renderExchangeRow = x => `<li class="link-row"><a href="#/admin/x/${esc(x.id)}">
  <span><span class="title">${esc(x.name)}${renderInactive(x.active, "closed to the family")}</span><br><span class="muted small">/#/x/${esc(x.slug)}</span></span>
  <span class="go">Manage</span></a></li>`;
const renderExchangeRows = list => list.map(renderExchangeRow).join("");
const renderNoExchanges = list => (list.length ? "" : `<p>No exchanges yet. Make the first one below.</p>`);

export const renderAdminHome = list => `
  <section class="card head">
    <h1>Admin</h1>
    <div class="btn-row"><button class="btn quiet" type="button" data-act="logout">Sign out</button></div>
  </section>
  <section class="card">
    <h2>Exchanges</h2>
    ${renderNoExchanges(list)}
    <ul class="rows">${renderExchangeRows(list)}</ul>
  </section>
  <section class="card" data-section="new-exchange">
    <h2>New exchange</h2>
    ${renderSlot()}
    <form data-form="new-exchange" novalidate>
      <label class="field"><span>Name</span><span class="hint">What the family sees, such as "Cousins".</span><input name="name" type="text" maxlength="80"></label>
      <label class="field"><span>Address</span><span class="hint">Lowercase letters, digits and dashes, such as "cousins". The page is /#/x/&lt;address&gt;.</span>
        <input name="slug" type="text" maxlength="40" autocapitalize="none" spellcheck="false"></label>
      <label class="field"><span>Family password</span><span class="hint">4 or more characters. Exchanges with the same password open together.</span>
        <input name="password" type="text" maxlength="128" autocapitalize="none" spellcheck="false" autocomplete="off"></label>
      ${renderSaveRow("Make the exchange")}
    </form>
  </section>`;

// one exchange: settings
const renderColorBox = x => `
  <label class="field"><span>Colour</span><input name="accent_color" type="color" value="${esc(validAccent(x.accent_color) ?? "#1d4f3c")}"></label>
  <label class="check"><input name="no_color" type="checkbox"${renderChecked(!validAccent(x.accent_color))}> Use the standard colour</label>`;
const renderSettings = x => `
  <h2>Settings</h2>
  ${renderSlot()}
  <form data-form="settings" novalidate>
    <label class="field"><span>Name</span><input name="name" type="text" maxlength="80" value="${esc(x.name)}"></label>
    <label class="field"><span>Address</span><span class="hint">Changing it breaks links people already have.</span>
      <input name="slug" type="text" maxlength="40" autocapitalize="none" spellcheck="false" value="${esc(x.slug)}"></label>
    ${renderColorBox(x)}
    <label class="field"><span>Order on the start page</span><input name="sort_order" type="number" step="1" value="${esc(x.sort_order)}"></label>
    <label class="check"><input name="active" type="checkbox"${renderChecked(x.active)}> Open to the family</label>
    ${renderSaveRow("Save settings")}
  </form>`;

const renderShareLink = url => (url ? `
  <label class="field"><span>Share link</span><input class="share-link" name="link" type="text" readonly value="${esc(url)}"></label>
  <div class="btn-row"><button class="btn primary" type="button" data-act="copy">Copy the link</button></div>` : "");
const renderAccess = (x, url) => `
  <h2>Password and share link</h2>
  ${renderSlot()}
  <form data-form="password" novalidate>
    <label class="field"><span>New family password</span>
      <span class="hint">Changing it signs every phone out of this exchange and stops the old share link.</span>
      <input name="password" type="text" maxlength="128" autocapitalize="none" spellcheck="false" autocomplete="off"></label>
    ${renderSaveRow("Change the password")}
  </form>
  <p>A share link opens ${esc(x.name)} without typing the password. Making a new one stops the previous link working.</p>
  <div class="btn-row"><button class="btn" type="button" data-act="make-link">Make a share link</button></div>
  ${renderShareLink(url)}`;

// people
const renderHousehold = p => (p.household ? ` · ${esc(p.household)}` : "");
const renderPerson = p => `
  <li><details data-id="${esc(p.id)}"><summary>${esc(p.name)}${renderHousehold(p)}${renderInactive(p.active, "not taking part")}</summary>
    <form data-form="person" data-id="${esc(p.id)}" novalidate>
      <label class="field"><span>Name</span><input name="name" type="text" maxlength="80" value="${esc(p.name)}"></label>
      <label class="field"><span>Household</span><span class="hint">Same label, same household: the pairings warn about those.</span>
        <input name="household" type="text" maxlength="80" value="${esc(p.household)}"></label>
      <label class="check"><input name="active" type="checkbox"${renderChecked(p.active)}> Still taking part</label>
      ${renderSaveRow("Save")}
    </form></details></li>`;
const renderPersonRows = people => people.map(renderPerson).join("");
const renderPeople = people => `
  <h2>People</h2>
  ${renderSlot()}
  <ul class="rows admin-list">${renderPersonRows(people)}</ul>
  <form data-form="new-person" novalidate>
    <h3>Add someone</h3>
    <label class="field"><span>Name</span><input name="name" type="text" maxlength="80"></label>
    <label class="field"><span>Household (optional)</span><input name="household" type="text" maxlength="80"></label>
    ${renderSaveRow("Add")}
  </form>`;

// years
const STATUS = [{ value: "open", label: "Open (lists can change)" }, { value: "closed", label: "Closed (read-only)" }];
const renderStatus = e => (e.status === "paired"
  ? `<p><strong>Status:</strong> paired. Use Pairings to unpair or change it.</p>`
  : `<label class="field"><span>Status</span><select name="status">${renderOptions(STATUS, e.status)}</select></label>`);
const renderRosterBox = (p, e) => `<label class="check"><input type="checkbox" name="person" value="${esc(p.id)}"${renderChecked(e.person_ids.includes(p.id))}> ${esc(p.name)}${renderInactive(p.active, "not taking part")}</label>`;
const renderRosterBoxes = (people, e) => rosterChoices(people, e).map(p => renderRosterBox(p, e)).join("");
const renderBudget = e => (Number.isInteger(e.budget_cents) ? ` · ${money(e.budget_cents)}` : "");
const renderEdition = (e, people, open) => `
  <li><details data-id="${esc(e.id)}"${renderOpen(open)}><summary>${esc(e.label)} · ${esc(e.status)}${renderBudget(e)}</summary>
    <div data-slot="msg"></div>
    <p><a class="btn primary" href="#/admin/e/${esc(e.id)}/pairings">Pairings for ${esc(e.label)}</a></p>
    <form data-form="edition" data-id="${esc(e.id)}" novalidate>
      <label class="field"><span>Label</span><input name="label" type="text" maxlength="40" value="${esc(e.label)}"></label>
      <label class="field"><span>Budget</span><span class="hint">Such as 50 or 25.00. Empty for none.</span>
        <input name="budget" type="text" inputmode="decimal" value="${esc(centsToText(e.budget_cents))}"></label>
      <label class="field"><span>Gift exchange day</span><input name="event_date" type="date" value="${esc(e.event_date)}"></label>
      <label class="field"><span>Where</span><input name="location" type="text" maxlength="200" value="${esc(e.location)}"></label>
      <label class="field"><span>Rules</span><textarea name="rules" rows="3" maxlength="2000">${esc(e.rules)}</textarea></label>
      ${renderStatus(e)}
      ${renderSaveRow("Save this year")}
    </form>
    <form data-form="roster" data-id="${esc(e.id)}" novalidate>
      <h3>Who's in it this year</h3>
      ${renderRosterBoxes(people, e)}
      ${renderSaveRow("Save who's in it")}
    </form></details></li>`;
const renderOpen = open => (open ? " open" : "");
const renderEditionRows = (editions, people, openIds) => editions.map(e => renderEdition(e, people, openIds.has(e.id))).join("");
const renderEditions = (editions, people, openIds) => `
  <h2>Years</h2>
  ${renderSlot()}
  <ul class="rows admin-list">${renderEditionRows(editions, people, openIds)}</ul>
  <form data-form="new-edition" novalidate>
    <h3>Start a year</h3>
    <p class="small muted">A past year (such as last year, entered from the bowl) lets the pairings warn about repeats.</p>
    <label class="field"><span>Year</span><input name="year" type="number" min="2000" max="2100" step="1" value="${esc(nextYear(editions))}"></label>
    <label class="check"><input name="copy_roster" type="checkbox" checked> Same people as the year before</label>
    ${renderSaveRow("Start it")}
  </form>`;

// profile fields
const renderFieldUp = (f, pos) => (pos > 0 ? `<button class="btn quiet" type="button" data-act="field-up" data-id="${esc(f.id)}">↑ Up</button>` : "");
const renderFieldDown = (f, pos, count) => (pos < count - 1 ? `<button class="btn quiet" type="button" data-act="field-down" data-id="${esc(f.id)}">↓ Down</button>` : "");
const renderField = (f, pos, count) => `
  <li><details data-id="${esc(f.id)}"><summary>${esc(f.label)}${renderInactive(f.active)}</summary>
    <form data-form="field" data-id="${esc(f.id)}" novalidate>
      <label class="field"><span>Label</span><input name="label" type="text" maxlength="60" value="${esc(f.label)}"></label>
      <label class="field"><span>Hint (optional)</span><input name="hint" type="text" maxlength="200" value="${esc(f.hint)}"></label>
      <label class="check"><input name="active" type="checkbox"${renderChecked(f.active)}> Show it (hiding keeps what people typed)</label>
      ${renderSaveRow("Save")}
    </form>
    <div class="btn-row">${renderFieldUp(f, pos)}${renderFieldDown(f, pos, count)}</div></details></li>`;
const renderFieldRows = fields => fields.map((f, i) => renderField(f, i, fields.length)).join("");
const renderFields = fields => `
  <h2>Profile fields</h2>
  <p class="small muted">Sizes and favorites on everyone's page. Values belong to the person and carry over each year.</p>
  ${renderSlot()}
  <ul class="rows admin-list">${renderFieldRows(fields)}</ul>
  <form data-form="new-field" novalidate>
    <h3>Add a field</h3>
    <label class="field"><span>Label</span><input name="label" type="text" maxlength="60"></label>
    <label class="field"><span>Hint (optional)</span><input name="hint" type="text" maxlength="200"></label>
    ${renderSaveRow("Add")}
  </form>`;

export const renderExchangePage = x => `
  <a class="back" href="#/admin">← All exchanges</a>
  <section class="card head"><h1>${esc(x.name)}</h1>
    <p>Family page: <a href="#/x/${esc(x.slug)}">/#/x/${esc(x.slug)}</a></p></section>
  <section class="card" data-section="settings"></section>
  <section class="card" data-section="access"></section>
  <section class="card" data-section="people"></section>
  <section class="card" data-section="editions"></section>
  <section class="card" data-section="fields"></section>`;

const renderNotFound = () => `<div class="notice"><p>No such exchange.</p><p><a class="btn" href="#/admin">All exchanges</a></p></div>`;

// ---------------------------------------------------------------- behaviour
const val = (form, name) => form.elements[name]?.value ?? "";
const checked = (form, name) => Boolean(form.elements[name]?.checked);

// Runs a change, showing failures in `slot` and leaving the form as typed. Resolves true on success.
async function attempt(slot, button, change) {
  slot.innerHTML = "";
  if (button) button.disabled = true;
  try {
    await change();
    return true;
  } catch (err) {
    slot.innerHTML = renderError(err?.error ?? "Something went wrong. Try again.");
    slot.scrollIntoView({ block: "nearest" });
    return false;
  } finally {
    if (button) button.disabled = false;
  }
}

function showLogin(ctx) {
  ctx.view.innerHTML = renderLogin();
  const form = ctx.view.querySelector("form");
  const input = form.elements.password;
  form.elements.show.addEventListener("change", () => { input.type = form.elements.show.checked ? "text" : "password"; });
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const okay = await attempt(form.querySelector("[data-slot=msg]"), form.querySelector("button"),
      () => send("POST", "/api/admin/login", { password: val(form, "password") }));
    if (okay) ctx.rerender();
  });
  form.elements.password.focus();
}

export async function render(ctx) {
  const session = await get("/api/session");
  if (!ctx.alive()) return;
  if (!session.admin) {
    showLogin(ctx);
    return;
  }
  if (ctx.parts[1] === "x" && /^[0-9]+$/.test(ctx.parts[2] ?? "")) return renderExchange(ctx, Number(ctx.parts[2]));
  return renderHome(ctx);
}

async function renderHome(ctx) {
  const { view } = ctx;
  const list = await get("/api/admin/exchanges");
  if (!ctx.alive()) return;
  view.innerHTML = renderAdminHome(list);
  view.querySelector("[data-act=logout]").addEventListener("click", async () => {
    await send("POST", "/api/admin/logout", {}).catch(() => null);
    location.hash = "#/";
  });
  const form = view.querySelector("form[data-form=new-exchange]");
  form.addEventListener("submit", async e => {
    e.preventDefault();
    let id = null;
    const okay = await attempt(view.querySelector("[data-section=new-exchange] [data-slot=msg]"), form.querySelector("button"), async () => {
      ({ id } = await send("POST", "/api/admin/exchanges", { name: val(form, "name"), slug: val(form, "slug").trim(), password: val(form, "password") }));
    });
    if (okay) location.hash = `#/admin/x/${id}`;
  });
}

async function renderExchange(ctx, xid) {
  const { view } = ctx;
  const [list, people, editions, fields] = await Promise.all([
    get("/api/admin/exchanges"), get(`/api/admin/exchanges/${xid}/people`), get(`/api/admin/exchanges/${xid}/editions`),
    get(`/api/admin/exchanges/${xid}/fields`),
  ]);
  if (!ctx.alive()) return;
  const data = { x: list.find(x => x.id === xid), people, editions, fields, link: null };
  if (!data.x) {
    view.innerHTML = renderNotFound();
    return;
  }
  view.innerHTML = renderExchangePage(data.x);
  const section = name => view.querySelector(`[data-section=${name}]`);
  const slotIn = el => el.querySelector("[data-slot=msg]");
  const openEditions = () => new Set([...section("editions").querySelectorAll("details[open]")].map(d => Number(d.dataset.id)));

  const draw = {
    settings: () => { section("settings").innerHTML = renderSettings(data.x); },
    access: () => { section("access").innerHTML = renderAccess(data.x, data.link); },
    people: () => { section("people").innerHTML = renderPeople(data.people); },
    editions: (open = openEditions()) => { section("editions").innerHTML = renderEditions(data.editions, data.people, open); },
    fields: () => { section("fields").innerHTML = renderFields(data.fields); },
  };
  for (const d of Object.values(draw)) d();

  const reload = {
    people: async () => { data.people = await get(`/api/admin/exchanges/${xid}/people`); },
    editions: async () => { data.editions = await get(`/api/admin/exchanges/${xid}/editions`); },
    fields: async () => { data.fields = await get(`/api/admin/exchanges/${xid}/fields`); },
  };

  view.addEventListener("submit", async e => {
    const form = e.target.closest("form[data-form]");
    if (!form) return;
    e.preventDefault();
    const kind = form.dataset.form;
    const id = Number(form.dataset.id);
    const button = form.querySelector("button[type=submit]");
    const box = slotIn(form.closest("details") ?? form.closest("section"));
    const run = change => attempt(box, button, change);

    if (kind === "settings") {
      const color = checked(form, "no_color") ? null : val(form, "accent_color");
      const sort = Number(val(form, "sort_order"));
      if (await run(async () => {
        data.x = await send("PATCH", `/api/admin/exchanges/${xid}`, {
          name: val(form, "name"), slug: val(form, "slug").trim(), accent_color: color, active: checked(form, "active"),
          sort_order: Number.isInteger(sort) ? sort : 0,
        });
      })) { draw.settings(); toast("Saved"); }
    } else if (kind === "password") {
      if (await run(() => send("PATCH", `/api/admin/exchanges/${xid}`, { password: val(form, "password") }))) {
        data.link = null;
        draw.access();
        slotIn(section("access")).innerHTML = `<p class="msg ok" role="status">Password changed. Every phone needs the new one, and old share links stopped working.</p>`;
      }
    } else if (kind === "person") {
      if (await run(async () => {
        await send("PATCH", `/api/admin/people/${id}`, { name: val(form, "name"), household: val(form, "household"), active: checked(form, "active") });
        await reload.people();
      })) { draw.people(); draw.editions(); toast("Saved"); }
    } else if (kind === "new-person") {
      if (await run(async () => {
        await send("POST", `/api/admin/exchanges/${xid}/people`, { name: val(form, "name"), household: val(form, "household") });
        await reload.people();
      })) { draw.people(); draw.editions(); toast("Added"); section("people").querySelector("form[data-form=new-person] input")?.focus(); }
    } else if (kind === "edition") {
      const body = { label: val(form, "label"), budget: val(form, "budget"), event_date: val(form, "event_date"),
        location: val(form, "location"), rules: val(form, "rules") };
      if (form.elements.status) body.status = val(form, "status");
      if (await run(async () => { await send("PATCH", `/api/admin/editions/${id}`, body); await reload.editions(); })) {
        draw.editions();
        toast("Saved");
      }
    } else if (kind === "roster") {
      const ids = [...form.querySelectorAll("input[name=person]:checked")].map(i => Number(i.value));
      if (await run(async () => { await send("PUT", `/api/admin/editions/${id}/roster`, { person_ids: ids }); await reload.editions(); })) {
        draw.editions();
        toast("Saved");
      }
    } else if (kind === "new-edition") {
      let created = null;
      if (await run(async () => {
        ({ id: created } = await send("POST", `/api/admin/exchanges/${xid}/editions`, {
          year: Number(val(form, "year")), copy_roster: checked(form, "copy_roster"),
        }));
        await reload.editions();
      })) { draw.editions(new Set([created])); toast("Started"); }
    } else if (kind === "field") {
      if (await run(async () => {
        await send("PATCH", `/api/admin/fields/${id}`, { label: val(form, "label"), hint: val(form, "hint"), active: checked(form, "active") });
        await reload.fields();
      })) { draw.fields(); toast("Saved"); }
    } else if (kind === "new-field") {
      if (await run(async () => {
        await send("POST", `/api/admin/exchanges/${xid}/fields`, { label: val(form, "label"), hint: val(form, "hint") });
        await reload.fields();
      })) { draw.fields(); toast("Added"); }
    }
  });

  view.addEventListener("click", async e => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === "make-link") {
      if (await attempt(slotIn(section("access")), btn, async () => {
        data.link = (await send("POST", `/api/admin/exchanges/${xid}/link`, {})).url;
      })) draw.access();
    } else if (act === "copy") {
      const input = section("access").querySelector("input[name=link]");
      const box = slotIn(section("access"));
      try {
        await navigator.clipboard.writeText(input.value);
        box.innerHTML = `<p class="msg ok" role="status">Copied. Paste it into the family message.</p>`;
      } catch {
        input.focus();
        input.select();
        box.innerHTML = `<p class="msg warn" role="status">Couldn't copy by itself: the link is selected, so press and hold it to copy.</p>`;
      }
    } else if (act === "field-up" || act === "field-down") {
      const ids = moved(data.fields.map(f => f.id), Number(btn.dataset.id), act === "field-up" ? -1 : 1);
      if (!ids) return;
      if (await attempt(slotIn(section("fields")), btn, async () => {
        await send("PUT", `/api/admin/exchanges/${xid}/fields/order`, { ids });
        await reload.fields();
      })) draw.fields();
    }
  });
}
