// The game's screen, shared by the run viewer (app.js) and the Play tab (play.js): a copy of it in the game's own
// 1920 x 1080 coordinates (measured from a game screenshot), scaled to the window. Cards, jokers and panels are
// springs (motion.js). show(frame) puts a recorded frame up at once; advance() plays the move to the next frame the
// way the game animates it, each event in the game's order and timing, measured frame by frame from gameplay
// footage (ANIMATION.md). Jumps snap.
import { background } from "./bg.js";
import { art, view, esc, el, cardEl, jokerEl, consumableEl, itemEl } from "./cards.js";
import { Stage, Sprite, CANCEL } from "./motion.js";
import { makeFlames } from "./flames.js";
import { tipFor } from "./panels.js";

const $ = (sel) => document.querySelector(sel);
const fmt = (n) => Math.round(n).toLocaleString("en-US");
const fmtMult = (m) => (Number.isInteger(m) ? fmt(m) : m.toFixed(1));
// Layout, in game pixels. Card sprites are 164 x 219 with a 2px clear margin, so the card shows as 159 x 214;
// positions below are of the visible card.
export const CARD_W = 159, CARD_H = 214, MARGIN = 2.3;
const RAISE = 24;    // how far a joker, consumable, offer or pack card picked in the Play tab rises (view.raise)
const TRAYS = { jokers: [523, 840, 59], consumables: [1396, 382, 59] };  // left, width, card top
// The hand's width is split over the hand size (10 cards 98 px apart, 8 cards 122) and its fan flattens as it
// fills. While the player chooses, it sits 160 px higher, above the Play / Sort / Discard buttons.
const HAND = { center: 1046, top: 808, width: 980, lift: 44, raise: -160 };
// Played cards rest with their tops at 503; the scoring ones rise 43 px.
const PLAY = { center: 1046.5, top: 503, step: 189, lift: 43 };
const DECK = { x: 1588, y: 808 };
const BELOW = 820, ABOVE = -440;  // where panels wait off screen
// Corner staircases measured from the game: inset (px) of each row from the corner.
const STAIR_M = [10, 10, 5, 4, 4, 2, 2, 2, 2, 2, 1, 0];
const STAIR_L = [14, 14, 9, 7, 7, 5, 4, 3, 3, 2, 2, 2, 1, 1, 0];

// state.hold(frame), when set (the Play tab): a promise a move waits on where the game waits for a click (the cash-out
// panel's Cash Out, the boss blind's Select), or nothing to go on at once.
export const state = { bosses: {}, jokers: [], picked: new Set(), frames: [], i: 0, playing: false, busy: false, token: 0 };
export let bg;
export const stage = new Stage();
// The hand's cards follow this anchor, a softer spring, so the hand rises and drops the way the game's does.
const handAnchor = stage.add(new Sprite(null, {}, { offset: true, damp: 0.38, pull: 0.12 }));
const ui = {};   // sprites for page elements that slide or juice: sidebar boxes and numbers, the hand count
let flames = null;

// Set the page up for the board: corner staircases, scaling to the window, the background, the sliding sidebar parts.
export function setup() {
  document.documentElement.style.setProperty("--stair", stair(STAIR_M));
  document.documentElement.style.setProperty("--stair-l", stair(STAIR_L));
  fit();
  addEventListener("resize", fit);
  new ResizeObserver(fit).observe($("#dock"));
  bg = background($("#bg"));
  for (const id of ["blind-box", "shop-sign", "hand-count", "hand-name-row", "chips", "mult", "round-score", "money", "hands", "discards"]) {
    ui[id] = stage.add(new Sprite($(`#${id}`), {}, { offset: true }));
  }
  ui["hand-count"].parent = handAnchor;
  // Over the table while a space pack is open: small squares drifting up and left (footage: Arcana, Spectral).
  const stars = el("div", "", Array.from({ length: 48 }, () => {
    const size = 3 + Math.floor(Math.random() * 3) * 2;
    return `<i style="left:${(Math.random() * 110).toFixed(1)}%;top:${(Math.random() * 110).toFixed(1)}%;--s:${size}px;`
      + `--d:${(14 + Math.random() * 16).toFixed(1)}s;animation-delay:-${(Math.random() * 30).toFixed(1)}s,-${(Math.random() * 3).toFixed(1)}s"></i>`;
  }).join(""));
  stars.id = "stars";
  $("#bg").after(stars);
  // The shadows of the hand, the played cards and the jokers and consumables (motion.js SHADOW), under every sprite.
  const shades = el("div", "", "");
  shades.id = "shades";
  $("#layer").prepend(shades);
  // Flames over the chips and mult boxes while the hand being scored beats the blind on its own (flames.js).
  flames = makeFlames($("#hand-box"));
}

function stair(a) {
  const n = a.length, P = [], R = (v) => `calc(100% - ${v}px)`, px = (v) => `${v}px`;
  for (let i = 0; i < n; i++) P.push(`${R(a[i])} ${px(i)}`, `${R(a[i])} ${px(i + 1)}`);
  for (let i = n - 1; i >= 0; i--) P.push(`${R(a[i])} ${R(i + 1)}`, `${R(a[i])} ${R(i)}`);
  for (let i = 0; i < n; i++) P.push(`${px(a[i])} ${R(i)}`, `${px(a[i])} ${R(i + 1)}`);
  for (let i = n - 1; i >= 0; i--) P.push(`${px(a[i])} ${px(i + 1)}`, `${px(a[i])} ${px(i)}`);
  return `polygon(${P.join(",")})`;
}

// Scale the 1920 x 1080 screen to its viewport: the window above the lab dock when it is showing (and left of the
// Play tab's side panel).
export function fit() {
  const dock = document.body.classList.contains("bare") ? 0 : $("#dock").offsetHeight;
  document.documentElement.style.setProperty("--dock-h", `${dock}px`);
  const vp = $("#viewport");
  document.documentElement.style.setProperty("--scale", Math.min(vp.clientWidth / 1920, (innerHeight - dock) / 1080));
}

// ---- the board: one sprite per card, joker, offer and panel, kept while it stays on screen ---------------
export const board = new Map();     // key -> { sp, sig, e }
const leaving = new Set();   // sprites on their way out; removed when they get there, or at once on a jump

// Keys that stay with a thing as it moves: a playing card's uid, otherwise its name and how many came before.
function keys(list, prefix, id) {
  const seen = {};
  return list.map((it) => {
    const k = id(it);
    seen[k] = (seen[k] || 0) + 1;
    return `${prefix}${k}#${seen[k]}`;
  });
}
const cardKeys = (cards, area) => {
  const named = keys(cards, area, (c) => c.label || `${c.rank}${c.suit}`);
  return cards.map((c, k) => (c.uid ? `c${c.uid}` : named[k]));
};
const named = (prefix) => (list) => keys(list, prefix, (x) => x.name);
const jokerKeys = named("j"), consumableKeys = named("k"), packKeys = named("x");

function shadowed(e) {
  e.classList.add("shadowed");
  return e;
}

// Bring the board to `entries`: move what stays, `spawn` what is new and `exit` what is gone (a spawn can
// claim a gone sprite to take over its place, as a bought card does; an entry's own spawn or exit, as a tag's,
// goes first). `snap` puts everything in place at once.
function sync(entries, { spawn = popIn, exit = vanish, snap = false } = {}) {
  const want = new Set(entries.map((e) => e.key));
  const gone = [];
  for (const [key, b] of board) if (!want.has(key)) { board.delete(key); gone.push(b); }
  const fresh = [];
  for (const e of entries) {
    let b = board.get(e.key);
    const at = { x: e.x, y: e.y, r: e.r ?? 0, s: e.s ?? 1, o: e.o ?? 1 };
    if (!b) {
      const node = e.make();
      node.dataset.key = e.key;
      $("#layer").append(node);
      const sp = stage.add(new Sprite(node, at, { m: e.m ?? MARGIN, offset: !!e.offset, lean: !e.offset, sway: !!e.sway }));
      if (e.shade) {                     // its shadow, in the shared layer, in the card's shape (cards.js JOKER_SHAPES)
        $("#shades").append(sp.shadow = el("i", "", ""));
        const shape = [...node.classList].find((c) => c === "wee" || c.startsWith("shape-"));
        if (shape) sp.shadow.classList.add(`shade-${shape.replace("shape-", "")}`);
      }
      sp.parent = e.parent ?? null;
      sp.from(sp.goal);
      b = { sp, sig: e.sig };
      board.set(e.key, b);
      fresh.push(b);
    } else if (e.sig !== b.sig) {
      refresh(b, e, snap);
    }
    b.e = e;
    b.sp.parent = e.parent ?? null;
    b.sp.jiggle = !!e.jiggle;          // a joker that is ready (Invisible Joker) shakes until it isn't
    b.sp.to(at);
    b.sp.z = e.z ?? 0;
  }
  if (snap) {
    for (const b of gone) stage.remove(b.sp);
    for (const b of board.values()) settle(b.sp.snap());
    return;
  }
  for (const b of fresh) (b.e.spawn || spawn)(b.sp, b.e, gone);
  for (const b of gone) if (!b.claimed) (b.e?.exit || exit)(b.sp, b.e);
  stage.paint();
}

// A thing on the board changed (a card enhanced, a joker's value, a price): redraw it, with a juice.
function refresh(b, e, snap) {
  const node = e.make(), target = b.sp.el;
  target.className = node.className;
  // the new content's nodes, not a copy of its HTML: an edition is painted on its img after it is made (cards.js
  // showEdition), and must land on the img shown (a face-down card keeps its face's nodes for when it turns up)
  if (b.sp.face) b.sp.face = [...node.childNodes];
  else target.replaceChildren(...node.childNodes);
  if (node.dataset.tip) target.dataset.tip = node.dataset.tip;
  else delete target.dataset.tip;
  b.sig = e.sig;
  if (!snap && e.juice !== false) b.sp.pop();
}

function leave(sp, sec) {
  leaving.add(sp);
  stage.after(sec, () => { leaving.delete(sp); stage.remove(sp); });
}

