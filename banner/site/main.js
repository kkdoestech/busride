import { createBanner } from './scene.js';
import { FPS, LOOP } from './util.js';

// Two modes. The live page loops in the window and reacts to you. `?record` is for
// banner/record.mjs: a fixed 900×300 frame at 2× pixels that renders only when asked
// (window.banner.render). `?t=4.9` holds one moment.

const params = new URLSearchParams(location.search);
const record = params.has('record');
const still = params.has('t') ? Number(params.get('t')) : null;
const stage = document.getElementById('stage');
if (record) document.body.classList.add('record');

const ready = createBanner(stage, { record });
window.banner = {
  duration: LOOP,
  fps: FPS,
  ready: ready.then(() => true),
  render: async (t) => (await ready).render(t),
};

const banner = await ready;

if (record) {
  banner.resize(900, 300, 2);
  banner.render(still ?? 0);
} else {
  const calm = matchMedia('(prefers-reduced-motion: reduce)');
  let t = still ?? (calm.matches ? 4.9 : 0);
  let paused = still !== null || calm.matches;
  let last = performance.now();
  const sway = { x: 0, y: 0 };
  const aim = { x: 0, y: 0 };

  const fit = () => banner.resize(innerWidth, innerHeight, Math.min(devicePixelRatio, 2));
  fit();
  addEventListener('resize', fit);
  addEventListener('pointermove', (e) => {
    aim.x = (e.clientX / innerWidth) * 2 - 1;
    aim.y = (e.clientY / innerHeight) * 2 - 1;
  });
  // Click: a new shuffle, dealt from the top.
  stage.addEventListener('click', () => {
    banner.shuffle(Math.floor(Math.random() * 2 ** 31));
    t = 0.4;
    if (!calm.matches) paused = false;
  });
  addEventListener('keydown', (e) => {
    if (e.code !== 'Space') return;
    e.preventDefault();
    paused = !paused;
  });

  const frame = (now) => {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    if (!paused) t = (t + dt) % LOOP;
    const k = Math.min(1, dt * 3);
    sway.x += (aim.x - sway.x) * k;
    sway.y += (aim.y - sway.y) * k;
    banner.render(t, calm.matches ? null : sway);
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}
