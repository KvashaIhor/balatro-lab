// The run viewer's interactive screens, laid out as the game shows them (measured from gameplay footage):
// tooltips for jokers, consumables, playing cards and shop offers; Run Info (poker hands, this ante's blinds,
// vouchers redeemed); and the deck view (the cards still to draw, or the full deck). Texts come from the rules
// data (/api/meta's "texts"), shortened the game's way for playing cards.
import { art, el, esc, cardEl, itemEl } from "./cards.js";

const RANK_NAME = { 11: "Jack", 12: "Queen", 13: "King", 14: "Ace" };
const RANK_SHORT = { 11: "J", 12: "Q", 13: "K", 14: "A" };
const SUITS = ["Spades", "Hearts", "Clubs", "Diamonds"];
const SUIT_SYMBOL = { Spades: "♠", Hearts: "♥", Clubs: "♣", Diamonds: "♦" };
const RARITY = { Common: "common", Uncommon: "uncommon", Rare: "rare", Legendary: "legendary" };
// How the game's own card tooltips word enhancements, seals and editions.
const ENHANCE = { Bonus: "+30 extra chips", Mult: "+4 Mult", Wild: "Can be used as any suit", Glass: "X2 Mult, 1 in 4 chance to destroy card",
  Steel: "X1.5 Mult while this card stays in hand", Stone: "+50 Chips, no rank or suit", Gold: "$3 if this card is held in hand at end of round",
  Lucky: "1 in 5 chance for +20 Mult, 1 in 15 chance to win $20" };
const SEAL = { Gold: "Earn $3 when this card is played and scores", Red: "Retrigger this card 1 time",
  Blue: "Creates the Planet card for final played poker hand of round if held in hand", Purple: "Creates a Tarot card when discarded" };
const EDITION = { Foil: "+50 Chips", Holographic: "+10 Mult", Polychrome: "X1.5 Mult", Negative: "+1 Joker slot" };
const HAND_WORDS = "Flush Five|Flush House|Five of a Kind|Straight Flush|Four of a Kind|Full House|Three of a Kind|Two Pair|High Card|Pair|Flush|Straight";

// The game's colours in descriptions: Mult red (XMult on red), Chips blue, money gold, chances green, poker hands
// orange, suits in their colours.
const KEYWORDS = new RegExp(`([xX×]\\s?\\d+(?:\\.\\d+)?)(\\s*Mult)|([+-]?\\d+(?:\\.\\d+)?)(\\s*Mult)|([+-]?\\d+)(\\s*[Cc]hips)|(\\$\\d+)|(\\d+ in \\d+)`
  + `|\\b(${HAND_WORDS})\\b|\\b(Spades?|Hearts?|Clubs?|Diamonds?)\\b`, "g");
export function colorize(text) {
  return esc(text || "").replace(KEYWORDS, (m, xm, xmT, pm, pmT, ch, chT, money, odds, hand, suit) => {
    if (xm) return `<span class="k-xmult">X${xm.replace(/^[xX×]\s?/, "")}</span>${xmT}`;
    if (pm) return `<span class="k-mult">${pm}</span>${pmT}`;
    if (ch) return `<span class="k-chips">${ch}</span>${chT}`;
    if (money) return `<span class="k-money">${money}</span>`;
    if (odds) return `<span class="k-odds">${odds}</span>`;
    if (hand) return `<span class="k-hand">${hand}</span>`;
    return `<span class="k-${suit.replace(/s$/, "").toLowerCase()}">${suit}</span>`;
  });
}

const pill = (text, cls) => `<span class="gt-pill t ${cls}">${esc(text)}</span>`;
const panel = (title, body, pills = [], tail = "") => `<div class="gt"><div class="gt-name t">${esc(title)}</div>`
  + `<div class="gt-desc">${body}</div>${tail}${pills.length ? `<div class="gt-pills">${pills.join("")}</div>` : ""}</div>`;

// ---- tooltips -------------------------------------------------------------------------------------
// `info` is what the board drew: { type: "joker" | "consumable" | "card" | "offer", ... }.
export function tipFor(info, texts) {
  if (!info || !texts) return "";
  if (info.type === "card") return cardTip(info);
  const kind = info.type === "joker" ? "Joker" : info.kind;
  if (kind === "Joker") return jokerTip(info, texts);
  if (kind === "Playing card") return cardTip(info.card || info);
  if (kind === "Voucher") return panel(info.name, colorize(texts.vouchers[info.name]), [pill("Voucher", "voucher")]);
  if (kind === "Pack") {
    const p = texts.packs[info.name];
    return panel(info.name, p ? `Choose <b>${p.choose}</b> of up to <b>${p.shown}</b>: ${colorize(p.contents)}` : "", [pill("Booster Pack", "pack")]);
  }
  const c = texts.consumables[info.name];
  const pills = [pill(kind, (kind || "").toLowerCase())];
  if (info.edition) pills.push(pill(info.edition, "edition"));
  return panel(info.name, colorize(c?.effect), pills);
}