// Undo whatever a cut-short move left half done: a face still hidden, rows of a panel not yet shown.
function settle(sp) {
  if (sp.face) { sp.el.replaceChildren(...sp.face); sp.face = null; }
  for (const n of sp.el.querySelectorAll(".hold")) n.classList.remove("hold");
  return sp;
}

const backHTML = () => `<img class="bg" alt="" src="${art.decks?.[view.deckBack] || ""}">`;
function faceDown(sp) {
  if (!sp.face) { sp.face = [...sp.el.childNodes]; sp.el.innerHTML = backHTML(); }   // (the face kept as its nodes)
}
function turnUp(sp) {
  if (sp.face) sp.flip(() => { if (sp.face) { sp.el.replaceChildren(...sp.face); sp.face = null; } }, 0.12);
}

// ---- how things come and go ----------------------------------------------------------------------
function popIn(sp) {
  sp.from({ s: 0.3, o: 0 });
}
function vanish(sp) {
  leave(sp, 0.35);
  sp.to({ s: 0.7, o: 0 });
}
function riseIn(sp) {
  sp.from({ y: sp.goal.y + BELOW });
}
function dropOut(sp) {
  leave(sp, 0.6);
  sp.to({ y: sp.T.y + BELOW });
}
// Off the right edge to the discard pile: the card leans into the throw and turns face down on the way.
function toss(sp) {
  leave(sp, 0.75);
  sp.parent = null;
  sp.z = 60;
  sp.to({ x: 2120, y: Math.min(sp.V.y, 640) - 100 - Math.random() * 120, r: 18 + Math.random() * 18, s: 1 });
  stage.after(0.1, () => sp.flip(() => { sp.face = null; sp.el.innerHTML = backHTML(); }));
}
// Off the top of the deck face down; it turns over in flight (edge on ~0.07 s out, face up as it lands).
function fromDeck(sp) {
  sp.from({ x: DECK.x, y: DECK.y, r: 0, s: 1, o: 1 });
  faceDown(sp);
  stage.after(0.03, () => turnUp(sp));
}
// Fades in where it belongs, with a juice: shop offers and pack cards.
function materialise(gap = 0.06) {
  let n = 0;
  return (sp) => {
    const sp0 = sp.from({ o: 0, s: 0.85 }).to({ o: 0, s: 0.85 });
    stage.after(0.05 + gap * n++, () => sp0.to({ o: 1, s: 1 }).pop(0.2));
  };
}
// Used up or redeemed: a last juice, then it dissolves.
function spent(sp) {
  sp.z = 70;
  sp.pop(0.35);
  stage.after(0.2, () => vanish(sp));
}
// A card bought or picked flies from its slot to where it goes: the new sprite takes the old one's place.
function claim(prefix) {
  return (sp, e, gone) => {
    const g = gone.find((b) => !b.claimed && b.e?.key.startsWith(prefix) && b.e.name === e.name);
    if (!g) return popIn(sp);
    g.claimed = true;
    sp.from({ x: g.sp.V.x, y: g.sp.V.y, r: 0 }).pop(0.2);
    stage.remove(g.sp);
  };
}

// ---- layout: where everything goes for a view of the board ---------------------------------------
// A view: jokers, consumables, the hand (lifted cards, raised while choosing), the played row (scoring cards
// up), the buttons, and the shop, an open pack or the cash-out panel.
export function viewOf(f) {
  const v = { jokers: f.jokers, consumables: f.consumables || [], handSize: f.hand_size ?? 8, hand: f.hand, lifted: [],
    raised: false, buttons: false, play: null, up: [], shop: null, pack: null, withHand: false, handDy: 0, cash: null };
  if (f.kind === "play") Object.assign(v, { hand: f.hand_after ?? f.before.filter((_, k) => !f.picked.includes(k)), play: f.played, up: f.scoring || [] });
  else if (f.kind === "discard") Object.assign(v, { hand: f.before, lifted: f.picked, raised: true, buttons: true });
  else if (f.kind === "shop") Object.assign(v, { hand: [], shop: f.shop });
  else if (f.kind === "pack") Object.assign(v, { pack: f.pack, withHand: f.hand.length > 0, handDy: -150 });
  else if (f.kind === "cash_out") Object.assign(v, { hand: [], cash: f });
  else if (f.kind === "select" || f.kind === "skip") Object.assign(v, { hand: [], select: f });
  else if (f._pack) Object.assign(v, { pack: f._pack, withHand: f.hand.length > 0, handDy: -150 });
  else if (f._offers) Object.assign(v, { hand: [], shop: f._offers });
  else if (choosing(f)) Object.assign(v, { raised: true, buttons: true });
  return v;
}

// How the board looks once a frame's move is over (viewOf is the moment worth stopping on).
export function endViewOf(f) {
  const v = viewOf(f);
  if (f.kind === "play") Object.assign(v, { play: null, up: [] });
  if (f.kind === "cash_out") v.cash = null;
  if (f.kind === "draw" && wonRound(f) && cur) v.hand = cur.hand;
  return v;
}

const wonRound = (f) => !!f.blind && f.round_score >= f.blind.chips;
// A run ended lost: not won, or won and then lost further on (its last blind short of its target).
const lostRun = (f) => !f.won || (!!f.blind && f.round_score < f.blind.chips);
// The player is choosing: a hand is out in a blind that isn't beaten yet.
const choosing = (f) => f.hand.length > 0 && !f._shop && !f._tagged && !wonRound(f) && ["draw", "blind", "use", "sell", "order", "keep"].includes(f.kind);

function entriesFor(v) {
  const out = [];
  tray(v.jokers, TRAYS.jokers, jokerKeys, jokerEl, out, "joker");
  tray(v.consumables, TRAYS.consumables, consumableKeys, consumableEl, out, "consumable");
  handFan(v, out);
  if (v.play) playRow(v, out);
  if (v.buttons) out.push(buttons(v.lifted.length > 0));
  if (v.shop) shopPanel(v.shop, out);
  if (v.pack) packView(v.pack, v.withHand, out);
  if (v.cash) out.push(cashPanel(v.cash));
  if (v.select) selectCards(v.select, out);
  tagColumn(v.tags || [], out);
  if (v.popup) out.push(v.popup);
  if (v.raise?.size) for (const e of out) if (v.raise.has(e.key)) e.y -= RAISE;   // picked in the Play tab
  return out;
}

// Each entry says what it is (`role`) and where in its list (`idx`), for the Play tab's clicks.
// Cards in a tray: first and last touch the tray's ends, the rest evenly between.
function tray(items, [left, width, top], keyer, make, out, type) {
  const n = items.length, ks = keyer(items);
  items.forEach((it, k) => {
    const x = n === 1 ? left + (width - CARD_W) / 2 : left + k * (width - CARD_W) / (n - 1);
    const { now, ...look } = it;          // a joker's growing value is for its tooltip, not a redraw
    out.push({ key: ks[k], name: it.name, role: type, idx: k, x, y: top, z: 1 + k, sway: true, sig: JSON.stringify(look),
      jiggle: !!it.jiggle, info: { type, ...it }, shade: true, make: () => make(it) });
  });
}

function handFan(v, out) {
  const cards = v.hand, n = cards.length, ks = cardKeys(cards, "h");
  const step = HAND.width / Math.max(v.handSize, n), tilt = Math.min(3.2, 13 / n), arc = Math.min(4, 60 / (n * n));
  cards.forEach((c, k) => {
    const off = k - (n - 1) / 2;
    out.push({ key: ks[k], role: "hand", idx: k, x: HAND.center + off * step - CARD_W / 2,
      y: HAND.top + off * off * arc - (v.lifted.includes(k) ? HAND.lift : 0), r: off * tilt, z: 10 + k, sway: true,
      parent: handAnchor, sig: cardSig(c), info: { type: "card", ...c }, shade: true, make: () => cardEl(c) });
  });
}

function playRow(v, out) {
  const n = v.play.length, ks = cardKeys(v.play, "p");
  v.play.forEach((c, k) => out.push({ key: ks[k], x: PLAY.center + (k - (n - 1) / 2) * PLAY.step - CARD_W / 2,
    y: PLAY.top - (v.up.includes(k) ? PLAY.lift : 0), z: 30 + k, sig: cardSig(c), info: { type: "card", ...c }, shade: true, make: () => cardEl(c) }));
}

const cardSig = ({ uid, label, ...look }) => JSON.stringify(look);

