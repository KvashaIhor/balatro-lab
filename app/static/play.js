// Balatro Lab, Play tab: play a run yourself on the run viewer's screen. Each move is played out with the run viewer's
// own board and animations (board.js): the server replays the game's recorded actions (balatro/interactive.py) and
// sends the frames the run recorded since the last decision, which play in order before the next decision's controls
// come up. Every decision, with what the value bot would have done, is kept in runs/played/ for the analysis; clicking
// a past decision plays from there again as a new branch (a jump, as the viewer's).
import { art, view as cardView, esc, el } from "./cards.js";
import { runInfo, deckView } from "./panels.js";
import * as B from "./board.js";

const $ = (sel) => document.querySelector(sel);
const fmt = (n) => Math.round(n ?? 0).toLocaleString("en-US");
const PACK_W = 204;                                       // a pack's sprite, 1.25x a card (board.js offerRow)

// The person's picks: cards in hand (st.hand, positions) and one joker, consumable, offer or pack card (st.raise:
// its board entry's role, position and key), raised on the board until acted on.
// While a move plays (st.animating), it may wait where the game waits for a click (st.holding: the cash-out panel's
// Cash Out, the boss blind's Select); st.passed is the last frame whose wait is over.
const st = { s: null, texts: null, hand: new Set(), raise: null, busy: false, animating: false, anim: 0, hint: false, previewFor: "",
  holding: null, passed: -1 };

// ---- talking to the server --------------------------------------------------------------------------------
async function api(path, body) {
  const r = await fetch(`/api/play/${path}`, body ? { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) } : {});
  const d = await r.json().catch(() => ({ error: r.statusText }));
  if (!r.ok || d.error) throw new Error(d.error || r.statusText);
  return d;
}

// One request at a time; an action's answer plays out (animates) before the next can be made.
async function request(path, body, animate = false) {
  if (st.busy) return;
  st.busy = true;
  document.body.classList.add("busy");
  let s;
  try {
    s = await api(path, body);
  } catch (e) {
    flash(e.message);
  } finally {
    st.busy = false;
    document.body.classList.remove("busy");
  }
  if (s) await arrive(s, animate);
}

// An action at the cursor: the server goes on along the line if it's the recorded next step, else branches.
const act = (action) => st.s && request("act", { id: st.s.id, action, cursor: st.s.cursor }, true);

// Move the cursor along the line: one step forward plays that decision out as it was played (the frames this side
// of it are held already); anything else jumps there. The steps after the cursor stay, until another action is taken.
function goTo(cursor) {
  const s = st.s;
  if (!s || st.busy || cursor < 0 || cursor > s.timeline.length || cursor === s.cursor) return;
  const forward = cursor === s.cursor + 1;
  request(`state?id=${encodeURIComponent(s.id)}&cursor=${cursor}${forward ? `&from=${B.state.frames.length}` : ""}`, null, forward);
}

// A state from the server: the frames it brings continue the run on screen (an action's) and play out, or replace it
// (a game opened, a rewind, a branch switched) and the board jumps to the last.
async function arrive(s, animate) {
  const same = st.s && st.s.id === s.id && st.s.branch === s.branch && st.s.step === s.step;
  // Picked cards stay picked through a move that keeps them in hand (a Planet used, the hand sorted): they are
  // followed by card; any other pick is dropped, and all of them when the game is opened, rewound or switched.
  const kept = animate && st.s ? new Set([...st.hand].map((k) => st.s.view.hand[k]?.uid).filter((u) => u != null)) : new Set();
  st.s = s;
  if (!same) {
    const hand = new Set(s.view.hand.map((c, k) => (kept.has(c.uid) ? k : -1)).filter((k) => k >= 0));
    Object.assign(st, { hand: s.decision === "round" || s.decision === "pack" ? hand : new Set(), raise: null, previewFor: "" });
  }
  try { history.replaceState(null, "", `#game=${s.id}`); } catch { /* sandboxed */ }
  cardView.deckBack = s.deck;
  B.state.deckName = s.deck;
  side(s);
  if (s.bot_pending && st.hint) fetchHint(s);
  refreshSaved(s.id);
  const have = B.state.frames.length;
  const goesOn = animate && s.frames && s.frames_from > 0 && s.frames_from <= have;
  // (a server from before frames were sent: the state as it stands, without the moves leading to it)
  const frames = goesOn ? B.state.frames.slice(0, s.frames_from).concat(s.frames) : s.frames || [{ ...s.view, kind: "now" }];
  B.state.frames = B.mark(frames);
  unhold();
  if (!goesOn || !s.frames.length) {                     // a game opened, a rewind, a branch: no waiting, no moves
    st.anim++;
    B.jump(frames.length - 1);
    return settle(true);
  }
  B.state.i = st.passed = s.frames_from - 1;              // the frame on screen: where the last decision was made
  B.state.picked_at = s.frames_from;                      // the person's move: its cards are up already
  st.animating = true;
  document.body.classList.add("animating");
  showPreview(null);                                      // (the picked cards' estimate gives way to the move's own)
  renderControls();
  await animateOn(++st.anim);
}

