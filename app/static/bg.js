// The game's swirling paint background, as one WebGL fragment shader (the same algorithm as Balatro's
// background shader: a pixelated, spun, iteratively warped field that blends three colours).

const VERT = `attribute vec2 p; void main() { gl_Position = vec4(p, 0.0, 1.0); }`;
const FRAG = `
precision highp float;
uniform vec2 size;
uniform float time, spin_time, contrast, spin_amount, pixel_fac;
uniform vec3 colour_1, colour_2, colour_3;
void main() {
  vec2 screen = vec2(gl_FragCoord.x, size.y - gl_FragCoord.y);
  float pixel_size = length(size) / pixel_fac;
  vec2 uv = (floor(screen / pixel_size) * pixel_size - 0.5 * size) / length(size) - vec2(0.12, 0.0);
  float uv_len = length(uv);
  float speed = spin_time * 0.5 * 0.2 + 302.2;
  float angle = atan(uv.y, uv.x) + speed - 0.5 * 20.0 * (spin_amount * uv_len + (1.0 - spin_amount));
  vec2 mid = (size / length(size)) / 2.0;
  uv = vec2(uv_len * cos(angle) + mid.x, uv_len * sin(angle) + mid.y) - mid;
  uv *= 30.0;
  speed = time * 2.0;
  vec2 uv2 = vec2(uv.x + uv.y);
  for (int i = 0; i < 5; i++) {
    uv2 += sin(max(uv.x, uv.y)) + uv;
    uv += 0.5 * vec2(cos(5.1123314 + 0.353 * uv2.y + speed * 0.131121), sin(uv2.x - 0.113 * speed));
    uv -= cos(uv.x + uv.y) - sin(uv.x * 0.711 - uv.y);
  }
  float contrast_mod = 0.25 * contrast + 0.5 * spin_amount + 1.2;
  float paint = min(2.0, max(0.0, length(uv) * 0.035 * contrast_mod));
  float c1p = max(0.0, 1.0 - contrast_mod * abs(1.0 - paint));
  float c2p = max(0.0, 1.0 - contrast_mod * abs(paint));
  float c3p = 1.0 - min(1.0, c1p + c2p);
  vec3 col = (0.3 / contrast) * colour_1 + (1.0 - 0.3 / contrast) * (colour_1 * c1p + colour_2 * c2p + colour_3 * c3p);
  gl_FragColor = vec4(col, 1.0);
}`;

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);

export function background(canvas) {
  const gl = canvas.getContext("webgl", { preserveDrawingBuffer: true });
  if (!gl) return { set() {}, freeze() {} };
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

  const state = { colour_1: "#7d459c", colour_2: "#4a3a5c", colour_3: "#261a30", contrast: 2, spin_amount: 0,
    pixel_fac: 700, frozen: null, t0: performance.now() };

  function draw(now) {
    // The canvas covers the window; it renders at the window's CSS size, like the game at its resolution.
    if (canvas.width !== canvas.clientWidth || canvas.height !== canvas.clientHeight) {
      canvas.width = canvas.clientWidth;
      canvas.height = canvas.clientHeight;
    }
    const t = state.frozen ?? { time: (now - state.t0) / 1000, spin_time: (now - state.t0) / 1000 };
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(u("size"), canvas.width, canvas.height);
    gl.uniform1f(u("time"), t.time);
    gl.uniform1f(u("spin_time"), t.spin_time);
    gl.uniform1f(u("contrast"), state.contrast);
    gl.uniform1f(u("spin_amount"), state.spin_amount);
    gl.uniform1f(u("pixel_fac"), state.pixel_fac);
    for (const k of ["colour_1", "colour_2", "colour_3"]) gl.uniform3f(u(k), ...hex(state[k]));
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    if (!state.frozen) requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);
  return {
    set(opts) { Object.assign(state, opts); if (state.frozen) requestAnimationFrame(draw); },
    freeze(time, spin_time) { state.frozen = { time, spin_time }; requestAnimationFrame(draw); },
  };
}