function bx(cls, x, y, w, h, html = "") {
  const e = el("div", `bx ${cls}`, html);
  Object.assign(e.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px` });
  return e;
}

// A panel: page-sized, placed by its children, moved as one.
function group(key, cls, z, sig, children) {
  return { key, x: 0, y: 0, m: 0, offset: true, z, sig, juice: false, make: () => {
    const g = el("div", `group ${cls}`);
    g.append(...children());
    return g;
  } };
}

// Play Hand / Sort Hand / Discard, grey until cards are selected.
function buttons(armed) {
  return group("buttons", `hand-buttons ${armed ? "armed" : ""}`, 5, String(armed), () => [
    bx("button-play", 725, 898, 205, 117, '<span class="t">Play Hand</span>'),
    bx("sort-box", 942, 897, 195, 125, '<span class="t">Sort Hand</span>'),
    bx("button-orange sort-pick", 962, 937, 76, 62, '<span class="t">Rank</span>'),
    bx("button-orange sort-pick", 1045, 937, 74, 62, '<span class="t">Suit</span>'),
    bx("button-discard", 1150, 898, 205, 117, '<span class="t">Discard</span>')]);
}

// The cash-out panel: the blind beaten and its reward, a row per other payout, and the Cash Out button. All of it
// starts hidden (`hold`): cashOutMove types each row in a letter at a time and ticks its dollars in one by one, the
// blind's first and the button last, as the game does (footage).
const PAYOUT = { hands: (f) => ["chips", f.hands_left, "Remaining Hands ($1 each)"], discards: (f) => ["mult", f.discards_left, "Remaining Discards ($1 each)"],
  jokers: (f, n) => ["money", n, "Jokers"], interest: (f, n) => ["money", n, `1 interest per $5 (${f.cap ?? 5} max)`] };
const typed = (text) => [...text].map((ch) => `<span class="hold">${ch === " " ? "&nbsp;" : esc(ch)}</span>`).join("");
const ticks = (n) => '<span class="hold tick">$</span>'.repeat(Math.max(0, n));
function cashPanel(f) {
  const b = f.blind || { name: "", chips: 0, reward: 0, kind: 0 };
  const chip = art.chips?.[b.name] ? b.name : ["Small Blind", "Big Blind", "Small Blind"][b.kind];
  const rows = (f.parts || []).filter(([what]) => what !== "blind" && PAYOUT[what]);
  return group("cash", "cash-panel", 6, `${f.earned}|${b.name}`, () => {
    const out = [bx("cash-outer", 595, 372, 898, 760), bx("cash-inner", 607, 385, 875, 115 + 85 * Math.max(1, rows.length) + 155),
      bx("button-orange cash-button hold", 750, 400, 585, 92, `<span class="t">Cash Out: $${f.earned}</span>`),
      el("div", "cash-blind", `<img class="hold" alt="" src="${art.chips?.[chip] || ""}"><span class="t at-least">${typed("Score at least")}</span>`
        + `<span class="t target hold"><i class="chip-icon"></i>${fmt(b.chips)}</span><span class="t money reward">${ticks(b.reward)}</span>`),
      el("div", "cash-rule hold", "")];
    rows.forEach(([what, amount], k) => {
      const [colour, count, label] = PAYOUT[what](f, amount);
      out.push(el("div", "cash-row", `<span class="t n ${colour} hold">${count}</span><span class="t label">${typed(label)}</span>`
        + `<span class="t money">${ticks(Math.min(amount, 12))}</span>`));
      out.at(-1).style.top = `${672 + 85 * k}px`;
    });
    return out;
  });
}

// Shows a panel part's hidden pieces in order: letters 0.018 s apart, dollars 0.15 s apart, each with a little pop.
async function typeIn(node) {
  for (const s of node ? [...node.querySelectorAll(".hold")] : []) {
    s.classList.remove("hold");
    if (s.classList.contains("tick")) {
      s.classList.add("ticked");
      await W(0.15);
    } else if (s.textContent.length <= 1 && s.tagName === "SPAN") await W(0.018);
  }
}

// ---- the shop and booster packs, laid out like the game's shop screen ------------------------------
const SHOP_BG = { colour_1: "#3d775f", colour_2: "#4f9476", colour_3: "#24493a" };
const PACK_EDGE = { Arcana: "#a782d1", Celestial: "#1f9ab1", Spectral: "#4584fa", Standard: "#c94e48", Buffoon: "#fe9a00" };

// In an offer's slot, which starts at the card sprite's corner (MARGIN above and left of the visible card).
function priceTag(o, left, gap) {
  return bx(`price-tag ${o.price === 0 ? "free" : ""}`, left, MARGIN - gap, 84, 46, `<span class="t">${o.price === 0 ? "Free" : "$" + o.price}</span>`);
}

// Offers spaced `step` apart, centred on cx, each with its price tag `gap` px above. Packs are drawn
// 1.25x the size of cards, as in the game's shop.
function offerRow(items, where, cx, top, step, gap, out, gen = null) {
  // (a reroll replaces every card: their keys carry the shop's reroll count, so a card rolled again comes in anew)
  const ks = keys(items, `o:${where}:${gen == null ? "" : `${gen}:`}`, (o) => o.name);
  items.forEach((o, k) => {
    const x = cx + (k - (items.length - 1) / 2) * step, pack = o.kind === "Pack";
    out.push({ key: ks[k], name: o.name, role: "offer", where, idx: k, x: pack ? x - 102 + MARGIN : x - CARD_W / 2, y: top, z: 2 + k,
      sig: JSON.stringify(o), info: { type: "offer", ...o }, make: () => {
      const item = shadowed(itemEl(o));
      if (pack || o.kind === "Voucher") item.dataset.tip = `<b>${esc(o.name)}</b>`;
      Object.assign(item.style, { left: "0px", top: "0px" });
      const slot = el("div", "slot");
      slot.append(item, priceTag(o, pack ? 60 : MARGIN + CARD_W / 2 - 42, gap));
      return slot;
    } });
  });
}

function shopPanel(s, out) {
  const ante = state.frames[state.i]?.ante ?? "";
  out.push(group("shop-panel", "shop-group", 1, `${s.reroll_cost}|${ante}`, () => {
    const edge = el("div", "", "");
    edge.id = "shop-panel-edge";
    return [edge, bx("button-red shop-button", 583, 393, 229, 121, '<span class="t">Next<br>Round</span>'),
      bx("button-green shop-button", 583, 527, 229, 129, `<span class="t">Reroll<b>$${s.reroll_cost}</b></span>`),
      bx("area", 831, 386, 686, 284), bx("area dark", 589, 723, 464, 287, `<span class="side-label t">ANTE ${ante} VOUCHER</span>`),
      bx("area", 1063, 723, 434, 294)];
  }));
  offerRow(s.cards, "card", 1174, 417, 184, 48, out, s._gen ?? 0);
  offerRow(s.vouchers, "voucher", 843, 766, 184, 62, out);
  offerRow(s.packs, "pack", 1284, 737, 192, 32, out);
}

function packView(p, withHand, out) {
  out.push(group("pack-panel", "pack-group", 1, `${p.name}|${p.picks_left}`, () => {
    const edge = el("div", "", "");
    edge.id = "pack-panel-edge";
    edge.style.setProperty("--pack-edge", PACK_EDGE[p.kind] || "#c94e48");
    const title = el("div", "t", esc(p.name));
    title.id = "pack-title";
    const skip = bx("button-red", 998, 1006, 166, 62, '<span class="t">Skip</span>');
    skip.id = "pack-skip";
    return [edge, title, skip, el("div", "t pack-picks", p.picks_left > 1 ? `Choose ${p.picks_left}` : "")];
  }));
  const top = withHand ? 360 : 640, step = Math.min(245, 900 / Math.max(1, p.cards.length)), ks = packKeys(p.cards);
  p.cards.forEach((c, k) => out.push({ key: ks[k], name: c.name, role: "pack", idx: k, x: 1081 + (k - (p.cards.length - 1) / 2) * step - CARD_W / 2,
    y: top, z: 20 + k, sway: true, sig: JSON.stringify(c), info: { type: "offer", ...c }, make: () => shadowed(itemEl(c)) }));
}

// "Choose your next Blind": the ante's three blinds, the next one raised with Select (Small and Big can be
// skipped for their tag), the others Defeated, Skipped or Upcoming. Measured from gameplay footage.
const SELECT = { x: [692, 1045, 1398], top: 372, raised: 312 };
function selectCards(f, out) {
  const blinds = f.ante_blinds || [], next = f.blind?.kind ?? 0;
  const skipped = new Set();
  for (let i = state.i; i >= 0 && state.frames[i].ante === f.ante; i--) if (state.frames[i].kind === "skip") skipped.add(state.frames[i].blind?.kind);
  blinds.forEach((b, k) => {
    const state_ = k < next ? (skipped.has(k) ? "Skipped" : "Defeated") : k === next ? (f.kind === "skip" ? "Skipped" : "Select") : "Upcoming";
    const tag = k < 2 ? f.skip_tags?.[k] : null;
    out.push({ key: `sel:${k}`, role: "select", idx: k, x: SELECT.x[k] - 150, y: k === next ? SELECT.raised : SELECT.top, z: 40 + k,
      sig: `${f.ante}|${b.name}|${state_}|${tag}`,
      make: () => selectCard(b, k, state_, tag, k === next) });
  });
}

function selectCard(b, k, label, tag, active) {
  const colour = art.chip_colours?.[b.name] || ["#3a55ab", "#e0a23a", "#c94e48"][k];
  const chip = art.chips?.[b.name] || art.chips?.[["Small Blind", "Big Blind", "Small Blind"][k]] || "";
  const e = el("div", `sel-card ${active ? "active" : ""} ${k === 2 ? "boss" : ""} ${label.toLowerCase()}`);
  e.style.setProperty("--blind", colour);
  e.innerHTML = (label === "Select" ? '<div class="sel-select t">Select</div>' : `<div class="sel-state t">${esc(label)}</div>`)
    + `<div class="sel-name t">${esc(b.name)}</div>` + (chip ? `<img class="sel-chip" alt="" src="${chip}">` : "")
    + (b.effect ? `<div class="sel-effect t">${esc(b.effect)}</div>` : "")
    + `<div class="sel-score"><span class="t">Score at least</span><span class="t sel-target"><i class="chip-icon"></i>${fmt(b.chips)}</span>`
    + `<span class="t">Reward: <span class="money">${"$".repeat(b.reward)}+</span></span></div>`
    + (k < 2 ? '<div class="sel-or t">or</div><div class="sel-skip">' + (tag ? `<img class="sel-tag" alt="" src="${art.tags?.[tag] || ""}">` : "")
      + '<div class="sel-skip-button t">Skip Blind</div></div>'
      : '<div class="sel-ante t"><b>Up the Ante</b><br>Raise all Blinds<br>Refresh Blinds</div>');
  const icon = e.querySelector(".sel-tag");
  if (icon && tag) icon.dataset.tiphtml = tagTip(tag);
  return e;
}

const tagTip = (name) => `<div class="gt"><div class="gt-name t">${esc(name)}</div><div class="gt-desc">${esc(state.texts?.tags?.[name] || "")}</div></div>`;

// Held tags, as the game keeps them (its HUD tags): the first right of the deck, level with its foot, each one
// after stacked above it; the rest drop down when one is used.
const TAGS = { x: 1788, y: 956, step: 70 };
const GREEN = "#4bc292", MONEY = "#f3b958", EDITION = "#5d5dff";
// The colour a tag flashes as it is used: its pack's for a pack tag, the money colour for one that pays.
const TAG_YEP = { "Rare Tag": "#fe5f55", "Investment Tag": "#eac058", "Juggle Tag": "#009dff", "Double Tag": "#009dff",
  "Foil Tag": EDITION, "Holographic Tag": EDITION, "Polychrome Tag": EDITION, "Negative Tag": EDITION,
  "Economy Tag": MONEY, "Garbage Tag": MONEY, "Handy Tag": MONEY, "Skip Tag": MONEY, "Speed Tag": MONEY,
  "Charm Tag": PACK_EDGE.Arcana, "Meteor Tag": PACK_EDGE.Celestial, "Ethereal Tag": PACK_EDGE.Spectral,
  "Standard Tag": PACK_EDGE.Standard, "Buffoon Tag": PACK_EDGE.Buffoon };

function tagColumn(tags, out) {
  keys(tags, "t:", (name) => name).forEach((key, k) => {
    const name = tags[k];
    out.push({ key, name, x: TAGS.x, y: TAGS.y - k * TAGS.step, z: 5, m: 0, sig: name, spawn: popIn, exit: yep,
      make: () => {
        const e = el("div", "held-tag", `<img alt="${esc(name)}" src="${art.tags?.[name] || ""}">`);
        e.dataset.tiphtml = tagTip(name);
        return e;
      } });
  });
}

// A tag used: its colour covers it with a "+", then it is gone (the game's Tag:yep).
function yep(sp, e) {
  leave(sp, 1);
  sp.z = 70;
  sp.el.style.setProperty("--yep", TAG_YEP[e.name] || GREEN);
  sp.el.append(el("div", "yep t", "+"));
  sp.pop(0.3);
  stage.after(0.6, () => sp.to({ s: 0.5, o: 0 }));
}

// ---- colour themes ---------------------------------------------------------------------------------
// The game tints the sidebar and background with the blind's colour. These shades are fitted to The Wall
// (#8a59a5) in a game screenshot: same hue, saturation and lightness scaled.
function hsl(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
  const h = d === 0 ? 0 : max === r ? 60 * (((g - b) / d) % 6) : max === g ? 60 * ((b - r) / d + 2) : 60 * ((r - g) / d + 4);
  return [(h + 360) % 360, s, l];
}

function hex([h, s, l]) {
  s = Math.min(1, s);
  l = Math.min(1, l);
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = l - c / 2;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return "#" + [r, g, b].map((v) => Math.round((v + m) * 255).toString(16).padStart(2, "0")).join("");
}

function shade(colour, sf, lf) {
  const [h, s, l] = hsl(colour);
  return hex([h, s * sf, l * lf]);
}

function mix(a, b, t) {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16)), pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return "#" + pa.map((v, k) => Math.round(v + (pb[k] - v) * t).toString(16).padStart(2, "0")).join("");
}

function theme(colour) {
  const vars = { "--boss": shade(colour, 1.29, 0.88), "--boss-lip": shade(colour, 1.45, 0.53),
    "--panel": shade(colour, 0.83, 0.556), "--side": mix("#28283c", colour, 0.08) };
  for (const [k, v] of Object.entries(vars)) document.documentElement.style.setProperty(k, v);
  return backdrop(colour);
}

const backdrop = (colour) => ({ colour_1: shade(colour, 0.7, 0.69), colour_2: shade(colour, 1.29, 0.88), colour_3: shade(colour, 1.47, 0.18) });

// The background's colours, faded over half a second when a blind or the shop begins (as in the game).
let bgShown = null;
function paintBackground(colours, fade) {
  if (state.scene) return;
  const from = bgShown;
  bgShown = colours;
  if (!fade || !from) return bg.set(colours);
  const keysC = Object.keys(colours);
  stage.tween(0.5, (p) => bg.set(Object.fromEntries(keysC.map((k) => [k, mix(from[k], colours[k], p)]))))
    .catch(() => { if (bgShown === colours) bg.set(colours); });
}

// The table's colour, as in footage of the game: the shop's green in the shop, between blinds and in Small and Big
// Blinds (their colour goes on the sidebar only); a boss blind's own; an open pack's (Arcana and Spectral measured;
// Celestial a guess at the Planet blue, Buffoon and Standard their packs' colours); red when the run is lost.
const PACK_BG = { Arcana: { colour_1: "#3e2b53", colour_2: "#583e73", colour_3: "#15131d" },
  Spectral: { colour_1: "#0f2e6b", colour_2: "#346ee4", colour_3: "#091a2b" },
  Celestial: { colour_1: "#0f3f5c", colour_2: "#2a9cc4", colour_3: "#08202e" } };
const LOST_BG = { colour_1: "#be3335", colour_2: "#cd4a4a", colour_3: "#8c2427" };
const starry = (on) => document.body.classList.toggle("starry", on);

function blindColours(blind, fade = false) {
  const b = blind || { name: "—", kind: 0 };
  const chip = art.chips?.[b.name] ? b.name : ["Small Blind", "Big Blind", "Small Blind"][b.kind];
  const colour = art.chip_colours?.[chip];
  if (colour && colour !== state.themed) {
    document.documentElement.style.removeProperty("--edge");
    state.themed = colour;
    starry(false);
    const boss = theme(colour);
    paintBackground(b.kind === 2 ? boss : SHOP_BG, fade);
  }
}

function shopColours(fade = false) {
  if (state.themed === "shop") return;
  state.themed = "shop";
  const vars = { "--boss": "#1b2629", "--boss-lip": "#0f1719", "--side": "#2d3a3d", "--edge": "#c94e48" };
  for (const [k, v] of Object.entries(vars)) document.documentElement.style.setProperty(k, v);
  starry(false);
  paintBackground(SHOP_BG, fade);
}

// Between blinds (choosing the next one, cashing out): the shop's dark sidebar without its red edge, on the green.
function betweenColours(fade = false) {
  if (state.themed === "between") return;
  state.themed = "between";
  const vars = { "--boss": "#1b2629", "--boss-lip": "#0f1719", "--side": "#2d3a3d" };
  for (const [k, v] of Object.entries(vars)) document.documentElement.style.setProperty(k, v);
  document.documentElement.style.removeProperty("--edge");
  starry(false);
  paintBackground(SHOP_BG, fade);
}

function packColours(pack, fade = false) {
  const kind = (pack?.name || "").match(/Arcana|Celestial|Spectral|Standard|Buffoon/)?.[0];
  if (state.themed === `pack:${kind}`) return;
  state.themed = `pack:${kind}`;
  starry(kind in PACK_BG);
  paintBackground(PACK_BG[kind] || (PACK_EDGE[kind] ? backdrop(PACK_EDGE[kind]) : SHOP_BG), fade);
}

function lostColours(fade = false) {
  if (state.themed === "lost") return;
  state.themed = "lost";
  starry(false);
  paintBackground(LOST_BG, fade);
}

// A frame's colours, shown as it stands (show) or faded to (generic moves).
function sceneColours(f, fade = false) {
  const pack = f.kind === "pack" ? f.pack : f._pack;
  if (f.kind === "end" && lostRun(f)) lostColours(fade);
  else if (pack) packColours(pack, fade);
  else if (f._shop) shopColours(fade);
  else if (["select", "skip", "cash_out"].includes(f.kind)) betweenColours(fade);
  else blindColours(f.blind, fade);
}

// ---- the sidebar --------------------------------------------------------------------------------------
function setBlind(blind) {
  const b = blind || { name: "—", chips: 0, reward: 0, kind: 0 };
  $("#blind-chip").classList.remove("burnt");
  $("#blind-name").textContent = b.name;
  $("#blind-desc").textContent = b.desc ?? (b.kind === 2 ? state.bosses[b.name] || "" : "");
  const chip = art.chips?.[b.name] ? b.name : ["Small Blind", "Big Blind", "Small Blind"][b.kind];
  $("#blind-chip").src = art.chips?.[chip] || "";
  $("#target").textContent = fmt(b.chips);
  $("#reward").textContent = "$".repeat(b.reward);
}

// Set a sidebar number; with `juice`, it swells and wobbles as it changes, like the game's.
export function setText(id, text, juice = false) {
  const e = $(`#${id}`);
  if (e.textContent === String(text)) return;
  e.textContent = text;
  if (juice) ui[id]?.pop(0.3, 2);
}

function count(id, from, to, dur, show = fmt) {
  return stage.tween(dur, (p) => setText(id, show(from + (to - from) * p)));
}

export function sidebar(f, juice = false) {
  // between rounds (the cash-out counted it away) the round score is 0, as the game shows it
  const between = f._shop || f._tagged || f.in_round === false || ["select", "skip", "cash_out"].includes(f.kind);
  setBlind(f.blind);
  setText("round-score", fmt(between ? 0 : f.round_score), juice);
  setText("hands", f.hands_left, juice);
  setText("discards", f.discards_left, juice);
  setText("money", `$${f.money}`, juice);
  $("#ante").textContent = f.ante;
  $("#round-num").textContent = f.round ?? "";
  // as in the game, a Negative card counts and raises the limit by one (so it takes no slot)
  const negatives = (xs) => xs.filter((x) => x.edition === "Negative").length;
  $("#joker-count").textContent = `${f.jokers.length}/${(f.joker_slots ?? 5) + negatives(f.jokers)}`;
  $("#consumable-count").textContent = `${(f.consumables || []).length}/${(f.consumable_slots ?? 2) + negatives(f.consumables || [])}`;
  // and the whole deck is back in the pile (the run's pile only fills at a blind)
  const left = between ? f.deck_size : f.deck_left;
  $("#deck-count").textContent = `${left}/${f.deck_size}`;
  deckPile(left);
}

export function showHand(h, juice = false) {
  $("#hand-name").textContent = h ? h.name : "";
  $("#hand-level").textContent = h?.level ? `lvl.${h.level}` : "";
  setText("chips", h ? fmt(h.chips) : "0", juice);
  setText("mult", h ? fmtMult(h.mult) : "0", juice);
  if (juice) ui["hand-name-row"].pop(0.25, 1.5);
}

function deckPile(count) {
  const pile = $("#deck-pile");
  const layers = Math.min(4, Math.max(1, Math.ceil(count / 15))), sig = `${layers}|${view.deckBack}`;
  if (pile.dataset.sig === sig) return;
  pile.dataset.sig = sig;
  pile.replaceChildren(...Array.from({ length: layers }, (_, k) => {
    const e = el("div", "deck-card", `<img alt="" src="${art.decks?.[view.deckBack] || ""}">`);
    e.style.left = e.style.top = `${-(layers - 1 - k) * 2}px`;
    return e;
  }));
}

export function scoreLog(f) {
  if (!$("#score-log")) return;                                   // (the run viewer's dock; not on the Play tab)
  $("#score-log").replaceChildren(...(f.kind === "play" ? f.score_log || [] : []).map(([src, kind, amount], k) => {
    const text = k === 0 ? `${kind}` : kind === "xmult" ? `×${amount}` : kind === "$" ? `+$${amount}` : `${kind[0]}${fmt(amount)} ${kind.slice(1)}`;
    const by = f.jokers?.[(f.score_who || [])[k]]?.name;            // a copier: "Blueprint → Blue Joker"
    const label = by && !src.startsWith(by) ? `${by} → ${src}` : src;
    return el("li", "", `<span>${esc(label)}</span><b>${esc(text)}</b>`);
  }));
}

// How a run ended, from its last frame. Its blind is the one it fell short on, or (a run stopped by "Up to ante",
// which ends one ante past the last boss beaten) that boss, beaten: a score short of the target is a loss.
export function endText(f) {
  const b = f.blind, short = b && f.round_score < b.chips;
  const where = `ante ${f.ante}${b ? `, ${b.name}${short ? ` (${fmt(f.round_score)} of ${fmt(b.chips)})` : ""}` : ""}`;
  if (!f.won) return `Lost at ${where}.`;
  return short ? `Won at ante 8, then lost at ${where}.` : `Won: beat ante ${f.ante - 1}, the last ante this run was set to play.`;
}

export function banner(f) {
  let text = "";
  if (f.kind === "play") text = `${f.hand_name} for ${fmt(f.total)}${f.earned ? ` and $${f.earned}` : ""}`;
  else if (f.kind === "discard") text = `Discard ${f.discarded.length} card${f.discarded.length > 1 ? "s" : ""}`;
  else if (f.kind === "shop") text = f.did || "Shop";
  else if (f.kind === "pack") text = f.did || f.pack.name;
  else text = {
    blind: `${f.blind?.name}: score at least ${fmt(f.blind?.chips ?? 0)}`,
    select: `Choose your next Blind: ${f.blind?.name}`,
    draw: "Draw",
    skip: `Skipped the ${f.blind?.name}${f.tag ? ` for the ${f.tag}` : ""}`,
    use: `Used ${f.used}${f.targets?.length ? ` on ${f.targets.map((c) => c.label).join(", ")}` : ""}`,
    sell: `Sold ${f.item?.name} for $${f.value}`,
    cash_out: `Cash out: +$${f.earned}`,
    held: `Gold cards held: +$${f.earned}`,
    end: `${endText(f)} Best hand ${fmt(f.best_hand)}.`,
  }[f.kind] || "";
  $("#banner").textContent = text;
  if ($("#scrub")) $("#scrub").value = state.i;                    // (the run viewer's timeline; not on the Play tab)
  if ($("#step-label")) $("#step-label").textContent = `${state.i + 1}/${state.frames.length} · Ante ${f.ante} · ${f.blind?.name ?? ""} · ${f.kind.replace("_", " ")}`;
}

// ---- showing a frame as it stands (jumps, scrubbing, scene snapshots) ---------------------------------
let cur = null;   // the view the board was last brought to

// The hand sits on its anchor: raised while the player chooses, higher still over an open pack. The tags held
// are always the frame's on screen (moves build their views from the last one).
export function put(v, opts = {}) {
  v.tags = state.frames[state.i]?._tags ?? [];
  cur = v;
  handAnchor.to({ y: (v.raised ? HAND.raise : 0) + v.handDy });
  if (opts.snap) handAnchor.snap();
  sync(entriesFor(v), opts);
  $("#hand-count").textContent = `${v.hand.length}/${v.handSize}`;
  $("#hand-count").style.visibility = v.pack ? "hidden" : "";   // (under an open pack's panel)
}

export function show(f) {
  for (const sp of leaving) stage.remove(sp);
  leaving.clear();
  sidebar(f);
  document.body.classList.toggle("in-shop", !!f._shop);
  improveTyped();
  sceneColours(f);
  flames?.reset();
  $("#hand-box")?.classList.remove("total");
  if (f.kind === "end") endScreen(f, false);
  else endScreen(null);
  showHand(f.kind === "play" ? { name: f.hand_display ?? f.hand_name, level: f.level, chips: f.chips, mult: f.mult } : null);
  const v = viewOf(f);
  if (f.popup) v.popup = scenePopup(f);
  put(v, { snap: true });
  ui["blind-box"].to({ y: f._shop || f._tagged || ["cash_out", "select", "skip"].includes(f.kind) ? ABOVE : 0 });
  ui["shop-sign"].to({ y: 0 });
  for (const sp of Object.values(ui)) sp.snap();
  scoreLog(f);
  banner(f);
  stage.paint();
}

// The score popup of a scene recreated from a screenshot, where the screenshot has it.
function scenePopup(f) {
  const n = f.played.length;
  return { key: "scene-popup", x: PLAY.center + (f.popup.card - (n - 1) / 2) * PLAY.step - 18, y: 460 - 92, m: 0, offset: false, z: 80,
    make: () => el("div", "popup t", esc(f.popup.text)) };
}

// ---- moving from one frame to the next, in the game's order and timing (seconds at 1x) ---------------
const W = (sec) => stage.wait(sec);

// The cards of the hand to be played or discarded rise one at a time, then the button is pressed: the
// buttons drop away and the hand settles back into its tray.
async function choose(f, v) {
  // Cards a person picked on the Play tab are up already (state.picked_at: the frame of the move they made).
  const up = state.picked_at === state.i;
  Object.assign(v, { hand: f.before, lifted: up ? [...f.picked] : [], raised: true, buttons: true, play: null, up: [], handDy: 0 });
  put(v, { spawn: fromDeck });
  await W(up ? 0.1 : 0.2);
  for (const k of up ? [] : f.picked) {
    v.lifted = [...v.lifted, k];
    put(v);
    await W(0.12);
  }
  if (f.kind === "play") {
    const base = f.score_trail?.[0] ?? [f.chips, f.mult];
    showHand({ name: f.hand_display ?? f.hand_name, level: f.level, chips: base[0], mult: base[1] }, true);
  }
  await W(0.35);
  Object.assign(v, { buttons: false, raised: false });
  put(v, { exit: dropOut });
  setText("hands", f.hands_left, f.kind === "play");
  setText("discards", f.discards_left, f.kind === "discard");
}

async function playMove(prev, f) {
  const v = { ...cur };
  await choose(f, v);
  await W(0.45);
  // The cards go up one at a time; the row stays centred and the hand closes up behind them.
  const going = f.picked.map((k) => f.before[k]);
  for (let j = 0; j < going.length; j++) {
    const moved = new Set(going.slice(0, j + 1));
    v.hand = f.before.filter((c) => !moved.has(c));
    v.lifted = v.hand.map((c, k) => (going.includes(c) ? k : -1)).filter((k) => k >= 0);
    v.play = f.played.slice(0, j + 1);
    put(v);
    await W(0.07);
  }
  if (f.hand_after) { v.hand = f.hand_after; put(v); }
  await W(0.45);
  for (const k of f.scoring || []) {
    v.up = [...v.up, k];
    put(v);
    await W(0.1);
  }
  await W(0.55);
  await tally(prev, f, v);
}

// Each effect in scoring order: its card or joker juices, its popup shows and the numbers change, 0.8 s apart.
const POPUP = { "+chips": (a) => `+${fmt(a)}`, "+mult": (a) => `+${fmtMult(a)} Mult`, xmult: (a) => `X${a} Mult`, $: (a) => `$${a}` };
async function tally(prev, f, v) {
  const log = f.score_log || [], trail = f.score_trail || [], who = f.score_who || [];
  // the flames come up once the hand being scored reaches the blind's whole target on its own (not what is left of
  // it: footage, a Big Blind of 450 with 316 scored had none at 55x8 = 440 and caught at 63x8 = 504), small at the
  // target and taller the further past it (a hand at 1.35x it and up flares high)
  const need = f.blind ? Math.max(1, f.blind.chips) : Infinity;
  let hot = false;
  const heat = (cm) => {
    if (cm && cm[0] * cm[1] >= need) { hot = true; flames?.ignite(cm[0] * cm[1]); }   // (flames.js: how big, by the score)
  };
  let money = prev.money, pos = 0;
  heat(trail[0]);
  for (let k = 1; k < log.length; k++) {
    const [src, kind, amount] = log[k];
    const hit = source(src, f, v, pos, who[k]);
    if (hit) {
      pos = hit.pos ?? pos;
      hit.sp.pop();
      if (POPUP[kind]) popup(hit.x, hit.y, POPUP[kind](amount), kind, hit.small);
    }
    if (trail[k]) {
      setText("chips", fmt(trail[k][0]), true);
      setText("mult", fmtMult(trail[k][1]), true);
      heat(trail[k]);
    }
    if (kind === "$") setText("money", `$${(money += amount)}`, true);
    await W(0.8);
  }
  await W(1.0);
  // The hand's score takes the place of its name, and chips and mult empty...
  $("#hand-level").textContent = "";
  $("#hand-name").textContent = fmt(f.total);
  $("#hand-box").classList.add("total");
  if (hot) flames?.settle();
  ui["hand-name-row"].pop(0.35, 3);
  setText("chips", "0", true);
  setText("mult", "0", true);
  await W(0.85);
  // ...then it counts over into the round score.
  const from = prev.round_score ?? 0;
  await stage.tween(0.5, (p) => {
    setText("round-score", fmt(from + (f.round_score - from) * p));
    $("#hand-name").textContent = p < 1 ? fmt(f.total * (1 - p)) : "";
  });
  burn(false);
  await W(0.3);
  // The played cards go to the discard pile one at a time; broken Glass cards shatter where they are.
  const broken = [...(f.destroyed || [])], ks = cardKeys(v.play, "p");
  for (let k = 0; k < v.play.length; k++) {
    const b = board.get(ks[k]);
    board.delete(ks[k]);
    const d = broken.indexOf(v.play[k].label);
    if (d >= 0) broken.splice(d, 1);
    if (b) d >= 0 ? spent(b.sp) : toss(b.sp);
    await W(0.08);
  }
  Object.assign(v, { play: null, up: [] });
  cur = v;
  showHand(null);
}

// Which card or joker an effect comes from, and where its popup goes: above a card, below a joker. `at`: the place
// of the joker that acted (score_who), so each of two twins juices for itself and Blueprint for what it copies;
// frames saved before it was recorded go by name.
function source(src, f, v, pos, at) {
  const name = src.replace(/ \([^)]*\)$/, "");
  const spot = (key, below, extra) => {
    const b = board.get(key);
    if (!b) return null;
    const g = b.sp.goal;
    return { sp: b.sp, x: g.x + CARD_W / 2, y: below ? g.y + CARD_H + 40 : g.y - 54, small: below, ...extra };
  };
  if (at != null && v.jokers[at]) return spot(jokerKeys(v.jokers)[at], true);
  if (/held\)$/.test(src)) {
    const k = v.hand.findIndex((c) => c.label === name);
    if (k >= 0) return spot(cardKeys(v.hand, "h")[k], false);
  }
  const sc = f.scoring || [];
  const i = [...sc.slice(pos), ...sc.slice(0, pos)].find((i) => f.played[i]?.label === name);
  if (i !== undefined && v.play) return spot(cardKeys(v.play, "p")[i], false, { pos: sc.indexOf(i) });
  const j = v.jokers.findIndex((x) => x.name === name);
  if (j >= 0) return spot(jokerKeys(v.jokers)[j], true);
  const c = v.consumables.findIndex((x) => x.name === name);
  if (c >= 0) return spot(consumableKeys(v.consumables)[c], true);
  return null;
}