// The bot's view comes by its own request (the server has a worker on it while the move plays out): shown when it
// is here, if the game is still where it was asked.
async function fetchHint(s) {
  const at = (x) => `${x.id}|${x.branch}|${x.cursor}`, asked = at(s);
  let d;
  try { d = await api(`hint?id=${encodeURIComponent(s.id)}&cursor=${s.cursor}`); } catch { return; }
  if (!st.s || at(st.s) !== asked || !st.s.bot_pending) return;
  st.s.bot = d.bot;
  delete st.s.bot_pending;
  side(st.s);
}

// Play the frames from the one on screen to the last, then bring up the decision (unless cut short: a skip or a jump).
async function animateOn(token) {
  while (B.state.i < B.state.frames.length - 1) {
    if (token !== st.anim || !(await B.advance())) return;
  }
  if (token === st.anim) settle(false);
}

// The moments the game waits on a click that aren't decisions (nothing is recorded for them): the cash-out panel
// after a blind is won (its Cash Out collects and opens the shop) and the boss blind's choice (Select: only the Small
// and Big Blinds can be skipped). Not where the next decision is the boss's reroll, which is asked right there.
function pausesAt(j) {
  const f = B.state.frames[j];
  if (f.kind === "cash_out") return true;
  return f.kind === "select" && f.blind?.kind === 2 && !(j === B.state.frames.length - 1 && st.s.decision === "boss");
}

// Wait at frame j for its button (or Enter or Space).
function hold(j) {
  const kind = B.state.frames[j].kind;
  return new Promise((resolve) => {
    st.holding = { j, kind, go: () => { unhold(); st.passed = j; resolve(); } };
    document.body.classList.add("holding", kind === "cash_out" ? "holding-cash" : "holding-select");
  });
}

function unhold() {
  st.holding = null;
  document.body.classList.remove("holding", "holding-cash", "holding-select");
}

// board.js asks this where a move could wait (state.hold): only while a move plays, at a wait not yet passed.
function holdFor(f) {
  const j = B.state.frames.indexOf(f);
  return st.animating && j > st.passed && pausesAt(j) ? hold(j) : null;
}

// A click or a key while a move plays skips to its end, or to the next wait on the way (which still waits).
function skip() {
  if (!st.animating || st.holding) return false;
  const token = ++st.anim, last = B.state.frames.length - 1;
  let k = -1;
  for (let j = Math.max(B.state.i, st.passed + 1); j <= last && k < 0; j++) if (pausesAt(j)) k = j;
  if (k < 0) {
    B.jump(last);
    settle(true);
  } else {
    B.jump(k);
    hold(k).then(() => token === st.anim && animateOn(token));
  }
  return true;
}

