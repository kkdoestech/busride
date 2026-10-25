import * as THREE from 'three';
import { landTime, slotAt, suitPath } from './cards.js';
import { CENTER, TITLE, px2world, unitsPerPx } from './layout.js';
import { BEAT, easeInOut, mulberry32, pulse, seg, wave } from './util.js';

const RED = new THREE.Color(3.4, 0.3, 0.2); // brighter than white, so the bloom catches it
const S = 1024;
const C = S / 2;

function canvas() {
  const c = document.createElement('canvas');
  c.width = c.height = S;
  const ctx = c.getContext('2d');
  ctx.strokeStyle = ctx.fillStyle = '#fff';
  return [c, ctx];
}

function ring(ctx, r, width) {
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.arc(C, C, r, 0, Math.PI * 2);
  ctx.stroke();
}

// The outer ring is inscribed with the four questions and their exact survival odds.
function outerRing() {
  const [cv, ctx] = canvas();
  ring(ctx, 496, 6);
  ring(ctx, 470, 2.5);
  ring(ctx, 408, 3.5);
  ctx.lineWidth = 3;
  for (let i = 0; i < 52; i++) {
    const a = (i / 52) * Math.PI * 2;
    const r0 = i % 13 === 0 ? 378 : 392;
    ctx.beginPath();
    ctx.moveTo(C + r0 * Math.sin(a), C - r0 * Math.cos(a));
    ctx.lineTo(C + 408 * Math.sin(a), C - 408 * Math.cos(a));
    ctx.stroke();
  }
  const text = 'RED OR BLACK · HIGHER OR LOWER · INSIDE OR OUTSIDE · WHICH SUIT · 0.50000 · 0.36199 · 0.23771 · 0.06307 · ';
  ctx.font = '700 30px Cinzel';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const widths = [...text].map((ch) => ctx.measureText(ch).width);
  const total = widths.reduce((a, b) => a + b, 0);
  let run = 0;
  [...text].forEach((ch, i) => {
    const a = ((run + widths[i] / 2) / total) * Math.PI * 2;
    run += widths[i];
    ctx.save();
    ctx.translate(C, C);
    ctx.rotate(a);
    ctx.fillText(ch, 0, -439);
    ctx.restore();
  });
  return cv;
}

