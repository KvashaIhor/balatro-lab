// Seed Finder: the player enters what a run showed at its start; the server scans every seed for it.

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const SUITS = [["S", "♠"], ["H", "♥"], ["C", "♣"], ["D", "♦"]];  // rows, in the game's hand order
const RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"];
const RANK_TEXT = { T: "10" };
const RANK_VALUE = Object.fromEntries("23456789TJQKA".split("").map((r, i) => [r, i + 2]));
const SUIT_SYMBOL = Object.fromEntries(SUITS);
const ART_KIND = { Joker: "jokers", Tarot: "tarots", Planet: "planets", Spectral: "spectrals" };

const state = { meta: null, hand: new Set(), boss: null, small_tag: null, big_tag: null, voucher: null, timer: null,
  decks: null, projections: new Map() };

function el(tag, cls = "", html = "") {
  const e = document.createElement(tag);
  e.className = cls;
  e.innerHTML = html;
  return e;
}

function art(kind, name) {
  return state.meta.art[kind]?.[name] || "";
}

function miniCard(code, small = false) {
  const [s, r] = code;
  const e = el(small ? "span" : "button", `mini suit-${s} ${small ? "small" : ""}`,
    `<span class="r">${RANK_TEXT[r] || r}<br>${SUIT_SYMBOL[s]}</span><span class="s">${SUIT_SYMBOL[s]}</span>`);
  e.title = `${RANK_TEXT[r] || r}${SUIT_SYMBOL[s]}`;
  return e;
}

function save() {
  try {
    localStorage.setItem("seed-finder", JSON.stringify({ hand: [...state.hand], boss: state.boss, small_tag: state.small_tag,
      big_tag: state.big_tag, voucher: state.voucher, shop: [$("#shop-1").value, $("#shop-2").value], no_o: $("#no-o").checked }));
  } catch { /* storage unavailable: the form just won't be remembered */ }
}

function restore() {
  try {
    const s = JSON.parse(localStorage.getItem("seed-finder") || "null");
    if (!s) return;
    state.hand = new Set(s.hand);
    Object.assign(state, { boss: s.boss, small_tag: s.small_tag, big_tag: s.big_tag, voucher: s.voucher });
    [$("#shop-1").value, $("#shop-2").value] = s.shop || ["", ""];
    $("#no-o").checked = s.no_o !== false;
  } catch { /* nothing saved */ }
}

// ---- the form ------------------------------------------------------------------------------------
function buildCardGrid() {
  const grid = $("#card-grid");
  grid.replaceChildren();
  for (const [s] of SUITS) {
    for (const r of RANKS) {
      const code = s + r;
      const b = miniCard(code);
      b.type = "button";
      b.setAttribute("aria-pressed", String(state.hand.has(code)));
      b.addEventListener("click", () => {
        if (state.hand.has(code)) state.hand.delete(code);
        else if (state.hand.size < 8) state.hand.add(code);
        b.setAttribute("aria-pressed", String(state.hand.has(code)));
        $("#hand-count").textContent = `${state.hand.size}/8`;
        save();
      });
      grid.append(b);
    }
  }
  $("#hand-count").textContent = `${state.hand.size}/8`;
}

// One-of-many picker with art; clicking the picked item again clears it.
function picker(sel, field, names, kind, label = false) {
  const row = $(sel);
  const buttons = names.map((name) => {
    const b = el("button", "pick", `<img alt="" src="${art(kind, name)}">${label ? `<span>${esc(name.replace(/^The /, ""))}</span>` : ""}`);
    b.type = "button";
    b.title = name;
    b.addEventListener("click", () => {
      state[field] = state[field] === name ? null : name;
      buttons.forEach((x) => x.setAttribute("aria-pressed", String(x.title === state[field])));
      save();
    });
    b.setAttribute("aria-pressed", String(state[field] === name));
    return b;
  });
  row.replaceChildren(...buttons);
}