// The decision's board: the last frame as the run viewer leaves it, with the run as it stands now (a sorted hand,
// the shop or pack on offer) and the person's picks raised.
function decisionView() {
  const s = st.s, d = s.decision, now = s.view, v = B.endViewOf(B.state.frames[B.state.frames.length - 1]);
  Object.assign(v, { jokers: now.jokers, consumables: now.consumables, handSize: now.hand_size });
  const clear = { play: null, up: [], shop: null, pack: null, cash: null, select: null, handDy: 0, raised: false, buttons: false };
  const picks = [...st.hand].sort((a, b) => a - b);
  if (d === "round") Object.assign(v, clear, { hand: now.hand, lifted: picks, raised: true, buttons: true });
  else if (d === "shop") Object.assign(v, clear, { hand: [], lifted: [], shop: { ...now.shop, _gen: v.shop?._gen ?? 0 } });
  else if (d === "pack") Object.assign(v, clear, { pack: now.pack, withHand: now.hand.length > 0, handDy: -150, hand: now.hand, lifted: picks });
  v.raise = st.raise ? new Set([st.raise.key]) : null;
  return v;
}

function settle(snap) {
  st.animating = false;
  unhold();
  document.body.classList.remove("animating");
  B.state.picked_at = null;
  const s = st.s;
  B.sidebar(s.view);
  $("#ante-of").textContent = `/ ${s.max_ante}`;
  B.put(decisionView(), { snap });
  renderControls();
  preview();
}

// A pick changed: the board springs to it (a card rises), and the controls follow.
function refresh() {
  if (st.animating || !st.s) return;
  B.put(decisionView());
  renderControls();
  preview();
}

function flash(msg) {
  $("#game .flash")?.remove();
  const f = el("div", "flash t", esc(msg));
  $("#game").append(f);
  setTimeout(() => f.remove(), 2600);
}

// The poker hand the picked cards make and what they would score (the bot's estimate, luck left out); when a boss's
// rule (The Mouth, The Eye, The Psychic...) or debuffs leave them nothing, why, in place of the numbers (or under the
// hand's name, when they still score something).
function showPreview(h) {
  $("#hand-name").textContent = h?.hand || "";
  $("#hand-level").textContent = h?.level ? `lvl.${h.level}` : "";
  const why = h?.reason, none = !!why && !h.estimate;
  $("#hand-why")?.remove();
  $("#hand-box").classList.toggle("why", none);
  if (why) {
    const w = el("div", `t ${none ? "" : "small"}`, esc(why));
    w.id = "hand-why";
    $("#hand-box").append(w);
  }
  $("#chips").textContent = h && !none ? `≈${fmt(h.estimate)}` : "0";
  $("#mult").textContent = h && !none ? "est." : "0";
  $("#chips").classList.toggle("est", !!h && !none);
  $("#mult").classList.toggle("est", !!h && !none);
}

async function preview() {
  const s = st.s, show = showPreview;
  const key = `${s.id}|${s.step}|${[...st.hand].sort().join(",")}`;
  if (s.decision !== "round" || !st.hand.size) { st.previewFor = ""; return show(null); }
  if (key === st.previewFor) return;
  st.previewFor = key;
  try {
    const p = await api("preview", { id: s.id, cards: [...st.hand].sort((a, b) => a - b), cursor: s.cursor });
    if (st.previewFor === key && !st.animating) show(p.hand ? p : null);
  } catch { /* a stale pick */ }
}

// ---- the person's controls, over the board ----------------------------------------------------------------
function tab(text, cls, x, y, on, enabled = true) {
  const b = el("div", `act-btn t ${cls} ${enabled ? "" : "off"}`, text);
  Object.assign(b.style, { left: `${x}px`, top: `${y}px` });
  if (enabled) b.addEventListener("click", (e) => { e.stopPropagation(); on(); });
  $("#controls").append(b);
  return b;
}

const picks = () => [...st.hand].sort((a, b) => a - b);
const sortMode = (btn) => (/rank/i.test(btn.textContent) ? "rank" : "suit");