// "+11", "+4 Mult": grows in a letter at a time over its badge, holds, then breaks up.
function popup(x, y, text, kind, small = false) {
  const cls = { "+chips": "chips", $: "dollars", plus: "plus", spent: "spent" }[kind] || "mult";
  const node = el("div", "popup-at", `<div class="pop t ${cls} ${small ? "small" : ""}">`
    + `${[...text].map((ch) => `<span class="hold">${ch === " " ? "&nbsp;" : esc(ch)}</span>`).join("")}</div>`);
  $("#layer").append(node);
  const sp = stage.add(new Sprite(node, { x, y }));
  sp.from({ s: 0.2 });
  leaving.add(sp);
  stage.paint();
  [...node.querySelectorAll(".hold")].forEach((s, k) => stage.after(0.025 * k, () => s.classList.remove("hold")));
  stage.after(0.62, () => sp.to({ s: 0.4, o: 0, r: 25 }));
  stage.after(0.85, () => { leaving.delete(sp); stage.remove(sp); });
}

// A boss blind's effect across the table as its hand is dealt (footage, The Hook at 9:43): the line comes in a few
// letters a frame (all of it in ~0.15 s) while a swell runs along it, each letter to ~1.9x with a tilt, 0.02 s apart;
// it holds ~2.85 s, then every letter shrinks away where it stands in 0.25 s. The game's line is short; a longer
// effect wraps, at most two lines (the font shrinks to keep it so).
const ANNOUNCE = { x: 1035, y: 528, size: 69, width: 1300, advance: 0.363 };  // advance: a letter's width per px of size
function announce(text) {
  if (!text) return;
  const size = Math.min(ANNOUNCE.size, (1.85 * ANNOUNCE.width) / (text.length * ANNOUNCE.advance));   // (slack for wrapping)
  const words = text.split(/\s+/).map((w) => `<span class="word">${[...w].map((ch) => `<span class="hold">${esc(ch)}</span>`).join("")}</span>`);
  const node = el("div", "popup-at", `<div class="announce t" style="font-size:${size.toFixed(1)}px;--k:${(1 / stage.speed).toFixed(3)}">${words.join(" ")}</div>`);
  $("#layer").append(node);
  const sp = stage.add(new Sprite(node, { x: ANNOUNCE.x, y: ANNOUNCE.y }));
  leaving.add(sp);
  stage.paint();
  const line = node.firstChild;
  [...line.querySelectorAll(".hold")].forEach((s, k) => {
    stage.after(0.004 * k, () => s.classList.remove("hold"));
    stage.after(0.02 * k, () => { s.style.setProperty("--r", `${((Math.random() - 0.5) * 24).toFixed(0)}deg`); s.classList.add("swell"); });
  });
  stage.after(2.85, () => line.classList.add("gone"));
  stage.after(3.15, () => { leaving.delete(sp); stage.remove(sp); });
}

