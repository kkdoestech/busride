import * as THREE from 'three';
import { eatenAt, landTime } from './cards.js';
import { ASPECT, BARS, H, ODDS_Y, PROMPT, REPO, SLOT, SLOTS, STATUS, SUBLINE, TAGLINE, TITLE, W } from './layout.js';
import { BEAT, DEAL_GAP, LOOP, easeOut, glitchAt, pulse, seg, smooth, wave } from './util.js';

// The words, drawn over the 3D scene in banner pixels (900×300, y down) so they stay sharp.
// They are always on screen: only the status line, the four slots and the title's glow move.

const SCALE = 2; // texture pixels per banner pixel
// The exact survival odds of perfect play (docs/SPEC.md, "Known values").
const ODDS = [0.5, 0.36199, 0.23771, 0.06307];
const MONO = '"JetBrains Mono", ui-monospace, monospace';
const GOLD = '#f2c45c';
const MUTED = '#a89a8a';
const RED = '#ff5f5f';
const CYAN = '#38bdf8';
const SHADOW = { color: 'rgba(0, 0, 0, 0.95)', blur: 8 };

const scratch = document.createElement('canvas').getContext('2d');

function measure(text, font, spacing) {
  scratch.font = font;
  scratch.letterSpacing = spacing;
  return scratch.measureText(text);
}

function canvasTexture(w, h, draw) {
  const canvas = document.createElement('canvas');
  canvas.width = w * SCALE;
  canvas.height = h * SCALE;
  const ctx = canvas.getContext('2d');
  ctx.scale(SCALE, SCALE);
  draw(ctx);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

const overlay = (map) => new THREE.MeshBasicMaterial({ map, transparent: true, depthTest: false, depthWrite: false });

// A text label anchored at its left edge, centre or right edge. `reserve` is the widest text it
// will ever show (the canvas keeps one size).
function label(text, { font, color, spacing = '0px', pad = 10, glow = SHADOW, align = 'left', size = 16, reserve = text }) {
  const w = Math.ceil(measure(reserve, font, spacing).width + 2 * pad);
  const h = Math.ceil(size * 1.4 + 2 * pad);
  const canvas = document.createElement('canvas');
  canvas.width = w * SCALE;
  canvas.height = h * SCALE;
  const ctx = canvas.getContext('2d');
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;

  function draw(str, fill) {
    ctx.setTransform(SCALE, 0, 0, SCALE, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.font = font;
    ctx.letterSpacing = spacing;
    ctx.textBaseline = 'middle';
    if (glow) {
      ctx.shadowColor = glow.color;
      ctx.shadowBlur = glow.blur;
    }
    ctx.fillStyle = fill;
    ctx.fillText(str, pad, h / 2 + 1);
    texture.needsUpdate = true;
  }

  let current = `${text}|${color}`;
  draw(text, color);
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), overlay(texture));
  return {
    mesh,
    width: w - 2 * pad,
    set(str, fill = color) {
      if (`${str}|${fill}` === current) return;
      current = `${str}|${fill}`;
      draw(str, fill);
    },
    place(x, y, alpha = 1) {
      const cx = align === 'left' ? x - pad + w / 2 : align === 'right' ? x + pad - w / 2 : x;
      mesh.position.set(cx, -y, 0);
      mesh.material.opacity = alpha;
      mesh.visible = alpha > 0.002;
    },
  };
}

