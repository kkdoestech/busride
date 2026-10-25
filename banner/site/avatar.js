import * as THREE from 'three';
import { AVATAR, CAMERA_POS, px2world, unitsPerPx } from './layout.js';
import { BEAT, mulberry32, pulse, seg, wave } from './util.js';

// The avatar from the kkdoestech profile (assets/avatars/2.png): a panda-faced official in a red
// hanfu. A flat cut-out with a dark sticker border and red/blue glitch ghosts, like the
// profile's own banners. He holds the deck at his hands.

const IMG = { w: 217, h: 452, hands: [108, 305] }; // image pixels
const BORDER = 4; // sticker border, image pixels
const PAD = BORDER * 2;
const UP = 2; // texture pixels per image pixel
const GLOW_PAD = 30; // room round the aura for its blur, image pixels
const Z = 0.3;

async function textures() {
  const img = new Image();
  img.src = './avatar.png';
  await img.decode();
  const w = (IMG.w + 2 * PAD) * UP;
  const h = (IMG.h + 2 * PAD) * UP;
  const make = () => {
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    return [c, c.getContext('2d')];
  };
  const [sil, s] = make();
  s.drawImage(img, PAD * UP, PAD * UP, IMG.w * UP, IMG.h * UP);
  s.globalCompositeOperation = 'source-in';
  s.fillStyle = '#0a0a10';
  s.fillRect(0, 0, w, h);

  const [sticker, ctx] = make();
  for (let i = 0; i < 16; i++) {
    const a = (i / 16) * Math.PI * 2;
    ctx.drawImage(sil, Math.cos(a) * BORDER * UP, Math.sin(a) * BORDER * UP);
  }
  ctx.drawImage(img, PAD * UP, PAD * UP, IMG.w * UP, IMG.h * UP);

  const aura = document.createElement('canvas');
  aura.width = w + 2 * GLOW_PAD * UP;
  aura.height = h + 2 * GLOW_PAD * UP;
  const g = aura.getContext('2d');
  g.filter = `blur(${10 * UP}px)`;
  g.drawImage(sticker, GLOW_PAD * UP, GLOW_PAD * UP);
  g.filter = 'none';
  g.globalCompositeOperation = 'source-in';
  g.fillStyle = '#fff';
  g.fillRect(0, 0, aura.width, aura.height);

  return [sticker, aura].map((c) => {
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  });
}

// A flat-coloured copy of the silhouette (glitch ghost or glow).
function tintMaterial(map, color, additive = false) {
  return new THREE.ShaderMaterial({
    uniforms: { map: { value: map }, uColor: { value: new THREE.Color(...color) }, uAlpha: { value: 0 } },
    vertexShader: /* glsl */ `
      varying vec2 vUv;
      void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: /* glsl */ `
      uniform sampler2D map;
      uniform vec3 uColor;
      uniform float uAlpha;
      varying vec2 vUv;
      void main() { gl_FragColor = vec4(uColor, texture2D(map, vUv).a * uAlpha); }`,
    transparent: true,
    depthWrite: false,
    blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending,
  });
}

export async function createAvatar() {
  const [sticker, auraTex] = await textures();
  const upx = unitsPerPx(Z);
  const scale = AVATAR.height / IMG.h; // banner px per image px
  const planeW = (IMG.w + 2 * PAD) * scale * upx;
  const planeH = (IMG.h + 2 * PAD) * scale * upx;
  const geo = new THREE.PlaneGeometry(planeW, planeH);

  const group = new THREE.Group();
  const centre = px2world(AVATAR.x, AVATAR.feet - AVATAR.height / 2, Z);
  group.position.copy(centre);
  group.lookAt(CAMERA_POS);

  const body = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ map: sticker, transparent: true, alphaTest: 0.02 }));
  const glowGeo = new THREE.PlaneGeometry(
    (IMG.w + 2 * PAD + 2 * GLOW_PAD) * scale * upx,
    (IMG.h + 2 * PAD + 2 * GLOW_PAD) * scale * upx,
  );
  const aura = new THREE.Mesh(glowGeo, tintMaterial(auraTex, [1.6, 0.1, 0.08], true));
  const ghostRed = new THREE.Mesh(geo, tintMaterial(sticker, [1, 0.014, 0.046]));
  const ghostBlue = new THREE.Mesh(geo, tintMaterial(sticker, [0, 0.39, 1]));
  aura.position.z = -0.03;
  ghostRed.position.z = -0.02;
  ghostBlue.position.z = -0.01;
  group.add(aura, ghostRed, ghostBlue, body);

  // A soft dark spot on the floor under his feet.
  const spot = document.createElement('canvas');
  spot.width = spot.height = 128;
  const sg = spot.getContext('2d');
  const grad = sg.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, 'rgba(0,0,0,0.7)');
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  sg.fillStyle = grad;
  sg.fillRect(0, 0, 128, 128);
  const feet = px2world(AVATAR.x, AVATAR.feet, Z);
  const shadow = new THREE.Mesh(
    new THREE.PlaneGeometry(planeW * 1.3, planeW * 0.7),
    new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(spot), transparent: true, depthWrite: false }),
  );
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.set(feet.x, 0.01, feet.z);

  const handsLocal = new THREE.Vector3(
    (IMG.hands[0] / IMG.w - 0.5) * IMG.w * scale * upx,
    (0.5 - IMG.hands[1] / IMG.h) * IMG.h * scale * upx,
    0.25,
  );
  const lift = new THREE.Vector3();

  // `glitch` (0..1) pulls the red and blue ghosts apart.
  function update(t, glitch = 0) {
    const px = upx;
    const float = 8 * pulse(t, BEAT.ignite - 0.15, BEAT.ignite + 0.3, BEAT.boom, BEAT.boom + 0.35);
    const hop = 12 * Math.sin(Math.PI * seg(t, BEAT.solved, BEAT.solved + 0.3));
    const recoil = -7 * pulse(t, BEAT.boom, BEAT.boom + 0.05, BEAT.boom + 0.1, BEAT.boom + 0.45);
    lift.set(recoil * px, (float + hop + 2.5 * wave(t, 3)) * px, 0);
    group.position.copy(centre).add(lift);
    body.rotation.z = 0.025 * wave(t, 2);
    aura.rotation.z = body.rotation.z;

    const auraOn = pulse(t, BEAT.ignite - 0.2, BEAT.ignite + 0.2, BEAT.boom + 0.1, BEAT.boom + 0.6);
    aura.material.uniforms.uAlpha.value = 0.1 + 0.7 * auraOn;

    const rand = mulberry32(Math.floor(t * 20) + 1);
    const split = (1.5 + 9 * glitch) * px;
    ghostRed.position.x = split;
    ghostBlue.position.x = -split;
    ghostRed.position.y = (rand() - 0.5) * 4 * glitch * px;
    ghostBlue.position.y = (rand() - 0.5) * 4 * glitch * px;
    ghostRed.material.uniforms.uAlpha.value = 0.75;
    ghostBlue.material.uniforms.uAlpha.value = 0.75;
    group.updateMatrixWorld(true);
  }

  // World position of his hands, where the deck sits.
  function hands(out = new THREE.Vector3()) {
    return out.copy(handsLocal).applyMatrix4(group.matrixWorld);
  }

  return { group, shadow, feet, update, hands };
}
