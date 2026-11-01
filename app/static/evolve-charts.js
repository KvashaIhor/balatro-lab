// Hand-built SVG charts for the Evolution tab: values per generation, the weights against their ranges, and
// the champion's weights over generations. Thin marks, recessive grid, direct labels, hover tooltips.

const SVG = "http://www.w3.org/2000/svg";

export function el(tag, attrs = {}, parent = null, text = null) {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== null) e.textContent = text;
  if (parent) parent.appendChild(e);
  return e;
}

// Progress (blinds beaten, plus the share of the failed blind) and the ante it means.
export const progress = (v) => `${v.toFixed(2)} · ante ${Math.floor(v / 3) + 1}`;

function niceStep(range, count) {
  const raw = range / Math.max(count, 1);
  const pow = 10 ** Math.floor(Math.log10(raw || 1));
  const m = raw / pow;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * pow;
}

export class Tooltip {
  constructor(node) {
    this.node = node;
  }
  show(html, x, y) {
    this.node.innerHTML = html;
    this.node.hidden = false;
    const r = this.node.getBoundingClientRect();
    const left = x + 16 + r.width > innerWidth - 8 ? x - 16 - r.width : x + 16;
    const top = Math.min(Math.max(8, y - r.height / 2), innerHeight - r.height - 8);
    this.node.style.left = `${left}px`;
    this.node.style.top = `${top}px`;
  }
  hide() {
    this.node.hidden = true;
  }
}

class SvgChart {
  constructor(container, height) {
    this.container = container;
    this.height = height;
    this.svg = el("svg", { height });
    container.appendChild(this.svg);
    new ResizeObserver(() => this.draw()).observe(container);
  }
  get width() {
    return Math.max(this.container.clientWidth, 280);
  }
  clear() {
    this.svg.textContent = "";
    this.svg.setAttribute("viewBox", `0 0 ${this.width} ${this.height}`);
    this.svg.setAttribute("height", this.height);
  }
  draw() {}
}