// The title: gold letters on fire, with red and blue glitch ghosts. Flames rise off the letters
// all the time and blaze at the boom; a hot band sweeps across when the ride is solved.
function title() {
  const font = '900 58px Cinzel';
  const spacing = '4px';
  const text = 'BUSRIDE';
  const pad = { x: 30, top: 50, bottom: 22 };
  const m = measure(text, font, spacing);
  const ascent = m.actualBoundingBoxAscent;
  const w = Math.ceil(m.width + 2 * pad.x);
  const h = Math.ceil(ascent + pad.top + pad.bottom);
  const base = pad.top + ascent;
  const letters = canvasTexture(w, h, (ctx) => {
    ctx.font = font;
    ctx.letterSpacing = spacing;
    ctx.shadowColor = 'rgba(255, 36, 24, 0.85)';
    ctx.shadowBlur = 16;
    ctx.fillStyle = '#4a0610';
    ctx.fillText(text, pad.x, base);
    ctx.shadowBlur = 0;
    ctx.lineWidth = 3;
    ctx.strokeStyle = 'rgba(40, 6, 8, 0.9)';
    ctx.strokeText(text, pad.x, base);
    const g = ctx.createLinearGradient(0, base - ascent, 0, base);
    g.addColorStop(0, '#fff4cf');
    g.addColorStop(0.45, '#f2c65e');
    g.addColorStop(1, '#9c6a1c');
    ctx.fillStyle = g;
    ctx.fillText(text, pad.x, base);
  });
  // Where flames can rise: the letters smeared upward and softened.
  const flames = canvasTexture(w, h, (ctx) => {
    ctx.font = font;
    ctx.letterSpacing = spacing;
    ctx.filter = 'blur(2px)';
    for (let dy = 0; dy <= 30; dy += 2) {
      ctx.fillStyle = `rgba(255, 255, 255, ${0.13 * (1 - dy / 34)})`;
      ctx.fillText(text, pad.x, base - dy);
    }
  });

  const mat = new THREE.ShaderMaterial({
    uniforms: {
      map: { value: letters },
      flames: { value: flames },
      uPhase: { value: 0 },
      uFire: { value: 0 },
      uSplit: { value: 0 },
      uSlice: { value: 0 },
      uSeed: { value: 0 },
      uSweep: { value: -1 },
      uHeat: { value: 0 },
    },
    vertexShader: /* glsl */ `
      varying vec2 vUv;
      void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: /* glsl */ `
      uniform sampler2D map, flames;
      uniform float uPhase, uFire, uSplit, uSlice, uSeed, uSweep, uHeat;
      varying vec2 vUv;

      float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      // Value noise that repeats every \`period\` cells in y, so scrolling it one period loops.
      float noise(vec2 p, float period) {
        vec2 i = floor(p);
        vec2 f = fract(p);
        f = f * f * (3.0 - 2.0 * f);
        float y0 = mod(i.y, period);
        float y1 = mod(i.y + 1.0, period);
        return mix(mix(hash(vec2(i.x, y0)), hash(vec2(i.x + 1.0, y0)), f.x),
                   mix(hash(vec2(i.x, y1)), hash(vec2(i.x + 1.0, y1)), f.x), f.y);
      }

      void main() {
        vec2 uv = vUv;
        // Glitch: a few horizontal bands slide sideways during a burst.
        float band = floor(uv.y * 12.0);
        float hit = step(1.0 - 0.45 * uSlice, hash(vec2(band, uSeed)));
        uv.x += hit * (hash(vec2(band, uSeed + 7.0)) - 0.5) * 0.16 * uSlice;

        // Fire: tongues of rising noise, stretched tall, that only break through close to the
        // letters (\`near\` falls off with height). The noise scrolls up one period per loop.
        vec2 q = vec2(uv.x * 70.0, uv.y * 3.0 - uPhase * 6.0);
        float n = 0.6 * noise(q, 6.0) + 0.4 * noise(q * vec2(2.3, 2.0) + 13.0, 12.0);
        float near = texture2D(flames, uv + vec2((n - 0.5) * 0.015, -0.02)).r;
        float heat = clamp((n - (0.8 - 0.35 * near * uFire)) * 4.0, 0.0, 1.0);
        vec3 fire = heat < 0.5 ? mix(vec3(0.5, 0.01, 0.0), vec3(1.0, 0.22, 0.01), heat * 2.0)
                               : mix(vec3(1.0, 0.22, 0.01), vec3(1.3, 0.6, 0.08), heat * 2.0 - 1.0);
        fire *= heat;
        float f = heat;

        vec4 c = texture2D(map, uv);
        float red = texture2D(map, uv + vec2(uSplit, 0.0)).a;
        float blue = texture2D(map, uv - vec2(uSplit, 0.0)).a;
        float hot = exp(-pow((uv.x - uSweep) / 0.07, 2.0));
        vec3 letters = c.rgb * (1.0 + 0.3 * uHeat) + vec3(3.0, 1.4, 0.6) * hot;

        float behind = 1.0 - c.a;
        vec3 ghosts = (vec3(1.0, 0.014, 0.046) * red + vec3(0.0, 0.39, 1.0) * blue) * 0.85 * behind;
        float ghostA = max(red, blue) * 0.85 * behind;
        vec3 col = letters * c.a + ghosts + fire * behind * (1.0 - ghostA);
        float alpha = clamp(c.a + ghostA + f * 0.9 * behind, 0.0, 1.0);
        gl_FragColor = vec4(col, alpha);
      }`,
    transparent: true,
    premultipliedAlpha: true,
    depthTest: false,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), mat);
  // Anchor: the letters' left edge at TITLE.x, their vertical middle at TITLE.y.
  mesh.position.set(TITLE.x - pad.x + w / 2, -(TITLE.y - (base - ascent / 2) + h / 2), 0);
  return { mesh, uniforms: mat.uniforms, uvPerPx: 1 / w };
}

// The outline of an empty card slot.
function slotOutline() {
  const w = SLOT.w + 8;
  const h = SLOT.h + 8;
  const texture = canvasTexture(w, h, (ctx) => {
    ctx.beginPath();
    ctx.roundRect(4, 4, SLOT.w, SLOT.h, 4);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = GOLD;
    ctx.setLineDash([4, 3]);
    ctx.stroke();
  });
  return new THREE.Mesh(new THREE.PlaneGeometry(w, h), overlay(texture));
}

function bar(x0, x1, color) {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(x1 - x0, 3), new THREE.MeshBasicMaterial({ color, depthTest: false, depthWrite: false }));
  mesh.position.set((x0 + x1) / 2, -BARS.y, 0);
  return mesh;
}

// Faint CRT lines over the whole banner.
function scanlines() {
  const texture = canvasTexture(W, H, (ctx) => {
    ctx.fillStyle = 'rgba(0, 0, 0, 0.16)';
    for (let y = 0; y < H; y += 3) ctx.fillRect(0, y, W, 1);
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(W, H), overlay(texture));
  mesh.position.set(W / 2, -H / 2, 0);
  mesh.renderOrder = 10;
  return mesh;
}

const pct = (v) => `${(v * 100).toFixed(1)}%`;

function status(t) {
  if (t >= BEAT.eat && t < BEAT.boom) {
    let eaten = 0;
    for (let k = 0; k < 52; k++) if (eatenAt(k) <= t) eaten++;
    return [`pulsar eating ${eaten}/52`, CYAN];
  }
  if (t >= BEAT.boom && t < BEAT.solved) return [`dealing ${Math.min(4, Math.floor((t - BEAT.boom) / DEAL_GAP) + 1)}/4`, GOLD];
  if (t >= BEAT.solved && t < BEAT.reset + 0.15) return ['solved ✓ exact odds', RED];
  return ['4 calls · 52 cards', MUTED];
}

export function createHud() {
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(0, W, 0, -H, -10, 10);

  const head = title();
  const tagline = label('Ride the Bus, solved.', { font: '700 19px Cinzel', color: '#f4e9d8', spacing: '0.5px', size: 19 });
  const subline = label('every decision has a right answer', { font: '500 14px Inter', color: '#b8ab9c', size: 14 });
  const prompt = label('> uv run busride', { font: `600 14px ${MONO}`, color: '#7dd3fc', size: 14, glow: null });
  const cursor = label('_', { font: `600 14px ${MONO}`, color: '#7dd3fc', size: 14, glow: null });
  const repo = label('// busride', { font: `600 14px ${MONO}`, color: '#fbbf24', size: 14, align: 'right', glow: null });
  const line = label('4 calls · 52 cards', { font: `600 13px ${MONO}`, color: MUTED, size: 13, reserve: 'pulsar eating 52/52__' });
  const outlines = SLOTS.map(() => slotOutline());
  const odds = SLOTS.map(() => label(pct(0), { font: '700 12px Inter', color: GOLD, size: 12, align: 'center', reserve: '00.0%' }));

  scene.add(head.mesh, tagline.mesh, subline.mesh, prompt.mesh, cursor.mesh, repo.mesh, line.mesh);
  scene.add(...outlines, ...odds.map((l) => l.mesh));
  scene.add(bar(...BARS.left, '#e5383b'), bar(...BARS.right, '#fbbf24'), scanlines());

  tagline.place(TAGLINE.x, TAGLINE.y);
  subline.place(SUBLINE.x, SUBLINE.y);
  prompt.place(PROMPT.x, PROMPT.y);
  repo.place(REPO.x, REPO.y);
  outlines.forEach((o, j) => o.position.set(SLOTS[j].x, -SLOTS[j].y, 0));

  function update(t) {
    const heat = pulse(t, BEAT.solved, BEAT.solved + 0.1, BEAT.solved + 0.4, BEAT.solved + 0.9);
    const blaze = pulse(t, BEAT.boom, BEAT.boom + 0.08, BEAT.boom + 0.4, BEAT.boom + 1.2);
    const glitch = glitchAt(t);
    const u = head.uniforms;
    u.uSweep.value = -0.2 + 1.4 * seg(t, BEAT.solved, BEAT.solved + 0.55);
    u.uHeat.value = heat;
    u.uPhase.value = t / LOOP;
    u.uFire.value = 0.9 + 0.15 * wave(t, 6) + 0.6 * blaze + 0.3 * heat;
    u.uSplit.value = (1.5 + 7 * glitch) * head.uvPerPx;
    u.uSlice.value = glitch;
    u.uSeed.value = Math.floor(t * 20);

    cursor.place(PROMPT.x + prompt.width + 2, PROMPT.y, Math.floor(t * 2) % 2 === 0 ? 1 : 0);
    line.set(...status(t));
    line.place(STATUS.x, STATUS.y);

    const clear = 1 - smooth(seg(t, BEAT.reset, BEAT.reset + 0.25));
    SLOTS.forEach((s, j) => {
      const land = landTime(j);
      const filled = smooth(seg(t, land - 0.1, land + 0.1)) * clear;
      outlines[j].material.opacity = 0.4 + 0.6 * filled;
      odds[j].set(pct(ODDS[j] * easeOut(seg(t, land + 0.1, land + 0.45))));
      odds[j].place(s.x, ODDS_Y, smooth(seg(t, land + 0.05, land + 0.2)) * clear);
    });
  }

  // Map the 900×300 banner into the largest 3:1 box centred in the viewport.
  function resize(vw, vh) {
    const wide = vw / vh >= ASPECT;
    const sw = wide ? vh * ASPECT : vw;
    const sh = wide ? vh : vw / ASPECT;
    const s = sw / W;
    const sx = (vw - sw) / 2;
    const sy = (vh - sh) / 2;
    camera.left = -sx / s;
    camera.right = (vw - sx) / s;
    camera.top = sy / s;
    camera.bottom = -(vh - sy) / s;
    camera.updateProjectionMatrix();
  }

  return { scene, camera, update, resize };
}