// "Improve your run!" under the SHOP sign types itself in once the sign has landed (footage, 11:05.9, every frame at
// 60 fps): the first letter 0.57 s after the sign starts to drop, then one every 0.019 s (the line in ~0.32 s), each
// popping in small and full size two frames later. improveTyped() puts the whole line back (a jump cancels the timers).
const IMPROVE = { start: 0.57, step: 0.019 };
function typeImprove() {
  const line = $("#shop-sign .improve");
  if (!line) return;
  line.innerHTML = typed(line.textContent.replace(/ /g, " "));
  line.style.setProperty("--k", (1 / stage.speed).toFixed(3));
  [...line.querySelectorAll(".hold")].forEach((s, k) =>
    stage.after(IMPROVE.start + IMPROVE.step * k, () => { s.classList.remove("hold"); s.classList.add("grow"); }));
}

function improveTyped() {
  for (const s of document.querySelectorAll("#shop-sign .improve .hold, #shop-sign .improve .grow")) s.classList.remove("hold", "grow");
}

async function discardMove(prev, f) {
  const v = { ...cur };
  await choose(f, v);
  await W(0.3);
  // The selected cards go to the discard pile one at a time; the hand closes up behind each.
  const going = f.picked.map((k) => f.before[k]);
  for (let j = 0; j < going.length; j++) {
    const moved = new Set(going.slice(0, j + 1));
    v.hand = f.before.filter((c) => !moved.has(c));
    v.lifted = v.hand.map((c, k) => (going.includes(c) ? k : -1)).filter((k) => k >= 0);
    put(v, { exit: toss });
    await W(0.08);
  }
  await W(0.25);
}