function renderControls() {
  const c = $("#controls");
  c.replaceChildren();
  const s = st.s;
  if (!s || st.animating) return;
  const d = s.decision, v = s.view, ctl = v.controls || {};
  $("#layer .button-discard")?.classList.toggle("off", d === "round" && v.discards_left <= 0);
  for (const b of document.querySelectorAll("#layer .sort-pick")) b.classList.toggle("active", d === "round" && v.hand_sort === sortMode(b));
  const r = st.raise, b = r && B.board.get(r.key);
  if (b && ["round", "shop", "pack"].includes(d)) {
    const e = b.e, x = e.x, y = e.y;
    if (r.role === "joker") {
      const j = v.jokers[r.idx], n = v.jokers.length;
      const order = (to) => { const p = [...Array(n).keys()]; p.splice(to, 0, p.splice(r.idx, 1)[0]); act(["order_jokers", p]); };
      tab(`Sell $${j.sell}`, "green", x + B.CARD_W - 18, y + 70, () => act(["sell_joker", r.idx]), !j.eternal);
      if (r.idx > 0) tab("<", "orange", x - 4, y + B.CARD_H + 8, () => order(r.idx - 1));
      if (r.idx < n - 1) tab(">", "orange", x + B.CARD_W - 52, y + B.CARD_H + 8, () => order(r.idx + 1));
    } else if (r.role === "consumable") {
      // One that takes no cards (a Planet, The Hermit) is used as it is, whatever cards are picked (they stay picked);
      // one that takes cards needs the right number picked from a hand (in a round or an open pack).
      const k = r.idx, cc = ctl.consumables?.[k] || {}, n = st.hand.size, none = !cc.max_targets;
      const ok = none ? !!cc.usable : d !== "shop" && n >= (cc.min_targets || 0) && n <= cc.max_targets;
      tab("Use", "red", x + B.CARD_W - 18, y + 40, () => act(["use", k, none ? [] : picks()]), ok);
      tab(`Sell $${cc.sell ?? "?"}`, "green", x + B.CARD_W - 18, y + 120, () => act(["sell_consumable", k]));
    } else if (r.role === "offer") {
      const where = { card: "cards", pack: "packs", voucher: "vouchers" }[e.where];
      const o = ctl.offers?.[where]?.[r.idx] || {}, w = e.where === "pack" ? PACK_W : B.CARD_W;
      if (e.where === "card") {
        tab("Buy", "green", x + w - 12, y + 60, () => act(["buy", "card", r.idx]), o.affordable && o.room !== false);
        if (o.consumable && o.usable) tab("Buy and use", "red", x + w - 12, y + 140, () => act(["buy_use", r.idx, []]), o.affordable);
      } else {
        tab(e.where === "pack" ? "Open" : "Redeem", "green", x + w - 12, y + 60, () => act(["buy", e.where, r.idx]), o.affordable);
      }
    } else if (r.role === "pack") {
      // a joker or playing card is taken; a consumable is used: as it is if it takes no cards (a Planet), else on the
      // picked cards of the hand the pack deals
      const cc = ctl.pack?.[r.idx] || {}, n = st.hand.size, none = !cc.joker && !cc.card && !cc.max_targets;
      const ok = cc.joker ? cc.room !== false : cc.card ? true : none ? !!cc.usable : n >= (cc.min_targets || 0) && n <= cc.max_targets;
      tab(cc.joker || cc.card ? "Take" : "Use", "green", x + 30, y + B.CARD_H + 14,
        () => act(["pick", r.idx, cc.joker || cc.card || none ? [] : picks()]), ok);
    }
  }
  if (d === "boss") bossPrompt(v);
  else if (!d) endScreen(s.result);
}

function bossPrompt(v) {
  const p = el("div", "prompt");
  p.innerHTML = `<div class="t title">${esc(v.boss.name)}</div><div class="t body">${esc(v.boss.effect)}</div>`
    + `<div class="t body">Reroll the boss for $10?</div>`;
  const row = el("div", "row");
  for (const [text, cls, a] of [["Reroll $10", "green", "reroll"], ["Keep it", "red", "keep"]]) {
    const b = el("div", `act-btn t ${cls}`, text);
    b.addEventListener("click", (e) => { e.stopPropagation(); act([a]); });
    row.append(b);
  }
  p.append(row);
  $("#controls").append(p);
}

// The run is over: the board shows the game's end screen (board.js endScreen); its New Run and Endless Mode buttons
// come back here as "board-end" events. Clicking a decision on the right plays on from there.
function endScreen() {}