function jokerTip(j, texts) {
  const t = texts.jokers[j.name] || {};
  const now = j.now ? `<div class="gt-now">(Currently ${colorize(j.now)})</div>` : "";
  const pills = [pill(t.rarity || "Joker", RARITY[t.rarity] || "common")];
  if (j.edition) pills.push(pill(j.edition, "edition"));
  for (const s of ["eternal", "perishable", "rental"]) if (j[s]) pills.push(pill(s[0].toUpperCase() + s.slice(1), "sticker"));
  const tail = (j.edition ? `<div class="gt-desc small">${colorize(EDITION[j.edition])}</div>` : "")
    + (j.debuffed ? '<div class="gt-desc small"><span class="k-mult">Debuffed</span>: does nothing this blind</div>' : "");
  return panel(j.name, colorize(t.effect) + now, pills, tail);
}

export function cardTip(c) {
  if (c.face_down) return '<div class="gt gt-card"><div class="gt-tag t">Face down</div></div>';
  const stone = c.enhancement === "Stone";
  const title = stone ? "Stone Card" : `${RANK_NAME[c.rank] ?? c.rank} of ${c.suit}`;
  const base = stone ? 50 : c.rank === 14 ? 11 : Math.min(c.rank, 10);
  const lines = [`<span class="k-chips">+${base + (c.bonus_chips || 0)}</span> chips`];
  if (c.enhancement && !stone) lines.push(colorize(ENHANCE[c.enhancement]));
  if (stone) lines.push("no rank or suit");
  if (c.edition) lines.push(colorize(EDITION[c.edition] || c.edition));
  if (c.seal) lines.push(`<span class="k-seal ${c.seal.toLowerCase()}">${c.seal} Seal</span>: ${colorize(SEAL[c.seal])}`);
  if (c.debuffed) lines.push('<span class="k-mult">Debuffed</span>: scores nothing');
  return `<div class="gt gt-card"><div class="gt-tag t">${colorize(title)}</div><div class="gt-desc">${lines.join("<br>")}</div></div>`;
}

// ---- the shared frame of the full-screen panels -------------------------------------------------
function frame(cls, tabs, tab, body) {
  const p = el("div", `ov-panel ${cls}`);
  const bar = el("div", "ov-tabs");
  for (const [id, label] of tabs) {
    const b = el("div", `ov-tab t${id === tab ? " on" : ""}`, esc(label));
    b.dataset.tab = id;
    bar.append(b);
  }
  const back = el("div", "ov-back t", "Back");
  back.dataset.close = "1";
  p.append(bar, body, back);
  return p;
}

// ---- Run Info ------------------------------------------------------------------------------------
export function runInfo(f, texts, tab = "hands") {
  const body = el("div", "ov-body");
  if (tab === "hands") body.append(handsTab(f, texts));
  else if (tab === "blinds") body.append(blindsTab(f));
  else body.append(vouchersTab(f, texts));
  return frame("ri", [["hands", "Poker Hands"], ["blinds", "Blinds"], ["vouchers", "Vouchers"]], tab, body);
}

function handsTab(f, texts) {
  const levels = f.hand_levels || {}, plays = f.hand_plays || {};
  const list = el("div", "ri-hands");
  for (const h of texts.hands) {
    const lvl = levels[h.name] ?? 1, n = plays[h.name] || 0;
    if (h.secret && !n && lvl <= 1) continue;                // secret hands show once played
    const chips = Math.max(0, h.chips + h.level_chips * (lvl - 1)), mult = Math.max(1, h.mult + h.level_mult * (lvl - 1));
    const row = el("div", "ri-row", `<span class="ri-lvl t">lvl.${lvl}</span><span class="ri-name t">${esc(h.name)}</span>`
      + `<span class="ri-cm"><span class="ri-chips t">${chips}</span><span class="ri-x t">X</span><span class="ri-mult t">${mult}</span></span>`
      + `<span class="ri-hash t">#</span><span class="ri-n t">${n}</span>`);
    row.dataset.tiphtml = `<div class="gt gt-card"><div class="gt-desc">${colorize(h.definition)}</div></div>`;
    list.append(row);
  }
  return list;
}