// Values per generation: lines, optional shaded bands, reference lines, a hover crosshair.
export class GenChart extends SvgChart {
  constructor(container, { tooltip, height = 220, format = (v) => v.toFixed(2) }) {
    super(container, height);
    Object.assign(this, { tooltip, format });
    this.data = null;
    this.m = { l: 48, r: 150, t: 14, b: 26 };
    this.svg.addEventListener("pointermove", (e) => this.hover(e));
    this.svg.addEventListener("pointerleave", () => {
      this.tooltip.hide();
      if (this.hoverG) this.hoverG.textContent = "";
    });
  }
  setData(data) {
    // { gens, series: [{ label, color, values }], bands: [{ lo, hi, label }], refs: [{ value, label }] }
    this.data = data;
    this.draw();
  }
  x(i) {
    const n = this.data.gens.length;
    return this.m.l + (n > 1 ? i / (n - 1) : 0.5) * (this.width - this.m.l - this.m.r);
  }
  y(v) {
    const h = this.height - this.m.t - this.m.b;
    return this.m.t + h - ((v - this.y0) / (this.y1 - this.y0)) * h;
  }
  draw() {
    this.clear();
    const d = this.data;
    if (!d || !d.gens.length) return;
    const svg = this.svg;
    const refs = d.refs || [];
    const all = [...d.series.flatMap((s) => s.values), ...(d.bands || []).flatMap((b) => [...b.lo, ...b.hi]), ...refs.map((r) => r.value)];
    let lo = Math.min(...all), hi = Math.max(...all);
    if (hi - lo < 0.5) [lo, hi] = [lo - 0.25, hi + 0.25];
    const step = niceStep(hi - lo, 4);
    this.y0 = Math.floor(lo / step) * step;
    this.y1 = Math.ceil(hi / step) * step;
    const right = this.width - this.m.r;
    for (let v = this.y0; v <= this.y1 + 1e-9; v += step) {
      el("line", { x1: this.m.l, x2: right, y1: this.y(v), y2: this.y(v), class: "gridline" }, svg);
      el("text", { x: this.m.l - 8, y: this.y(v), "text-anchor": "end", "dominant-baseline": "central", class: "axis-text" }, svg, v.toFixed(step < 1 ? 1 : 0));
    }
    const n = d.gens.length;
    const xStep = Math.max(1, niceStep(n, 6));
    for (let i = 0; i < n; i++) {
      if (i === 0 || d.gens[i] % xStep === 0) el("text", { x: this.x(i), y: this.height - 8, "text-anchor": "middle", class: "axis-text" }, svg, i === 0 ? `gen ${d.gens[i]}` : String(d.gens[i]));
    }
    for (const r of refs) {
      el("line", { x1: this.m.l, x2: right, y1: this.y(r.value), y2: this.y(r.value), class: "ref-line" }, svg);
      el("text", { x: this.m.l + 6, y: this.y(r.value) - 6, class: "ref-text" }, svg, `${r.label} ${this.format(r.value)}`);
    }
    for (const b of d.bands || []) {
      const top = b.hi.map((v, i) => `${this.x(i).toFixed(1)} ${this.y(v).toFixed(1)}`);
      const bottom = b.lo.map((v, i) => `${this.x(i).toFixed(1)} ${this.y(v).toFixed(1)}`).reverse();
      el("path", { d: `M${top.join("L")}L${bottom.join("L")}Z`, class: "band" }, svg);
    }
    const labels = [];
    for (const s of d.series) {
      const pts = s.values.map((v, i) => `${this.x(i).toFixed(1)} ${this.y(v).toFixed(1)}`);
      el("path", { d: `M${pts.join("L")}`, class: "series-line", stroke: s.color }, svg);
      labels.push({ s, v: s.values[n - 1], y: this.y(s.values[n - 1]) });
    }
    labels.sort((a, b) => a.y - b.y);
    labels.forEach((lb, i) => (lb.ly = i ? Math.max(lb.y, labels[i - 1].ly + 16) : lb.y));
    const ex = this.x(n - 1);
    for (const lb of labels) {
      el("circle", { cx: ex, cy: lb.y, r: 4.5, fill: lb.s.color, class: "end-dot" }, svg);
      const text = el("text", { x: ex + 10, y: lb.ly, "dominant-baseline": "central", class: "end-label" }, svg);
      el("tspan", {}, text, `${lb.s.label} `);
      el("tspan", { class: "v" }, text, lb.v.toFixed(2));
    }
    this.hoverG = el("g", {}, svg);
  }
  hover(e) {
    const d = this.data;
    if (!d || !d.gens.length || !this.hoverG) return;
    const r = this.svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * this.width;
    const n = d.gens.length;
    const i = Math.round(Math.min(Math.max((px - this.m.l) / (this.width - this.m.l - this.m.r), 0), 1) * (n - 1));
    this.hoverG.textContent = "";
    el("line", { x1: this.x(i), x2: this.x(i), y1: this.m.t, y2: this.height - this.m.b, class: "hover-line" }, this.hoverG);
    const rows = d.series.map((s) => `<div class="tt-row"><span><i class="swatch" style="background:${s.color}"></i>${s.label}</span><b>${this.format(s.values[i])}</b></div>`);
    for (const b of d.bands || []) rows.push(`<div class="tt-row"><span class="tt-muted">${b.label}</span><b>${b.lo[i].toFixed(2)} – ${b.hi[i].toFixed(2)}</b></div>`);
    this.tooltip.show(`<div class="tt-title">Generation ${d.gens[i]}</div>${rows.join("")}`, e.clientX, e.clientY);
  }
}

const norm = (g, v) => (v - g.low) / (g.high - g.low);
const fmtGene = (g, v) => (g.section === "Money" ? v.toFixed(3) : v.toFixed(2));