// The game's own buttons, drawn by the board: Play Hand, Discard, Sort, Next Round, Reroll, Skip (a pack), Select and
// Skip Blind.
function button(btn) {
  const s = st.s, d = s.decision, v = s.view;
  if (btn.matches(".button-play")) {
    if (d !== "round") return;
    if (!st.hand.size) return flash("Pick 1-5 cards to play");
    return act(["play", picks()]);
  }
  if (btn.matches(".button-discard")) {
    if (d !== "round") return;
    if (v.discards_left <= 0) return flash("No discards left");
    if (!st.hand.size) return flash("Pick 1-5 cards to discard");
    return act(["discard", picks()]);
  }
  if (btn.matches(".sort-pick")) {
    // a sort mode, as the game keeps it: the hand is sorted again after every draw (the server's run.hand_sort)
    if (d !== "round") return;
    const mode = sortMode(btn);
    if (v.hand_sort === mode) return flash(`Already sorted by ${mode}`);
    return act(["sort_hand", mode]);
  }
  if (btn.matches(".shop-button") && d === "shop") return act(/reroll/i.test(btn.textContent) ? ["reroll"] : ["leave"]);
  if (btn.matches("#pack-skip") && d === "pack") return act(["skip"]);
  if (btn.matches(".sel-select") && d === "select") return act(["select"]);
  if (btn.matches(".sel-skip-button") && d === "select") {
    if (!v.select?.tag) return flash("This blind has no tag to skip for");
    return act(["skip"]);
  }
}

// Something on the board picked: a card in hand toggles (up to 5), a joker, consumable, offer or pack card is raised.
function pick(e) {
  const d = st.s.decision;
  if (e.role === "hand" && (d === "round" || d === "pack")) {
    if (st.hand.has(e.idx)) st.hand.delete(e.idx);
    else if (st.hand.size < 5) st.hand.add(e.idx);
    else return flash("Up to 5 cards");
  } else if (["joker", "consumable", "offer", "pack"].includes(e.role) && ["round", "shop", "pack"].includes(d)) {
    st.raise = st.raise?.key === e.key ? null : { role: e.role, idx: e.idx, key: e.key };
  } else return;
  refresh();
}

// Dragging a card in hand moves it, as in the game: dropped between two others, it goes there (the order Death reads
// left to right, and played cards score in). It lasts until the next draw sorts the hand again. A press that doesn't
// move is still a click (a pick).
const drag = { on: null, dropped: false };

function onPointerDown(e) {
  if (e.button !== 0 || st.busy || st.holding || st.animating || !st.s || !["round", "pack"].includes(st.s.decision)) return;
  const node = e.target.closest("#layer [data-key]");
  const b = node && B.board.get(node.dataset.key);
  if (b?.e?.role !== "hand") return;
  drag.on ={ b, x0: e.clientX, y0: e.clientY, tx: b.sp.T.x, ty: b.sp.T.y, z: b.sp.z, moved: false,
              scale: $("#game").getBoundingClientRect().width / 1920 };
}

function onPointerMove(e) {
  const g = drag.on;
  if (!g) return;
  const dx = (e.clientX - g.x0) / g.scale, dy = (e.clientY - g.y0) / g.scale;
  if (!g.moved && Math.hypot(dx, dy) < 8) return;
  g.moved = true;
  g.b.sp.z = 90;
  g.b.sp.to({ x: g.tx + dx, y: g.ty + Math.min(dy, 0) - 20 });
  B.stage.paint();
}

function onPointerUp() {
  const g = drag.on;
  drag.on = null;
  if (!g?.moved) return;
  drag.dropped = true;                                   // (the click this release makes is the drop, not a pick)
  g.b.sp.z = g.z;
  const others = [...B.board.values()].filter((b) => b.e?.role === "hand" && b !== g.b).sort((a, b) => a.e.idx - b.e.idx);
  const order = others.map((b) => b.e.idx);
  order.splice(others.filter((b) => b.e.x < g.b.sp.T.x).length, 0, g.b.e.idx);
  if (order.every((x, k) => x === k)) return refresh();  // back where it was
  act(["order_hand", order]);
}

