// The game's art as DOM elements at the game's own size (a card is 164 x 219): playing cards, jokers,
// consumables, packs and vouchers. Shared by the run viewer and the Seed Planner; styles in cards.css.
// Editions are painted on the art itself, as the game's shaders do (editions.js).
import { loadImage, paintEdition, showEdition } from "./editions.js";

export const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
export const SUIT_SYMBOL = { Spades: "♠", Hearts: "♥", Clubs: "♣", Diamonds: "♦" };
export const RANK_TEXT = { 11: "J", 12: "Q", 13: "K", 14: "A" };
const ENHANCER_ART = { Bonus: "Bonus", Mult: "Mult", Wild: "Wild Card", Glass: "Glass Card", Steel: "Steel Card",
  Stone: "Stone Card", Gold: "Gold Card", Lucky: "Lucky Card" };
const KIND_ART = { Tarot: "tarots", Planet: "planets", Spectral: "spectrals" };
// Pip positions (x, y as fractions of the card) for number cards, like a standard deck.
const PIPS = {
  2: [[0.5, 0.22], [0.5, 0.78, 1]],
  3: [[0.5, 0.22], [0.5, 0.5], [0.5, 0.78, 1]],
  4: [[0.32, 0.22], [0.68, 0.22], [0.32, 0.78, 1], [0.68, 0.78, 1]],
  5: [[0.32, 0.22], [0.68, 0.22], [0.5, 0.5], [0.32, 0.78, 1], [0.68, 0.78, 1]],
  6: [[0.32, 0.22], [0.68, 0.22], [0.32, 0.5], [0.68, 0.5], [0.32, 0.78, 1], [0.68, 0.78, 1]],
  7: [[0.32, 0.22], [0.68, 0.22], [0.5, 0.36], [0.32, 0.5], [0.68, 0.5], [0.32, 0.78, 1], [0.68, 0.78, 1]],
  8: [[0.32, 0.22], [0.68, 0.22], [0.5, 0.36], [0.32, 0.5], [0.68, 0.5], [0.5, 0.64, 1], [0.32, 0.78, 1], [0.68, 0.78, 1]],
  9: [[0.32, 0.2], [0.68, 0.2], [0.32, 0.4], [0.68, 0.4], [0.5, 0.5], [0.32, 0.6, 1], [0.68, 0.6, 1], [0.32, 0.8, 1], [0.68, 0.8, 1]],
  10: [[0.32, 0.2], [0.68, 0.2], [0.5, 0.31], [0.32, 0.4], [0.68, 0.4], [0.32, 0.6, 1], [0.68, 0.6, 1], [0.5, 0.69, 1], [0.32, 0.8, 1], [0.68, 0.8, 1]],
};

// Filled from /api/meta by the page; `view.deckBack` is the deck whose back face-down cards show.
export const art = {};
export const view = { deckBack: "Red Deck" };

export function el(tag, cls, html = "") {
  const e = document.createElement(tag);
  e.className = cls;
  e.innerHTML = html;
  return e;
}

export function cardEl(c) {
  const e = el("div", `card ${c.edition ? `ed-${c.edition}` : ""} ${c.debuffed ? "debuffed" : ""}`);
  if (c.face_down) {
    e.innerHTML = `<img class="bg" alt="" src="${art.decks?.[view.deckBack] || ""}">`;
    return e;
  }
  const bgArt = c.enhancement ? art.enhancers?.[ENHANCER_ART[c.enhancement]] : art.cards?.base;
  let html = `<img class="bg" alt="" src="${bgArt || ""}">`;
  if (c.enhancement !== "Stone") {
    const sym = SUIT_SYMBOL[c.suit];
    const rank = RANK_TEXT[c.rank] || c.rank;
    const faceArt = c.rank >= 11 && c.rank <= 13 ? (art.faces_hc || art.faces)?.[`${rank}${c.suit[0]}`] : null;
    if (faceArt) html += `<img class="face" alt="" src="${faceArt}">`;
    else if (c.rank === 14) html += `<span class="pip ace suit-${c.suit}" style="left:50%;top:52%">${sym}</span>`;
    else html += (PIPS[c.rank] || []).map(([x, y, flip]) => `<span class="pip suit-${c.suit} ${flip ? "flip" : ""}" style="left:${x * 100}%;top:${y * 100}%">${sym}</span>`).join("");
    if (!faceArt) html += `<span class="corner tl suit-${c.suit}">${rank}<small>${sym}</small></span><span class="corner br suit-${c.suit}">${rank}<small>${sym}</small></span>`;
  }
  if (c.seal && art.seals?.[c.seal]) html += `<img class="seal" alt="" src="${art.seals[c.seal]}">`;
  e.innerHTML = html;
  e.dataset.tip = cardTip(c);
  if (c.edition && bgArt) {                   // the card drawn whole, the edition painted on it; the seal stays on top
    const faceArt = c.rank >= 11 && c.rank <= 13 ? (art.faces_hc || art.faces)?.[`${RANK_TEXT[c.rank]}${c.suit[0]}`] : null;
    const key = `${bgArt}|${faceArt}|${c.rank}|${c.suit}|${c.edition}`;
    if (!painted.has(key)) painted.set(key, cardCanvas(c, bgArt, faceArt).then((canvas) => paintEdition(canvas, c.edition).toDataURL()));
    painted.get(key).then((url) => {
      e.querySelectorAll(".face, .pip, .corner").forEach((n) => n.remove());
      e.querySelector("img.bg").src = url;
    }).catch(() => {});
  }
  return e;
}

const painted = new Map();                    // a playing card's art in an edition, by its art and edition

