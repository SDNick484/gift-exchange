// #/x/<slug>/p/<pid>[?e=<edition id>]  One person's page: the basics (profile values with "updated Nov 2025",
// dimmed with "may be out of date" when stale), Anything else, the Amazon list, and Ideas. Every part has its own
// edit form.
//
// Nothing typed is lost (review focus 3). Each part (the basics, Anything else, each idea, the new-idea form) is a
// "unit" with its own form. A save or a Reload in one unit redraws only units that aren't being edited, so another
// open form keeps its typing. On a 409 the form stays open as typed, the server's message shows above it with a
// Reload button; Reload fetches the page again, shows what is saved now, and leaves the form alone until the person
// chooses: save theirs over it, or "Use what's saved". Fields they hadn't touched take the fresh values on Reload,
// so saving theirs never quietly puts back someone else's older text.
import { get, send } from "./api.js";
import { applyAccent, dayLabel, esc, fromHtml, isStale, monthLabel, nowSec, renderError, renderLink, toast } from "./core.js";
import { homePath, renderWho } from "./home.js";
import { me, showPicker } from "./whoami.js";

const q = s => encodeURIComponent(s);
export const pagePath = (slug, pid, editionId) =>
  `/api/x/${q(slug)}/people/${q(pid)}${editionId ? `?edition=${q(editionId)}` : ""}`;

// ---------------------------------------------------------------- DOM-free helpers (tests/frontend.test.mjs)
export const filledFields = profile => profile.filter(f => f.value !== null && f.value !== "");

// {field_id: updated_at or null}: what a profile save sends as `expected`.
export const stamps = profile => Object.fromEntries(profile.map(f => [String(f.field_id), f.updated_at ?? null]));

// The profile PUT body for the fields the person changed (form names "f<field id>"): only those are sent, so a field
// someone else changed meanwhile, and this person didn't touch, is neither overwritten nor a false conflict.
export function profileBody(current, orig, expected) {
  const values = {};
  const exp = {};
  for (const [name, value] of Object.entries(current)) {
    if (!/^f[0-9]+$/.test(name) || value === orig[name]) continue;
    const fid = name.slice(1);
    values[fid] = value;
    exp[fid] = expected[fid] ?? null;
  }
  return { values, expected: exp };
}

// After a Reload: fields still as they were when the form opened take the fresh saved value; the ones the person
// typed in are kept. Returns { set: {name: fresh value} to write into the form, orig: the new baseline, touched }.
export function mergeFresh(current, orig, fresh) {
  const set = {};
  const next = { ...orig };
  const touched = [];
  for (const [name, value] of Object.entries(fresh)) {
    if (!(name in current)) continue;
    if (current[name] === orig[name]) {
      set[name] = value;
      next[name] = value;
    } else {
      touched.push(name);
    }
  }
  return { set, orig: next, touched };
}

// The newest change on the page (details, ideas, profile values): { at, by } or null.
export function lastUpdate(page) {
  const all = [{ at: page.updated_at, by: page.updated_by }, ...page.items, ...page.profile]
    .filter(x => Number.isFinite(x.updated_at ?? x.at))
    .map(x => ({ at: x.at ?? x.updated_at, by: x.by ?? x.updated_by }));
  return all.reduce((best, x) => (!best || x.at > best.at ? x : best), null);
}

export function lastText(page) {
  const last = lastUpdate(page);
  return last && last.by ? `Last updated by ${last.by}, ${dayLabel(last.at)}` : "";
}

// The saved values of one unit, by form field name, as the form would show them.
export function freshValues(kind, page, itemId) {
  if (kind === "basics") return Object.fromEntries(page.profile.map(f => [`f${f.field_id}`, f.value ?? ""]));
  if (kind === "details") return { about: page.about ?? "", amazon_url: page.amazon_url ?? "" };
  const it = page.items.find(i => i.id === itemId);
  return it ? { title: it.title ?? "", url: it.url ?? "", note: it.note ?? "" } : null;
}

