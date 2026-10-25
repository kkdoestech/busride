import * as THREE from 'three';
import { CENTER, SLOT, SLOTS, px2world, unitsPerPx } from './layout.js';
import { BEAT, DEAL_GAP, easeInOut, easeOut, lerp, mulberry32, seg, smooth } from './util.js';

export const RANKS = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'];
export const SUITS = ['s', 'h', 'd', 'c'];
export const CARD_W = 1.5;
export const CARD_H = 2.1;

// A winning ride, dealt in the recording: red, then higher, then inside, then the right suit.
const SHOWCASE = ['7h', 'Qs', '9d', '3c'];

const RED_INK = '#d62828';
const BLACK_INK = '#16161c';
const CW = 240;
const CH = 336;
const PAD = 8;
const CELL_W = CW + 2 * PAD;
const CELL_H = CH + 2 * PAD;

// ---------------------------------------------------------------- drawing

// The outline of a suit, centred on (x, y), about 2s tall. The caller fills it.
export function suitPath(ctx, suit, x, y, s) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(s, s);
  ctx.beginPath();
  if (suit === 'd') {
    ctx.moveTo(0, -1);
    ctx.lineTo(0.72, 0);
    ctx.lineTo(0, 1);
    ctx.lineTo(-0.72, 0);
    ctx.closePath();
  } else if (suit === 'h') {
    ctx.moveTo(0, 0.95);
    ctx.bezierCurveTo(-0.35, 0.6, -1, 0.15, -1, -0.35);
    ctx.bezierCurveTo(-1, -0.8, -0.45, -1.05, 0, -0.6);
    ctx.bezierCurveTo(0.45, -1.05, 1, -0.8, 1, -0.35);
    ctx.bezierCurveTo(1, 0.15, 0.35, 0.6, 0, 0.95);
  } else if (suit === 's') {
    ctx.moveTo(0, -1);
    ctx.bezierCurveTo(-0.35, -0.55, -1, -0.2, -1, 0.22);
    ctx.bezierCurveTo(-1, 0.72, -0.4, 0.82, -0.1, 0.45);
    ctx.lineTo(-0.32, 1);
    ctx.lineTo(0.32, 1);
    ctx.lineTo(0.1, 0.45);
    ctx.bezierCurveTo(0.4, 0.82, 1, 0.72, 1, 0.22);
    ctx.bezierCurveTo(1, -0.2, 0.35, -0.55, 0, -1);
  } else {
    // clubs: every piece wound clockwise so the overlaps stay filled
    for (const [cx, cy, r] of [[0, -0.5, 0.4], [-0.48, 0.12, 0.4], [0.48, 0.12, 0.4], [0, 0.05, 0.25]]) {
      ctx.moveTo(cx + r, cy);
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
    }
    ctx.moveTo(0.1, 0.2);
    ctx.lineTo(0.32, 1);
    ctx.lineTo(-0.32, 1);
    ctx.lineTo(-0.1, 0.2);
    ctx.closePath();
  }
  ctx.restore();
}

const PIPS = {
  2: [[0.5, 0.2], [0.5, 0.8]],
  3: [[0.5, 0.2], [0.5, 0.5], [0.5, 0.8]],
  4: [[0.32, 0.2], [0.68, 0.2], [0.32, 0.8], [0.68, 0.8]],
  5: [[0.32, 0.2], [0.68, 0.2], [0.5, 0.5], [0.32, 0.8], [0.68, 0.8]],
  6: [[0.32, 0.2], [0.68, 0.2], [0.32, 0.5], [0.68, 0.5], [0.32, 0.8], [0.68, 0.8]],
};
PIPS[7] = [...PIPS[6], [0.5, 0.35]];
PIPS[8] = [...PIPS[6], [0.5, 0.35], [0.5, 0.65]];
PIPS[9] = [[0.32, 0.2], [0.68, 0.2], [0.32, 0.4], [0.68, 0.4], [0.5, 0.5], [0.32, 0.6], [0.68, 0.6], [0.32, 0.8], [0.68, 0.8]];
PIPS[10] = [[0.32, 0.2], [0.68, 0.2], [0.5, 0.3], [0.32, 0.4], [0.68, 0.4], [0.32, 0.6], [0.68, 0.6], [0.5, 0.7], [0.32, 0.8], [0.68, 0.8]];

function pip(ctx, suit, x, y, s) {
  ctx.save();
  ctx.translate(x, y);
  if (y > CH / 2 + 1) ctx.rotate(Math.PI);
  suitPath(ctx, suit, 0, 0, s);
  ctx.fill();
  ctx.restore();
}

