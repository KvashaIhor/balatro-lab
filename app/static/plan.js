// Seed Planner: plan a seed's run on the server and show the plan step by step, with the game's own cards.
import { art, view, esc, el, cardEl, itemEl, jokerEl } from "./cards.js";

const $ = (sel) => document.querySelector(sel);
const fmt = (n) => (n % 1 ? n.toFixed(1) : Math.round(n).toLocaleString("en-US"));
const ICON = { play: "▶", discard: "✕", use: "✦", pick: "✦", buy: "$", open: "▣", sell: "$", reroll: "↻", order: "⇄",
  "cash out": "$", "boss reroll": "↻", saved: "♥", "skip pack": "↷" };
const SUIT = { S: "♠", H: "♥", C: "♣", D: "♦" };
const state = { timer: null, result: null, settled: 0, synced: false, bosses: {} };
// Sizes relative to the game's (a card is 164 x 219 there).
const Z = { hand: 0.42, item: 0.42, small: 0.3, tiny: 0.22 };

function duration(s) {
  s = Math.round(s || 0);
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
}

// Suit symbols in red or dark, like the cards.
function suits(text) {
  return esc(text).replace(/(10|[2-9JQKA])([♠♣♥♦])/g, (_, r, s) => `<span class="cardref ${"♥♦".includes(s) ? "red" : "dark"}">${r}${s}</span>`);
}

const cardName = (c) => (c.label === "Stone" ? "Stone" : c.label.slice(0, -1) + SUIT[c.label.slice(-1)]);
const consumableKind = (name) => (art.tarots?.[name] ? "Tarot" : art.planets?.[name] ? "Planet" : "Spectral");

function outcome(r) {
  return r.won ? `Wins the run, then reaches ante ${r.ante}` : `Reaches ante ${r.ante}`;
}

// ---- the game's art, scaled --------------------------------------------------------------------
function sprite(e, z, cls = "") {
  const w = el("span", `sprite ${cls} ${e.classList.contains("pack-art") ? "pack" : ""}`);
  w.style.setProperty("--z", z);
  const tip = e.dataset.tip || e.querySelector("img")?.alt;
  if (tip) w.title = tip.replace("</b>", ": ").replace(/<[^>]+>/g, "").replace(/: $/, "");
  w.append(e);
  return w;
}

function priced(o, z, cls = "") {
  const w = el("span", `priced ${cls}`);
  if (o.price !== undefined) w.append(el("span", `price ${o.price === 0 ? "free" : ""}`, o.price === 0 ? "Free" : `$${o.price}`));
  w.append(sprite(itemEl(o), z));
  return w;
}

function row(items, cls = "") {
  const r = el("div", `row ${cls}`);
  r.append(...items.filter(Boolean));
  return r;
}

// The hand as the game shows it (sorted by rank), the cards to select lifted, positions underneath.
function handEl(st) {
  const box = el("div", `hand ${st.kind}`);
  st.hand.forEach((c, k) => {
    const picked = st.picked.includes(k);
    const slot = el("div", `slot ${picked ? "picked" : ""}`);
    slot.append(sprite(cardEl(c), Z.hand), el("span", "pos", String(k + 1)));
    if (c.face_down) slot.append(el("span", "hidden-name", suits(cardName(c))));
    box.append(slot);
  });
  return box;
}

function scoreEl(st) {
  return el("div", "score-row",
    `<span class="hand-name">${esc(st.hand_name)} <small>lvl.${st.level}</small></span>` +
    `<span class="chips">${fmt(st.chips)}</span><span class="x">×</span><span class="mult">${fmt(st.mult)}</span>` +
    `<span class="eq">= <b>${fmt(st.total)}</b></span>` +
    `<span class="round ${st.round_score >= st.target ? "beaten" : ""}">round score ${fmt(st.round_score)} of ${fmt(st.target)}</span>`);
}

function detail(st, bought) {
  switch (st.kind) {
    case "play": { const d = el("div", "detail"); d.append(handEl(st), scoreEl(st)); return d; }
    case "discard": return handEl(st);
    case "use": return row([sprite(itemEl({ kind: consumableKind(st.item.name), name: st.item.name }), Z.item),
      ...st.targets.map((c) => sprite(cardEl(c), Z.small))]);
    case "buy": return row([priced(st.item, Z.small), ...(st.targets || []).map((c) => sprite(cardEl(c), Z.small))]);
    case "reroll": return row([el("span", "row-label", "New cards"), ...st.offers.map((o) => priced(o, Z.small, bought.has(o.name) ? "bought" : ""))]);
    case "open": return row([sprite(itemEl({ kind: "Pack", name: st.pack.name }), Z.small), el("span", "arrow", "→"),
      ...st.pack.cards.map((o) => sprite(itemEl(o), Z.small)),
      st.picks > 1 ? el("span", "row-label", `choose ${st.picks}`) : null]);
    case "pick": return st.item?.kind ? row([sprite(itemEl(st.item), Z.item), ...(st.targets || []).map((c) => sprite(cardEl(c), Z.small))]) : null;
    case "sell": return row([sprite(itemEl(st.item), Z.small, "sold")]);
    case "order": return row(st.jokers.map((j) => sprite(jokerEl(j), Z.small)));
    default: return null;
  }
}

