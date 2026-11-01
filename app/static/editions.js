// The game's edition effects (Foil, Holographic, Polychrome, Negative), applied pixel by pixel to card art.
// In the game they are shaders that move with time; here each is held at the moment that best matches the
// Balatro Wiki's pictures of the Joker in each edition (fitted on the 2x art; mean error 4/255 for Polychrome,
// 12 for Negative, 13-17 for Holographic and Foil, whose patterns move fastest). Results are cached per image.

const cache = new Map();

function rgb2hsl(r, g, b) {
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
  if (d === 0) return [0, 0, l];
  const s = l < 0.5 ? d / (mx + mn) : d / (2 - mx - mn);
  let h = r === mx ? (g - b) / d : g === mx ? 2 + (b - r) / d : 4 + (r - g) / d;
  h = (((h / 6) % 1) + 1) % 1;
  return [h, s, l];
}

function hue2rgb(p, q, t) {
  t = ((t % 1) + 1) % 1;
  return t < 1 / 6 ? p + (q - p) * 6 * t : t < 1 / 2 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p;
}

function hsl2rgb(h, s, l) {
  if (s === 0) return [l, l, l];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  return [hue2rgb(p, q, h + 1 / 3), hue2rgb(p, q, h), hue2rgb(p, q, h - 1 / 3)];
}

// The shared wavy field the game's Holographic and Polychrome shaders read hue shifts from.
function field(fx, fy, t, scale) {
  const cx = (fx - 0.5) * scale, cy = (fy - 0.5) * scale;
  const a = [cx + 50 * Math.sin(-t / 143.634), cy + 50 * Math.cos(-t / 99.4324)];
  const b = [cx + 50 * Math.cos(t / 53.1532), cy + 50 * Math.cos(t / 61.4532)];
  const c = [cx + 50 * Math.sin(-t / 87.53218), cy + 50 * Math.sin(-t / 49.0)];
  return (1 + (Math.cos(Math.hypot(...a) / 19.483) + Math.sin(Math.hypot(...b) / 33.155) * Math.cos(b[1] / 15.73)
    + Math.cos(Math.hypot(...c) / 27.193) * Math.sin(c[0] / 21.92))) / 2;
}