function onGameClick(e) {
  if (drag.dropped) {
    drag.dropped = false;
    return void e.stopPropagation();
  }
  if (st.holding) {                                      // only the waiting button goes on
    if (e.target.closest(st.holding.kind === "cash_out" ? ".cash-button" : ".sel-select")) st.holding.go();
    return void e.stopPropagation();
  }
  if (skip()) return void e.stopPropagation();
  if (st.busy || !st.s || e.target.closest("#controls > *, #overlay, #run-info, #deck-pile, #options")) return;
  const btn = e.target.closest(".button-play, .button-discard, .sort-pick, .shop-button, #pack-skip, .sel-select, .sel-skip-button");
  if (btn) return button(btn);
  const node = e.target.closest("#layer [data-key]");
  const entry = node && B.board.get(node.dataset.key)?.e;
  if (entry?.role) return pick(entry);
  if (st.raise) {                                        // a click on the table drops a raised pick
    st.raise = null;
    refresh();
  }
}

// ---- beside the game ----------------------------------------------------------------------------------------
// Worths with places enough to tell close options apart (+0.0265), one count for a whole list so the points line up
// (enough for its smallest), and on hover what each means.
const worthPlaces = (vs) => {
  const small = Math.min(...vs.filter((v) => v).map(Math.abs));
  return small >= 1 ? 2 : small >= 0.1 ? 3 : 4;
};
const worthText = (v, places) => (v >= 0 ? "+" : "") + v.toFixed(places);
const worthTitle = (w) => `${w.worth >= 0 ? "+" : ""}${w.worth} in power, the log of the build's typical score `
  + `(+0.1 is about 10.5% more)` + (w.dollars == null ? "" : `; to the bot as good as $${w.dollars.toFixed(2)}`);

// Two best options within this much power (about 2% of a typical score) are a coin flip to the bot, not advice: on a
// Jumbo Buffoon Pack (C5X6MXUN, 28 Oct) it "chose" Sock and Buskin over Burglar on the Uncommon bonus alone, +0.05 each.
const CLOSE = 0.02;
const closeCall = (worths) => {
  const vs = (worths || []).map((w) => w.worth).sort((a, b) => b - a);
  return vs.length > 1 && vs[0] - vs[1] < CLOSE
    ? `<div class="muted small">About equal: the best ${vs.filter((v) => vs[0] - v < CLOSE).length} are within ${CLOSE} (about 2% of a typical score), a coin flip to the bot.</div>`
    : "";
};

