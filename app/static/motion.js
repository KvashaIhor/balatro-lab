// Motion like the game's, fitted frame by frame to 60 fps gameplay footage (numbers in ANIMATION.md):
// - Everything that moves is a damped spring stepped 60 times per game second:
//   v = 0.435 v + 0.33 (target - x), x += v, at most 100 px per step. A 46 px move settles in ~0.12 s with a
//   ~10% overshoot; cards dealt from the deck travel at ~100 px per frame. Moving cards lean into their
//   sideways velocity and draw above cards at rest.
// - A sprite can follow a parent: its target is relative to the parent's position, so a softer parent
//   (the hand's anchor, v = 0.38 v + 0.12 (target - x)) gives the hand's slow, S-shaped rise and drop.
// - A hit ("juice") swells and wobbles a sprite: scale 1 + a sin(51t) (1 - t/0.4)^3, tilt r sin(54t) (1 - t/0.4)^2.
// - Cards at rest sway about 1.2 deg and 2 px over ~3 s.
// - A card that is ready (Invisible Joker) shakes: a small juice every 0.8 s while it stays ready (the game's
//   juice_card_until with juice_up(0.1, 0.1), recalled from the game's code, not fitted to footage).
// Drawing happens between steps (interpolated) on every display frame, so motion is smooth at any refresh
// rate. Game time runs at the chosen speed (1 = the footage); waits and tweens use it and stop on cancel().

export const STEP = 1 / 60;
const LEAN = 0.3, MAX_LEAN = 25, FLYING = 24;
// A card's shadow falls this far below it (footage: a thin strip under the hand and the jokers), drawn in one shared
// layer (board.js #shades) made see-through once, so where cards overlap their shadows don't darken twice.
const SHADOW = 10;
const JIGGLE = { every: 0.8, a: 0.1, r: 5.7 };   // seconds between, swell, tilt (deg: the game's 0.1 rad)
export const CANCEL = Symbol("cancel");

export class Sprite {
  // `at`: x, y (top left, game px; relative to the parent if it has one), r (deg), s (scale), o (opacity).
  // Options: m = margin subtracted from the position (card sprites have a 2.3 px clear edge), offset = move
  // by transform only (page elements already placed by CSS), lean = tilt with sideways speed, sway = idle
  // sway at rest, damp / pull / max = the spring.
  constructor(el, at = {}, { m = 0, offset = false, lean = false, sway = false, damp = 0.435, pull = 0.33, max = 100 } = {}) {
    this.el = el;
    this.T = { x: 0, y: 0, r: 0, s: 1, o: 1, ...at };
    this.V = { ...this.T };   // where it is now (on the page, whatever the parent)
    this.P = { ...this.T };   // where it was one step ago, to draw in between
    this.v = { x: 0, y: 0, r: 0, s: 0 };
    Object.assign(this, { m, offset, lean, sway, damp, pull, max, parent: null, z: 0, clock: null,
      juice: null, turn: null, phase: Math.random() * 100, painted: "", placed: false });
  }

  // Where it is heading, on the page.
  get goal() {
    const p = this.parent?.V;
    return p ? { x: this.T.x + p.x, y: this.T.y + p.y } : { x: this.T.x, y: this.T.y };
  }

  to(t) {
    Object.assign(this.T, t);
    return this;
  }

  // Put it somewhere at once (page coordinates), to move on from there.
  from(t) {
    Object.assign(this.V, t);
    Object.assign(this.P, t);
    return this;
  }

  snap() {
    Object.assign(this.V, this.T, this.goal);
    Object.assign(this.P, this.V);
    for (const k in this.v) this.v[k] = 0;
    this.juice = this.turn = null;
    return this;
  }

  get time() {
    return this.clock?.time ?? 0;
  }

  pop(a = 0.32, r = (Math.random() < 0.5 ? -3.5 : 3.5)) {
    this.juice = { t0: this.time, a, r };
    return this;
  }

  // Turn the card over: it narrows to an edge, `swap` changes its face, and it widens again.
  flip(swap, dur = 0.16) {
    this.turn = { t0: this.time, dur, swap, swapped: false };
    return this;
  }

  step(time) {
    if (this.jiggle && !this.juice && !this.clock?.still && time - (this.jiggled ?? -1) >= JIGGLE.every) {   // juice_card_until
      this.jiggled = time;
      this.pop(JIGGLE.a, Math.random() < 0.5 ? -JIGGLE.r : JIGGLE.r);
    }
    const { T, V, v, damp, pull, max } = this, g = this.goal;
    Object.assign(this.P, V);
    v.x = damp * v.x + pull * (g.x - V.x);
    v.y = damp * v.y + pull * (g.y - V.y);
    const speed = Math.hypot(v.x, v.y);
    if (speed > max) { v.x *= max / speed; v.y *= max / speed; }
    V.x += v.x;
    V.y += v.y;
    v.r = damp * v.r + pull * (T.r - V.r);
    V.r += v.r;
    v.s = damp * v.s + pull * (T.s - V.s);
    V.s += v.s;
    V.o += (T.o - V.o) * 0.3;
    if (this.juice && time - this.juice.t0 >= 0.4) this.juice = null;
    const turn = this.turn;
    if (turn) {
      if (!turn.swapped && time - turn.t0 >= turn.dur / 2) { turn.swapped = true; turn.swap?.(); }
      if (time - turn.t0 >= turn.dur) this.turn = null;
    }
  }