const SUIT_INK = { Spades: "#242b55", Hearts: "#f03464", Clubs: "#235955", Diamonds: "#f06b3f" };   // as cards.css

// A playing card's art (background, then its face or its pips and indices; not the seal) on a canvas at the
// art's own size, laid out as cardEl lays it out in the DOM.
async function cardCanvas(c, bgArt, faceArt) {
  const [bg, face] = await Promise.all([loadImage(bgArt), faceArt ? loadImage(faceArt) : null]);
  const W = bg.naturalWidth, H = bg.naturalHeight, k = W / 164;
  const canvas = Object.assign(document.createElement("canvas"), { width: W, height: H });
  const ctx = canvas.getContext("2d");
  ctx.drawImage(bg, 0, 0);
  if (face) {
    ctx.drawImage(face, 0, 0, W, H);
  } else if (c.enhancement !== "Stone") {
    await document.fonts.load(`${Math.round(36 * k)}px m6x11plus`);
    const sym = SUIT_SYMBOL[c.suit], rank = String(RANK_TEXT[c.rank] || c.rank);
    Object.assign(ctx, { fillStyle: SUIT_INK[c.suit], textAlign: "center", textBaseline: "middle", imageSmoothingEnabled: false });
    const glyph = (text, x, y, size, flip) => {
      ctx.save();
      ctx.translate(x, y);
      if (flip) ctx.rotate(Math.PI);
      ctx.font = `${Math.round(size * k)}px m6x11plus`;
      ctx.fillText(text, 0, 0);
      ctx.restore();
    };
    if (c.rank === 14) glyph(sym, 0.5 * W, 0.52 * H, 96);
    else for (const [x, y, flip] of PIPS[c.rank] || []) glyph(sym, x * W, y * H, 36, flip);
    for (const flip of [false, true]) {          // indices: the rank over a smaller suit, top left and turned round
      ctx.save();
      if (flip) { ctx.translate(W, H); ctx.rotate(Math.PI); }
      glyph(rank, 0.06 * W + 11 * k, 0.06 * H + 15 * k, 38);
      glyph(sym, 0.06 * W + 11 * k, 0.06 * H + 41 * k, 30);
      ctx.restore();
    }
  }
  return canvas;
}

export function cardTip(c) {
  if (c.face_down) return "<b>Face down</b>";
  const name = c.enhancement === "Stone" ? "Stone card" : `${RANK_TEXT[c.rank] ? { J: "Jack", Q: "Queen", K: "King", A: "Ace" }[RANK_TEXT[c.rank]] : c.rank} of ${c.suit}`;
  const mods = [c.enhancement && c.enhancement !== "Stone" && `${c.enhancement} card`, c.edition, c.seal && `${c.seal} seal`, c.bonus_chips && `+${c.bonus_chips} extra chips`, c.debuffed && "debuffed"].filter(Boolean);
  return `<b>${esc(name)}</b>${mods.map(esc).join(" · ")}`;
}

const STICKERS = { eternal: "Eternal: can't be sold or destroyed", perishable: "Perishable: debuffed after 5 rounds",
  rental: "Rental: costs $3 every round" };

// Jokers whose card isn't a full card (card.lua): Wee Joker 0.7 the size, Half Joker H / 1.7, Square Joker H = W,
// Photograph H / 1.2. Each sits centred where a card would be, and its shadow has its shape (cards.css, board.js).
export const JOKER_SHAPES = { "Wee Joker": "wee", "Half Joker": "shape-half", "Square Joker": "shape-square",
  "Photograph": "shape-photo" };

export function jokerEl(j) {
  const soul = art.souls?.[j.name];          // the figure a legendary (or Hologram's face) floats above its card
  const e = el("div", `joker ${j.edition ? `ed-${j.edition}` : ""} ${j.debuffed ? "debuffed" : ""} ${JOKER_SHAPES[j.name] || ""}`,
    `<img alt="${esc(j.name)}" src="${art.jokers?.[j.name] || ""}">`
    + (soul ? `<img class="soul${j.name === "Hologram" ? " holo-face" : ""}" alt="" src="${soul}">` : ""));
  const notes = [j.edition, ...Object.keys(STICKERS).filter((s) => j[s]).map((s) => STICKERS[s]), j.debuffed && "debuffed", j.sell !== undefined && `sells for $${j.sell}`];
  e.dataset.tip = `<b>${esc(j.name)}</b>${notes.filter(Boolean).map(esc).join(" · ")}`;
  if (j.edition) e.querySelectorAll("img").forEach((img) => showEdition(img, j.edition));
  return e;
}

export function consumableEl(c) {
  const e = el("div", `consumable ${c.edition ? `ed-${c.edition}` : ""}`,
    `<img alt="${esc(c.name)}" src="${art[KIND_ART[c.kind]]?.[c.name] || ""}">`);
  e.dataset.tip = `<b>${esc(c.name)}</b>${esc(c.kind)}${c.edition ? " · " + esc(c.edition) : ""}`;
  if (c.edition) showEdition(e.querySelector("img"), c.edition);
  return e;
}

// Any shop or pack item: a joker, playing card, pack, voucher or consumable. Packs are 1.25x a card.
export function itemEl(o) {
  if (o.kind === "Joker") return jokerEl(o);
  if (o.kind === "Playing card") return cardEl(o.card);
  if (o.kind === "Pack") return el("div", "pack-art", `<img alt="${esc(o.name)}" src="${art.boosters?.[o.name] || ""}">`);
  if (o.kind === "Voucher") return el("div", "voucher-art", `<img alt="${esc(o.name)}" src="${art.vouchers?.[o.name] || ""}">`);
  return consumableEl(o);
}