function stepEl(st, bought) {
  const e = el("li", `step s-${st.kind.replace(" ", "-")}`,
    `<div class="line"><span class="icon">${ICON[st.kind] || "·"}</span><span class="text">${suits(st.text)}</span></div>`);
  const d = st.hand || st.item || st.pack || st.offers || st.jokers ? detail(st, bought) : null;
  if (d) e.append(d);
  return e;
}

// What the player has going in: money, jokers, consumables.
function contextEl(sec) {
  const c = el("div", "context");
  if (sec.money === undefined) return c;                      // a plan saved before steps carried state
  c.append(el("span", "money", `$${sec.money}`));
  if (sec.jokers.length) c.append(row(sec.jokers.map((j) => sprite(jokerEl(j), Z.tiny)), "tiny"));
  if (sec.consumables.length) c.append(row(sec.consumables.map((o) => sprite(itemEl(o), Z.tiny)), "tiny"));
  return c;
}

function offersEl(sec, bought) {
  const o = sec.offers;
  const mark = (x) => priced(x, Z.small, bought.has(x.name) ? "bought" : "");
  return row([el("span", "row-label", "In the shop"), ...o.cards.map(mark), el("span", "gap"), ...o.vouchers.map(mark),
    el("span", "gap"), ...o.packs.map(mark)], "offers");
}

function sectionEl(sec) {
  const e = el("article", `section ${sec.kind}`);
  const head = el("div", "sec-head");
  const bought = new Set(sec.steps.filter((s) => s.kind === "buy" && s.item).map((s) => s.item.name));
  if (sec.kind === "blind" && sec.blind) {
    const b = sec.blind;
    const chip = art.chips?.[b.name] ? b.name : ["Small Blind", "Big Blind", "Small Blind"][b.kind];
    e.style.setProperty("--accent", art.chip_colours?.[chip] || "#0092ff");
    const effect = b.kind === 2 && state.bosses[b.name];
    head.innerHTML = `<img class="chip" alt="" src="${art.chips?.[chip] || ""}"><div class="title"><h3>${esc(b.name)}</h3>` +
      `<p>Score at least <b class="target">${fmt(b.chips)}</b> · reward <span class="money">${"$".repeat(b.reward)}</span></p>` +
      (effect ? `<p class="effect">${esc(effect)}</p>` : "") + "</div>";
  } else if (sec.kind === "skip") {
    head.innerHTML = `<img class="tag" alt="" src="${art.tags?.[sec.tag] || ""}"><div class="title"><h3>${esc(sec.title)}</h3>` +
      `<p>Skip it on the blind select screen; the tag's reward comes now or at its trigger.</p></div>`;
  } else {
    head.innerHTML = `<div class="title"><h3>${esc(sec.title)}</h3></div>`;
  }
  head.append(contextEl(sec));
  e.append(head);
  if (sec.kind === "shop" && sec.offers) e.append(offersEl(sec, bought));
  if (sec.steps.length) {
    const ol = el("ol", "steps");
    ol.append(...sec.steps.map((st) => stepEl(st, bought)));
    e.append(ol);
  } else if (sec.kind === "shop") {
    e.append(el("p", "quiet", "Leave without buying."));
  }
  return e;
}

// Sections with an "Ante N" divider where a new ante starts.
function sectionsEl(sections) {
  const out = [];
  let ante = null;
  for (const sec of sections) {
    if (sec.ante !== ante) {
      ante = sec.ante;
      out.push(el("h2", "ante-divider", `Ante ${ante}`));
    }
    out.push(sectionEl(sec));
  }
  return out;
}

function endCard(title, text = "") {
  const e = el("article", "section end", `<div class="sec-head"><div class="title"><h3>${esc(title)}</h3>${text ? `<p>${esc(text)}</p>` : ""}</div></div>`);
  return e;
}

// While the search runs: the steps every line still in the search agrees on. They won't change.
function renderSettled(sections) {
  const count = sections.reduce((n, sec) => n + 1 + sec.steps.length, 0);
  if (count === state.settled) return;
  state.settled = count;
  $("#plan-steps").replaceChildren(...sectionsEl(sections),
    endCard("Still searching from here…", "The steps above are settled: every line the planner is still considering starts this way."));
}

// The form shows the plan on screen (running, or the last one made).
function showForm(plan) {
  $("#seed").value = plan.seed;
  $("#deck").value = plan.deck;
  $("#max-ante").value = String(plan.max_ante);
  if (plan.effort) $("#effort").value = plan.effort;
  view.deckBack = plan.deck;
}