function drawFace(ctx, rank, suit) {
  const ink = suit === 'h' || suit === 'd' ? RED_INK : BLACK_INK;
  ctx.beginPath();
  ctx.roundRect(0, 0, CW, CH, 18);
  ctx.fillStyle = '#f7f2e8';
  ctx.fill();
  ctx.lineWidth = 3;
  ctx.strokeStyle = '#cfc6b4';
  ctx.stroke();

  ctx.fillStyle = ink;
  for (const flip of [false, true]) {
    ctx.save();
    if (flip) {
      ctx.translate(CW, CH);
      ctx.rotate(Math.PI);
    }
    ctx.font = rank === '10' ? '700 34px Cinzel' : '700 44px Cinzel';
    ctx.textAlign = 'center';
    ctx.fillText(rank, 32, 54);
    suitPath(ctx, suit, 32, 80, 14);
    ctx.fill();
    ctx.restore();
  }

  if (rank === 'J' || rank === 'Q' || rank === 'K') {
    ctx.beginPath();
    ctx.roundRect(56, 48, CW - 112, CH - 96, 8);
    ctx.fillStyle = '#f3e6c9';
    ctx.fill();
    ctx.lineWidth = 4;
    ctx.strokeStyle = '#c9a24a';
    ctx.stroke();
    ctx.fillStyle = ink;
    ctx.font = '900 104px Cinzel';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(rank, CW / 2, CH / 2 + 4);
    ctx.textBaseline = 'alphabetic';
    pip(ctx, suit, CW / 2, 84, 16);
    pip(ctx, suit, CW / 2, CH - 84, 16);
  } else if (rank === 'A') {
    suitPath(ctx, suit, CW / 2, CH / 2, 56);
    ctx.fill();
  } else {
    for (const [x, y] of PIPS[Number(rank)]) pip(ctx, suit, x * CW, y * CH, 22);
  }
}

function drawBack(ctx) {
  ctx.beginPath();
  ctx.roundRect(0, 0, CW, CH, 18);
  ctx.fillStyle = '#f7f2e8';
  ctx.fill();
  ctx.beginPath();
  ctx.roundRect(12, 12, CW - 24, CH - 24, 12);
  ctx.fillStyle = '#8c1022';
  ctx.fill();
  ctx.save();
  ctx.clip();
  ctx.strokeStyle = 'rgba(232, 186, 90, 0.35)';
  ctx.lineWidth = 2;
  for (let d = -CH; d < CW + CH; d += 22) {
    ctx.beginPath();
    ctx.moveTo(d, 0);
    ctx.lineTo(d + CH, CH);
    ctx.moveTo(d, CH);
    ctx.lineTo(d + CH, 0);
    ctx.stroke();
  }
  ctx.restore();
  ctx.beginPath();
  ctx.roundRect(22, 22, CW - 44, CH - 44, 8);
  ctx.lineWidth = 3;
  ctx.strokeStyle = '#d9aa4a';
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(CW / 2, CH / 2, 46, 0, Math.PI * 2);
  ctx.fillStyle = '#5e0914';
  ctx.fill();
  ctx.lineWidth = 4;
  ctx.stroke();
  ctx.fillStyle = '#e8bd62';
  ctx.font = '700 40px Cinzel';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('br', CW / 2, CH / 2 + 2);
}

function textures(anisotropy) {
  const atlas = document.createElement('canvas');
  atlas.width = CELL_W * 13;
  atlas.height = CELL_H * 4;
  const ctx = atlas.getContext('2d');
  SUITS.forEach((suit, row) =>
    RANKS.forEach((rank, col) => {
      ctx.save();
      ctx.translate(col * CELL_W + PAD, row * CELL_H + PAD);
      drawFace(ctx, rank, suit);
      ctx.restore();
    }),
  );
  const back = document.createElement('canvas');
  back.width = CW;
  back.height = CH;
  drawBack(back.getContext('2d'));
  return [atlas, back].map((canvas) => {
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = anisotropy;
    return tex;
  });
}

// ---------------------------------------------------------------- poses

const Y = new THREE.Vector3(0, 1, 0);
const Z = new THREE.Vector3(0, 0, 1);
const makePose = () => ({ p: new THREE.Vector3(), q: new THREE.Quaternion(), s: 1, str: 0, bend: 0 });

// out = a → b at k, bowed along `arc` in the middle of the move. out may be a.
function blend(out, a, b, k, arc) {
  if (k <= 0) return out;
  out.p.lerpVectors(a.p, b.p, k);
  if (arc) out.p.addScaledVector(arc, Math.sin(Math.PI * k));
  out.q.slerpQuaternions(a.q, b.q, k);
  out.s = lerp(a.s, b.s, k);
  out.str = lerp(a.str, b.str, k);
  out.bend = lerp(a.bend, b.bend, k);
  return out;
}