function observation() {
  const shop = [$("#shop-1").value.trim(), $("#shop-2").value.trim()].filter(Boolean);
  return { hand: [...state.hand], boss: state.boss, small_tag: state.small_tag, big_tag: state.big_tag,
    voucher: state.voucher, shop: shop.length === 2 ? shop : null, no_o: $("#no-o").checked };
}

// ---- what a seed shows -----------------------------------------------------------------------------
function item(kind, name, cls = "", note = "") {
  const e = el("span", `item ${cls}`, `<img alt="" src="${art(kind, name)}"><span>${esc(name)}${note ? ` (${esc(note)})` : ""}</span>`);
  return e;
}

function openingEl(o, wrong = []) {
  const box = el("div", "opening");
  const row = (label, ...items) => {
    const k = el("span", "k", label + (wrong.some((w) => label.toLowerCase().includes(w.replace("_", " "))) ? " ✗" : ""));
    const v = el("span", "v");
    v.append(...items);
    box.append(k, v);
  };
  row("Skip tags", item("tags", o.small_tag, "tag"), item("tags", o.big_tag, "tag"));
  row("Boss", item("chips", o.boss, "chip"));
  row("First hand", ...[...o.first_hand].sort(byRank).map((c) => miniCard(c, true)));
  row("Voucher", item("vouchers", o.voucher));
  row("Shop", ...o.shop_cards.map((c) => item(ART_KIND[c.type] || "jokers", c.name, "", c.edition || "")));
  row("Packs", ...o.packs.map((p) => item("boosters", p)));
  return box;
}

async function check(seed) {
  const out = $("#check-out");
  out.textContent = "…";
  const res = await fetch(`/api/seed/opening?seed=${encodeURIComponent(seed)}`);
  const o = await res.json();
  if (!res.ok) return void (out.textContent = o.error);
  out.replaceChildren(el("div", "found", `<div class="seed">${esc(o.seed)}</div>`), openingEl(o), projectionEl(o.seed));
}

// ---- a seed's run, ante by ante (balatro/projection.py) ------------------------------------------------
// Along one path: every blind played, nothing bought, no rerolls; each shop's packs opened in order.
async function deckNames() {
  if (!state.decks) {
    try {
      state.decks = (await (await fetch("/api/meta")).json()).decks;
    } catch {
      state.decks = ["Red Deck"];
    }
  }
  return state.decks;
}

function cardsEl(codes) {
  const row = el("div", "proj-cards");
  row.append(...codes.map((c) => miniCard(c, true)));
  return row;
}

function offerEl(c, price = true) {
  const note = [c.edition, price && c.price != null ? `$${c.price}` : ""].filter(Boolean).join(", ");
  if (c.type === "Playing card") {
    const m = miniCard(c.code, true);
    m.title += [c.enhancement, c.edition, c.seal && `${c.seal} Seal`, "the Lab's own draw"].filter(Boolean).map((x) => ` · ${x}`).join("");
    return m;
  }
  return item(ART_KIND[c.type] || "jokers", c.name, "", note);
}

const byRank = (a, b) => RANK_VALUE[b[1]] - RANK_VALUE[a[1]] || "SHCD".indexOf(a[0]) - "SHCD".indexOf(b[0]);

function blindEl(b) {
  const box = el("div", "proj-blind");
  box.append(el("div", "proj-title", `${esc(b.name)} · score at least ${b.chips.toLocaleString()} · first hand`),
    cardsEl([...b.hand].sort(byRank)));                 // as the game sorts it; the draws stay in draw order
  const draws = el("details", "proj-draws");
  draws.append(el("summary", "", `The next ${b.draws.length} cards, in the order they're drawn`), cardsEl(b.draws));
  box.append(draws);
  const shop = el("div", "proj-shop");
  shop.append(el("span", "k", "Shop"), ...b.shop.cards.map((c) => offerEl(c)));
  if (b.shop.voucher) shop.append(item("vouchers", b.shop.voucher));
  for (const p of b.shop.packs) {
    const pack = el("span", "proj-pack");
    pack.title = `${p.name}: choose ${p.choose}${p.exact ? "" : " (the Lab's own draw: Standard packs aren't in the game model)"}`;
    pack.append(item("boosters", p.name, "", `$${p.price}`), ...p.cards.map((c) => offerEl(c, false)));
    shop.append(pack);
  }
  box.append(shop);
  return box;
}