// New cards come off the deck one at a time, 0.13 s apart; the hand re-spaces for each.
async function dealCards(v, target, f) {
  const ks = cardKeys(target, "h"), have = new Set(cardKeys(v.hand, "h").filter((k) => ks.includes(k)));
  v.hand = target.filter((_, k) => have.has(ks[k]));
  put(v);
  let left = f.deck_left + target.length - have.size;
  for (let k = 0; k < target.length; k++) {
    if (have.has(ks[k])) continue;
    have.add(ks[k]);
    v.hand = target.filter((_, j) => have.has(ks[j]));
    put(v, { spawn: fromDeck });
    $("#deck-count").textContent = `${--left}/${f.deck_size}`;
    await W(0.13);
  }
}

async function drawMove(prev, f) {
  const v = { ...cur };
  if (wonRound(f)) return;   // the game deals no more once the blind is beaten
  await dealCards(v, f.hand, f);
  await W(0.3);
  if (choosing(f)) {
    Object.assign(v, { raised: true, buttons: true });
    put(v, { spawn: riseIn });
  }
  await W(0.25);
}

async function blindMove(prev, f) {
  const v = { ...cur, shop: null, pack: null, cash: null, select: null, play: null, hand: [], lifted: [], buttons: false, raised: false, handDy: 0 };
  put(v, { exit: dropOut });
  document.body.classList.remove("in-shop");
  setBlind(f.blind);
  ui["blind-box"].to({ y: 0 });
  blindColours(f.blind, true);
  await W(0.6);
  await dealCards(v, f.hand, f);
  if (f.blind?.kind === 2) announce(f.blind.desc ?? state.bosses[f.blind.name]);   // as the last card lands
  await W(0.3);
  Object.assign(v, { raised: true, buttons: true });
  put(v, { spawn: riseIn });
  await W(0.25);
}

async function cashOutMove(prev, f) {
  const v = { ...cur, buttons: false, raised: false, lifted: [] };
  put(v, { exit: dropOut });
  await W(0.2);
  // Any played cards still out go to the discard pile; what is left of the hand slides back onto the deck (footage:
  // the deck's count climbs as it goes in), then the discard pile follows it in.
  for (const key of cardKeys(v.play || [], "p")) {
    const b = board.get(key);
    board.delete(key);
    if (b) toss(b.sp);
    await W(0.07);
  }
  let left = prev.deck_left ?? 0;
  for (const key of cardKeys(v.hand, "h")) {
    const b = board.get(key);
    board.delete(key);
    if (b) toDeck(b.sp);
    $("#deck-count").textContent = `${++left}/${f.deck_size}`;
    await W(0.06);
  }
  Object.assign(v, { hand: [], play: null, up: [] });
  cur = v;
  await W(0.3);
  for (let k = 0; k < 8; k++) {
    returnCard();
    await W(0.05);
  }
  $("#deck-count").textContent = `${f.deck_size}/${f.deck_size}`;
  await W(0.35);
  // The cash-out panel comes up empty and the blind's row types in; then the blind's chip burns away, its panel leaves
  // the sidebar and the table fades to the green between blinds; then the other rows, and last the Cash Out button.
  v.cash = f;
  put(v, { spawn: riseIn });
  const panel = board.get("cash")?.sp.el;
  await W(0.6);
  await typeIn(panel?.querySelector(".cash-blind"));
  burnChip();
  await W(0.5);
  ui["blind-box"].to({ y: ABOVE });
  betweenColours(true);
  await W(0.3);
  panel?.querySelector(".cash-rule")?.classList.remove("hold");
  await W(0.3);
  for (const row of panel?.querySelectorAll(".cash-row") || []) {
    await typeIn(row);
    await W(0.15);
  }
  panel?.querySelector(".cash-button")?.classList.remove("hold");
  await (state.hold?.(f) || W(1.1));      // the Play tab waits here for its Cash Out button (state.hold)
  // Cash out: the panel drops away, the round score empties and the money counts up.
  v.cash = null;
  put(v, { exit: dropOut });
  await W(0.3);
  await count("round-score", prev.round_score, 0, 0.35);
  moneyPopup(`+$${f.earned}`);
  await count("money", prev.money, f.money, 0.4, (n) => `$${Math.round(n)}`);
  await W(0.3);
}