function side(s) {
  const bot = s.bot, hint = $("#hint");
  hint.hidden = !st.hint || (!bot && !s.bot_pending);
  if (hint.hidden) hint.replaceChildren();
  else if (!bot) hint.innerHTML = `<div class="muted small">The bot is thinking…</div>`;
  else {
    const places = worthPlaces((bot.worths || []).map((w) => w.worth));
    // each option opens to what its number is made of: a play's scoring step by step, an offer's worth in parts
    const opt = (head, value, title, lines) => lines && lines.length
      ? `<li class="opt"><details><summary><span>${head}</span><b title="${esc(title)}">${value}</b></summary><ol class="steps">${lines.join("")}</ol></details></li>`
      : `<li><span>${head}</span><b title="${esc(title)}">${value}</b></li>`;
    const num = (x) => (Number.isInteger(x) ? fmt(x) : x.toFixed(2).replace(/\.?0+$/, ""));
    const signed = (x) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(4);
    const rows = (bot.plays || []).map((p) => opt(`${esc(p.hand)}: ${esc(p.text)}`, fmt(p.score), "",
      (p.steps || []).map((st) => `<li><span>${esc(st.text)}</span><b>${num(st.chips)} × ${num(st.mult)}</b></li>`)))
      .concat((bot.worths || []).map((w) => opt(esc(w.text), worthText(w.worth, places), worthTitle(w),
        (w.parts || []).map((pt) => `<li><span>${esc(pt.text)}</span><b>${pt.worth == null ? "" : signed(pt.worth)}</b></li>`))));
    // a free first step (a Tarot used, a joker sold, a reorder) leads somewhere: the whole plan under it, so the move
    // it leads to is seen (the user's CCU44VLE, 30 Oct: "Use The Devil" hid the discard that followed)
    const steps = (bot.plan_text || "").split(" → ").filter(Boolean);
    const rest = steps[0] === bot.text ? steps.slice(1) : steps;   // (a reorder first is left out of the plan's line)
    const plan = rest.length ? `<div class="plan-line">then: ${esc(rest.join(" → "))}</div>` : "";
    // (a card bought ahead of the reroll that would throw it away: both are the move, no coin flip between them)
    const close = bot.both ? `<div class="muted small">Both: it is bought first, as the reroll would throw it away.</div>` : closeCall(bot.worths);
    hint.innerHTML = `<div class="choice">${esc(bot.text)}</div>${plan}${close}${rows.length ? `<ul>${rows.join("")}</ul>` : ""}`
      + `<button class="btn" id="do-bot">Do the bot's move</button>`;
    $("#do-bot").addEventListener("click", () => act(bot.action));
  }
  $("#events").replaceChildren(...(s.events.length ? s.events : ["—"]).map((t) => el("li", "", esc(t))));
  // sorting the hand isn't compared with the bot (no mark, not counted; a quieter line)
  const compared = s.timeline.filter((t) => !t.aside), agree = compared.filter((t) => t.agree).length;
  $("#agree").textContent = compared.length ? `· same as the bot ${agree}/${compared.length}` : "";
  let ante = null;
  $("#timeline").replaceChildren(...s.timeline.map((t) => {
    const cls = [t.agree === false ? "differs" : "", t.aside ? "aside" : "", t.ante !== ante ? "ante-start" : "",
      t.i >= s.cursor ? "ahead" : "", t.i === s.cursor ? "next" : ""].join(" ");
    const li = el("li", cls, `<span class="n">${t.i}</span><span class="text">${t.ante !== ante ? `<b>Ante ${t.ante}</b> ` : ""}${esc(t.text)}</span>`);
    ante = t.ante;
    li.title = `You: ${t.text}` + (t.aside ? "" : `\nBot: ${t.bot || "?"}`) + "\nClick to go back to this decision (the line after it is kept"
      + " until you do something else there)";
    li.addEventListener("click", () => goTo(t.i));
    return li;
  }));
  ($("#timeline .next") || $("#timeline").lastElementChild)?.scrollIntoView({ block: "nearest" });
  const n = s.timeline.length;
  $("#line-pos").textContent = s.cursor < n ? `at decision ${s.cursor} of ${n}: the rest of the line is ahead` : `${n} decisions`;
  $("#step-back").disabled = s.cursor <= 0;
  $("#step-on").disabled = $("#step-end").disabled = s.cursor >= n;
  $("#branch-pick").replaceChildren(...s.branches.map((b) => Object.assign(document.createElement("option"), {
    value: b.id, selected: b.id === s.branch,
    textContent: `Branch ${b.id}${b.parent == null ? " (first)" : ` from ${b.parent} at decision ${b.from_step}`} · ${b.steps} decisions`
      + (b.result ? ` · ${b.result.won ? "won" : `lost at ante ${b.result.ante}`}` : ""),
  })));
  $("#game-label").textContent = `${s.seed} · ${s.deck} · ${s.stake} · saved as runs/played/${s.id}.json`;
  const done = s.result && s.result.progress >= 3 * s.max_ante;
  $("#banner").textContent = s.decision ? `Ante ${s.view.ante} · decision ${s.step}` : (s.result?.won ? "Run won" : done ? "Run complete" : "Run over");
}

async function refreshSaved(current) {
  try {
    const { games } = await api("games");
    $("#saved-pick").replaceChildren(Object.assign(document.createElement("option"), { value: "", textContent: "—" }),
      ...games.map((g) => Object.assign(document.createElement("option"), { value: g.id, selected: g.id === current,
        textContent: `${g.seed} · ${g.deck} · ${g.steps} decisions${g.result ? (g.result.won ? " · won" : ` · lost a${g.result.ante}`) : ""} · ${g.updated || ""}` })));
  } catch { /* offline */ }
}

// ---- Run Info and the deck --------------------------------------------------------------------------------------
function openPanel(kind, tab) {
  closePanel();
  const s = st.s;
  if (!s || !st.texts) return;
  const p = kind === "info" ? runInfo(s.view, st.texts, tab) : deckView(s.view, s.view.deck_cards, s.deck, st.texts, tab);
  const o = el("div", "");
  o.id = "overlay";
  o.append(p);
  o.addEventListener("click", (e) => {
    const t = e.target.closest("[data-tab]");
    if (t) return void openPanel(kind, t.dataset.tab);
    if (e.target === o || e.target.closest("[data-close]")) closePanel();
  });
  $("#game").append(o);
}
const closePanel = () => $("#overlay")?.remove();