const ITEM_LABELS = { title: "What it is", url: "Link", note: "Note" };
const DETAIL_LABELS = { about: "Anything else", amazon_url: "Amazon list link" };
// [{label, value}] of what is saved now, for the box Reload shows: the fields the person typed in when there are any.
export function savedRows(kind, page, fresh, touched) {
  if (kind === "basics") {
    const pick = touched.length ? page.profile.filter(f => touched.includes(`f${f.field_id}`)) : filledFields(page.profile);
    return pick.map(f => ({ label: f.label, value: f.value ?? "" }));
  }
  const labels = kind === "details" ? DETAIL_LABELS : ITEM_LABELS;
  return Object.entries(labels).map(([name, label]) => ({ label, value: fresh[name] }));
}

// ---------------------------------------------------------------- markup
const renderButtons = label => `<div class="btn-row"><button class="btn primary" type="submit">${esc(label)}</button><button class="btn quiet" type="button" data-act="cancel">Cancel</button></div>`;
const renderHint = hint => (hint ? `<span class="hint">${esc(hint)}</span>` : "");
const renderEditButton = (show, label) => (show ? `<p><button class="btn" type="button" data-act="edit">${esc(label)}</button></p>` : "");

// the basics
const staleNow = f => isStale(f.updated_at, nowSec());
const renderStaleClass = f => (staleNow(f) ? "stale" : "");
const renderStaleNote = f => (staleNow(f) ? " · may be out of date" : "");
const renderFact = f => `<div class="${renderStaleClass(f)}"><dt>${esc(f.label)}</dt><dd>${esc(f.value)}</dd><dd class="when">updated ${monthLabel(f.updated_at)}${renderStaleNote(f)}</dd></div>`;
const renderFacts = profile => filledFields(profile).map(renderFact).join("");
const renderBasicsBody = profile => (filledFields(profile).length ? `<dl class="basics">${renderFacts(profile)}</dl>` : `<p class="muted">Nothing here yet.</p>`);
export const renderBasicsView = page => `
  <h2>The basics</h2>
  ${renderBasicsBody(page.profile)}
  ${renderEditButton(true, "Edit sizes and favorites")}`;

const renderFieldInput = f => `<label class="field"><span>${esc(f.label)}</span>${renderHint(f.hint)}<textarea class="short" name="f${esc(f.field_id)}" rows="2" maxlength="500">${esc(f.value)}</textarea></label>`;
const renderFieldInputs = profile => profile.map(renderFieldInput).join("");
export const renderBasicsForm = page => `
  <h2>The basics</h2>
  <div data-slot="msg"></div>
  <form data-form="save" novalidate>
    <p class="muted small">Leave a box empty to clear it. These carry over to next year.</p>
    ${renderFieldInputs(page.profile)}
    ${renderButtons("Save")}
  </form>`;

// Anything else and the Amazon list
const renderAbout = page => (page.about ? `<p class="about">${esc(page.about)}</p>` : `<p class="muted">Nothing here yet.</p>`);
const renderAmazon = page => (page.amazon_url ? `<h2>Amazon list</h2><p>${renderLink(page.amazon_url, "btn primary")}</p>` : "");
export const renderDetailsView = (page, readOnly) => `
  <h2>Anything else</h2>
  ${renderAbout(page)}
  ${renderAmazon(page)}
  ${renderEditButton(!readOnly, "Edit this and the Amazon link")}`;

export const renderDetailsForm = page => `
  <h2>Anything else</h2>
  <div data-slot="msg"></div>
  <form data-form="save" novalidate>
    <label class="field"><span>Anything else</span><span class="hint">Anything that would help someone choose a gift.</span>
      <textarea name="about" rows="5" maxlength="4000">${esc(page.about)}</textarea></label>
    <label class="field"><span>Amazon list link</span><span class="hint">Paste the link to an Amazon wish list, if there is one.</span>
      <input name="amazon_url" type="text" inputmode="url" autocapitalize="none" autocomplete="off" spellcheck="false" maxlength="2000" value="${esc(page.amazon_url)}"></label>
    ${renderButtons("Save")}
  </form>`;