// A card from the discard pile (off the right edge) flying back onto the deck.
function returnCard() {
  const node = el("div", "deck-card", backHTML());
  $("#layer").append(node);
  const sp = stage.add(new Sprite(node, { x: DECK.x, y: DECK.y }, { m: MARGIN, lean: true }));
  sp.from({ x: 1980, y: 660 + Math.random() * 160, r: -15 });
  sp.z = 40;
  stage.paint();
  leave(sp, 0.45);
}

// A popup on a sidebar box: the money's "+$11" or "-$6", the ante's or round's "+1".
function boxPopup(id, text, kind, dy = 10) {
  const box = $(`#${id}`).getBoundingClientRect(), game = $("#game").getBoundingClientRect(), k = 1920 / game.width;
  popup((box.left - game.left + box.width / 2) * k, (box.top - game.top) * k + dy, text, kind, true);
}
const moneyPopup = (text, kind = "$") => boxPopup("money-box", text, kind);

// What is left of a won round's hand goes back onto the deck, turning face down on the way.
function toDeck(sp) {
  leave(sp, 0.5);
  sp.parent = null;
  sp.z = 45;
  sp.to({ x: DECK.x, y: DECK.y, r: 0, s: 1 });
  stage.after(0.12, () => sp.flip(() => { sp.face = null; sp.el.innerHTML = backHTML(); }));
}

// The beaten blind's chip burns away (footage): it flares and shrinks to nothing while embers rise off it.
function burnChip() {
  const chip = $("#blind-chip"), panel = $("#blind-panel");
  chip.classList.add("burnt");
  for (let k = 0; k < 12; k++) {
    const e = el("i", "ember");
    e.style.cssText = `left:${25 + Math.random() * 85}px;top:${100 + Math.random() * 70}px;--dx:${((Math.random() - 0.5) * 90).toFixed(0)}px;`
      + `animation-delay:${(Math.random() * 0.3).toFixed(2)}s`;
    panel.append(e);
    stage.after(1.4, () => e.remove());
  }
}

// A pack bursting open: white squares fly out from its middle and fade.
function burst(x, y) {
  for (let k = 0; k < 28; k++) {
    const a = Math.random() * Math.PI * 2, d = 120 + Math.random() * 220, size = 10 + Math.floor(Math.random() * 4) * 6;
    const s = el("i", "shard");
    s.style.cssText = `left:${x}px;top:${y}px;--s:${size}px;--dx:${(Math.cos(a) * d).toFixed(0)}px;--dy:${(Math.sin(a) * d * 0.8).toFixed(0)}px`;
    $("#layer").append(s);
    stage.after(0.8, () => s.remove());
  }
}

// The flames over the chips and mult boxes die away (flames.js lights them).
function burn() {
  flames?.out();
  $("#hand-box")?.classList.remove("total");
}

async function shopMove(prev, f) {
  const v = { ...cur, hand: [], play: null, cash: null, buttons: false, raised: false, lifted: [] };
  document.body.classList.add("in-shop");
  shopColours(true);
  if (prev._shop && prev.kind !== "pack") {
    // Still in the shop. A bought card flies from its slot into its tray (a voucher or pack is used up where it
    // stands); a reroll dissolves the cards and new ones materialise.
    Object.assign(v, { shop: f.shop, jokers: f.jokers, consumables: f.consumables || [] });
    if (f.act?.do === "reroll") put(v, { spawn: materialise(), exit: vanish });
    else put(v, { spawn: claim("o:"), exit: (sp, e) => (e.key.startsWith("o:") ? spent(sp) : vanish(sp)) });
    if (f.money < prev.money) moneyPopup(`-$${prev.money - f.money}`, "spent");
    await count("money", prev.money, f.money, 0.3, (n) => `$${Math.round(n)}`);
    await W(0.5);
    return;
  }
  // Opening the shop: its sign drops into the sidebar, the panel comes up empty, then the offers materialise.
  if (!prev._shop) {
    ui["shop-sign"].from({ y: ABOVE }).to({ y: 0 });
    typeImprove();
  }
  Object.assign(v, { pack: null, withHand: false, handDy: 0, shop: { ...f.shop, cards: [], vouchers: [], packs: [] } });
  put(v, { spawn: riseIn, exit: dropOut });
  await W(0.25);
  v.shop = f.shop;
  put(v, { spawn: materialise() });
  await W(0.7);
}

async function packMove(prev, f) {
  const v = { ...cur };
  if (/^Opened/.test(f.did || "")) {
    // The shop (or, for a pack a tag opened, the blinds) drops away while the pack bought flies to the middle, shakes
    // and bursts (footage) as the table takes the pack's colour; then its panel comes up and its cards materialise
    // (and a hand is dealt, for packs whose cards are used on cards).
    const key = [...board.keys()].find((k) => k.startsWith("o:pack:") && board.get(k).e?.name === f.pack.name);
    const bought = key ? board.get(key) : null;
    if (bought) board.delete(key);
    Object.assign(v, { shop: null, select: null, cash: null, hand: [], play: null });
    put(v, { exit: dropOut });
    if (f.money < prev.money) moneyPopup(`-$${prev.money - f.money}`, "spent");
    packColours(f.pack, true);
    if (bought) {
      const sp = bought.sp;
      sp.el.querySelector(".price-tag")?.remove();
      sp.z = 70;
      sp.to({ x: 1081 - 102, y: 400, r: 0, s: 1.2 });
      await W(0.5);
      for (let k = 0; k < 3; k++) {
        sp.pop(0.3 + 0.15 * k);
        await W(0.2);
      }
      burst(sp.V.x + 102, sp.V.y + 130);
      stage.remove(sp);
      await W(0.15);
    } else await W(0.3);
    Object.assign(v, { pack: f.pack, withHand: f.hand.length > 0, handDy: -150 });
    const appear = materialise(0.08);
    put(v, { spawn: (sp, e) => (e.key === "pack-panel" ? riseIn(sp) : appear(sp)) });
    if (v.withHand) {
      await W(0.4);
      await dealCards(v, f.hand, f);
    }
    await W(0.6);
    return;
  }
  // A pick flies to its tray (a Planet is used on the spot); a skip dissolves what is left.
  Object.assign(v, { pack: f.pack, jokers: f.jokers, consumables: f.consumables || [], hand: v.withHand ? f.hand : [] });
  put(v, { spawn: claim("x"), exit: (sp, e) => (e.key.startsWith("x") ? spent(sp) : vanish(sp)) });
  await W(0.6);
}

// A consumable (from its tray, an open pack, or the shop if bought to use) moves up to the middle of the
// board, juices with its targets, and dissolves.
async function useMove(prev, f) {
  const v = { ...cur };
  const key = [...board.keys()].find((k) => /^(k|x|o:card:)/.test(k) && board.get(k).e?.name === f.used);
  if (key) {
    const { sp } = board.get(key);
    board.delete(key);
    sp.el.querySelector(".price-tag")?.remove();
    sp.z = 70;
    sp.to({ x: 880, y: 330, r: 0, s: 1.1 });
    await W(0.35);
    sp.pop(0.4);
    const targets = new Set((f.targets || []).map((c) => (c.uid ? `c${c.uid}` : c.label)));
    for (const [k, b] of board) if (targets.has(k)) b.sp.pop();
    await W(0.4);
    vanish(sp);
  }
  put(Object.assign(v, endViewOf(f)));
  sidebar(f, true);
  await W(0.5);
}

async function sellMove(prev, f) {
  const key = [...board.keys()].find((k) => /^[jk]/.test(k) && board.get(k).e?.name === f.item?.name);
  if (key) {
    const { sp } = board.get(key);
    board.delete(key);
    spent(sp);
  }
  moneyPopup(`+$${f.value}`);
  await count("money", prev.money, f.money, 0.3, (n) => `$${Math.round(n)}`);
  put({ ...cur, ...endViewOf(f) });
  await W(0.4);
}

// Anything else (skips, boss rerolls, reordering jokers): everything springs to its new place.
async function generic(prev, f) {
  sceneColours(f, true);
  document.body.classList.toggle("in-shop", !!f._shop);
  ui["blind-box"].to({ y: f._shop || f._tagged ? ABOVE : 0 });
  sidebar(f, true);
  put(endViewOf(f), { exit: vanish });
  await W(0.6);
}

// Choosing the next blind (or skipping one): the blinds rise from below, the blind panel steps aside.
async function selectMove(prev, f) {
  document.body.classList.remove("in-shop");
  betweenColours(true);
  ui["blind-box"].to({ y: ABOVE });
  sidebar(f, true);
  put(viewOf(f), { spawn: riseIn, exit: dropOut });
  await W(f.kind === "skip" ? 0.7 : 0.9);
  await state.hold?.(f);                  // (the Play tab: the boss's Select)
}

// As the round ends, each Gold card still held pays: it juices with its "$3" and the money counts up, one by one.
async function heldMove(prev, f) {
  const v = { ...cur, buttons: false };
  put(v);
  const keys = cardKeys(v.hand, "h");
  let money = prev.money;
  for (const [i, amount] of f.paid || []) {
    const k = v.hand.findIndex((c) => c.uid === f.hand[i]?.uid);
    const b = k >= 0 ? board.get(keys[k]) : null;
    if (b) {
      b.sp.pop();
      popup(b.sp.goal.x + CARD_W / 2, b.sp.goal.y - 54, `$${amount}`, "$");
    }
    setText("money", `$${(money += amount)}`, true);
    await W(0.45);
  }
  await W(0.4);
}

// The run's end, as the game shows a loss (footage): the table turns red under a red wash, the GAME OVER panel with
// the run's numbers comes up, and Jimbo tumbles in beside it with a line. A win shows YOU WIN! the same way, its
// title in gold and the table as it is (no footage of a win to go by).
async function endMove(prev, f) {
  put({ ...cur, buttons: false, raised: false });
  sidebar(f, true);
  showHand(null);
  await W(0.5);
  endScreen(f, true);
  await W(1.2);
}

