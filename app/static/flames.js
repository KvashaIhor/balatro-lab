// The flames the game draws on the chips and mult boxes when a hand reaches the blind's target on its own: the game's
// own flame shader (the user's copy, 30 Oct, a Godot port of Balatro's), run in WebGL on a square sprite per box,
// as the game draws it. The rest is set to match the game and the 60 fps gameplay footage measured on 28 Oct:
// - The sprite is about 2.5 game units square, on boxes 2 wide: 208 board px, centred on the box. Its row 116 sits on
//   the box's top edge, so the flame's solid base (the shader's band about uv.y 0.1) is behind the box.
// - Intensity aims at log5(score) - 2 and follows it through a slow spring that overshoots to about 1.8x near 1 s
//   and settles over 2-3 s. Measured through this shader that is ~17 px at a 900 score and ~50 px at 6,072, settling
//   near 10 px: the footage's ~20 px, ~58 px and ~10 px.
// - The shader's clock runs faster for a bigger flame (1 + 0.2 x intensity).
// - Its second colour is each box's colour mixed with the game's yellow, as the game derives it.
// The footage-based player this replaces drew recorded outlines (flame-data.json, now unused).

const SPRITE = 208;                     // board px a side
const EDGE = 116;                       // the sprite row on the box's top edge
const YELLOW = [0xfd, 0xa2, 0x00];
const FACE = { chips: [0x00, 0x92, 0xff], mult: [0xff, 0x4b, 0x40] };   // the boxes' colours (style.css --chips, --mult)

const VERT = `attribute vec2 p; varying vec2 v; void main() { v = vec2(p.x, -p.y) * 0.5 + 0.5; gl_Position = vec4(p, 0.0, 1.0); }`;
// The user's shader as given, in GLSL ES 1.0: the sprite's own uv (texture_details and image_details cancel for a
// sprite drawn alone), y down as the game samples it; a transparent pixel is 0 (the canvas is premultiplied).
const FRAG = `
precision highp float;
varying vec2 v;
uniform float time, amount, id;
uniform vec4 colour_1, colour_2;
const float PIXEL_SIZE_FAC = 60.0;
void main() {
  float intensity = min(10.0, amount);
  if (intensity < 0.1) { gl_FragColor = vec4(0.0); return; }
  vec2 uv = v - 0.5;
  vec2 floored_uv = floor(uv * PIXEL_SIZE_FAC) / PIXEL_SIZE_FAC;
  vec2 uv_scaled_centered = floored_uv;
  uv_scaled_centered += uv_scaled_centered * 0.01 * (sin(-1.123 * floored_uv.x + 0.2 * time) * cos(5.3332 * floored_uv.y + time * 0.931));
  vec2 flame_up_vec = vec2(0.0, mod(4.0 * time, 10000.0) - 5000.0 + mod(1.781 * id, 1000.0));
  float scale_fac = (7.5 + 3.0 / (2.0 + 2.0 * intensity));
  vec2 sv = uv_scaled_centered * scale_fac + flame_up_vec;
  float speed = mod(20.781 * id, 100.0) + 1.0 * sin(time + id) * cos(time * 0.151 + id);
  vec2 sv2 = vec2(0.0, 0.0);
  for (int i = 0; i < 5; i++) {
    float iteration_mod = (mod(float(i), 2.0) > 1.0 ? -1.0 : 1.0);
    sv2 += sv + 0.05 * sv2.yx * iteration_mod + 0.3 * (cos(length(sv) * 0.411) + 0.3344 * sin(length(sv)) - 0.23 * cos(length(sv)));
    sv += 0.5 * vec2(cos(cos(sv2.y) + speed * 0.0812) * sin(3.22 + sv2.x - speed * 0.1531),
                     sin(-sv2.x * 1.21222 + 0.113785 * speed) * cos(sv2.y * 0.91213 - 0.13582 * speed));
  }
  float smoke_res = max(0.0, ((length((sv - flame_up_vec) / scale_fac * 5.0) + 0.1 * (length(uv_scaled_centered) - 0.5))
                               * (2.0 / (2.0 + intensity * 0.2))));
  smoke_res = smoke_res + max(0.0, 2.0 - 0.3 * intensity) * max(0.0, 2.0 * (uv_scaled_centered.y - 0.5) * (uv_scaled_centered.y - 0.5));
  if (abs(uv.x) > 0.4) smoke_res += 10.0 * (abs(uv.x) - 0.4);
  float hole = length((uv - vec2(0.0, 0.1)) * vec2(0.19, 1.0));
  if (hole < min(0.1, intensity * 0.5) && smoke_res > 1.0) smoke_res += min(8.5, intensity * 10.0) * (hole - 0.1);
  if (smoke_res > 1.0) { gl_FragColor = vec4(0.0); return; }
  vec4 ret_col = colour_1;
  if (uv.y < 0.12) {
    float y_factor = 0.12 - uv.y;
    ret_col.rgb = ret_col.rgb * (1.0 - 0.5 * y_factor) + 2.5 * y_factor * colour_2.rgb;
    ret_col.rgb += ret_col.rgb * (-2.0 + 0.5 * intensity * smoke_res) * y_factor;
  }
  gl_FragColor = vec4(clamp(ret_col.rgb, 0.0, 1.0), 1.0);
}`;

