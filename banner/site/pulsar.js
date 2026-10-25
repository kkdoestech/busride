import * as THREE from 'three';
import { eatenAt } from './cards.js';
import { CENTER, px2world, unitsPerPx } from './layout.js';
import { BEAT, easeIn, easeOut, mulberry32, seg, smooth } from './util.js';

// The pulsar that eats the deck, after tools/make_pulsar.py in the kkdoestech profile repo:
// three log-spiral arms (white-hot near the core, then blue, red, deep blue), two lighthouse
// beams sweeping round, a pulsing core, and streaks spiralling in. It implodes and explodes.

const Z = -0.8;
const R = 190; // half-size of the pulsar plane, banner px
const SCALE = 2; // the profile pulsar is drawn at 2× this size; its formulas use those pixels

const quad = (size, fragmentShader, uniforms) =>
  new THREE.Mesh(
    new THREE.PlaneGeometry(size, size),
    new THREE.ShaderMaterial({
      uniforms,
      vertexShader: /* glsl */ `
        varying vec2 vUv;
        void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
      fragmentShader,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }),
  );

const PULSAR = /* glsl */ `
  uniform float uLevel, uSpin, uBeam, uCore, uShrink;
  varying vec2 vUv;
  const vec3 WHITE = vec3(1.0);
  const vec3 BLUE = vec3(0.0, 0.39, 1.0);     // #00A8FF
  const vec3 RED = vec3(1.0, 0.014, 0.046);   // #FF1F3D
  const vec3 DEEP = vec3(0.0, 0.063, 1.0);    // #0047FF
  const vec3 NAVY = vec3(0.003, 0.007, 0.045);

  vec3 vortexRamp(float t) {
    if (t < 0.12) return mix(WHITE, BLUE, t / 0.12);
    if (t < 0.35) return mix(BLUE, RED, (t - 0.12) / 0.23);
    if (t < 0.7) return mix(RED, DEEP, (t - 0.35) / 0.35);
    return mix(DEEP, NAVY, (t - 0.7) / 0.3);
  }

  float wrapAngle(float a) { return atan(sin(a), cos(a)); }

  void main() {
    vec2 d = (vUv - 0.5) * 2.0 * ${R.toFixed(1)} * ${SCALE.toFixed(1)} * uShrink;
    float r = length(d) + 1e-3;
    float th = atan(d.y, d.x);

    float arms = pow(0.5 + 0.5 * cos(3.0 * (th + 1.6 * log(r)) + uSpin), 3.0);
    float fall = exp(-r / 150.0) * clamp((r - 10.0) / 25.0, 0.0, 1.0);
    vec3 col = vortexRamp(clamp(r / 330.0, 0.0, 1.0)) * clamp(arms * fall * 1.4, 0.0, 1.0);

    float width = 0.05 + 0.6 / (r / 12.0 + 1.0);
    float b1 = wrapAngle(th - uBeam);
    float b2 = wrapAngle(th - uBeam - 3.14159265);
    float beam = clamp((exp(-pow(b1 / width, 2.0)) + exp(-pow(b2 / width, 2.0))) * exp(-r / 260.0), 0.0, 1.0);
    col += mix(mix(WHITE, vec3(0.19, 0.64, 1.0), clamp(r / 100.0, 0.0, 1.0)), DEEP, clamp((r - 100.0) / 300.0, 0.0, 1.0)) * beam;

    float glow = exp(-pow(r / (18.0 + 10.0 * uCore), 2.0)) * (0.75 + uCore);
    float halo = exp(-r / (40.0 + 30.0 * uCore)) * 0.55 * (0.75 + uCore);
    col += mix(vec3(2.5), vec3(0.0, 0.2, 1.0), clamp(r / 90.0, 0.0, 1.0)) * clamp(glow + halo, 0.0, 1.5);

    float edge = 1.0 - smoothstep(0.75, 1.0, length(vUv - 0.5) * 2.0);
    gl_FragColor = vec4(col * uLevel * edge * 1.8, 1.0);
  }`;

const SHOCK = /* glsl */ `
  uniform float uRadius, uLevel;
  varying vec2 vUv;
  void main() {
    float r = length(vUv - 0.5) * 2.0;
    float w = 0.035;
    float red = exp(-pow((r - uRadius - 0.012) / w, 2.0));
    float white = exp(-pow((r - uRadius) / w, 2.0));
    float blue = exp(-pow((r - uRadius + 0.012) / w, 2.0));
    vec3 col = vec3(1.0, 0.03, 0.08) * red * 1.2 + vec3(1.4) * white + vec3(0.0, 0.4, 1.6) * blue;
    gl_FragColor = vec4(col * uLevel, 1.0);
  }`;

function glowTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.2, 'rgba(255,255,255,0.5)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

export function createPulsar() {
  const group = new THREE.Group();
  const upx = unitsPerPx(Z);
  const centre = px2world(CENTER.x, CENTER.y, Z);
  group.position.copy(centre);

  const pulsar = quad(2 * R * upx, PULSAR, {
    uLevel: { value: 0 },
    uSpin: { value: 0 },
    uBeam: { value: 0 },
    uCore: { value: 0 },
    uShrink: { value: 1 },
  });
  const shock = quad(2 * 320 * upx, SHOCK, { uRadius: { value: 0 }, uLevel: { value: 0 } });
  shock.position.z = 0.4;
  const flash = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: glowTexture(), color: new THREE.Color(4, 4.5, 6), blending: THREE.AdditiveBlending, depthWrite: false }),
  );
  flash.position.z = 0.6;
  group.add(pulsar, shock, flash);

  // Streaks flowing inward along the same spiral as the cards (y squashed, like a tilted disk).
  const N = 120;
  const rand = mulberry32(4242);
  const streaks = Array.from({ length: N }, () => ({
    p0: rand(),
    a0: rand() * Math.PI * 2,
    col: [[2, 2, 2], [0, 0.8, 2], [2, 2, 2], [2, 1.6, 0]][Math.floor(rand() * 4)],
  }));
  const pos = new Float32Array(N * 6);
  const colour = new Float32Array(N * 6);
  const lineGeo = new THREE.BufferGeometry();
  lineGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  lineGeo.setAttribute('color', new THREE.BufferAttribute(colour, 3));
  const lines = new THREE.LineSegments(
    lineGeo,
    new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }),
  );
  lines.position.z = 0.2;
  lines.frustumCulled = false;
  group.add(lines);

  const spiral = (p, a0, out) => {
    const r = 200 * (1 - p) ** 1.4 * upx;
    const a = a0 + Math.PI * 2 * p;
    out[0] = r * Math.cos(a);
    out[1] = 0.55 * r * Math.sin(a);
    out[2] = 0;
  };
  const a = [0, 0, 0];
  const b = [0, 0, 0];

  // How hard the core flares as each card falls in.
  function swallow(t) {
    let f = 0;
    for (let k = 0; k < 52; k++) f += Math.exp(-(((t - eatenAt(k)) / 0.05) ** 2));
    return Math.min(1, f);
  }

  function update(t) {
    const on = smooth(seg(t, BEAT.ignite, BEAT.ignite + 0.45));
    const implode = easeIn(seg(t, BEAT.implode, BEAT.boom));
    const gone = smooth(seg(t, BEAT.boom, BEAT.boom + 0.2));
    const level = on * (1 - gone) * (1 + 0.8 * implode);
    const u = pulsar.material.uniforms;
    u.uLevel.value = level;
    u.uSpin.value = 3 * (1.7 * t + 9 * implode);
    u.uBeam.value = 2 * Math.PI * 0.55 * t;
    u.uCore.value = 0.25 * Math.cos(2 * Math.PI * 4 * (t / 6)) + 0.6 * swallow(t) + 2 * implode;
    u.uShrink.value = 1 + 3 * implode;

    const k = seg(t, BEAT.boom, BEAT.boom + 0.6);
    shock.material.uniforms.uRadius.value = 0.95 * easeOut(k);
    shock.material.uniforms.uLevel.value = k > 0 && k < 1 ? (1 - k) ** 1.5 : 0;
    const f = Math.exp(-(((t - BEAT.boom) / 0.09) ** 2));
    flash.scale.setScalar((40 + 240 * f) * upx);
    flash.material.opacity = Math.min(1, 1.1 * f + 0.25 * implode * (1 - gone));
    flash.visible = flash.material.opacity > 0.01;

    const bright = on * (1 - gone);
    for (let i = 0; i < N; i++) {
      const s = streaks[i];
      const p = (s.p0 + t * 0.45) % 1;
      spiral(p, s.a0, a);
      spiral(Math.max(0, p - 0.035), s.a0, b);
      pos.set([b[0], b[1], 0, a[0], a[1], 0], i * 6);
      const c = p < 0.85 ? s.col : [2.5, 2.5, 2.5];
      const k2 = bright * Math.min(1, p / 0.1);
      colour.set([0, 0, 0, c[0] * k2, c[1] * k2, c[2] * k2], i * 6);
    }
    lineGeo.attributes.position.needsUpdate = true;
    lineGeo.attributes.color.needsUpdate = true;
  }

  return { group, update };
}
