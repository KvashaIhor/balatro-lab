// Balatro Lab, run viewer: replays a recorded run on a copy of the game's screen (board.js, shared with the Play
// tab), with the lab's controls: deal a run with a model, play, pause, step, scrub, speed, Run Info and the deck view.
import { art, view, el, esc } from "./cards.js";
import { runInfo, deckView } from "./panels.js";
import { state, stage, bg, setup, fit, jump, advance, mark, wireTooltips, endText } from "./board.js";

const $ = (sel) => document.querySelector(sel);

// ---- controls -----------------------------------------------------------------------------------
async function playLoop() {
  const run = (state.loop = {});
  while (state.playing && state.loop === run && state.i < state.frames.length - 1) {
    if (!(await advance())) break;
    try { await stage.wait(0.4); } catch { break; }
  }
  if (state.loop === run) setPlaying(false);
}

function setPlaying(on = !state.playing) {
  state.playing = on && state.frames.length > 0;
  document.querySelector('[data-act="play"]').textContent = state.playing ? "❚❚" : "▶";
  if (!state.playing) return void (state.loop = null);
  if (state.i >= state.frames.length - 1) jump(0);
  playLoop();
}

function load(frames) {
  state.frames = mark(frames);
  $("#scrub").max = frames.length - 1;
  showOutcome(frames[frames.length - 1]);
  jump(0);
}

// How the run ended, beside its name from the start (the frames hold the whole run).
function showOutcome(f) {
  const out = $("#run-result");
  out.className = "run-result";
  out.textContent = "";
  if (f?.kind !== "end") return;
  const text = endText(f).replace(/\.$/, "");
  out.textContent = `· ${text[0].toLowerCase()}${text.slice(1)}`;
  out.classList.add(f.won ? "won" : "lost");
}

async function deal(e) {
  e?.preventDefault();
  setPlaying(false);
  const seed = $("#seed").value.trim();
  const params = new URLSearchParams({ model: $("#model-pick").value || "greedy", max_ante: $("#max-ante").value || 8,
    jokers: [...state.picked].join(","), deck: $("#deck-pick").value, stake: $("#stake-pick").value });
  if (seed) params.set("seed", seed);
  $("#banner").textContent = "Dealing…";
  const res = await fetch(`/api/run?${params}`);
  const data = await res.json();
  if (!res.ok) {
    $("#banner").textContent = data.error || "Something went wrong.";
    return;
  }
  view.deckBack = $("#deck-pick").value || "Red Deck";
  state.deckName = $("#deck-pick").value || null;
  $("#seed").placeholder = `random (last: ${data.seed})`;
  const model = [...$("#model-pick").options].find((o) => o.value === data.model);
  $("#run-label").textContent = `${model?.textContent ?? data.model} · seed ${data.seed}`;
  load(data.frames);
  setPlaying(true);
}