const HAND_Q = new THREE.Quaternion().setFromEuler(new THREE.Euler(-0.05, 0.25, 0.08));
const HAND_OFFSET = new THREE.Vector3(0, 0.05, 0.15);
const HAND_N = new THREE.Vector3(0, 0, 1).applyQuaternion(HAND_Q);
// The closed deck stands where the pulsar will light up; its spine is its left edge.
const BOOK_S = 0.85;
const BOOK = px2world(CENTER.x, CENTER.y, 0).add(new THREE.Vector3((-CARD_W * BOOK_S) / 2, 0, 0));
const BOOK_Q = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.1, -0.3, 0));
// The cards fall in just in front of the pulsar.
const CORE_Z = -0.5;
const CORE = px2world(CENTER.x, CENTER.y, CORE_Z);
const RIM = 175 * unitsPerPx(CORE_Z);
const SLOT_Z = 0.4;
const SLOT_AT = SLOTS.map((s) => px2world(s.x, s.y, SLOT_Z));
const SLOT_S = (SLOT.h * unitsPerPx(SLOT_Z)) / CARD_H;
const ARC_TOSS = new THREE.Vector3(0, 0.8, 0.5);
const ARC_DEAL = new THREE.Vector3(0, 0.35, 0.8);
const ARC_HOME = new THREE.Vector3(0, 0.6, 0.7);

export const landTime = (j) => BEAT.deal + DEAL_GAP * j;
export const slotAt = (j) => SLOT_AT[j];
// Card k (fresh-deck order) is pulled off the book at releaseAt(k) and reaches the core at eatenAt(k).
export const releaseAt = (k) => BEAT.eat + (1.0 * k) / 51;
export const eatenAt = (k) => releaseAt(k) + 1.05;

// ---------------------------------------------------------------- the deck