// One row per weight on its range: population mean ± sd, the hand-set value (ring), the champion (dot).
export class GeneChart extends SvgChart {
  constructor(container, { tooltip, onInfo = null }) {
    super(container, 100);
    this.tooltip = tooltip;
    this.onInfo = onInfo;              // (gene, event): the "?" next to a weight was clicked
    this.data = null;
  }
  setData(data) {
    this.data = data; // { genes, champion, baseline, mean, sd } (values by gene name)
    const sections = new Set(data.genes.map((g) => g.section)).size;
    this.height = 12 + sections * 30 + data.genes.length * 22;
    this.draw();
  }
  draw() {
    this.clear();
    const d = this.data;
    if (!d) return;
    const svg = this.svg;
    const labelW = Math.min(260, this.width * 0.36);
    const valueW = 120;
    const x0 = labelW + 12, x1 = this.width - valueW;
    const x = (v) => x0 + Math.min(Math.max(v, 0), 1) * (x1 - x0);
    let y = 12;
    let section = null;
    for (const g of d.genes) {
      if (g.section !== section) {
        section = g.section;
        el("text", { x: 0, y: y + 14, class: "gene-section" }, svg, section);
        y += 30;
      }
      const cy = y + 9;
      const row = el("g", {}, svg);
      el("rect", { x: 0, y: cy - 11, width: this.width, height: 22, fill: "transparent" }, row);
      el("text", { x: 24, y: cy, "dominant-baseline": "central", class: "gene-label" }, row, g.label);
      if (this.onInfo) {
        const help = el("g", { class: "gene-help", role: "button", tabindex: 0, "aria-label": `What is ${g.label}?` }, row);
        el("circle", { cx: 9, cy, r: 8 }, help);
        el("text", { x: 9, y: cy + 0.5, "text-anchor": "middle", "dominant-baseline": "central" }, help, "?");
        help.addEventListener("click", (e) => { e.stopPropagation(); this.tooltip.hide(); this.onInfo(g, e); });
        help.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.onInfo(g, e); } });
        help.addEventListener("pointermove", (e) => e.stopPropagation());
      }
      el("line", { x1: x(0), x2: x(1), y1: cy, y2: cy, class: "track" }, row);
      if (d.mean) {
        const lo = x(norm(g, d.mean[g.name] - d.sd[g.name])), hi = x(norm(g, d.mean[g.name] + d.sd[g.name]));
        el("rect", { x: lo, y: cy - 3, width: Math.max(hi - lo, 3), height: 6, rx: 3, class: "spread" }, row);
      }
      el("circle", { cx: x(norm(g, d.baseline[g.name])), cy, r: 5, class: "base-ring" }, row);
      el("circle", { cx: x(norm(g, d.champion[g.name])), cy, r: 5.5, class: "champ-dot" }, row);
      const text = el("text", { x: x1 + 14, y: cy, "dominant-baseline": "central", class: "gene-value" }, row);
      el("tspan", {}, text, fmtGene(g, d.champion[g.name]));
      el("tspan", { class: "base" }, text, `  ${fmtGene(g, d.baseline[g.name])}`);
      row.addEventListener("pointermove", (e) => {
        const rows = [["Champion", fmtGene(g, d.champion[g.name])], ["Hand-set", fmtGene(g, d.baseline[g.name])]];
        if (d.mean) rows.push(["Population", `${fmtGene(g, d.mean[g.name])} ± ${fmtGene(g, d.sd[g.name])}`]);
        rows.push(["Range", `${fmtGene(g, g.low)} – ${fmtGene(g, g.high)}`]);
        this.tooltip.show(`<div class="tt-title">${g.label}</div>${rows.map(([k, v]) => `<div class="tt-row"><span class="tt-muted">${k}</span><b>${v}</b></div>`).join("")}`, e.clientX, e.clientY);
      });
      row.addEventListener("pointerleave", () => this.tooltip.hide());
      y += 22;
    }
  }
}

// The champion's weights (rows) over generations (columns), shaded by position in each weight's range.
const RAMP = ["#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"];
const hexRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
function shade(v) {
  const x = Math.min(Math.max(v, 0), 1) * (RAMP.length - 1);
  const i = Math.min(Math.floor(x), RAMP.length - 2);
  const [a, b] = [hexRgb(RAMP[i]), hexRgb(RAMP[i + 1])];
  return `rgb(${a.map((c, k) => Math.round(c + (b[k] - c) * (x - i))).join(",")})`;
}

export class GeneHeatmap extends SvgChart {
  constructor(container, { tooltip }) {
    super(container, 100);
    this.tooltip = tooltip;
    this.data = null;
    this.svg.addEventListener("pointermove", (e) => this.hover(e));
    this.svg.addEventListener("pointerleave", () => this.tooltip.hide());
  }
  setData(data) {
    this.data = data; // { genes, gens, champions: [genome per generation] }
    this.cell = 13;
    this.height = 26 + data.genes.length * this.cell;
    this.draw();
  }
  layout() {
    const labelW = Math.min(230, this.width * 0.3);
    return { x0: labelW + 10, x1: this.width - 4 };
  }
  draw() {
    this.clear();
    const d = this.data;
    if (!d || !d.champions.length) return;
    const svg = this.svg;
    const { x0, x1 } = this.layout();
    const n = d.champions.length;
    const w = (x1 - x0) / n;
    d.genes.forEach((g, r) => {
      const y = r * this.cell;
      el("text", { x: x0 - 10, y: y + this.cell / 2, "text-anchor": "end", "dominant-baseline": "central", class: "axis-text" }, svg, g.label);
      d.champions.forEach((c, k) => el("rect", { x: x0 + k * w, y: y + 0.5, width: Math.max(w - (w > 4 ? 1 : 0), 0.6), height: this.cell - 1, fill: shade(norm(g, c[g.name])) }, svg));
    });
    const step = Math.max(1, niceStep(n, 6));
    for (let k = 0; k < n; k++) {
      if (k === 0 || d.gens[k] % step === 0) el("text", { x: x0 + (k + 0.5) * w, y: d.genes.length * this.cell + 16, "text-anchor": "middle", class: "axis-text" }, svg, k === 0 ? `gen ${d.gens[k]}` : String(d.gens[k]));
    }
  }
  hover(e) {
    const d = this.data;
    if (!d || !d.champions.length) return;
    const r = this.svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * this.width;
    const py = ((e.clientY - r.top) / r.height) * this.height;
    const { x0, x1 } = this.layout();
    const k = Math.floor(((px - x0) / (x1 - x0)) * d.champions.length);
    const row = Math.floor(py / this.cell);
    if (k < 0 || k >= d.champions.length || row < 0 || row >= d.genes.length) return this.tooltip.hide();
    const g = d.genes[row];
    this.tooltip.show(`<div class="tt-title">Generation ${d.gens[k]}</div><div class="tt-row"><span class="tt-muted">${g.label}</span><b>${fmtGene(g, d.champions[k][g.name])}</b></div>`, e.clientX, e.clientY);
  }
}