// ideas
const renderNote = it => (it.note ? `<p class="note">${esc(it.note)}</p>` : "");
const renderItemLink = it => (it.url ? `<p>${renderLink(it.url)}</p>` : "");
const renderUp = (it, pos) => (pos > 0 ? `<button class="btn quiet" type="button" data-act="up" aria-label="Move ${esc(it.title)} up">↑ Up</button>` : "");
const renderDown = (it, pos, count) => (pos < count - 1 ? `<button class="btn quiet" type="button" data-act="down" aria-label="Move ${esc(it.title)} down">↓ Down</button>` : "");
const renderItemActions = (it, readOnly, pos, count) => (readOnly ? "" : `
  <div class="btn-row"><button class="btn quiet" type="button" data-act="edit">Edit</button><button class="btn quiet danger" type="button" data-act="delete">Delete</button>${renderUp(it, pos)}${renderDown(it, pos, count)}</div>`);
export const renderItemView = (it, readOnly, pos, count) => `
  <li data-id="${esc(it.id)}"><div data-slot="msg"></div>
    <p class="title">${esc(it.title)}</p>${renderNote(it)}${renderItemLink(it)}${renderItemActions(it, readOnly, pos, count)}</li>`;

const renderItemFields = it => `
  <label class="field"><span>What is it?</span><input name="title" type="text" maxlength="200" value="${esc(it.title)}"></label>
  <label class="field"><span>Link (if there is one)</span><span class="hint">Paste a web address.</span>
    <input name="url" type="text" inputmode="url" autocapitalize="none" autocomplete="off" spellcheck="false" maxlength="2000" value="${esc(it.url)}"></label>
  <label class="field"><span>Note (if you like)</span><span class="hint">Size, colour, where to find it.</span>
    <textarea class="short" name="note" rows="2" maxlength="1000">${esc(it.note)}</textarea></label>`;
export const renderItemForm = it => `
  <li data-id="${esc(it.id)}" class="editing"><div data-slot="msg"></div>
    <form data-form="save" novalidate>${renderItemFields(it)}${renderButtons("Save")}</form></li>`;
export const renderItemDelete = it => `
  <li data-id="${esc(it.id)}"><div data-slot="msg"></div>
    <p class="title">${esc(it.title)}</p>
    <p><strong>Delete this idea?</strong></p>
    <div class="btn-row"><button class="btn danger primary" type="button" data-act="delete-yes">Yes, delete it</button><button class="btn" type="button" data-act="delete-no">No, keep it</button></div></li>`;

// "Deleted · Undo", shown for UNDO_MS after a delete. One per deleted idea, each with its own timer.
export const UNDO_MS = 8000;
export const renderUndo = it => `
  <div class="msg ok undo" role="status" data-undo="${esc(it.id)}">Deleted · <button class="linkish" type="button" data-act="undo" aria-label="Undo delete of ${esc(it.title)}">Undo</button></div>`;

const renderAddButton = () => `<p><button class="btn primary wide" type="button" data-act="add-open">+ Add an idea</button></p>`;
const renderAddForm = () => `
  <h3>New idea</h3>
  <div data-slot="msg"></div>
  <form data-form="save" novalidate>${renderItemFields({})}
    <div class="btn-row"><button class="btn primary" type="submit">Add it</button><button class="btn quiet" type="button" data-act="cancel">Done</button></div>
  </form>`;
const renderBringOver = readOnly => (readOnly ? "" : `<p><button class="btn quiet wide" type="button" data-act="bring-over">Bring over last year's items</button></p>`);
const renderAddArea = readOnly => (readOnly ? "" : `<div data-unit="add">${renderAddButton()}</div>`);
const renderIdeas = readOnly => `
  <h2>Ideas</h2>
  <div data-slot="list-msg"></div>
  <div data-slot="undo"></div>
  <ul class="rows" data-list="items"></ul>
  <p class="muted" data-empty hidden>No ideas yet.</p>
  ${renderAddArea(readOnly)}
  ${renderBringOver(readOnly)}`;

