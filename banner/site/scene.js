import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { createAvatar } from './avatar.js';
import { createDeck } from './cards.js';
import { GlitchShader } from './glitch.js';
import { createHud } from './hud.js';
import { ASPECT, CAMERA_POS, CAMERA_TARGET, FOV, H, W, px2world } from './layout.js';
import { createMagic } from './magic.js';
import { createPulsar } from './pulsar.js';
import { BEAT, glitchAt, mulberry32, pulse } from './util.js';

const FONTS = ['900 58px Cinzel', '700 19px Cinzel', '500 14px Inter', '700 12px Inter', '600 14px "JetBrains Mono"'];

// Waits for the web fonts the canvases draw with; gives up after 8 s (offline: fallback fonts).
async function loadFonts() {
  const link = document.getElementById('fonts');
  const sheet = new Promise((resolve) => (link?.sheet ? resolve() : link?.addEventListener('load', resolve) ?? resolve()));
  const fonts = sheet.then(() => Promise.all(FONTS.map((f) => document.fonts.load(f))));
  await Promise.race([fonts, new Promise((resolve) => setTimeout(resolve, 8000))]);
}

function backdropTexture() {
  const c = document.createElement('canvas');
  c.width = 1024;
  c.height = 512;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(512, 256, 0, 512, 256, 512);
  g.addColorStop(0, '#24123c');
  g.addColorStop(0.3, '#140b24');
  g.addColorStop(1, '#07070c');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 1024, 512);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function fadeTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(128, 128, 0, 128, 128, 128);
  g.addColorStop(0, '#fff');
  g.addColorStop(0.45, '#fff');
  g.addColorStop(1, '#000');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 256, 256);
  return new THREE.CanvasTexture(c);
}

export async function createBanner(container, { record = false } = {}) {
  await loadFonts();

  const renderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: record, powerPreference: 'high-performance' });
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x07070c);
  scene.fog = new THREE.FogExp2(0x07070c, 0.03);
  scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.22;

  const camera = new THREE.PerspectiveCamera(FOV, ASPECT, 0.1, 100);

  const backdrop = new THREE.Mesh(new THREE.PlaneGeometry(120, 50), new THREE.MeshBasicMaterial({ map: backdropTexture(), fog: false }));
  backdrop.position.copy(px2world(W / 2, H * 0.4, -30));
  scene.add(backdrop);

  // A round stage floor that fades into the dark, so there is no hard horizon.
  const floor = new THREE.Mesh(
    new THREE.CircleGeometry(24, 64),
    new THREE.MeshStandardMaterial({ color: 0x0d0a10, roughness: 0.5, metalness: 0.2, alphaMap: fadeTexture(), transparent: true }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(1, 0, -5);
  floor.receiveShadow = true;
  floor.renderOrder = -1;
  scene.add(floor);

  const avatar = await createAvatar();
  const magePos = avatar.feet.clone();
  magePos.y = 0;
  const cardsAt = px2world(W / 2, H * 0.6, 0);

  scene.add(new THREE.HemisphereLight(0x3a2a55, 0x080608, 0.6));
  // The red spotlight on the avatar.
  const spot = new THREE.SpotLight(0xff3b2e, 0, 0, 0.36, 0.55, 0);
  spot.position.set(magePos.x + 0.6, 9, magePos.z + 3.5);
  spot.target.position.set(magePos.x, 1.6, magePos.z);
  spot.castShadow = true;
  spot.shadow.mapSize.set(1024, 1024);
  spot.shadow.bias = -0.0005;
  // A warm light on the cards, so their faces read.
  const warm = new THREE.SpotLight(0xffe2c4, 0, 0, 0.5, 0.85, 0);
  warm.position.set(cardsAt.x + 1.2, 7, 10);
  warm.target.position.copy(cardsAt);
  const fill = new THREE.DirectionalLight(0xffc8b8, 0.6);
  fill.position.set(-6, 3, 10);
  scene.add(spot, spot.target, warm, warm.target, fill);

  const deck = createDeck({ anisotropy: renderer.capabilities.getMaxAnisotropy() });
  const magic = createMagic(magePos);
  const hud = createHud();
  const pulsar = createPulsar();
  scene.add(avatar.group, avatar.shadow, pulsar.group, deck.group, magic.group);

  const target = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 });
  const composer = new EffectComposer(renderer, target);
  composer.addPass(new RenderPass(scene, camera));
  const words = new RenderPass(hud.scene, hud.camera);
  words.clear = false;
  words.clearDepth = true;
  composer.addPass(words);
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.55, 0.4, 1.15);
  composer.addPass(bloom);
  const glitch = new ShaderPass(GlitchShader);
  composer.addPass(glitch);
  composer.addPass(new OutputPass());

  const hands = new THREE.Vector3();

  // One frame of the loop. `sway` (-1..1 each way) nudges the camera on the live page.
  function render(t, sway = null) {
    const light = 1;
    const boom = pulse(t, BEAT.boom, BEAT.boom + 0.05, BEAT.boom + 0.15, BEAT.boom + 0.7);
    const solved = pulse(t, BEAT.solved, BEAT.solved + 0.12, BEAT.solved + 0.25, BEAT.solved + 0.7);
    const burst = glitchAt(t);
    spot.intensity = 12 * light;
    warm.intensity = 2.2;
    avatar.update(t, burst);
    avatar.hands(hands);
    deck.update(t, hands);
    pulsar.update(t);
    magic.update(t, { light, hand: hands });
    hud.update(t);
    bloom.strength = 0.55 + 0.35 * boom + 0.2 * solved;
    glitch.uniforms.uAmount.value = 0.55 * burst;
    glitch.uniforms.uSeed.value = Math.floor(t * 20);

    camera.position.copy(CAMERA_POS);
    if (sway) {
      camera.position.x += 0.5 * sway.x;
      camera.position.y -= 0.25 * sway.y;
    }
    // The boom shakes the camera for a moment.
    const shake = 0.12 * pulse(t, BEAT.boom, BEAT.boom + 0.03, BEAT.boom + 0.1, BEAT.boom + 0.45);
    if (shake > 0) {
      const rand = mulberry32(Math.floor(t * 20) + 99);
      camera.position.x += shake * (rand() - 0.5);
      camera.position.y += shake * (rand() - 0.5);
    }
    camera.lookAt(CAMERA_TARGET);
    composer.render();
  }

  function resize(w, h, dpr) {
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h);
    composer.setPixelRatio(dpr);
    composer.setSize(w, h);
    const a = w / h;
    camera.aspect = a;
    // Keep the whole 3:1 design frame in view at any shape.
    camera.fov = a >= ASPECT ? FOV : THREE.MathUtils.radToDeg(2 * Math.atan((Math.tan(THREE.MathUtils.degToRad(FOV) / 2) * ASPECT) / a));
    camera.updateProjectionMatrix();
    hud.resize(w, h);
    magic.resize(h * dpr, camera.fov);
  }

  return { render, resize, shuffle: (seed) => deck.shuffle(seed) };
}