// The inner ring: a 13-point star (one point per rank) and the four suits.
function innerRing() {
  const [cv, ctx] = canvas();
  ring(ctx, 360, 3);
  ring(ctx, 200, 2);
  ring(ctx, 70, 2);
  const pts = Array.from({ length: 13 }, (_, i) => {
    const a = (i / 13) * Math.PI * 2;
    return [C + 356 * Math.sin(a), C - 356 * Math.cos(a)];
  });
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i <= 13; i++) {
    const [x, y] = pts[(i * 5) % 13];
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
  for (const [x, y] of pts) {
    ctx.beginPath();
    ctx.arc(x, y, 8, 0, Math.PI * 2);
    ctx.fill();
  }
  ['s', 'h', 'd', 'c'].forEach((suit, i) => {
    const a = Math.PI / 4 + (i * Math.PI) / 2;
    const x = C + 280 * Math.sin(a);
    const y = C - 280 * Math.cos(a);
    ctx.save();
    ctx.globalCompositeOperation = 'destination-out';
    ctx.beginPath();
    ctx.arc(x, y, 48, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.arc(x, y, 46, 0, Math.PI * 2);
    ctx.stroke();
    suitPath(ctx, suit, x, y, 26);
    ctx.fill();
  });
  suitPath(ctx, 'd', C, C, 40);
  ctx.lineWidth = 3;
  ctx.stroke();
  return cv;
}

function sigilMaterial(cv) {
  return new THREE.ShaderMaterial({
    uniforms: {
      map: { value: new THREE.CanvasTexture(cv) },
      uDraw: { value: 0 },
      uGlow: { value: 0 },
      uDisk: { value: 0 },
      uColor: { value: RED },
    },
    vertexShader: /* glsl */ `
      varying vec2 vUv;
      void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: /* glsl */ `
      uniform sampler2D map;
      uniform float uDraw, uGlow, uDisk;
      uniform vec3 uColor;
      varying vec2 vUv;
      void main() {
        vec2 d = vUv - 0.5;
        float r = length(d) * 2.0;
        float a = fract(atan(d.x, d.y) / 6.2831853 + 1.0);   // 0 at the top, clockwise
        float edge = uDraw * 1.05;
        float shown = 1.0 - smoothstep(edge - 0.05, edge, a);
        float head = exp(-pow((a - edge + 0.03) / 0.025, 2.0)) * step(uDraw, 0.999);
        float line = texture2D(map, vUv).a;
        vec3 col = uColor * line * shown + vec3(4.0, 2.6, 1.6) * line * head;
        col += uColor * uDisk * exp(-r * r * 4.0) * 0.05;
        gl_FragColor = vec4(col * uGlow, 1.0);
      }`,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
  });
}

function glowTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.25, 'rgba(255,255,255,0.45)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

// Soft round points; colour is premultiplied by brightness, so 0 hides a point.
function pointsMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { uScale: { value: 400 } },
    vertexShader: /* glsl */ `
      attribute float size;
      attribute vec3 color;
      uniform float uScale;
      varying vec3 vColor;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mv;
        gl_PointSize = size * uScale / -mv.z;
        vColor = color;
      }`,
    fragmentShader: /* glsl */ `
      varying vec3 vColor;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float a = smoothstep(0.5, 0.0, d);
        gl_FragColor = vec4(vColor * a * a, 1.0);
      }`,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
}

function pointCloud(n) {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  geo.setAttribute('size', new THREE.BufferAttribute(new Float32Array(n), 1));
  const pts = new THREE.Points(geo, pointsMaterial());
  pts.frustumCulled = false;
  return pts;
}

const HOT = new THREE.Color(4, 2.2, 1.2);
const EMBER = new THREE.Color(3.2, 0.35, 0.2);
const GOLD = new THREE.Color(3.6, 2.4, 0.8);

// `feet`: where the avatar stands (the floor circle, light cone and dust gather there).
export function createMagic(magePos) {
  const group = new THREE.Group();

  // The circle behind the cards, and a smaller one on the floor under the magician.
  const centre = px2world(CENTER.x, CENTER.y - 6, -1.6);
  const radius = 112 * unitsPerPx(-1.6);
  const outer = new THREE.Mesh(new THREE.PlaneGeometry(radius * 2, radius * 2), sigilMaterial(outerRing()));
  const inner = new THREE.Mesh(new THREE.PlaneGeometry(radius * 2, radius * 2), sigilMaterial(innerRing()));
  outer.position.copy(centre);
  inner.position.copy(centre);
  inner.position.z += 0.01;
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(4, 4), sigilMaterial(outerRing()));
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(magePos.x, 0.02, magePos.z);
  const sigils = [outer, inner, floor];
  for (const m of sigils) {
    m.renderOrder = 2;
    group.add(m);
  }

  const redLight = new THREE.PointLight(0xff2a1a, 0, 16, 1.2);
  redLight.position.set(centre.x, centre.y + 0.5, centre.z + 5.5);
  group.add(redLight);

  // A glowing orb in the raised hand.
  const glow = glowTexture();
  const orb = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, color: new THREE.Color(6, 0.8, 0.5), blending: THREE.AdditiveBlending, depthWrite: false }));
  group.add(orb);

  // The light cone from the spotlight above the magician.
  const cone = new THREE.Mesh(
    new THREE.ConeGeometry(2.1, 8.6, 48, 1, true),
    new THREE.ShaderMaterial({
      uniforms: { uLevel: { value: 0 }, uColor: { value: new THREE.Color(1.0, 0.18, 0.12) } },
      vertexShader: /* glsl */ `
        varying float vH;
        varying vec3 vN;
        varying vec3 vView;
        void main() {
          vH = position.y / 8.6 + 0.5;
          vN = normalize(normalMatrix * normal);
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          vView = normalize(-mv.xyz);
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: /* glsl */ `
        uniform float uLevel;
        uniform vec3 uColor;
        varying float vH;
        varying vec3 vN;
        varying vec3 vView;
        void main() {
          float facing = abs(dot(normalize(vN), normalize(vView)));
          float a = uLevel * pow(facing, 2.5) * (0.2 + 0.8 * vH) * smoothstep(0.0, 0.2, vH);
          gl_FragColor = vec4(uColor * a, 1.0);
        }`,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
    }),
  );
  cone.position.set(magePos.x, 4.3, magePos.z);
  group.add(cone);

  // Sparks: 0..209 rise around the magician, 210..419 fly off the circle as it draws,
  // then four bursts where the dealt cards land, then embers off the title.
  const N_MAGE = 160;
  const N_RIM = 160;
  const N_BURST = 24;
  const N_TITLE = 90;
  const nSparks = N_MAGE + N_RIM + 4 * N_BURST + N_TITLE;
  const sparks = pointCloud(nSparks);
  group.add(sparks);
  const rand = mulberry32(11);
  const seeds = Array.from({ length: nSparks }, () => Array.from({ length: 8 }, rand));

  const N_DUST = 150;
  const dust = pointCloud(N_DUST);
  group.add(dust);
  const dustSeeds = Array.from({ length: N_DUST }, () => Array.from({ length: 8 }, rand));

  const titleLeft = px2world(TITLE.x + 10, TITLE.y, 0.6);
  const titleRight = px2world(TITLE.x + 340, TITLE.y, 0.6);
  const titleSpan = 44 * unitsPerPx(0.6);

  const tmp = new THREE.Vector3();
  const col = new THREE.Color();

  function setPoint(cloud, i, p, c, brightness, size) {
    const g = cloud.geometry.attributes;
    g.position.setXYZ(i, p.x, p.y, p.z);
    g.color.setXYZ(i, c.r * brightness, c.g * brightness, c.b * brightness);
    g.size.setX(i, brightness > 0 ? size : 0);
  }

  function updateSparks(t) {
    let i = 0;
    for (; i < N_MAGE; i++) {
      const [r1, r2, r3, r4, r5, r6, r7] = seeds[i];
      const life = 0.7 + 0.6 * r2;
      const age = t - (BEAT.ignite + 1.2 * r1);
      if (age < 0 || age > life) {
        setPoint(sparks, i, magePos, HOT, 0, 0);
        continue;
      }
      const k = age / life;
      const a = r3 * Math.PI * 2 + age * (2 + 1.5 * r4);
      const rad = 1.5 * (1 - 0.4 * k) * (0.8 + 0.3 * r5);
      tmp.set(magePos.x + rad * Math.cos(a), 0.05 + age * (1.6 + 1.4 * r6), magePos.z + 0.6 * rad * Math.sin(a));
      col.copy(HOT).lerp(EMBER, k);
      setPoint(sparks, i, tmp, col, Math.sin(Math.PI * k), 0.05 + 0.06 * r7);
    }
    for (; i < N_MAGE + N_RIM; i++) {
      const [r1, r2, r3, , , r6, r7] = seeds[i];
      const theta = r3 * Math.PI * 2;
      const life = 0.6 + 0.6 * r2;
      const age = t - (BEAT.ignite - 0.1 + 0.55 * r3 + 0.5 * r1);
      if (age < 0 || age > life) {
        setPoint(sparks, i, centre, HOT, 0, 0);
        continue;
      }
      const k = age / life;
      const rr = radius * 0.97 + 0.5 * age;
      const a = theta + 0.4 * age;
      tmp.set(centre.x + rr * Math.sin(a), centre.y + rr * Math.cos(a) + 0.6 * age, centre.z + 0.3 * age);
      col.copy(HOT).lerp(EMBER, k);
      setPoint(sparks, i, tmp, col, Math.sin(Math.PI * k) * 0.9, 0.04 + 0.05 * r6 + 0.02 * r7);
    }
    for (let j = 0; j < 4; j++) {
      const base = slotAt(j);
      for (let n = 0; n < N_BURST; n++, i++) {
        const [r1, r2, r3, r4, r5] = seeds[i];
        const life = 0.35 + 0.3 * r2;
        const age = t - (landTime(j) + 0.04 * r1);
        if (age < 0 || age > life) {
          setPoint(sparks, i, base, GOLD, 0, 0);
          continue;
        }
        const k = age / life;
        const a = r3 * Math.PI * 2;
        const speed = 0.6 + 0.9 * r4;
        tmp.set(base.x + Math.cos(a) * speed * age, base.y + (Math.sin(a) * 0.8 + 0.4) * speed * age - 2.2 * age * age, base.z + 0.3 * r5 * age);
        setPoint(sparks, i, tmp, GOLD, 1 - k, 0.035 + 0.04 * r5);
      }
    }
    for (; i < nSparks; i++) {
      const [r1, r2, r3, r4, r5] = seeds[i];
      const f = 0.05 + 0.9 * r1;
      const life = 0.4 + 0.4 * r2; // every ember is out before the loop restarts
      const age = t - (BEAT.boom + 0.45 * f);
      if (age < 0 || age > life) {
        setPoint(sparks, i, titleLeft, GOLD, 0, 0);
        continue;
      }
      const k = age / life;
      tmp.lerpVectors(titleLeft, titleRight, f);
      tmp.y += (r3 - 0.5) * titleSpan + age * (0.5 + 0.6 * r4);
      tmp.x += (r5 - 0.5) * 0.6 * age;
      col.copy(GOLD).lerp(EMBER, k);
      setPoint(sparks, i, tmp, col, (1 - k) * 0.8, 0.03 + 0.03 * r4);
    }
    for (const a of ['position', 'color', 'size']) sparks.geometry.attributes[a].needsUpdate = true;
  }

  function updateDust(t, light) {
    for (let i = 0; i < N_DUST; i++) {
      const [r1, r2, r3, r4, r5, r6, r7, r8] = dustSeeds[i];
      const a = r1 * Math.PI * 2;
      const r = Math.sqrt(r2) * 1.7;
      tmp.set(
        magePos.x + r * Math.cos(a) + 0.15 * wave(t, 1 + Math.floor(r6 * 2), r3 * 6),
        0.3 + 5.4 * r4 + 0.25 * wave(t, 1, r5 * 6),
        magePos.z + 0.8 * r * Math.sin(a) + 0.1 * wave(t, 2, r7 * 6),
      );
      col.setRGB(1.0, 0.55, 0.45);
      setPoint(dust, i, tmp, col, light * (0.35 + 0.25 * wave(t, 3 + Math.floor(r8 * 3), r1 * 6)), 0.025 + 0.02 * r3);
    }
    for (const a of ['position', 'color', 'size']) dust.geometry.attributes[a].needsUpdate = true;
  }

  // ctx: light (stage light level), hand (world position of the avatar's hands).
  function update(t, { light, hand }) {
    const m = BEAT.ignite - 0.15;
    const on = pulse(t, m, m + 0.15, BEAT.reset, BEAT.reset + 0.5);
    const flare = pulse(t, BEAT.boom, BEAT.boom + 0.08, BEAT.boom + 0.2, BEAT.boom + 0.9);
    const solved = pulse(t, BEAT.solved, BEAT.solved + 0.12, BEAT.solved + 0.25, BEAT.solved + 0.7);
    // Dim while the pulsar burns in front of it, so its arms read; it flares at the boom.
    const busy = pulse(t, BEAT.ignite, BEAT.ignite + 0.3, BEAT.boom - 0.1, BEAT.boom);
    const level = on * ((0.6 - 0.35 * busy) + 0.6 * flare + 0.5 * solved);
    outer.material.uniforms.uDraw.value = easeInOut(seg(t, m + 0.05, m + 0.6));
    inner.material.uniforms.uDraw.value = easeInOut(seg(t, m + 0.15, m + 0.7));
    floor.material.uniforms.uDraw.value = easeInOut(seg(t, m + 0.05, m + 0.5));
    for (const m of sigils) m.material.uniforms.uGlow.value = level;
    inner.material.uniforms.uDisk.value = 1;
    outer.rotation.z = -0.15 * (t - m);
    inner.rotation.z = 0.25 * (t - m);
    floor.rotation.z = 0.3 * (t - m);
    redLight.intensity = 4 * level;

    const orbOn = pulse(t, BEAT.ignite - 0.1, BEAT.ignite + 0.1, BEAT.implode, BEAT.boom);
    orb.position.copy(hand);
    orb.scale.setScalar((0.7 + 0.25 * Math.sin(t * 9)) * orbOn + 1e-3);
    orb.material.opacity = orbOn;

    cone.material.uniforms.uLevel.value = 0.1 * light;
    updateSparks(t);
    updateDust(t, light);
  }

  // Point sizes are in world units; this sets pixels per unit at distance 1.
  function resize(bufferHeight, fov) {
    const scale = bufferHeight / (2 * Math.tan(THREE.MathUtils.degToRad(fov) / 2));
    sparks.material.uniforms.uScale.value = scale;
    dust.material.uniforms.uScale.value = scale;
  }

  return { group, update, resize };
}