// The game's second colour for a box: its colour half and half with yellow, lifted and squared (each channel 0.1-1).
const accent = (c) => c.map((x, i) => Math.min(1, Math.max(0.1, ((x / 255) * 0.5 + (YELLOW[i] / 255) * 0.5 + 0.1) ** 2)));

// One box's flame on its canvas: draw(time, amount) renders a frame.
function painter(canvas, box, id) {
  canvas.width = canvas.height = SPRITE;
  const gl = canvas.getContext("webgl", { premultipliedAlpha: true, antialias: false });
  if (!gl) return null;
  const shader = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  };
  const prog = gl.createProgram();
  gl.attachShader(prog, shader(gl.VERTEX_SHADER, VERT));
  gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FRAG));
  gl.linkProgram(prog);
  gl.useProgram(prog);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, "p");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const u = (name) => gl.getUniformLocation(prog, name);
  gl.uniform4f(u("colour_1"), ...FACE[box].map((x) => x / 255), 1);
  gl.uniform4f(u("colour_2"), ...accent(FACE[box]), 1);
  gl.uniform1f(u("id"), id);
  gl.viewport(0, 0, SPRITE, SPRITE);
  return (time, amount) => {
    gl.uniform1f(u("time"), time);
    gl.uniform1f(u("amount"), amount);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };
}

// Flames over a sidebar's chips and mult boxes (`host` gets two canvases, styled by .flames in style.css, behind the
// boxes). ignite(score): the hand being scored has reached the blind on its own, at this score (a higher one raises
// the flame); settle(): kept for the board's call, the spring settles by itself; out(): it dies away.
export function makeFlames(host) {
  const box = document.createElement("div");
  box.className = "flames";
  box.innerHTML = '<canvas class="chips"></canvas><canvas class="mult"></canvas>';
  host.prepend(box);
  const base = 1 + Math.floor(Math.random() * 500);           // the game's sprite IDs: each flame its own pattern
  let paint = null;
  try {
    paint = [painter(box.children[0], "chips", base), painter(box.children[1], "mult", base + 1)].filter(Boolean);
  } catch { paint = null; }                                   // (no WebGL, or the shader failed: no flames)
  let target = 0, real = 0, vel = 0, clock = 0, last = 0, running = false;
  const frame = (now) => {
    const dt = Math.min(0.1, last ? (now - last) / 1000 : 0);
    last = now;
    // the spring the game's flame handler runs: velocity pulled toward the target, a falling one damped hard
    const keep = Math.exp(-0.4 * dt);
    if (vel < 0) vel *= Math.max(0, 1 - 10 * dt);
    vel = (1 - keep) * (target - real) * dt * 25 + keep * vel;
    real = Math.max(0, real + vel);
    clock += dt * (1 + 0.2 * target);
    if (paint) for (const p of paint) p(clock, real);
    running = target > 0 || real > 0.02 || Math.abs(vel) > 1e-4;
    if (running) requestAnimationFrame(frame);
    else { last = 0; real = vel = 0; if (paint) for (const p of paint) p(clock, 0); }
  };
  const go = () => { if (!running) { running = true; requestAnimationFrame(frame); } };
  return {
    ignite(score) {
      const want = Math.max(0, Math.log(Math.max(1, score)) / Math.log(5) - 2);
      if (want > target) { target = want; go(); }
    },
    settle() {},
    out() { target = 0; go(); },
    reset() { target = real = vel = 0; go(); },
  };
}