// ---- starting up ---------------------------------------------------------------------------------------------
async function init() {
  B.setup();
  const meta = await (await fetch("/api/meta")).json();
  Object.assign(art, meta.art);
  st.texts = B.state.texts = meta.texts;
  B.state.bosses = meta.bosses || {};
  const option = (v) => Object.assign(document.createElement("option"), { value: v, textContent: v });
  $("#deck-pick").append(...meta.decks.map(option));
  $("#deck-pick").value = meta.decks.includes("Red Deck") ? "Red Deck" : meta.decks[0];
  $("#stake-pick").append(...meta.stakes.map(option));
  try { st.hint = localStorage.getItem("play-hint") === "1"; } catch { /* private window */ }
  if (/[#&]hint=1\b/.test(location.hash)) st.hint = true;   // a link that opens with the bot's view: #game=<id>&hint=1
  $("#hint-on").checked = st.hint;
  $("#hint-on").addEventListener("change", (e) => {
    st.hint = e.target.checked;
    try { localStorage.setItem("play-hint", st.hint ? "1" : "0"); } catch { /* private window */ }
    if (st.s) side(st.s);
    if (st.hint && st.s?.bot_pending) fetchHint(st.s);
  });
  $("#options").addEventListener("click", () => { $("#hint-on").click(); });
  B.wireTooltips({ pin: false });
  $("#run-info").addEventListener("click", () => openPanel("info", "hands"));
  $("#deck-pile").addEventListener("click", () => openPanel("deck", "remaining"));
  $("#game").addEventListener("click", onGameClick);
  $("#game").addEventListener("pointerdown", onPointerDown);
  addEventListener("pointermove", onPointerMove);
  addEventListener("pointerup", onPointerUp);
  // the side panel's and dock's buttons let go of the focus once clicked, so the keys go on working the game
  document.addEventListener("click", (e) => e.target.closest("#side button, #dock button")?.blur());
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select, textarea")) return;
    if ($("#overlay") && e.key === "Escape") return closePanel();
    if (st.holding) {                                    // Enter or Space presses the waiting button
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); st.holding.go(); }
      return;
    }
    if (skip()) return e.preventDefault();
    if (e.key === "ArrowLeft" && st.s) { e.preventDefault(); goTo(st.s.cursor - 1); }          // along the line
    else if (e.key === "ArrowRight" && st.s) { e.preventDefault(); goTo(st.s.cursor + 1); }
  });
  B.state.hold = holdFor;
  B.state.endless = true;                // the end screen offers Endless Mode after a win (request "endless")
  document.addEventListener("board-end", (e) => {
    if (e.detail === "new") $("#new-game").requestSubmit();
    else if (e.detail === "endless" && st.s) request("endless", { id: st.s.id });
  });
  $("#step-back").addEventListener("click", () => st.s && goTo(st.s.cursor - 1));
  $("#step-on").addEventListener("click", () => st.s && goTo(st.s.cursor + 1));
  $("#step-end").addEventListener("click", () => st.s && goTo(st.s.timeline.length));
  $("#new-game").addEventListener("submit", (e) => {
    e.preventDefault();
    request("new", { seed: $("#seed").value.trim(), deck: $("#deck-pick").value, stake: $("#stake-pick").value,
      max_ante: Number($("#max-ante").value) || 8 });
  });
  $("#saved-pick").addEventListener("change", (e) => e.target.value && open(e.target.value));
  $("#branch-pick").addEventListener("change", (e) => st.s && request("branch", { id: st.s.id, branch: Number(e.target.value) }));
  const hash = location.hash.match(/^#game=([\w-]+)/);
  await refreshSaved(hash?.[1]);
  if (hash) return open(hash[1]);
  $("#banner").textContent = "Start a new game, or open a saved one.";
}

async function open(id) {
  try {
    await arrive(await api(`state?id=${encodeURIComponent(id)}`), false);
  } catch (e) {
    $("#banner").textContent = e.message;
  }
}

init();