// A network's correction of each item (rows) over generations (columns): green up, red down, grey about none.
// Empty cells: that generation logged only its largest corrections, and this item wasn't among them.
export class CorrectionHeatmap extends SvgChart {
  constructor(container, { tooltip, describe }) {
    super(container, 100);
    this.tooltip = tooltip;
    this.describe = describe;          // (row, gen, value) -> tooltip html
    this.data = null;
    this.svg.addEventListener("pointermove", (e) => this.hover(e));
    this.svg.addEventListener("pointerleave", () => this.tooltip.hide());
  }
  setData(data) {
    this.data = data; // { rows: [{ label }], gens, cells: [[value|null per gen] per row], max, mode: signed|magnitude }
    this.cell = data.rows.length > 60 ? 12 : 15;
    this.height = 26 + data.rows.length * this.cell;
    this.draw();
  }
  layout() {
    const labelW = Math.min(220, this.width * 0.3);
    return { x0: labelW + 10, x1: this.width - 4 };
  }
  colour(v, row = 0) {
    if (v === null || v === undefined) return "rgba(255,255,255,0.03)";
    const t = Math.min(1, Math.abs(v) / ((this.data.rowMax ? this.data.rowMax[row] : this.data.max) || 1));
    if (this.data.mode === "magnitude") return shade(t * 0.999);
    const [r, g, b] = v >= 0 ? [53, 189, 134] : [254, 76, 64];
    const base = [58, 74, 77];
    return `rgb(${[r, g, b].map((c, k) => Math.round(base[k] + (c - base[k]) * t)).join(",")})`;
  }
  draw() {
    this.clear();
    const d = this.data;
    if (!d || !d.gens.length) return;
    const svg = this.svg;
    const { x0, x1 } = this.layout();
    const n = d.gens.length;
    const w = (x1 - x0) / n;
    d.rows.forEach((row, r) => {
      const y = r * this.cell;
      el("text", { x: x0 - 10, y: y + this.cell / 2, "text-anchor": "end", "dominant-baseline": "central", class: "axis-text" }, svg, row.label);
      d.cells[r].forEach((v, c) => el("rect", { x: x0 + c * w, y: y + 0.5, width: Math.max(w - (w > 4 ? 1 : 0), 0.6), height: this.cell - 1, fill: this.colour(v, r) }, svg));
    });
    const step = Math.max(1, niceStep(n, 6));
    for (let c = 0; c < n; c++) {
      const label = d.colLabel ? d.colLabel(d.gens[c], c) : c === 0 ? `gen ${d.gens[c]}` : String(d.gens[c]);
      if (d.colLabel || c === 0 || d.gens[c] % step === 0) el("text", { x: x0 + (c + 0.5) * w, y: d.rows.length * this.cell + 16, "text-anchor": "middle", class: "axis-text" }, svg, label);
    }
  }
  hover(e) {
    const d = this.data;
    if (!d || !d.gens.length) return;
    const r = this.svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * this.width;
    const py = ((e.clientY - r.top) / r.height) * this.height;
    const { x0, x1 } = this.layout();
    const c = Math.floor(((px - x0) / (x1 - x0)) * d.gens.length);
    const row = Math.floor(py / this.cell);
    if (c < 0 || c >= d.gens.length || row < 0 || row >= d.rows.length) return this.tooltip.hide();
    this.tooltip.show(this.describe(d.rows[row], d.gens[c], d.cells[row][c]), e.clientX, e.clientY);
  }
}