// the 409 flow
// The server's message and a Reload button. `typing`: a form below holds the person's text. `act`: "reload" for a
// unit (its form, or an idea waiting on "Delete?"), "reload-list" for the order of the ideas.
const renderTypingNote = typing => (typing ? `<p class="small">Your typing is still in the form below. Reload shows what's saved now without clearing it.</p>` : "");
export const renderConflict = (message, typing, act = "reload") => `
  <div class="msg error conflict" role="alert">
    <p>${esc(message)}</p>
    ${renderTypingNote(typing)}
    <div class="btn-row"><button class="btn primary" type="button" data-act="${esc(act)}">Reload</button></div>
  </div>`;
const renderSavedRow = r => `<div><dt>${esc(r.label)}</dt><dd>${esc(r.value || "(empty)")}</dd></div>`;
const renderSavedRows = rows => rows.map(renderSavedRow).join("");
const renderReloadedHead = (rows, gone) => (gone
  ? `<p><strong>This idea was deleted on another phone.</strong> Press "Add it back" to keep yours as a new idea.</p>`
  : `<p><strong>Here's what's saved now:</strong></p><dl class="saved basics">${renderSavedRows(rows)}</dl>`);
export const renderReloaded = (rows, gone) => `
  <div class="msg warn conflict" role="status">
    ${renderReloadedHead(rows, gone)}
    <p>Your typing is still in the form below. Save it to replace what's saved, or use what's saved instead.</p>
    <div class="btn-row"><button class="btn" type="button" data-act="use-saved">${esc(gone ? "Let it go" : "Use what's saved")}</button></div>
  </div>`;

const renderClosedNote = readOnly => (readOnly ? `<p class="msg warn">This year is closed, so the ideas and "Anything else" can't change. Sizes and favorites still can.</p>` : "");
export const renderPage = (home, page, who, backHash, readOnly) => `
  <a class="back" href="${esc(backHash)}">← Back to ${esc(home.exchange.name)}</a>
  <section class="card head"><h1>${esc(page.person.name)}</h1>
    <p class="muted">${esc(home.exchange.name)} · ${esc(home.edition.label)}</p>${renderClosedNote(readOnly)}</section>
  ${renderWho(who)}
  <section class="card" data-unit="basics"></section>
  <section class="card" data-unit="details"></section>
  <section class="card" data-unit="ideas">${renderIdeas(readOnly)}</section>
  <p class="muted small" data-slot="last"></p>`;

// ---------------------------------------------------------------- the screen
const formValues = form => Object.fromEntries([...form.elements].filter(el => el.name).map(el => [el.name, el.value]));