const QUIPS = { lost: ["Even a fool knows when to fold.", "The deck had other plans.", "Shuffle up. Again?", "That blind was rigged. Probably.",
  "Chin up, it's only cards."], won: ["Now that's a hand!", "Jimbo approves.", "Encore? The endless antes await."] };

// The end screen over the board (`f`: the run's last frame; null takes it away). `animate`: tumble in, else just be there.
function endScreen(f, animate = false) {
  $("#end-screen")?.remove();
  $("#wash")?.classList.remove("on");
  if (!f) return;
  const lost = lostRun(f), b = f.blind, s = f.stats || {};
  if (lost) lostColours(animate);
  const wash = $("#wash") || $("#layer").insertAdjacentElement("afterend", el("div", "", ""));
  wash.id = "wash";
  if (lost) animate ? requestAnimationFrame(() => wash.classList.add("on")) : wash.classList.add("on");
  const chip = b && (art.chips?.[b.name] ? b.name : ["Small Blind", "Big Blind", "Small Blind"][b.kind]);
  const most = s.most_played ? `${esc(s.most_played[0])} <small>(${s.most_played[1]})</small>` : "—";
  const row = (label, value, cls = "") => `<div class="end-row"><span class="lab t">${label}</span><span class="val t ${cls}">${value ?? "—"}</span></div>`;
  const quips = QUIPS[lost ? "lost" : "won"];
  const node = el("div", `${lost ? "lost" : "won"} ${animate ? "animate" : ""}`, `
    <div class="end-panel">
      <div class="end-title t">${lost ? "GAME OVER" : "YOU WIN!"}</div>
      <div class="end-stats">
        ${row("Best Hand", `<i class="chip-icon"></i>${fmt(f.best_hand ?? 0)}`, "wide red")}
        ${row("Most Played Hand", most, "wide")}
        <div class="end-cols">
          <div class="end-col">
            ${row("Cards Played", s.cards_played, "blue")}${row("Cards Discarded", s.cards_discarded, "red")}
            ${row("Cards Purchased", s.cards_bought, "gold")}${row("Times Rerolled", s.rerolls, "green")}
            ${row("Seed", s.seed ? esc(s.seed) : null, "seed")}
          </div>
          <div class="end-col">
            ${row("Ante", f.ante, "orange")}${row("Round", f.round, "orange")}
            ${lost && b ? `<div class="defeated"><span class="lab t">Defeated By</span><div class="by"><span class="t">${esc(b.name)}</span>`
              + `<img alt="" src="${art.chips?.[chip] || ""}"></div></div>` : ""}
          </div>
        </div>
      </div>
      <div class="end-buttons"><div class="end-btn t" data-end="new">New Run</div>
        ${state.endless && !lost ? '<div class="end-btn gold t" data-end="endless">Endless Mode</div>' : ""}</div>
    </div>
    <img class="jimbo" alt="" src="${art.jokers?.Joker || ""}">
    <div class="bubble t">${esc(quips[Math.floor(Math.random() * quips.length)])}</div>
    ${Array.from({ length: 10 }, (_, k) => `<i class="spark" style="--k:${k}"></i>`).join("")}`);
  node.id = "end-screen";
  node.addEventListener("click", (e) => {
    const go = e.target.closest("[data-end]")?.dataset.end;
    if (go) document.dispatchEvent(new CustomEvent("board-end", { detail: go }));
  });
  wash.after(node);
}

const MOVES = { play: playMove, discard: discardMove, draw: drawMove, blind: blindMove, cash_out: cashOutMove,
  shop: shopMove, pack: packMove, use: useMove, sell: sellMove, select: selectMove, skip: selectMove, held: heldMove, end: endMove };

// ---- a run's frames: marked, shown, played ---------------------------------------------------------
// Frames between the shop opening and the next blind are in the shop (using or selling a card there too); a pack
// a skip's tag opens at the blind select is not (`_tagged`: the blinds step aside for it, not the shop's sign).
// Using, selling or reordering there leaves the shop's offers showing (`_offers`, less a card bought and
// used at once), and a card used from an open pack leaves the rest of the pack (`_pack`).
export function mark(frames) {
  let shop = false, tagged = false, pack = null, offers = null, prev = null, gen = 0;
  for (const f of frames) {
    // A skip is recorded before its tag is taken: the tag shows from the skip on (one used at once, as a pack
    // tag is, goes on the next frame).
    f._tags = [...(f.tags || []), ...(f.kind === "skip" && f.tag ? [f.tag] : [])];
    if (f.kind === "shop") shop = true;
    else if (f.kind === "pack") tagged = !shop;
    else if (!["use", "sell", "keep", "order"].includes(f.kind)) shop = tagged = false;
    f._shop = shop;
    f._tagged = tagged;
    if (f.kind === "pack") pack = f.pack;
    else if (f.kind === "use" && pack) {
      const k = pack.cards.findIndex((c) => c.name === f.used);
      f._pack = pack = { ...pack, cards: pack.cards.filter((_, j) => j !== k) };
    } else pack = null;
    if (f.kind === "shop") {
      if (f.act?.do === "reroll") gen++;       // the shop's cards rolled again: a new generation (offerRow's keys)
      f.shop._gen = gen;
      offers = f.shop;
    }
    else if (!shop) offers = null;
    else if (offers && f.kind !== "pack" && !f._pack) {
      const bought = f.kind === "use" && !(prev?.consumables || []).some((c) => c.name === f.used);
      const k = bought ? offers.cards.findIndex((o) => o.name === f.used) : -1;
      f._offers = offers = k < 0 ? offers : { ...offers, cards: offers.cards.filter((_, j) => j !== k) };
    }
    prev = f;
  }
  return frames;
}

// Show frame i as it stands, cutting short any move in progress.
export function jump(i) {
  state.token++;
  state.busy = false;
  stage.cancel();
  state.i = Math.max(0, Math.min(state.frames.length - 1, i));
  if (state.frames.length) show(state.frames[state.i]);
}

// Play the move from the frame on screen to the next one. Resolves false if cut short.
export async function advance() {
  if (state.i >= state.frames.length - 1) return false;
  if (state.busy) jump(state.i);
  const token = ++state.token;
  state.busy = true;
  const prev = state.frames[state.i], f = state.frames[++state.i];
  banner(f);
  if (f.kind !== "end") endScreen(null);
  if (!["blind", "select", "skip", "cash_out", "end"].includes(f.kind) && !f._shop && !f._tagged) blindColours(f.blind, true);
  try {
    await (MOVES[f.kind] || generic)(prev, f);
  } catch (e) {
    if (e !== CANCEL) console.error(e);
  }
  if (token !== state.token) return false;
  state.busy = false;
  // Whatever the move left out springs into place, and the sidebar shows the frame's numbers; an ante or round
  // that went up says "+1" (footage: on the boss beaten, on the next blind chosen).
  sidebar(f);
  if (f.ante > prev.ante) boxPopup("ante-box", "+1", "plus", 40);
  if ((f.round ?? 0) > (prev.round ?? 0) && f.ante === prev.ante) boxPopup("round-num-box", "+1", "plus", 40);
  put({ ...endViewOf(f) });
  scoreLog(f);
  return true;
}

// Tooltips as the game draws them, over what the pointer is on (jokers, consumables, cards, offers, Run Info's rows,
// the deck view's cards); a click keeps one up until the next click. Other things keep the plain tooltip.
export function wireTooltips({ pin = true } = {}) {      // pin: a click keeps a tooltip up (not on the Play tab, where clicks pick)
  const tip = $("#tooltip"), game = $("#game");
  const gtip = el("div", "gtip");
  gtip.hidden = true;
  game.append(gtip);
  let pinned = null;
  const target = (e) => e.target.closest("#game [data-key], #game [data-tiphtml]");
  const showGame = (node) => {
    const html = node.dataset.tiphtml || tipFor(board.get(node.dataset.key)?.e?.info, state.texts);
    if (!html) return false;
    gtip.innerHTML = html;
    gtip.hidden = false;
    // where the game puts it: under jokers and consumables, to the left of shop and pack cards, above the rest
    const g = game.getBoundingClientRect(), r = node.getBoundingClientRect(), s = g.width / 1920;
    const w = gtip.offsetWidth, h = gtip.offsetHeight, key = node.dataset.key || "";
    const left = (r.left - g.left) / s, right = (r.right - g.left) / s, top = (r.top - g.top) / s, bottom = (r.bottom - g.top) / s;
    const x = (left + right) / 2, clampX = (v) => Math.max(8, Math.min(1912 - w, v)), clampY = (v) => Math.max(8, Math.min(1072 - h, v));
    let at;
    if (/^[jk]/.test(key)) at = [clampX(x - w / 2), clampY(bottom + 24)];
    else if (/^(o:|x)/.test(key)) at = [left - w - 20 >= 8 ? left - w - 20 : Math.min(1912 - w, right + 20), clampY(top)];
    else at = [clampX(x - w / 2), top - h - 20 >= 8 ? top - h - 20 : clampY(bottom + 20)];
    gtip.style.left = `${at[0]}px`;
    gtip.style.top = `${at[1]}px`;
    return true;
  };
  document.addEventListener("mousemove", (e) => {
    if (pinned) return;
    const node = target(e);
    if (node && showGame(node)) return void (tip.hidden = true);
    gtip.hidden = true;
    const t = e.target.closest("[data-tip]");
    if (!t) return void (tip.hidden = true);
    tip.innerHTML = t.dataset.tip;
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    tip.style.left = `${Math.min(e.clientX + 14, innerWidth - r.width - 8)}px`;
    tip.style.top = `${Math.min(e.clientY + 14, innerHeight - r.height - 8)}px`;
  });
  if (!pin) return;
  document.addEventListener("click", (e) => {
    const node = target(e);
    pinned = node && node !== pinned && showGame(node) ? node : null;
    if (!pinned && !node) gtip.hidden = true;
  });
}