function render(res) {
  state.result = res;
  showForm(res);
  $("#summary").hidden = false;
  $("#headline").textContent = `${res.seed}: ${outcome(res)}`;
  $("#compare").textContent = `The plain strategy on this seed: ${outcome(res.base).toLowerCase()}. ` +
    `${res.rollouts} test runs in ${duration(res.seconds)}.` + (res.left_settled
      ? " The search's own line fell behind the plain strategy by the end, so this plan is the plain strategy's run; the steps shown while it searched no longer apply."
      : "");
  const last = res.steps[res.steps.length - 1];
  const end = !res.won || res.ante <= res.max_ante
    ? [endCard(res.won && res.ante > res.max_ante ? "Plan horizon reached" : `The run ends here (ante ${last?.ante ?? res.ante})`)] : [];
  $("#plan-steps").replaceChildren(...sectionsEl(res.steps), ...end);
  $("#notes").hidden = false;
  $("#exact").replaceChildren(...res.exact.map((t) => Object.assign(document.createElement("li"), { textContent: t })));
  $("#simulated").replaceChildren(...res.simulated.map((t) => Object.assign(document.createElement("li"), { textContent: t })));
}

function showStatus(st) {
  const running = st.status === "running";
  $("#go").disabled = running;
  $("#stop").disabled = !running;
  const p = st.progress;
  const limit = p?.limit;                                   // none for a thorough search
  $("#bar-fill").style.width = `${running ? (limit ? Math.min(100, 100 * st.elapsed / limit) : 100) : st.status === "done" ? 100 : 0}%`;
  $("#bar-fill").classList.toggle("open-ended", running && !limit);
  if (running) {
    $("#progress-text").textContent = p
      ? `Decision ${p.decision} · ${p.rollouts.toLocaleString("en-US")} test runs · best line so far ${p.won ? "wins and " : ""}reaches ante ${p.ante}` +
        ` (plain strategy: ${p.base_progress < 3 ? "dies in ante 1" : `ante ${Math.floor(p.base_progress / 3) + 1}`}) · ${duration(st.elapsed)}${limit ? ` of ${duration(limit)}` : ""}`
      : `Starting · ${duration(st.elapsed)}`;
    if (p?.steps?.length) renderSettled(p.steps);
  } else if (st.status === "done") {
    $("#progress-text").textContent = `Planned ${st.seed} (${st.deck}) in ${duration(st.elapsed)}.`;
  } else if (st.status !== "idle") {
    $("#progress-text").textContent = `Plan ${st.status}.`;
  }
}

async function poll() {
  const st = await (await fetch("/api/plan/status")).json();
  if (!state.synced && st.seed) showForm(st);
  state.synced = true;
  showStatus(st);
  clearTimeout(state.timer);
  if (st.status === "running") state.timer = setTimeout(poll, 1000);
  else if ((st.status === "done" || st.status === "idle") && (!state.result || state.result.seed !== st.seed)) {
    const res = await fetch("/api/plan/result");
    if (res.ok) render(await res.json());
  }
}

async function start(e) {
  e.preventDefault();
  $("#error").textContent = "";
  const seed = $("#seed").value.trim().toUpperCase();
  try { localStorage.setItem("plan-seed", seed); } catch { /* not remembered */ }
  const res = await fetch("/api/plan", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seed, deck: $("#deck").value, max_ante: Number($("#max-ante").value), effort: $("#effort").value }) });
  const st = await res.json();
  if (!res.ok) return void ($("#error").textContent = st.error);
  state.result = null;
  state.settled = 0;
  view.deckBack = $("#deck").value;
  $("#summary").hidden = true;
  $("#plan-steps").replaceChildren();
  showStatus(st);
  poll();
}

function asText(res) {
  const lines = [`${res.seed} (${res.deck}): ${outcome(res)}`];
  for (const sec of res.steps) {
    lines.push("", `Ante ${sec.ante} · ${sec.title}`);
    for (const s of sec.steps) lines.push(`  ${s.text}`);
  }
  return lines.join("\n");
}

async function init() {
  const meta = await (await fetch("/api/meta")).json();
  Object.assign(art, meta.art);
  state.bosses = meta.bosses || {};
  $("#deck").replaceChildren(...meta.decks.map((d) => Object.assign(document.createElement("option"), { value: d, textContent: d, selected: d === "Red Deck" })));
  try { $("#seed").value = localStorage.getItem("plan-seed") || ""; } catch { /* nothing remembered */ }
  $("#plan-form").addEventListener("submit", start);
  $("#stop").addEventListener("click", async () => showStatus(await (await fetch("/api/plan/stop", { method: "POST" })).json()));
  $("#copy").addEventListener("click", () => state.result && navigator.clipboard?.writeText(asText(state.result)));
  poll();
}

init();