function anteEl(a) {
  const box = el("details", "proj-ante");
  box.open = a.ante === 1;
  box.append(el("summary", "", `Ante ${a.ante} · ${esc(a.boss)}`));
  const head = el("div", "proj-head");
  head.append(item("chips", a.boss, "chip"), ...a.tags.filter(Boolean).map((t) => item("tags", t, "tag")));
  if (a.voucher) head.append(item("vouchers", a.voucher));
  box.append(head, ...a.blinds.map(blindEl));
  return box;
}

function projectionEl(seed) {
  const box = el("div", "projection");
  const bar = el("div", "proj-bar");
  const go = el("button", "btn blue small", "Projection");
  go.type = "button";
  const deck = document.createElement("select");
  const antes = document.createElement("select");
  antes.append(...[1, 2, 3, 4, 5, 6, 7, 8].map((n) => Object.assign(document.createElement("option"), { value: n, textContent: `${n} ante${n > 1 ? "s" : ""}` })));
  antes.value = "4";
  deckNames().then((names) => {
    deck.append(...names.map((n) => Object.assign(document.createElement("option"), { value: n, textContent: n })));
    deck.value = names.includes("Red Deck") ? "Red Deck" : names[0];
  });
  const out = el("div", "proj-out");
  go.addEventListener("click", async () => {
    out.textContent = "…";
    const res = await fetch(`/api/seed/projection?seed=${encodeURIComponent(seed)}&deck=${encodeURIComponent(deck.value)}&antes=${antes.value}`);
    const p = await res.json().catch(() => ({ error: "The server doesn't know projections yet: restart it." }));
    if (!res.ok) return void (out.textContent = p.error || "The server doesn't know projections yet: restart it.");
    out.replaceChildren(el("p", "proj-note", `Assumes ${esc(p.path)}. ${esc(p.note)}`), ...p.antes.map(anteEl));
  });
  bar.append(go, deck, antes);
  box.append(bar, out);
  return box;
}

// ---- the search ----------------------------------------------------------------------------------
function duration(s) {
  if (s == null) return "—";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : m ? `${m}m ${s % 60}s` : `${s}s`;
}

// ETA from the last ~30 s of progress, not the average since the start (which other work on the
// machine can drag down).
const samples = [];
function recentRate(st) {
  if (st.status !== "running") return void (samples.length = 0);
  samples.push([st.elapsed, st.scanned]);
  while (samples.length > 2 && samples[samples.length - 1][0] - samples[0][0] > 30) samples.shift();
  const [t0, n0] = samples[0], [t1, n1] = samples[samples.length - 1];
  return t1 - t0 >= 5 && n1 > n0 ? (n1 - n0) / (t1 - t0) : st.rate;
}