// Who plays: the bots and every evolved model the server knows (balatro/models.py). The page opens on the one
// a #model=<id>[&seed=SEED] link names, else the last one picked here, else "Value bot, latest" (the Play tab's
// advisor too), else the value bot, else the planner's weights, else Greedy. (A new key on 30 Oct, so a choice
// remembered from before starts on the latest once.)
const MODEL_KEY = "balatro-lab-model-2";
function pickModel(models) {
  const select = $("#model-pick"), link = location.hash.match(/^#model=([\w:.-]+)(?:&seed=([1-9A-Za-z]{1,8}))?/);
  select.replaceChildren(...models.map((m) => Object.assign(document.createElement("option"),
    { value: m.id, textContent: m.name, title: m.detail || "" })));
  let saved = null;
  try { saved = localStorage.getItem(MODEL_KEY); } catch { /* storage blocked: no memory */ }
  const ids = models.map((m) => m.id);
  select.value = [link?.[1], saved, "value-latest", "value", "active", "greedy"].find((id) => id && ids.includes(id)) || ids[0];
  if (link?.[2]) $("#seed").value = link[2];
  select.title = models.find((m) => m.id === select.value)?.detail || "";
  select.addEventListener("change", () => {
    select.title = models.find((m) => m.id === select.value)?.detail || "";
    try { localStorage.setItem(MODEL_KEY, select.value); } catch { /* not remembered */ }
  });
}

function buildPicker() {
  $("#picker").replaceChildren(...state.jokers.map((name) => {
    const soul = art.souls?.[name];
    const b = el("button", "pick", `<img alt="${esc(name)}" src="${art.jokers?.[name] || ""}">${soul ? `<img class="soul" alt="" src="${soul}">` : ""}`);
    b.type = "button";
    b.title = name;
    b.setAttribute("aria-pressed", String(state.picked.has(name)));
    b.addEventListener("click", () => {
      if (state.picked.has(name)) state.picked.delete(name);
      else if (state.picked.size < 5) state.picked.add(name);
      b.setAttribute("aria-pressed", String(state.picked.has(name)));
      $("#picked-count").textContent = `(${state.picked.size}/5)`;
    });
    return b;
  }));
  $("#picked-count").textContent = `(${state.picked.size}/5)`;
}

// Run Info and the deck view: full-screen panels over the board, as in the game. Playback pauses while one is open.
function openPanel(kind, tab) {
  setPlaying(false);
  closePanel();
  const f = state.frames[state.i];
  if (!f || !state.texts) return;
  let p;
  if (kind === "info") p = runInfo(f, state.texts, tab);
  else {
    let cards = null;
    for (let i = state.i; i >= 0 && !cards; i--) cards = state.frames[i].deck_cards || null;
    p = deckView(f, cards, state.deckName, state.texts, tab);
  }
  const o = el("div", "");
  o.id = "overlay";
  o.dataset.kind = kind;
  o.append(p);
  o.addEventListener("click", (e) => {
    const t = e.target.closest("[data-tab]");
    if (t) return void openPanel(kind, t.dataset.tab);
    if (e.target === o || e.target.closest("[data-close]")) closePanel();
  });
  $("#game").append(o);
}

function closePanel() {
  $("#overlay")?.remove();
}

// #scene=<name>: one fixed game state from scenes/<name>.json, for comparing with a game screenshot.
async function scene(name) {
  document.body.classList.add("bare");
  fit();
  state.scene = name;
  stage.still = true;
  const s = await (await fetch(`scenes/${name}.json`)).json();
  view.deckBack = s.deck_back || view.deckBack;
  if (s.background) bg.set(s.background);
  bg.freeze(s.background?.time ?? 0, s.background?.spin_time ?? 0);
  state.frames = mark([s]);
  jump(0);
  await document.fonts.ready;
  document.body.dataset.ready = "1";
}

async function init() {
  setup();
  const meta = await (await fetch("/api/meta")).json();
  Object.assign(art, meta.art);
  state.jokers = meta.jokers;
  state.texts = meta.texts;
  state.bosses = meta.bosses || {};
  const hash = location.hash.match(/^#scene=([\w-]+)/);
  if (hash) return scene(hash[1]);
  const planned = location.hash === "#plan" ? await fetch("/api/plan/frames") : null;
  const option = (v) => Object.assign(document.createElement("option"), { value: v, textContent: v });
  $("#deck-pick").append(...meta.decks.map(option));
  if (meta.decks.includes("Red Deck")) $("#deck-pick").value = "Red Deck";   // the game's own default, and the bots' measures
  $("#stake-pick").append(...meta.stakes.map(option));
  pickModel(meta.models || [{ id: "greedy", name: "Greedy bot" }]);
  state.picked = new Set();
  buildPicker();
  wireTooltips();
  $("#controls").addEventListener("submit", deal);
  $("#run-info").addEventListener("click", () => openPanel("info", "hands"));
  $("#deck-pile").addEventListener("click", () => openPanel("deck", "remaining"));
  document.querySelectorAll(".timeline [data-act]").forEach((b) => b.addEventListener("click", () => {
    const act = b.dataset.act;
    if (act === "play") return setPlaying();
    setPlaying(false);
    if (act === "next") return void advance();
    jump({ first: 0, prev: state.i - 1, last: state.frames.length - 1 }[act]);
  }));
  $("#scrub").addEventListener("input", (e) => { setPlaying(false); jump(Number(e.target.value)); });
  document.addEventListener("board-end", (e) => {      // the end screen's New Run: a run on a fresh seed
    if (e.detail === "new") { $("#seed").value = ""; deal(); }
  });
  document.querySelectorAll(".speed button").forEach((b) => b.addEventListener("click", () => {
    stage.speed = Number(b.dataset.speed);
    document.querySelectorAll(".speed button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
  }));
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select")) return;
    if ($("#overlay")) { if (e.key === "Escape") closePanel(); return; }
    if (e.key === " ") { e.preventDefault(); setPlaying(); }
    else if (e.key === "ArrowLeft") { setPlaying(false); jump(state.i - 1); }
    else if (e.key === "ArrowRight") { setPlaying(false); advance(); }
    else if (e.key === "Home") { setPlaying(false); jump(0); }
    else if (e.key === "End") { setPlaying(false); jump(state.frames.length - 1); }
    else if (e.key === "h" || e.key === "H") { document.body.classList.toggle("bare"); fit(); }
  });
  if (planned?.ok) {                                   // #plan: replay the Seed Planner's line
    const p = await planned.json();
    view.deckBack = p.deck;
    state.deckName = p.deck;
    $("#seed").placeholder = `plan for ${p.seed}`;
    $("#run-label").textContent = `Seed Planner's line · seed ${p.seed}`;
    load(p.frames);
    setPlaying(true);
    return;
  }
  deal();
}

init();