function blindsTab(f) {
  const blinds = f.ante_blinds || [];
  const cur = f.blind?.kind ?? 0, inRound = !f._shop && !["cash_out", "shop", "pack", "end"].includes(f.kind) && !!f.blind;
  const nextAnte = !inRound && cur === 2 && blinds[2]?.name === "Boss Blind";     // after a boss: the next ante's blinds
  const row = el("div", "ri-blinds");
  blinds.forEach((b, k) => {
    const state = nextAnte ? "Upcoming" : k < cur || (k === cur && !inRound) ? "Defeated" : k === cur ? "Current" : "Upcoming";
    const chip = art.chips?.[b.name] || art.chips?.[["Small Blind", "Big Blind", "Small Blind"][b.kind]] || "";
    row.append(el("div", `ri-blind ${state.toLowerCase()}`, `<div class="ri-state t">${state}</div><div class="ri-bname t">${esc(b.name)}</div>`
      + (chip ? `<img class="ri-chip" alt="" src="${chip}">` : "")
      + `<div class="ri-score"><span class="t">Score at least</span><span class="t ri-target"><i class="chip-icon"></i>${b.chips.toLocaleString("en-US")}</span>`
      + `<span class="t">Reward: <span class="k-money">${"$".repeat(b.reward)}</span></span></div>`
      + (b.effect ? `<div class="ri-effect">${colorize(b.effect)}</div>` : "")));
  });
  const box = el("div", "ri-blinds-wrap");
  box.append(el("div", "ri-ante t", `Ante ${f.ante}`), row);
  return box;
}

function vouchersTab(f, texts) {
  const box = el("div", "ri-vouchers");
  if (!f.vouchers?.length) {
    box.append(el("div", "ri-none t", "No vouchers redeemed yet"));
    return box;
  }
  for (const name of f.vouchers) {
    const cell = el("div", "ri-voucher");
    const art_ = itemEl({ kind: "Voucher", name });
    art_.dataset.tiphtml = panel(name, colorize(texts.vouchers[name]), [pill("Voucher", "voucher")]);
    cell.append(art_, el("div", "ri-vname t", esc(name)));
    box.append(cell);
  }
  return box;
}

// ---- the deck --------------------------------------------------------------------------------------
// `cards`: the frame's compact deck rows [uid, rank, suit, enhancement, edition, seal, extra chips, to draw, debuffed].
export function deckView(f, cards, deckName, texts, tab = "remaining") {
  const all = (cards || []).map(([uid, rank, suit, enhancement, edition, seal, bonus_chips, left, debuffed]) =>
    ({ uid, rank, suit, enhancement, edition, seal, bonus_chips, left: !!left, debuffed: !!debuffed }));
  const counted = tab === "remaining" ? all.filter((c) => c.left) : all;
  const body = el("div", "ov-body");
  // the deck and its base cards
  const side = el("div", "dv-side");
  side.append(el("div", "dv-deck", `<div class="t dv-name">${esc(deckName || "Standard deck")}</div>`
    + `<div class="dv-eff">${colorize(texts.decks?.[deckName] || "No deck effect")}</div>`));
  const ranked = counted.filter((c) => c.enhancement !== "Stone");
  const count = (fn) => ranked.filter(fn).length;
  const base = el("div", "dv-base", '<div class="t dv-title">Base Cards</div>');
  const grid = el("div", "dv-grid");
  for (const [label, n, cls] of [["A", count((c) => c.rank === 14), ""], ["JQK", count((c) => c.rank >= 11 && c.rank <= 13), ""],
    ["#", count((c) => c.rank <= 10), ""], ...SUITS.map((s) => [SUIT_SYMBOL[s], count((c) => c.suit === s), s.toLowerCase()])]) {
    grid.append(el("div", "dv-count", `<span class="dv-icon t ${cls}">${label}</span><span class="t">${n}</span>`));
  }
  base.append(grid);
  const stones = counted.length - ranked.length;
  if (stones) base.append(el("div", "dv-stones t", `Stone cards ${stones}`));
  side.append(base);
  // cards by rank
  const ranks = el("div", "dv-ranks");
  for (let r = 14; r >= 2; r--) ranks.append(el("div", "dv-rank", `<span class="t dv-r">${RANK_SHORT[r] ?? r}</span><span class="t">${count((c) => c.rank === r)}</span>`));
  // four rows by suit, highest first; in Remaining, the cards drawn or played are greyed out, as in the game
  const rows = el("div", "dv-rows");
  const W = 1120, CW = 164 * 0.78;
  SUITS.forEach((s, k) => {
    const row = all.filter((c) => c.suit === s).sort((a, b) => (b.enhancement === "Stone") - (a.enhancement === "Stone") || b.rank - a.rank);
    const step = row.length > 1 ? Math.min(86, (W - 20 - CW) / (row.length - 1)) : 0;
    row.forEach((c, i) => {
      const e = cardEl(c);
      e.classList.add("dv-card");
      if (tab === "remaining" && !c.left) e.classList.add("gone");
      Object.assign(e.style, { left: `${10 + i * step}px`, top: `${8 + k * 152}px`, zIndex: String(i + 1) });
      e.dataset.tiphtml = cardTip(c);
      rows.append(e);
    });
  });
  body.append(side, ranks, rows, el("div", "dv-total t", `${counted.length} card${counted.length === 1 ? "" : "s"}${tab === "remaining" ? ` left of ${all.length}` : ""}`));
  return frame("dv", [["remaining", "Remaining"], ["full", "Full Deck"]], tab, body);
}