function showStatus(st) {
  const running = st.status === "running";
  if (running) {
    st.rate = recentRate(st) || st.rate;
    st.eta = st.rate ? (st.total - st.scanned) / st.rate : st.eta;
  }
  $("#find").disabled = running;
  $("#stop").disabled = !running;
  $("#bar-fill").style.width = `${st.percent || 0}%`;
  if (st.status === "idle") return;
  if (st.phase === "table" && st.status === "done") {
    $("#progress-text").textContent = `Found instantly in the precomputed table (${duration(st.elapsed)}).`;
  }
  const parts = [`${st.status === "running" ? (st.phase === "table" ? "Looking it up in the table" : "Searching") : st.status[0].toUpperCase() + st.status.slice(1)}`,
    `${(st.percent || 0).toFixed(2)}% of ${st.total >= 1e12 ? (st.total / 1e12).toFixed(2) + " trillion" : (st.total / 1e9).toFixed(1) + " billion"} seeds`];
  if (running) parts.push(`${(st.rate / 1e6).toFixed(0)} M seeds/s`, `ETA ${duration(st.eta)}`);
  parts.push(`elapsed ${duration(st.elapsed)}`, `${st.found.length} seed${st.found.length === 1 ? "" : "s"} fit`);
  if (!(st.phase === "table" && st.status === "done")) $("#progress-text").textContent = parts.join(" · ");
  const results = $("#results");
  results.replaceChildren(...st.found.map((c) => {
    const box = el("div", "found", `<div class="seed">${esc(c.seed)} <button class="btn blue" type="button">Copy</button></div>`);
    box.querySelector("button").addEventListener("click", () => navigator.clipboard?.writeText(c.seed));
    if (!state.projections.has(c.seed)) state.projections.set(c.seed, projectionEl(c.seed));   // kept across polls
    box.append(openingEl(c.opening), state.projections.get(c.seed));
    return box;
  }));
  if (st.rejected.length) {
    results.append(el("div", "rejected", `Matched the hand${st.obs.boss ? " and boss" : ""} but not the rest: ` +
      st.rejected.map((c) => `${esc(c.seed)} (${esc(c.wrong.join(", "))})`).join(", ")));
  }
  if (!running && st.status === "done" && !st.found.length) {
    results.append(el("div", "rejected", "No seed fits. Check the cards and boss, and whether the seed could contain an O."));
  }
}

async function tableStatus() {
  const t = await (await fetch("/api/seed/table")).json();
  $("#table-text").textContent = !t.built ? "No precomputed table yet: every search is a full scan."
    : `Precomputed table: ${t.segments}/${t.segments_total} parts built, finds about ${t.success.toFixed(0)}% of seeds in seconds ` +
      "when you enter the hand, boss and both tags (with the voucher in about a second, without it about half a minute); " +
      "otherwise the full scan runs.";
}

async function poll() {
  const st = await (await fetch("/api/seed/status")).json();
  showStatus(st);
  clearTimeout(state.timer);
  if (st.status === "running") state.timer = setTimeout(poll, 1000);
}

async function find() {
  $("#error").textContent = "";
  if (state.hand.size !== 8) return void ($("#error").textContent = "Pick the 8 cards of the first hand.");
  const res = await fetch("/api/seed/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(observation()) });
  const st = await res.json();
  if (!res.ok) return void ($("#error").textContent = st.error);
  showStatus(st);
  poll();
}

function buildForm() {
  buildCardGrid();
  picker("#boss-pick", "boss", state.meta.bosses, "chips", true);
  picker("#small-pick", "small_tag", state.meta.tags, "tags");
  picker("#big-pick", "big_tag", state.meta.tags, "tags");
  picker("#voucher-pick", "voucher", state.meta.vouchers, "vouchers");
}

async function init() {
  state.meta = await (await fetch("/api/seed/meta")).json();
  restore();
  buildForm();
  $("#shop-names").replaceChildren(...state.meta.shop.map((n) => Object.assign(document.createElement("option"), { value: n })));
  for (const id of ["#shop-1", "#shop-2", "#no-o"]) $(id).addEventListener("change", save);
  $("#find").addEventListener("click", find);
  $("#stop").addEventListener("click", async () => showStatus(await (await fetch("/api/seed/stop", { method: "POST" })).json()));
  $("#clear").addEventListener("click", () => {
    Object.assign(state, { hand: new Set(), boss: null, small_tag: null, big_tag: null, voucher: null });
    $("#shop-1").value = $("#shop-2").value = "";
    save();
    buildForm();
  });
  $("#check-form").onsubmit = (e) => { e.preventDefault(); check($("#check-seed").value.trim()); };
  $("#test-seeds").replaceChildren(...state.meta.test_seeds.map((s) => {
    const b = el("button", "btn", esc(s));
    b.type = "button";
    b.addEventListener("click", () => { $("#check-seed").value = s; check(s); });
    return b;
  }));
  poll();
  tableStatus();
  setInterval(tableStatus, 60000);
}

init();