export async function render(ctx) {
  const { view } = ctx;
  const slug = ctx.parts[1];
  const pid = ctx.parts[3];
  const editionId = /^[0-9]+$/.test(ctx.query.e ?? "") ? ctx.query.e : null;
  const path = pagePath(slug, pid, editionId);
  const [home, first] = await Promise.all([get(homePath(slug, editionId)), get(path)]);
  if (!ctx.alive()) return;
  applyAccent(home.exchange.accent_color);
  const readOnly = home.edition?.status === "closed";
  const backHash = `#/x/${q(slug)}${editionId ? `?e=${q(editionId)}` : ""}`;
  const base = `/api/x/${q(slug)}`;
  let page = first;

  view.innerHTML = renderPage(home, page, me(slug), backHash, readOnly);
  const list = view.querySelector("[data-list=items]");
  const listMsg = view.querySelector("[data-slot=list-msg]");
  const undoSlot = view.querySelector("[data-slot=undo]");
  const undoTimers = new Map(); // item id -> timer that removes its "Deleted · Undo" line
  const units = {
    basics: { kind: "basics", root: view.querySelector("[data-unit=basics]"), mode: "view" },
    details: { kind: "details", root: view.querySelector("[data-unit=details]"), mode: "view" },
    add: { kind: "add", root: view.querySelector("[data-unit=add]"), mode: "view" },
  };
  const items = new Map(); // item id -> { kind: "item", id, root: <li>, mode: "view" | "edit" | "delete", ... }

  // ---- drawing. Units being edited are never redrawn: their DOM holds the person's typing.
  function drawBasics() {
    const u = units.basics;
    u.root.hidden = page.profile.length === 0;
    if (u.mode === "view") u.root.innerHTML = renderBasicsView(page);
  }
  function drawDetails() {
    const u = units.details;
    if (u.mode === "view") u.root.innerHTML = renderDetailsView(page, readOnly);
  }
  function drawItems() {
    const nodes = page.items.map((it, pos) => {
      const open = items.get(it.id);
      if (open && open.mode !== "view") return open.root;
      const li = fromHtml(renderItemView, it, readOnly, pos, page.items.length);
      items.set(it.id, { kind: "item", id: it.id, root: li, mode: "view" });
      return li;
    });
    for (const u of items.values()) { // an idea deleted elsewhere while its form is open keeps its form, at the end
      if (u.mode === "edit" && !nodes.includes(u.root)) nodes.push(u.root);
    }
    for (const [id, u] of items) if (!nodes.includes(u.root)) items.delete(id);
    list.replaceChildren(...nodes);
    view.querySelector("[data-empty]").hidden = nodes.length > 0;
  }
  function drawAll() {
    drawBasics();
    drawDetails();
    drawItems();
    view.querySelector("[data-slot=last]").textContent = lastText(page);
  }
  async function refresh() {
    page = await get(path);
    if (ctx.alive()) drawAll();
    return page;
  }
  drawAll();

  // ---- who is saving
  function drawWho() {
    view.querySelector(".who")?.replaceWith(fromHtml(renderWho, me(slug)));
  }
  async function whoSaves() {
    const who = me(slug) ?? (await showPicker(slug, home.people));
    drawWho();
    return who;
  }
  if (!me(slug) && home.people.length) showPicker(slug, home.people).then(drawWho);

  // ---- units
  const formOf = u => u.root.querySelector("form[data-form=save]");
  const slotOf = u => u.root.querySelector("[data-slot=msg]");
  const itemData = id => page.items.find(i => i.id === id);
  const replaceRoot = (u, li) => { u.root.replaceWith(li); u.root = li; };

  function openForm(u) {
    if (u.kind === "basics") {
      u.root.innerHTML = renderBasicsForm(page);
      u.expected = stamps(page.profile);
    } else if (u.kind === "details") {
      u.root.innerHTML = renderDetailsForm(page);
      u.version = page.version;
    } else if (u.kind === "item") {
      const it = itemData(u.id);
      replaceRoot(u, fromHtml(renderItemForm, it));
      u.version = it.version;
    } else {
      u.root.innerHTML = renderAddForm();
    }
    u.mode = "edit";
    u.gone = false;
    u.orig = formValues(formOf(u));
    formOf(u).querySelector("input, textarea")?.focus();
  }

  function closeForm(u) {
    u.mode = "view";
    if (u.kind === "add") u.root.innerHTML = renderAddButton();
    else if (u.kind === "item" && u.gone) { items.delete(u.id); u.root.remove(); }
    else drawAll();
  }

  function showFailure(u, err) {
    const slot = slotOf(u);
    if (err?.status === 409 || (err?.status === 404 && u.kind === "item")) {
      slot.innerHTML = renderConflict(err.status === 404 ? "This idea was changed or deleted on another phone." : err.error, true);
    } else {
      slot.innerHTML = renderError(err?.error ?? "Something went wrong. Try again.");
    }
    slot.scrollIntoView({ block: "nearest" });
  }

  async function save(u) {
    const form = formOf(u);
    const slot = slotOf(u);
    slot.innerHTML = "";
    const who = await whoSaves();
    if (!who) {
      slot.innerHTML = renderError("Tap your name (or Just looking) first, so your name goes on the change.");
      return;
    }
    const cur = formValues(form);
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      if (u.kind === "basics") {
        const body = profileBody(cur, u.orig, u.expected);
        if (Object.keys(body.values).length) await send("PUT", `${base}/people/${q(pid)}/profile`, { ...body, updated_by: who.name });
      } else if (u.kind === "details") {
        await send("PUT", `${base}/people/${q(pid)}/details`, {
          edition_id: page.edition_id, about: cur.about, amazon_url: cur.amazon_url, version: u.version, updated_by: who.name,
        });
      } else if (u.kind === "item" && !u.gone) {
        await send("PATCH", `${base}/items/${q(u.id)}`, {
          title: cur.title, url: cur.url, note: cur.note, version: u.version, updated_by: who.name,
        });
      } else {
        await send("POST", `${base}/people/${q(pid)}/items`, {
          edition_id: page.edition_id, title: cur.title, url: cur.url, note: cur.note, updated_by: who.name,
        });
      }
    } catch (err) {
      showFailure(u, err);
      return;
    } finally {
      button.disabled = false;
    }
    if (u.kind === "add") {
      form.reset();
      u.orig = formValues(form);
      slot.innerHTML = `<p class="msg ok" role="status">Added. Add another, or press Done.</p>`;
      form.elements.title.focus();
    } else if (u.kind === "item" && u.gone) {
      items.delete(u.id);
      u.root.remove();
    } else {
      u.mode = "view";
    }
    toast(u.kind === "add" || u.gone ? "Added" : "Saved");
    await refreshQuietly(slot);
  }

  // After a change the page is fetched again; if that fails the change still happened, so say only that.
  async function refreshQuietly(slot, done = "Saved.") {
    try {
      await refresh();
    } catch {
      if (slot.isConnected) slot.innerHTML = renderError(`${done} The page couldn't refresh: reload it to see the latest.`);
    }
  }

  // Reload after a 409: fetch, show what's saved, keep the form as typed until the person chooses.
  async function reload(u) {
    const slot = slotOf(u);
    try {
      await refresh();
    } catch (err) {
      slot.innerHTML = renderError(err?.error ?? "Couldn't reload. Try again.");
      return;
    }
    if (u.mode === "delete") { // nothing typed: show the idea as it is now
      u.mode = "view";
      drawItems();
      return;
    }
    const form = formOf(u);
    const fresh = freshValues(u.kind, page, u.id);
    if (fresh === null) { // the idea is gone: its form stays, and saving adds it back
      u.gone = true;
      slot.innerHTML = renderReloaded([], true);
      form.querySelector("button[type=submit]").textContent = "Add it back";
      return;
    }
    const merged = mergeFresh(formValues(form), u.orig, fresh);
    for (const [name, value] of Object.entries(merged.set)) form.elements[name].value = value;
    u.orig = merged.orig;
    if (u.kind === "basics") u.expected = stamps(page.profile);
    else if (u.kind === "details") u.version = page.version;
    else u.version = itemData(u.id).version;
    slot.innerHTML = renderReloaded(savedRows(u.kind, page, fresh, merged.touched), false);
    form.querySelector("button[type=submit]").textContent = "Save mine instead";
  }

  async function remove(u) {
    const slot = slotOf(u);
    slot.innerHTML = "";
    try {
      await send("DELETE", `${base}/items/${q(u.id)}`, { version: u.version });
    } catch (err) {
      if (err?.status !== 404) { // 404: already deleted elsewhere, which is what was asked
        if (err?.status === 409) slot.innerHTML = renderConflict(err.error, false);
        else slot.innerHTML = renderError(err?.error ?? "Something went wrong. Try again.");
        return;
      }
    }
    items.delete(u.id);
    u.root.remove();
    offerUndo(itemData(u.id) ?? { id: u.id, title: "this idea" });
    await refreshQuietly(listMsg, "Deleted.");
  }

  function dropUndo(id) {
    clearTimeout(undoTimers.get(id));
    undoTimers.delete(id);
    undoSlot.querySelector(`[data-undo="${id}"]`)?.remove();
  }
  function offerUndo(it) {
    undoSlot.append(fromHtml(renderUndo, it));
    undoTimers.set(it.id, setTimeout(() => dropUndo(it.id), UNDO_MS));
  }
  async function bringOver(btn) {
    listMsg.innerHTML = "";
    const who = await whoSaves();
    if (!who) {
      listMsg.innerHTML = renderError("Tap your name (or Just looking) first, so your name goes on the change.");
      return;
    }
    btn.disabled = true;
    let copied;
    try {
      ({ copied } = await send("POST", `${base}/people/${q(pid)}/bring-over`, { edition_id: page.edition_id, updated_by: who.name }));
    } catch (err) {
      listMsg.innerHTML = renderError(err?.status === 400 ? "There is nothing new to bring over from last year." : (err?.error ?? "Something went wrong. Try again."));
      return;
    } finally {
      btn.disabled = false;
    }
    toast(copied === 1 ? "Brought over 1 idea" : `Brought over ${copied} ideas`);
    await refreshQuietly(listMsg, "Brought over.");
  }
  async function undo(id, btn) {
    btn.disabled = true;
    try {
      await send("POST", `${base}/items/${q(id)}/restore`, {});
    } catch (err) {
      dropUndo(id);
      listMsg.innerHTML = renderError(err?.status === 404 ? "Too late to undo: that idea is gone for good." : (err?.error ?? "Couldn't undo. Try again."));
      return;
    }
    dropUndo(id);
    toast("Restored");
    await refreshQuietly(listMsg, "Restored.");
  }

  async function move(u, step) {
    const ids = page.items.map(i => i.id);
    const at = ids.indexOf(u.id);
    if (at < 0 || at + step < 0 || at + step >= ids.length) return;
    [ids[at], ids[at + step]] = [ids[at + step], ids[at]];
    listMsg.innerHTML = "";
    try {
      await send("PUT", `${base}/people/${q(pid)}/items/order`, { edition_id: page.edition_id, ids });
    } catch (err) {
      if (err?.status === 409) listMsg.innerHTML = renderConflict(err.error, false, "reload-list");
      else listMsg.innerHTML = renderError(err?.error ?? "Something went wrong. Try again.");
      return;
    }
    await refreshQuietly(listMsg, "Moved.");
    list.querySelector(`li[data-id="${u.id}"] [data-act=${step < 0 ? "up" : "down"}]`)?.focus();
  }

  function unitOf(el) {
    const li = el.closest("li[data-id]");
    if (li && list.contains(li)) return items.get(Number(li.dataset.id)) ?? null;
    const name = el.closest("[data-unit]")?.dataset.unit;
    return units[name] ?? null;
  }

  view.addEventListener("click", async e => {
    const btn = e.target.closest("button[data-act]");
    if (!btn || !view.contains(btn)) return;
    const act = btn.dataset.act;
    if (act === "notme") {
      if (await showPicker(slug, home.people)) drawWho();
      return;
    }
    if (act === "reload-list") {
      listMsg.innerHTML = "";
      await refreshQuietly(listMsg, "");
      return;
    }
    if (act === "bring-over") {
      bringOver(btn);
      return;
    }
    if (act === "undo") {
      undo(Number(btn.closest("[data-undo]").dataset.undo), btn);
      return;
    }
    const u = unitOf(btn);
    if (!u) return;
    if (act === "edit" || act === "add-open") openForm(u);
    else if (act === "cancel" || act === "use-saved") closeForm(u);
    else if (act === "reload") reload(u);
    else if (act === "delete") {
      const it = itemData(u.id);
      u.mode = "delete";
      u.version = it.version;
      replaceRoot(u, fromHtml(renderItemDelete, it));
      u.root.querySelector("[data-act=delete-no]").focus();
    } else if (act === "delete-no") {
      u.mode = "view";
      drawItems();
    } else if (act === "delete-yes") remove(u);
    else if (act === "up") move(u, -1);
    else if (act === "down") move(u, 1);
  });

  view.addEventListener("submit", e => {
    const form = e.target.closest("form[data-form=save]");
    if (!form) return;
    e.preventDefault();
    const u = unitOf(form);
    if (u && u.mode === "edit") save(u);
  });
}