export function createDeck({ anisotropy = 4 } = {}) {
  const [faceTex, backTex] = textures(anisotropy);
  const faceMat = new THREE.MeshStandardMaterial({
    map: faceTex,
    roughness: 0.55,
    alphaTest: 0.5,
    emissive: 0xffffff,
    emissiveMap: faceTex,
    emissiveIntensity: 0.1,
  });
  const backMat = new THREE.MeshStandardMaterial({
    map: backTex,
    roughness: 0.45,
    metalness: 0.1,
    alphaTest: 0.5,
    emissive: 0xffffff,
    emissiveMap: backTex,
    emissiveIntensity: 0.14,
  });

  const group = new THREE.Group();
  const cards = [];
  SUITS.forEach((suit, row) =>
    RANKS.forEach((rank, col) => {
      const backGeo = new THREE.PlaneGeometry(CARD_W, CARD_H, 10, 1);
      const faceGeo = backGeo.clone().rotateY(Math.PI).translate(0, 0, -0.004);
      const uv = faceGeo.attributes.uv;
      const u0 = (col * CELL_W + PAD) / (CELL_W * 13);
      const u1 = (col * CELL_W + PAD + CW) / (CELL_W * 13);
      const vTop = 1 - (row * CELL_H + PAD) / (CELL_H * 4);
      const vBottom = 1 - (row * CELL_H + PAD + CH) / (CELL_H * 4);
      for (let i = 0; i < uv.count; i++) uv.setXY(i, lerp(u0, u1, uv.getX(i)), lerp(vBottom, vTop, uv.getY(i)));
      const obj = new THREE.Group();
      const back = new THREE.Mesh(backGeo, backMat);
      const face = new THREE.Mesh(faceGeo, faceMat);
      for (const m of [back, face]) {
        m.frustumCulled = false;
        obj.add(m);
      }
      group.add(obj);
      cards.push({
        id: rank + suit,
        obj,
        parts: [back, face].map((m) => [m, Float32Array.from(m.geometry.attributes.position.array)]),
        bend: -1,
        k: cards.length, // position in a fresh deck (A of spades to K of clubs), 0 = top
        row: -1, // which of the four dealt cards, or -1
        fall: null, // its path into the pulsar
        pose: makePose(),
      });
    }),
  );

  // Curls the card away from its spine edge; `bend` is roughly the curl in card widths.
  function bendCard(card, bend) {
    if (Math.abs(bend - card.bend) < 1e-3) return;
    card.bend = bend;
    for (const [mesh, base] of card.parts) {
      const pos = mesh.geometry.attributes.position;
      for (let i = 0; i < pos.count; i++) {
        const u = (base[i * 3] + CARD_W / 2) / CARD_W;
        pos.setZ(i, base[i * 3 + 2] + bend * CARD_W * 0.35 * u * u);
      }
      pos.needsUpdate = true;
      mesh.geometry.computeVertexNormals();
    }
  }

  // New paths into the pulsar and four cards to deal. The recording deals the showcase ride.
  function shuffle(seed, showcase = false) {
    const rand = mulberry32(seed);
    const order = [...cards];
    for (let i = order.length - 1; i > 0; i--) {
      const j = Math.floor(rand() * (i + 1));
      [order[i], order[j]] = [order[j], order[i]];
    }
    const dealt = showcase ? SHOWCASE.map((id) => cards.find((c) => c.id === id)) : order.slice(0, 4);
    for (const c of cards) {
      c.row = dealt.indexOf(c);
      c.fall = { a0: rand() * Math.PI * 2, turns: 1.2 + 0.8 * rand(), spin: 4 + 6 * rand() };
    }
  }

  const local = new THREE.Vector3();
  const tmpQ = new THREE.Quaternion();
  const target = makePose();

  function handPose(card, hand, out) {
    out.p.copy(hand).add(HAND_OFFSET).addScaledVector(HAND_N, -card.k * 0.0026);
    out.q.copy(HAND_Q);
    out.s = 0.3;
    out.str = 0;
    out.bend = 0;
    return out;
  }

  const pageStart = (card) => BEAT.pages + (0.5 * card.k) / 51;

  // The deck opens like a book: each card turns over about the spine, like a page.
  function bookPose(card, t, out) {
    const p = easeInOut(seg(t, pageStart(card), pageStart(card) + 0.28));
    const theta = Math.PI * p;
    local.set((CARD_W * BOOK_S) / 2, 0, -card.k * 0.004).applyAxisAngle(Y, theta);
    out.p.copy(local).applyQuaternion(BOOK_Q).add(BOOK);
    out.q.setFromAxisAngle(Y, theta).premultiply(BOOK_Q);
    out.s = BOOK_S;
    out.str = 0;
    out.bend = 0.55 * Math.sin(Math.PI * p);
    return out;
  }

  // Flung out to the rim, then down the spiral into the core: shrinking, stretching, flipping.
  function fallPose(card, t, out) {
    const f = card.fall;
    const p = seg(t, releaseAt(card.k), eatenAt(card.k));
    const r = RIM * (1 - p) ** 1.4;
    const a = f.a0 + Math.PI * 2 * f.turns * p;
    out.p.set(CORE.x + r * Math.cos(a), CORE.y + 0.55 * r * Math.sin(a), CORE.z + 0.3 * (1 - p));
    out.q.setFromAxisAngle(Z, a + Math.PI / 2 + 2.1 * p).multiply(tmpQ.setFromAxisAngle(Y, f.spin * p));
    out.s = 0.55 * (1 - p) ** 0.8;
    out.str = p;
    out.bend = 0.1;
    return out;
  }

  // Lands face down in its slot on the right, then flips face up.
  function slotPose(j, t, out) {
    const f = easeInOut(seg(t, landTime(j) + 0.02, landTime(j) + 0.25));
    out.p.copy(SLOT_AT[j]);
    out.p.z += 0.25 * Math.sin(Math.PI * f);
    out.q.setFromAxisAngle(Y, Math.PI * f);
    out.s = SLOT_S;
    out.str = 0;
    out.bend = 0.12 * Math.sin(Math.PI * f);
    return out;
  }

  // Every card's place at time t. `hand` is the world position of the avatar's hands.
  function update(t, hand) {
    for (const c of cards) {
      const p = handPose(c, hand, c.pose);
      const toss = BEAT.toss + c.k * 0.001;
      blend(p, p, bookPose(c, t, target), easeInOut(seg(t, toss, toss + 0.33)), ARC_TOSS);
      const release = releaseAt(c.k);
      blend(p, p, fallPose(c, t, target), smooth(seg(t, release, release + 0.25)), null);
      if (c.row >= 0) {
        const land = landTime(c.row);
        blend(p, p, slotPose(c.row, t, target), easeOut(seg(t, land - 0.35, land)), ARC_DEAL);
      }
      const home = BEAT.reset + (0.15 * c.k) / 51;
      blend(p, p, handPose(c, hand, target), easeInOut(seg(t, home, home + 0.45)), ARC_HOME);
      c.obj.position.copy(p.p);
      c.obj.quaternion.copy(p.q);
      c.obj.scale.set(p.s * (1 - 0.6 * p.str), p.s * (1 + 0.9 * p.str), p.s);
      c.obj.visible = p.s > 0.004;
      bendCard(c, p.bend);
    }
  }

  shuffle(7, true);
  return { group, update, shuffle };
}
