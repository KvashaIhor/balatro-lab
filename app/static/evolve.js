// Evolution tab: start and watch evolution runs of the value bot's weights.
import { art, el, itemEl } from "./cards.js";
import { CorrectionHeatmap, GenChart, GeneChart, GeneHeatmap, Tooltip, progress } from "./evolve-charts.js";

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const COLORS = { best: "#3fa6ff", median: "#f6b245", bench: "#3fa6ff" };
const evo = { runs: [], selected: null, records: [], detail: null, timer: null, charts: null, genes: {}, tooltip: null,
  cat: "out:joker", sort: "game", texts: { items: {}, facts: {} }, timing: null, timingFor: null, timingMode: "total", timingScale: "row", synergy: null,
  sweep: null };
const RUN_PANELS = ["#empty", "#run-head", "#tiles", "#bench-card", "#fit-card", "#genes-card", "#movers-card", "#corr-card", "#timing-card", "#learned-card", "#heat-card"];

function duration(sec) {
  if (sec < 60) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${String(Math.round(sec % 60)).padStart(2, "0")}s`;
  return `${Math.floor(sec / 3600)}h ${String(Math.round((sec % 3600) / 60)).padStart(2, "0")}m`;
}

async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

// ---- runs --------------------------------------------------------------------------------------
async function pollRuns() {
  const data = await api("/api/evolve/runs");
  evo.runs = data.runs;
  const a = data.active;
  $("#active").textContent = a.source === "hand" ? "Hand-set weights, no network. Pick an evolved champion with \"Use these weights\" on its run."
    : `From ${a.source}${a.gen ? `, generation ${a.gen}` : ""}${a.network ? ", with its network" : ""}${a.benchmark != null ? `: benchmark ${progress(a.benchmark)}` : ""}.`;
  if (!evo.selected && evo.runs.length) evo.selected = evo.runs[0].id;
  renderRunList();
}

async function pollDetail() {
  const id = evo.selected;
  if (!id || id === "sweep") return;
  const since = evo.records.length ? evo.records[evo.records.length - 1].gen : 0;
  const data = await api(`/api/evolve/runs/${encodeURIComponent(id)}?since=${since}`);
  if (id !== evo.selected) return;
  evo.records.push(...data.records);
  evo.detail = data;
  renderRun();
}

// A run's fitness as text: progress (with its ante), or for runs evolved to beat ante 8, the share of seeds they beat it on.
const fitnessFormat = (kind) => (kind === "wins" ? (v) => `${v.toFixed(1)}% beat ante 8` : progress);

function renderRunList() {
  $("#runs").innerHTML = evo.runs.map((r) => `
    <li class="run-item${r.id === evo.selected ? " selected" : ""}" data-run="${esc(r.id)}">
      <span class="rid">${esc(r.id)}${r.kind === "network" ? ' <span class="badge network">network</span>' : ""}${r.fitness === "wins" ? ' <span class="badge wins">wins</span>' : ""}${r.active ? ' <span class="badge active">in use</span>' : ""}</span>
      <span class="badge ${esc(r.state)}">${esc(r.state)}</span>
      <span class="rmeta">generation ${r.gen} of ${r.generations ?? "?"}${r.benchmark != null ? ` · benchmark ${fitnessFormat(r.fitness)(r.benchmark)}` : ""}</span>
    </li>`).join("") || '<li class="note">No runs yet. Start one above.</li>';
}

function selectRun(id) {
  evo.selected = id;
  evo.records = [];
  evo.detail = null;
  renderRunList();
  const sweep = id === "sweep";
  for (const sel of RUN_PANELS) $(sel).hidden = true;
  $("#empty").hidden = sweep;
  $("#sweep-tiles").hidden = $("#sweep-card").hidden = !sweep;
  renderSweepItem();
  if (sweep) renderSweep();
  else pollDetail().catch(showError);
}

// ---- the behaviour modifiers' strength sweep (scripts/sweep_mods.py) ------------------------------
async function pollSweep() {
  evo.sweep = await api("/api/evolve/sweep");
  renderSweepItem();
  renderSweep();
}

function renderSweepItem() {
  const s = evo.sweep;
  $("#sweep-side").hidden = !s || s.state === "none";
  if (!s || s.state === "none") return;
  const done = s.rules.filter((r) => r.result).length;
  const item = $("#sweep-item");
  item.classList.toggle("selected", evo.selected === "sweep");
  item.innerHTML = `<span class="rid">Modifier strengths</span><span class="badge ${esc(s.state)}">${esc(s.state)}</span>`
    + `<span class="rmeta">${done} of ${s.rules.length} jokers done${s.eta_min != null ? ` · ${duration(s.eta_min * 60)} left` : ""}</span>`;
}

const pct = (x) => `${(100 * x).toFixed(1)}%`;
const signedPts = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(100 * x).toFixed(1)}`;

function renderSweep() {
  const s = evo.sweep;
  if (!s || s.state === "none" || evo.selected !== "sweep") return;
  const strengths = s.plan.strengths;
  const done = s.rules.filter((r) => r.result);
  const now = s.rules.find((r) => r.status === "running");
  const changed = done.filter((r) => r.result.use !== 1);
  $("#sweep-tiles").innerHTML = [
    tile("Jokers done", `${done.length} / ${s.rules.length}`, now ? `now: ${esc(now.rule)}` : esc(s.state)),
    tile("Games", s.total ? `${Math.floor((100 * s.games) / s.total)}%` : "—",
      s.total ? `${s.games.toLocaleString("en-US")} of ${s.total.toLocaleString("en-US")}${s.per_minute ? ` · ${s.per_minute} a minute` : ""}` : ""),
    tile(s.eta_min != null ? "Time left" : "State", s.eta_min != null ? duration(s.eta_min * 60) : esc(s.state), `started ${esc(s.plan.started.slice(11, 16))}`),
    tile("Strengths changed", done.length ? String(changed.length) : "—", changed.length ? changed.map((r) => `${esc(r.rule)} → ${r.result.use}`).join(", ") : "from 1, so far"),
  ].join("");
  $("#sweep-note").textContent = `Each row's games all start with that joker, and only how much the bot cares about its rule changes: `
    + `0 ignores it, 1 is as measured, 3 counts it triple. A cell is the share of ${s.plan.seeds} fresh seeds (Red Deck) beaten through ante 8, `
    + `and below it the difference from strength 1 on the same seeds, in points, ± its standard error. The outlined cell is the strength the bot `
    + `will use: the best, if it beats 1 by more than twice its standard error; otherwise 1 stays. Dashed cells are a joker still playing: its `
    + `numbers so far, over the seeds every strength has finished. Rows are in order of how often the joker turns up.`;
  const head = `<div class="sweep-row head" style="--n:${strengths.length}"><span>Joker and its rule</span>${strengths.map((x) => `<span>${x === 1 ? "1 (as measured)" : x}</span>`).join("")}</div>`;
  const rows = s.rules.map((r) => {
    const rule = `<div class="sweep-rule" data-rule="${esc(r.rule)}"><span class="sweep-art" data-joker="${esc(r.rule)}"></span>`
      + `<div><div class="sr-name">${esc(r.rule)}</div><div class="sr-what">${esc(r.what)}</div></div></div>`;
    const res = r.result || r.partial;
    if (!res) {
      const text = r.status === "running" ? "playing now…" : s.state === "running" ? "waiting" : "not done";
      return `<div class="sweep-row" style="--n:${strengths.length}">${rule}<div class="sweep-wait ${r.status}">${text}</div></div>`;
    }
    const live = !r.result;               // still playing: the seeds every strength has finished so far
    const cells = res.rows.map((c) => {
      const d = c.won_vs_1, se = c.won_se;
      const tint = c.strength === 1 || !se ? "" : Math.abs(d) > 2 * se ? (d > 0 ? "up" : "down") : Math.abs(d) > se ? `${d > 0 ? "up" : "down"} faint` : "";
      const pick = c.strength === res.use ? " pick" : "";
      return `<div class="sweep-cell ${tint}${pick}${live ? " live" : ""}" data-rule="${esc(r.rule)}" data-s="${c.strength}"><span class="sc-rate">${pct(c.won)}</span>`
        + `<span class="sc-diff">${c.strength === 1 ? (live ? `${res.seeds} of ${s.plan.seeds} seeds` : "reference") : `${signedPts(d)} ± ${(100 * se).toFixed(1)}`}</span></div>`;
    }).join("");
    return `<div class="sweep-row${live ? " live" : ""}" style="--n:${strengths.length}">${rule}${cells}</div>`;
  }).join("");
  $("#sweep-table").innerHTML = head + rows;
  $("#sweep-table").querySelectorAll("[data-joker]").forEach((slot) => slot.replaceWith(sprite(itemEl({ kind: "Joker", name: slot.dataset.joker }), 0.26)));
}

function describeSweepCell(ruleName, strength) {
  const r = evo.sweep?.rules.find((x) => x.rule === ruleName);
  const res = r?.result || r?.partial;
  const c = res?.rows.find((x) => x.strength === strength);
  if (!c) return "";
  const live = !r.result;
  const pic = artOf("joker", ruleName);
  const vs = (v, se, f) => `${v >= 0 ? "+" : "−"}${f(Math.abs(v))} ± ${f(se)}`;
  return `<div class="tt-title">${esc(ruleName)} · strength ${strength}</div>${pic ? `<img class="tt-art" src="${pic}" alt="">` : ""}${effectOf({ kind: "joker", name: ruleName })}`
    + `<div class="tt-row"><span class="tt-muted">beat ante 8</span><b>${pct(c.won)}</b></div>`
    + (strength !== 1 ? `<div class="tt-row"><span class="tt-muted">against strength 1</span><b>${vs(c.won_vs_1, c.won_se, (x) => `${(100 * x).toFixed(1)} points`)}</b></div>` : "")
    + `<div class="tt-row"><span class="tt-muted">mean progress</span><b>${c.progress.toFixed(2)}</b></div>`
    + (strength !== 1 ? `<div class="tt-row"><span class="tt-muted">against strength 1</span><b>${vs(c.progress_vs_1, c.progress_se, (x) => x.toFixed(2))}</b></div>` : "")
    + `<div class="tt-note">${live ? `Still playing: so far ${res.seeds} of ${evo.sweep.plan.seeds} seeds have finished at every strength, so these numbers will move. ` : ""}`
    + `Rule: ${esc(r.what)}. ${res.seeds} seeds, each starting with ${esc(ruleName)}. Progress: blinds beaten plus the share of the failed blind (24 = ante 8 beaten).</div>`;
}

// ---- one run -----------------------------------------------------------------------------------
function tile(label, value, sub = "") {
  return `<div class="tile"><span class="tile-label">${label}</span><span class="tile-value">${value}</span>${sub ? `<span class="tile-sub">${sub}</span>` : ""}</div>`;
}

function renderRun() {
  const d = evo.detail;
  if (!d) return;
  const s = d.summary;
  const cfg = d.config || {};
  $("#empty").hidden = true;
  for (const id of ["#run-head", "#tiles"]) $(id).hidden = false;
  $("#run-title").textContent = s.id;
  $("#run-state").textContent = s.state;
  $("#run-state").className = `badge ${s.state}`;
  $("#run-stop").hidden = !(s.state === "running" || s.state === "starting");
  $("#run-continue").hidden = !(s.kind === "network" && d.champion && !["running", "starting"].includes(s.state));
  $("#run-use").disabled = !d.champion || s.active;
  $("#run-use").textContent = s.active ? `The planner uses ${s.kind === "network" ? "this network" : "these weights"}`
    : `Use ${s.kind === "network" ? "this network" : "these weights"} in the planner`;
  const showLog = ["error", "died", "starting", "stopped"].includes(s.state) && d.log_tail?.length;
  $("#run-log").hidden = !showLog;
  if (showLog) $("#run-log").textContent = d.log_tail.join("\n");

  const recs = evo.records;
  const last = recs[recs.length - 1];
  const hand = cfg.baseline?.benchmark;
  const perGen = recs.length ? last.elapsed / recs.length : null;
  const left = s.state === "running" && perGen ? (s.generations - s.gen) * perGen : null;
  const champ = d.champion;
  const wins = s.fitness === "wins", fmt = fitnessFormat(s.fitness);
  const benchSeeds = (cfg.bench_seeds || []).length || 48;
  evo.charts.bench.format = evo.charts.fit.format = fmt;
  $("#bench-card .hint").textContent = `each generation's best, on the same ${benchSeeds} seeds${wins ? " (Red Deck, to ante 8)" : ""}`;
  const gain = champ && hand != null ? champ.benchmark - hand : null;
  $("#tiles").innerHTML = [
    tile("Generation", `${s.gen} / ${s.generations ?? "?"}`, perGen ? `${duration(perGen)} each` : ""),
    tile("Champion on the benchmark", champ ? fmt(champ.benchmark) : "—", champ ? `from generation ${champ.gen}` : ""),
    tile(s.kind === "network" ? "Value bot, no network" : "Hand-set weights", hand != null ? fmt(hand) : "—", `same ${benchSeeds} seeds`),
    tile("Gain", gain != null ? `${gain >= 0 ? "+" : ""}${gain.toFixed(wins ? 1 : 2)}${wins ? " points" : ""}` : "—",
      s.kind === "network" ? "progress from the network" : wins ? "beating ante 8, over hand-set" : "progress over hand-set"),
    tile(left != null ? "Time left" : "Run time", left != null ? duration(left) : last ? duration(last.elapsed) : "—"),
  ].join("");
  if (!recs.length) return;
  const network = s.kind === "network";
  for (const id of ["#bench-card", "#fit-card"]) $(id).hidden = false;
  for (const id of ["#genes-card", "#heat-card"]) $(id).hidden = network;
  $("#learned-card").hidden = !network;
  $("#corr-card").hidden = !network;
  $("#movers-card").hidden = !network || recs.length < 2;
  const gens = recs.map((r) => r.gen);
  const refs = [];
  if (hand != null) refs.push({ value: hand, label: network ? "value bot, no network" : "hand-set weights" });
  if (cfg.active && cfg.active.benchmark !== hand) refs.push({ value: cfg.active.benchmark, label: cfg.config?.init ? "starting weights" : "planner's weights at the start" });
  let best = -Infinity;
  evo.charts.bench.setData({ gens, refs, series: [
    { label: "best so far", color: COLORS.median, values: recs.map((r) => (best = Math.max(best, r.benchmark))) },
    { label: "generation's best", color: COLORS.bench, values: recs.map((r) => r.benchmark) },
  ] });
  evo.charts.fit.setData({ gens, refs: [], bands: [{ lo: recs.map((r) => r.p10), hi: recs.map((r) => r.p90), label: "10th–90th percentile" }],
    series: [{ label: "best", color: COLORS.best, values: recs.map((r) => r.best) }, { label: "median", color: COLORS.median, values: recs.map((r) => r.median) }] });
  $("#timing-card").hidden = !network;
  if (network) {
    renderLearned(last.learned || []);
    renderCorrections(recs, cfg);
    loadTiming(s.id, d.champion?.gen).then(renderTiming);
    return;
  }
  const genes = cfg.genes || [];
  evo.charts.genes.setData({ genes, champion: (champ || last).genome || last.champion, baseline: cfg.baseline.genome, mean: last.pop_mean, sd: last.pop_sd });
  evo.charts.heat.setData({ genes, gens, champions: recs.map((r) => r.champion) });
}

// ---- what a network learned ---------------------------------------------------------------------
const KIND_OF = { joker: "Joker", tarot: "Tarot", planet: "Planet", spectral: "Spectral", pack: "Pack", voucher: "Voucher" };

function renderLearned(learned) {
  const pct = (b) => `${Math.round(Math.abs(Math.exp(b) - 1) * 100)}% ${b >= 0 ? "more" : "less"}`;
  $("#learned").replaceChildren(...learned.slice(0, 32).map((it) => {
    const cell = el("div", "learned-item");
    const art = it.kind === "keep" ? el("div", "keep-art", `keep a ${esc(it.name)}`) : sprite(itemEl({ kind: KIND_OF[it.kind], name: it.name }), 0.3);
    const what = it.kind === "keep" ? `Keeping a ${it.name}` : it.name;
    cell.append(art, el("div", "", `<div class="li-name">${esc(what)}</div><div class="li-value ${it.bias >= 0 ? "up" : "down"}">${it.bias >= 0 ? "+" : "−"}${Math.abs(it.bias).toFixed(2)}</div><div class="li-kind">${esc(it.kind)}</div>`));
    cell.addEventListener("pointermove", (e) => evo.tooltip.show(`<div class="tt-title">${esc(what)}</div>${effectOf({ kind: it.kind, name: it.name })}<div>The network adds ${it.bias >= 0 ? "+" : "−"}${Math.abs(it.bias).toFixed(2)} power to the value bot's worth of it in an average situation: valued as if it made hands score about ${pct(it.bias)}. The correction also moves with the build, deck and money.</div>${pairsOf(it)}`, e.clientX, e.clientY));
    cell.addEventListener("pointerleave", () => evo.tooltip.hide());
    return cell;
  }));
}

// Each generation's correction of every item: full when the run logged all of them, else its 40 largest.
function correctionsByGen(recs, cfg) {
  const items = Array.isArray(cfg.network?.items) ? cfg.network.items.map(([kind, name]) => `${kind}|${name}`) : null;
  return recs.map((r) => {
    const m = new Map();
    if (r.biases && items) r.biases.forEach((b, i) => m.set(items[i], b));
    else for (const it of r.learned || []) m.set(`${it.kind}|${it.name}`, it.bias);
    return { full: !!(r.biases && items), map: m };
  });
}

const artOf = (kind, name) => ({ joker: art.jokers, tarot: art.tarots, planet: art.planets, spectral: art.spectrals, pack: art.boosters, voucher: art.vouchers })[kind]?.[name];
const itemLabel = (kind, name) => (kind === "keep" ? `Keeping a ${name}` : name);

// The facts the network reads, in groups (by their names in the run's config).
const FACT_GROUPS = { basics: (f, i) => i < 8, suits: (f) => /^share of (Spades|Hearts|Clubs|Diamonds)$/.test(f),
  ranks: (f) => /^share of (\d+|Jack|Queen|King|Ace)s$/.test(f), enhancements: (f) => / cards$/.test(f) && f.startsWith("share of"),
  seals: (f) => / seal$/.test(f), editions: (f) => /^share that is/.test(f), hands: (f) => / level$/.test(f), vouchers: (f) => /^has /.test(f) };

// Rows and per-generation values for the chosen category: every card of it, in game order or by its latest value.
function category(recs, cfg) {
  const [side, what] = evo.cat.split(":");
  const items = Array.isArray(cfg.network?.items) ? cfg.network.items : null;
  let rows = [], cells = [];
  if (side === "out") {
    const byGen = correctionsByGen(recs, cfg);
    if (items) {
      rows = items.map(([kind, name], i) => ({ kind, name, i, label: itemLabel(kind, name) })).filter((r) => r.kind === what);
      cells = rows.map((r) => byGen.map((g) => (g.full ? g.map.get(`${r.kind}|${r.name}`) ?? 0 : g.map.get(`${r.kind}|${r.name}`) ?? null)));
    } else {
      const names = [...new Set(byGen.flatMap((g) => [...g.map.keys()]))].filter((k) => k.startsWith(`${what}|`));
      rows = names.map((k) => { const [kind, name] = k.split("|"); return { kind, name, label: itemLabel(kind, name) }; });
      cells = rows.map((r) => byGen.map((g) => g.map.get(`${r.kind}|${r.name}`) ?? null));
    }
  } else if (items) {
    const facts = cfg.network.facts || [];
    if (what === "jokers" || what === "consumables") {
      const kinds = what === "jokers" ? ["joker"] : ["tarot", "planet", "spectral"];
      rows = items.filter(([kind]) => kinds.includes(kind)).map(([kind, name], i) => ({ kind, name, i, label: name }));
    } else {
      rows = facts.map((f, i) => ({ kind: "fact", name: f, i, label: f })).filter((r) => FACT_GROUPS[what](r.name, r.i));
    }
    const src = what === "jokers" || what === "consumables" ? what : "facts";
    cells = rows.map((r) => recs.map((rec) => rec.influence?.[src]?.[r.i] ?? null));
  }
  if (evo.sort === "value") {
    const order = rows.map((_, k) => k).sort((a, b) => (cells[b].at(-1) ?? -Infinity) - (cells[a].at(-1) ?? -Infinity));
    rows = order.map((k) => rows[k]);
    cells = order.map((k) => cells[k]);
  }
  return { side, rows, cells };
}

function renderCorrections(recs, cfg) {
  document.querySelectorAll("#cat-switch [data-cat]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.cat === evo.cat)));
  const { side, rows, cells } = category(recs, cfg);
  const full = Array.isArray(cfg.network?.items);
  const values = cells.flat().filter((v) => v !== null);
  const max = Math.max(0.05, ...values.map(Math.abs));
  $("#corr-legend").innerHTML = side === "out"
    ? '<span><i class="sw up"></i>valued up</span><span><i class="sw down"></i>valued down</span><span><i class="sw none"></i>about none</span>'
    : '<span><i class="sw ramp"></i>none → strong</span>';
  $("#corr-hint").textContent = !full ? "This run recorded only its largest corrections each generation, so most cards are blank; continue it (button above) to record every card."
    : side === "out" ? `How much the network revalues each card, generation by generation (scale: ±${max.toFixed(2)} power). Hover a cell.`
    : `How strongly each input moves the network's corrections of all 252 items (largest here ${max.toFixed(2)} power per unit). Zero until it learns to use the input.`;
  evo.charts.corr.setData({ gens: recs.map((r) => r.gen), max, cells, rows, mode: side === "out" ? "signed" : "magnitude" });
  // what moved most since the previous generation (corrections, every category)
  const byGen = correctionsByGen(recs, cfg);
  if (byGen.length < 2) return;
  const latest = byGen[byGen.length - 1].map, prev = byGen[byGen.length - 2].map;
  const moves = [...latest.entries()].filter(([k]) => prev.has(k)).map(([k, v]) => [k, v, v - prev.get(k)])
    .sort((a, b) => Math.abs(b[2]) - Math.abs(a[2])).slice(0, 8);
  $("#movers-hint").textContent = `generation ${recs[recs.length - 2].gen} → ${recs[recs.length - 1].gen}`;
  $("#movers").replaceChildren(...moves.map(([k, v, dv]) => {
    const [kind, name] = k.split("|");
    const cell = el("div", "learned-item");
    const pic = kind === "keep" ? el("div", "keep-art", `keep a ${esc(name)}`) : sprite(itemEl({ kind: KIND_OF[kind], name }), 0.3);
    cell.append(pic, el("div", "", `<div class="li-name">${esc(itemLabel(kind, name))}</div><div class="li-move ${dv >= 0 ? "up" : "down"}">${dv >= 0 ? "▲ +" : "▼ −"}${Math.abs(dv).toFixed(3)}</div><div class="li-kind">now ${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}</div>`));
    cell.addEventListener("pointermove", (e) => evo.tooltip.show(`<div class="tt-title">${esc(itemLabel(kind, name))}</div>${effectOf({ kind, name })}${pairsOf({ kind, name })}`, e.clientX, e.clientY));
    cell.addEventListener("pointerleave", () => evo.tooltip.hide());
    return cell;
  }));
}

function describeCorrection(row, gen, v) {
  if (evo.cat.startsWith("in:")) return describeInfluence(row, gen, v);
  const pic = artOf(row.kind, row.name);
  const img = pic ? `<img class="tt-art" src="${pic}" alt="">` : "";
  if (v === null || v === undefined) return `<div class="tt-title">${esc(row.label)}</div>${img}${effectOf(row)}<div>Generation ${gen}: not among the 40 largest corrections it logged.</div>${pairsOf(row)}`;
  const pct = `${Math.round(Math.abs(Math.exp(v) - 1) * 100)}% ${v >= 0 ? "more" : "less"}`;
  return `<div class="tt-title">${esc(row.label)} · generation ${gen}</div>${img}${effectOf(row)}<div class="tt-row"><span class="tt-muted">correction</span><b>${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(3)}</b></div>`
    + `<div>In an average situation it is valued as if it made hands score about ${pct} than the value bot alone would say.</div>${pairsOf(row)}`;
}

// What a card does (or what an input means), from /api/evolve/items.
function effectOf(row) {
  const text = row.kind === "fact" ? evo.texts.facts[row.name] : evo.texts.items[`${row.kind}|${row.name}`];
  return text ? `<div class="tt-effect">${esc(text)}</div>` : "";
}

// ---- what goes best and worst with a card in scoring (/api/evolve/synergy, made once) ---------------
async function loadSynergy() {
  try {
    evo.synergy = await api("/api/evolve/synergy");
  } catch { /* the lists just don't show */ }
  if (evo.synergy?.state === "computing") setTimeout(loadSynergy, 5000);
}

function pairsOf(row) {
  const s = evo.synergy;
  if (s?.state === "computing") return '<div class="tt-note">Working out what each card plays best with (about a minute, once)…</div>';
  const r = s?.cards?.[`${row.kind}|${row.name}`];
  if (!r) return "";
  const line = ([kind, name, label, v]) => {
    const pic = artOf(kind, name);
    return `<div class="tt-pair">${pic ? `<img src="${pic}" alt="">` : '<i class="tt-dot"></i>'}<span>${esc(label)}</span>`
      + `<b class="${v >= 0 ? "up" : "down"}">${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}</b></div>`;
  };
  const list = (xs) => (xs.length ? xs.map(line).join("") : '<span class="tt-muted">nothing notable</span>');
  return `<div class="tt-pairs"><div><div class="tt-pairs-h up">Plays best with</div>${list(r.up)}</div><div><div class="tt-pairs-h down">Plays worst with</div>${list(r.down)}</div></div>`
    + `<div class="tt-note">${r.via && row.kind !== "fact" ? `As ${esc(r.via)} (what it makes). ` : ""}How much more hands score with both than the two add alone, `
    + `in build power (+0.1 ≈ 10% more), over ${s.hands} hands from a standard deck. Only scoring counts: not money, growth or rule changes.</div>`;
}

// ---- value by ante -------------------------------------------------------------------------------
async function loadTiming(id, gen) {
  if (!gen) return;
  const key = `${id}@${gen}`;
  if (evo.timingFor === key && evo.timing?.state === "done") return;
  const t = await api(`/api/evolve/runs/${encodeURIComponent(id)}/timing`);
  if (id !== evo.selected) return;
  evo.timing = t;
  evo.timingFor = key;
  if (t.state === "computing") setTimeout(() => loadTiming(id, gen).then(renderTiming), 3000);
}

function renderTiming() {
  const t = evo.timing;
  const [side, what] = evo.cat.split(":");
  if (!t || t.state !== "done") {
    $("#timing-hint").textContent = t?.state === "computing" ? `Valuing every card at each ante with the champion (generation ${t.gen}) over 16 games: a minute or two.` : "No champion yet.";
    evo.charts.timing.setData({ gens: [], rows: [], cells: [], max: 1 });
    return;
  }
  if (side !== "out") {
    $("#timing-hint").textContent = "Pick a card category under \"What it corrects\" to see its value by ante.";
    evo.charts.timing.setData({ gens: [], rows: [], cells: [], max: 1 });
    return;
  }
  const mode = evo.timingMode;
  let rows = t.items.map(([kind, name], i) => ({ kind, name, i, label: itemLabel(kind, name) })).filter((r) => r.kind === what);
  let cells = rows.map((r) => t[mode][r.i]);
  if (evo.sort === "value") {
    const avg = (xs) => { const v = xs.filter((x) => x !== null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : -Infinity; };
    const order = rows.map((_, k) => k).sort((a, b) => avg(cells[b]) - avg(cells[a]));
    rows = order.map((k) => rows[k]);
    cells = order.map((k) => cells[k]);
  }
  const max = Math.max(0.05, ...cells.flat().filter((v) => v !== null).map(Math.abs));
  $("#timing-legend").innerHTML = '<span><i class="sw up"></i>worth more</span><span><i class="sw down"></i>worth less (or a cost)</span>';
  $("#timing-hint").textContent = `The champion (generation ${t.gen}) played ${t.seeds} benchmark seeds and valued every card at the first shop of each ante. `
    + (mode === "total" ? "Total worth is what it would pay for the card then, in build power (+0.1 ≈ hands scoring 10% more), before its price."
      : "The network's correction is only what the network adds to the value bot's own estimate.")
    + (evo.timingScale === "row" ? " Each row is shaded on its own scale, to show how that card's worth moves through the run." : " One scale for all rows, to compare cards.")
    + ` Late antes rest on fewer shops (${t.antes.map((a, k) => `ante ${a}: ${t.shops[k]}`).join(", ")}), so they are noisier.`;
  const rowMax = evo.timingScale === "row" ? cells.map((c) => Math.max(0.02, ...c.filter((v) => v !== null).map(Math.abs))) : null;
  evo.charts.timing.setData({ gens: t.antes, rows, cells, max, rowMax, mode: "signed", colLabel: (a) => `ante ${a}`,
    total: rows.map((r) => t.total[r.i]), correction: rows.map((r) => t.correction[r.i]) });
}

function describeTiming(row, ante, v) {
  const t = evo.timing;
  const k = t.antes.indexOf(ante);
  const total = t.total[row.i][k], corr = t.correction[row.i][k];
  const pic = artOf(row.kind, row.name);
  const img = pic ? `<img class="tt-art" src="${pic}" alt="">` : "";
  const fmt = (x) => (x === null ? "—" : `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(2)}`);
  return `<div class="tt-title">${esc(row.label)} · ante ${ante}</div>${img}${effectOf(row)}`
    + `<div class="tt-row"><span class="tt-muted">total worth</span><b>${fmt(total)}</b></div>`
    + (total !== null ? `<div class="tt-row"><span class="tt-muted">value bot</span><b>${fmt(total - corr)}</b></div>` : "")
    + `<div class="tt-row"><span class="tt-muted">network</span><b>${fmt(corr)}</b></div>`
    + `<div>Worth in build power, before the price: +0.1 is hands scoring about 10% more.</div>${pairsOf(row)}`;
}

function describeInfluence(row, gen, v) {
  const pic = row.kind !== "fact" ? artOf(row.kind, row.name) : null;
  const img = pic ? `<img class="tt-art" src="${pic}" alt="">` : "";
  if (v === null || v === undefined) return `<div class="tt-title">${esc(row.label)}</div>${img}${effectOf(row)}<div>Not recorded for generation ${gen}.</div>`;
  const what = row.kind === "joker" ? `Owning ${row.name}` : row.kind !== "fact" ? `Holding ${row.name}` : `A change in ${row.name} (from 0 to 1)`;
  return `<div class="tt-title">${esc(row.label)} · generation ${gen}</div>${img}${effectOf(row)}<div class="tt-row"><span class="tt-muted">influence</span><b>${v.toFixed(3)}</b></div>`
    + `<div>${esc(what)} moves the network's corrections of all 252 items by ${v.toFixed(2)} power in total (root of the sum of squares). 0 means the network ignores it.</div>${pairsOf(row)}`;
}

// ---- what a weight is ("?" next to it) ----------------------------------------------------------
function sprite(e, z) {
  const w = el("span", `sprite ${e.classList.contains("pack-art") ? "pack" : ""}`);
  w.style.setProperty("--z", z);
  w.append(e);
  return w;
}

function itemCell(it, withText) {
  const cell = el("div", `gi-item${withText ? " wide" : ""}`);
  const card = it.kind === "Playing card" ? itemEl(it) : itemEl({ kind: it.kind, name: it.name, edition: it.edition });
  cell.append(sprite(card, withText ? 0.5 : 0.36));
  const label = el("div", "gi-name", esc(it.name) + (it.edition ? ` <span class="tt-muted">(${esc(it.edition)})</span>` : ""));
  cell.append(withText ? Object.assign(el("div", "gi-text"), { innerHTML: `${label.outerHTML}<p>${esc(it.text)}</p>` }) : label);
  if (!withText) {
    cell.addEventListener("pointermove", (e) => evo.tooltip.show(`<div class="tt-title">${esc(it.name)}${it.rarity ? ` <span class="tt-muted">${esc(it.rarity)}</span>` : ""}</div><div>${esc(it.text)}</div>`, e.clientX, e.clientY));
    cell.addEventListener("pointerleave", () => evo.tooltip.hide());
  }
  return cell;
}

// How to read a weight's numbers, worked through with the champion's own weights.
function howToRead(g, d, info) {
  const c = d.champion, money = c.money, v = c[g.name];
  const score = (p) => `${Math.abs(Math.round((Math.exp(p) - 1) * 100))}% ${p >= 0 ? "more" : "less"}`;
  const signed = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(2)}`;
  const net = (worth, price) => {
    const cost = price * money, n = worth - cost;
    return `worth ${worth.toFixed(2)} − price $${price} × ${money.toFixed(3)} = ${cost.toFixed(2)} → net <b>${signed(n)}</b>: `
      + (n > 0 ? "the bot buys it when it has the money and nothing is worth more" : "the bot doesn't buy it on its own (the planner still can)");
  };
  const lines = ["<b>Champion</b>: this run's best weights · <b>hand-set</b>: where evolution started · <b>population</b>: the average of the current weight sets ± how much they differ (small = they agree) · <b>range</b>: where evolution may move it.",
    "Worths are in <b>build power</b>, the average log of the best hand's score: +0.1 is a build whose hands score about 10% more."];
  const bonus = ["grows", "pays", "rules", "negative"].includes(g.name) || g.name.startsWith("rarity:");
  if (g.name === "money") lines.push(`${v.toFixed(3)} per $1: a $5 purchase has to add at least ${(5 * v).toFixed(2)} power, a build that scores about ${score(5 * v)}.`);
  else if (g.name === "interest") lines.push(`${v.toFixed(3)} per $1 of interest: spending from $25 to $20 loses $1 of interest each round, which costs ${v.toFixed(2)} power on top of the price.`);
  else if (bonus) lines.push(`${signed(v)} is added to such a joker's worth: it is valued as if it made hands score about ${score(v)} than it does today. 0 would judge it on today's hands alone.`);
  else if (g.name === "sell_margin") lines.push(`With every slot full, a new joker replaces the weakest only if it is worth ${v.toFixed(2)} more power (hands scoring about ${score(v)}).`);
  else if (info.sizes) for (const sz of info.sizes) lines.push(`${esc(sz.name)}: ${v.toFixed(2)} × ${sz.mult} for its size, ${net(v * sz.mult, sz.cost)}.`);
  else if (info.price != null) lines.push(`${esc(info.price_of)}: ${net(v, info.price)}.`);
  if (info.price != null || info.sizes) lines.push("A purchase that takes money below a multiple of $5 also pays for the interest it loses (see Money).");
  return `<div class="gi-read"><h4>How to read these numbers</h4><ul>${lines.map((l) => `<li>${l}</li>`).join("")}</ul></div>`;
}

function showInfo(g, e) {
  const info = evo.genes[g.name] || {};
  const d = evo.charts.genes.data;
  const fmt = (v) => (g.section === "Money" ? v.toFixed(3) : v.toFixed(2));
  const box = $("#gene-info");
  const values = d ? `Champion <b>${fmt(d.champion[g.name])}</b> · hand-set <b>${fmt(d.baseline[g.name])}</b>`
    + (d.mean ? ` · population <b>${fmt(d.mean[g.name])} ± ${fmt(d.sd[g.name])}</b>` : "") + ` · range ${fmt(g.low)} to ${fmt(g.high)}` : "";
  box.innerHTML = `<button type="button" class="gi-close" aria-label="Close">×</button><div class="gi-section">${esc(g.section)}</div>`
    + `<h3>${esc(g.label)}</h3><div class="gi-values">${values}</div><p>${esc(info.text || "")}</p>${d ? howToRead(g, d, info) : ""}`;
  const items = info.items || [];
  if (items.length) {
    const grid = el("div", `gi-items${items.length <= 3 ? " few" : ""}`);
    grid.append(...items.map((it) => itemCell(it, items.length <= 3)));
    box.append(grid);
    if (items.length > 3) box.append(el("p", "hint", `${items.length} cards · hover one for what it does`));
  }
  box.querySelector(".gi-close").addEventListener("click", hideInfo);
  box.hidden = false;
  const r = box.getBoundingClientRect();
  box.style.left = `${Math.max(8, Math.min(e.clientX + 18, innerWidth - r.width - 8))}px`;
  box.style.top = `${Math.max(8, Math.min(e.clientY - 40, innerHeight - r.height - 8))}px`;
}

function hideInfo() {
  $("#gene-info").hidden = true;
  evo.tooltip.hide();
}

// ---- actions -----------------------------------------------------------------------------------
function showError(err) {
  $("#e-error").textContent = err.message || String(err);
}

async function startRun(e) {
  e.preventDefault();
  $("#e-error").textContent = "";
  try {
    const { id } = await api("/api/evolve/runs", { kind: $("#e-kind").value, generations: Number($("#e-generations").value),
      population: Number($("#e-population").value), pairs: Number($("#e-pairs").value), seeds: Number($("#e-seeds").value) });
    await pollRuns();
    selectRun(id);
    schedule();
  } catch (err) {
    showError(err);
  }
}

function note() {
  const network = $("#e-kind").value === "network";
  $("#f-population").hidden = network;
  $("#f-pairs").hidden = !network;
  const candidates = network ? 2 * (Number($("#e-pairs").value) || 0) : Number($("#e-population").value) || 0;
  const runs = candidates * (Number($("#e-seeds").value) || 0) + 48;
  const gens = Number($("#e-generations").value) || 0;
  $("#e-note").textContent = `${runs.toLocaleString("en-US")} runs per generation, 48 of them the benchmark; about ${duration(runs * 0.035 * gens)} in all on this machine. The seed table build pauses meanwhile.`
    + (network ? " The network starts neutral (plays like the value bot) and learns corrections." : "");
}

function schedule() {
  clearTimeout(evo.timer);
  const tick = async () => {
    try {
      await pollRuns();
      await pollSweep().catch(() => {});
      await pollDetail();
    } catch (err) {
      showError(err);
    }
    const active = evo.runs.some((r) => r.state === "running" || r.state === "starting");
    evo.timer = setTimeout(tick, active ? 2000 : 8000);
  };
  tick();
}

async function init() {
  const tooltip = evo.tooltip = new Tooltip($("#tooltip"));
  evo.charts = {
    bench: new GenChart($("#bench-chart"), { tooltip, format: progress }),
    fit: new GenChart($("#fit-chart"), { tooltip, format: progress }),
    genes: new GeneChart($("#genes-chart"), { tooltip, onInfo: showInfo }),
    heat: new GeneHeatmap($("#heat-chart"), { tooltip }),
    corr: new CorrectionHeatmap($("#corr-chart"), { tooltip, describe: describeCorrection }),
    timing: new CorrectionHeatmap($("#timing-chart"), { tooltip, describe: describeTiming }),
  };
  ["#e-population", "#e-pairs", "#e-seeds", "#e-generations", "#e-kind"].forEach((id) => $(id).addEventListener("input", note));
  note();
  $("#evolve-setup").addEventListener("submit", startRun);
  $("#runs").addEventListener("click", (e) => {
    const item = e.target.closest("[data-run]");
    if (item) selectRun(item.dataset.run);
  });
  $("#sweep-item").addEventListener("click", () => selectRun("sweep"));
  $("#sweep-table").addEventListener("pointermove", (e) => {
    const cell = e.target.closest(".sweep-cell");
    const html = cell ? describeSweepCell(cell.dataset.rule, Number(cell.dataset.s)) : "";
    if (html) evo.tooltip.show(html, e.clientX, e.clientY);
    else evo.tooltip.hide();
  });
  $("#sweep-table").addEventListener("pointerleave", () => evo.tooltip.hide());
  $("#run-stop").addEventListener("click", async () => {
    try { await api(`/api/evolve/runs/${encodeURIComponent(evo.selected)}/stop`, {}); } catch (err) { showError(err); }
  });
  $("#cat-switch").addEventListener("click", (e) => {
    const b = e.target.closest("[data-cat]");
    if (!b) return;
    evo.cat = b.dataset.cat;
    renderRun();
  });
  $("#corr-sort").addEventListener("change", (e) => { evo.sort = e.target.value; renderRun(); });
  $("#timing-mode").addEventListener("change", (e) => { evo.timingMode = e.target.value; renderTiming(); });
  $("#timing-scale").addEventListener("change", (e) => { evo.timingScale = e.target.value; renderTiming(); });
  $("#run-continue").addEventListener("click", async () => {
    try {
      const { id } = await api("/api/evolve/runs", { kind: "network", init: evo.selected, generations: Number($("#e-generations").value),
        pairs: Number($("#e-pairs").value), seeds: Number($("#e-seeds").value) });
      await pollRuns();
      selectRun(id);
    } catch (err) { showError(err); }
  });
  $("#run-use").addEventListener("click", async () => {
    try { await api(`/api/evolve/runs/${encodeURIComponent(evo.selected)}/use`, {}); await pollRuns(); await pollDetail(); } catch (err) { showError(err); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideInfo(); });
  document.addEventListener("pointerdown", (e) => { if (!e.target.closest("#gene-info, .gene-help")) hideInfo(); });
  schedule();
  const [meta, genes, texts] = await Promise.all([api("/api/meta"), api("/api/evolve/genes"), api("/api/evolve/items")]);
  Object.assign(art, meta.art);
  evo.genes = genes;
  evo.texts = texts;
  loadSynergy();
}

init();