  // Draw it `alpha` of the way from the last step to this one, with juice, turn and sway at time `now`.
  paint(now, alpha, still) {
    if (!this.el) return;
    const { V, P, juice, turn } = this, at = (k) => P[k] + (V[k] - P[k]) * alpha;
    let x = at("x") - this.m, y = at("y") - this.m, r = at("r"), s = at("s"), sx = 1;
    if (this.lean && !still) r += Math.max(-MAX_LEAN, Math.min(MAX_LEAN, this.v.x * LEAN));
    if (juice) {
      const t = Math.max(0, now - juice.t0), left = Math.max(0, 1 - t / 0.4);
      s += juice.a * Math.sin(51 * t) * left ** 3;
      r += juice.r * Math.sin(54 * t) * left ** 2;
    }
    if (turn) sx = Math.abs(1 - 2 * Math.min(1, Math.max(0, now - turn.t0) / turn.dur));
    if (this.sway && !still) {
      const p = now * 2.1 + this.phase;
      r += 1.2 * Math.sin(p);
      x += 2 * Math.sin(p * 0.7 + 1);
      y += 1.5 * Math.cos(p * 0.9);
    }
    const g = this.goal, flying = Math.abs(g.x - V.x) + Math.abs(g.y - V.y) > FLYING;
    const z = this.z + (flying && !this.offset ? 100 : 0);
    const spin = Math.abs(r) > 0.01 || Math.abs(s - 1) > 0.0005 || sx !== 1
      ? `rotate(${r.toFixed(2)}deg) scale(${(s * sx).toFixed(4)}, ${s.toFixed(4)})` : "";
    const o = Math.max(0, Math.min(1, at("o")));
    const key = `${x.toFixed(2)}|${y.toFixed(2)}|${spin}|${o.toFixed(3)}|${z}`;
    if (key === this.painted) return;
    this.painted = key;
    const st = this.el.style;
    if (this.offset) {
      st.transform = Math.abs(x) + Math.abs(y) < 0.005 ? spin : `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px) ${spin}`;
    } else if (!still) {
      // Moving cards are placed by transform on their own layer: no layout, and their shadow isn't redrawn.
      if (!this.placed) { st.left = st.top = "0px"; st.willChange = "transform"; this.placed = true; }
      st.transform = `translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, 0) ${spin}`;
    } else {
      // Scene snapshots: placed exactly as a static page would be, for comparing with screenshots.
      st.left = `${x}px`;
      st.top = `${y}px`;
      st.transform = spin;
    }
    st.opacity = o > 0.995 ? "" : o.toFixed(3);
    st.zIndex = z || "";
    if (this.shadow) {
      this.shadow.style.transform = `translate3d(${x.toFixed(2)}px, ${(y + SHADOW).toFixed(2)}px, 0) ${spin}`;
      this.shadow.style.opacity = st.opacity;
    }
  }
}

// The clock, the sprites and everything waiting on game time. `still` (scene snapshots) turns off sway and
// leaning and places sprites exactly, so a fixed state renders the same every time.
export class Stage {
  constructor() {
    Object.assign(this, { sprites: new Set(), speed: 1, time: 0, acc: 0, last: null, timers: [], tweens: new Set(), still: false });
    requestAnimationFrame((now) => this.frame(now));
  }

  add(sp) {
    sp.clock = this;
    this.sprites.add(sp);
    return sp;
  }

  remove(sp) {
    this.sprites.delete(sp);
    sp.el?.remove();
    sp.shadow?.remove();
  }

  frame(now) {
    const dt = this.last === null ? 0 : Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    this.acc += dt * this.speed;
    let n = 0;
    while (this.acc >= STEP && n++ < 16) {
      this.acc -= STEP;
      this.tick();
    }
    if (n >= 16) this.acc = 0;
    this.paint();
    requestAnimationFrame((t) => this.frame(t));
  }

  tick() {
    this.time += STEP;
    for (const sp of this.sprites) sp.step(this.time);
    for (const tw of [...this.tweens]) {
      const p = Math.min(1, (this.time - tw.start) / tw.dur);
      tw.fn(p);
      if (p >= 1) { this.tweens.delete(tw); tw.res(); }
    }
    const due = this.timers.filter((t) => t.at <= this.time + 1e-9);
    if (due.length) {
      this.timers = this.timers.filter((t) => t.at > this.time + 1e-9);
      for (const t of due) t.res();
    }
  }

  // Draw every sprite as it stands between the last step and the next. Also called right after sprites are
  // added, so nothing shows for a frame before it is placed.
  paint() {
    const alpha = Math.min(1, this.acc / STEP), now = this.time - STEP + this.acc;
    for (const sp of this.sprites) sp.paint(now, alpha, this.still);
  }

  // Resolves after `sec` of game time; rejects with CANCEL if cancel() comes first.
  wait(sec) {
    if (sec <= 0) return Promise.resolve();
    return new Promise((res, rej) => this.timers.push({ at: this.time + sec, res, rej }));
  }

  // Calls fn(p) with p from 0 to 1 over `dur` of game time.
  tween(dur, fn) {
    fn(0);
    return new Promise((res, rej) => this.tweens.add({ start: this.time, dur: Math.max(dur, STEP), fn, res, rej }));
  }

  // Run fn after `sec` of game time unless cancelled, without holding up the caller.
  after(sec, fn) {
    this.wait(sec).then(fn, () => {});
  }

  cancel() {
    for (const t of this.timers) t.rej(CANCEL);
    for (const tw of this.tweens) tw.rej(CANCEL);
    this.timers = [];
    this.tweens.clear();
  }
}