const EFFECTS = {
  Polychrome(r, g, b, ux, uy, fx, fy) {               // hue rolled across the card in a slow wave, saturated
    const delta = Math.max(r, g, b) - Math.min(r, g, b);
    const sat = 1 - Math.max(0, 0.05 * (1.1 - delta));
    const [h, s, l] = rgb2hsl(r * sat, g * sat, b);
    const res = 0.5 + 0.5 * Math.cos(2.62 + (field(fx, fy, 96, 50) - 0.5) * 3.14);
    return hsl2rgb((h + res + 0.17) % 1, Math.min(0.6, s + 0.5), l);
  },
  Holographic(r, g, b, ux, uy, fx, fy) {              // a lattice and a shifting pastel sheen over a dulled card
    const [h, s, l] = rgb2hsl(0.5 * r, 0.5 * g, 0.5 * b + 0.5);
    const res = 0.5 + 0.5 * Math.cos(2.36 + (field(fx, fy, 504, 250) - 0.5) * 3.14);
    const delta = 0.2 + 0.3 * (Math.max(r, g, b) - Math.min(r, g, b)) + 0.1 * Math.max(r, g, b);
    const k = 0.79;
    const fac = 0.5 * Math.max(Math.max(Math.max(0, 7 * Math.abs(Math.cos(ux * k * 20)) - 6),
      Math.max(0, 7 * Math.cos(uy * k * 45 + ux * k * 20) - 6)), Math.max(0, 7 * Math.cos(uy * k * 45 - ux * k * 20) - 6));
    const [hr, hg, hb] = hsl2rgb((h + res + fac) % 1, Math.min(1, s * 1.3), l * 0.6 + 0.4);
    return [(1 - delta) * r + delta * hr * 0.9, (1 - delta) * g + delta * hg * 0.8, (1 - delta) * b + delta * hb * 1.2];
  },
  Foil(r, g, b, ux, uy) {                             // blue ripples from the centre, blended over the card
    const ax = ux - 0.5, ay = uy - 0.5, fr = 2.25, fg = 10, rad = Math.hypot(ax, ay);
    const delta = Math.min(Math.max(r, g, b), Math.max(0.5, 1 - Math.min(r, g, b)));
    const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
    const fac = clamp(2 * Math.sin(90 * rad + fr * 2 + 3 * (1 + 0.8 * Math.cos(113.1121 * rad - fr * 3.121))) - 1 - Math.max(5 - 90 * rad, 0), 0, 1);
    const rx = Math.cos(fr * 0.1221), ry = Math.sin(fr * 0.3512);
    const angle = (rx * ax + ry * ay) / (Math.hypot(rx, ry) * Math.max(rad, 1e-9));
    const fac2 = clamp(5 * Math.cos(fg * 0.3 + angle * 3.14 * (2.2 + 0.9 * Math.sin(fr * 1.65 + 0.2 * fg))) - 4 - Math.max(2 - 20 * rad, 0), 0, 1);
    const fac3 = 0.3 * clamp(2 * Math.sin(fr * 5 + ux * 3 + 3 * (1 + 0.5 * Math.cos(fr * 7))) - 1, -1, 1);
    const fac4 = 0.3 * clamp(2 * Math.sin(fr * 6.66 + uy * 3.8 + 3 * (1 + 0.5 * Math.cos(fr * 3.414))) - 1, -1, 1);
    const maxfac = Math.max(Math.max(fac, fac2, fac3, fac4, 0) + 2.2 * (fac + fac2 + fac3 + fac4), 0);
    const a = Math.min(1, 0.3 + 0.9 * Math.min(0.5, maxfac * 0.1));
    const over = [clamp(r - delta + delta * maxfac * 0.3, 0, 1), clamp(g - delta + delta * maxfac * 0.3, 0, 1), clamp(b + delta * maxfac * 1.9, 0, 1)];
    return [(1 - a) * r + a * over[0], (1 - a) * g + a * over[1], (1 - a) * b + a * over[2]];
  },
  Negative(r, g, b) {                                 // lightness inverted, hue mirrored, a slate tint added
    const [h, s, l] = rgb2hsl(r, g, b);
    const [nr, ng, nb] = hsl2rgb((((0.2 - h) % 1) + 1) % 1, s, 1 - l);
    return [nr + 47 / 255, ng + 64 / 255, nb + 87 / 255];
  },
};

// Apply an edition to a canvas in place.
export function paintEdition(canvas, edition) {
  const effect = EFFECTS[edition];
  if (!effect) return canvas;
  const ctx = canvas.getContext("2d");
  const { width: w, height: h } = canvas;
  const img = ctx.getImageData(0, 0, w, h);
  const px = img.data;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      if (px[i + 3] === 0) continue;
      const [r, g, b] = effect(px[i] / 255, px[i + 1] / 255, px[i + 2] / 255, (x + 0.5) / w, (y + 0.5) / h, x / w, y / h);
      px[i] = Math.round(Math.min(1, Math.max(0, r)) * 255);
      px[i + 1] = Math.round(Math.min(1, Math.max(0, g)) * 255);
      px[i + 2] = Math.round(Math.min(1, Math.max(0, b)) * 255);
    }
  }
  ctx.putImageData(img, 0, 0);
  return canvas;
}

export function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

// An image's art in an edition, as a data URL (cached).
export function withEdition(src, edition) {
  const key = `${src}|${edition}`;
  if (!cache.has(key)) {
    cache.set(key, loadImage(src).then((img) => {
      const canvas = Object.assign(document.createElement("canvas"), { width: img.naturalWidth, height: img.naturalHeight });
      canvas.getContext("2d").drawImage(img, 0, 0);
      return paintEdition(canvas, edition).toDataURL();
    }));
  }
  return cache.get(key);
}

// Swap an <img> for its art in `edition` once that is ready.
export function showEdition(img, edition) {
  if (!img?.src || !EFFECTS[edition]) return;
  withEdition(img.src, edition).then((url) => { img.src = url; }).catch(() => {});
}
