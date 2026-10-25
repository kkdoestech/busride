// Timing helpers. Every frame is a pure function of t in [0, LOOP): no clocks and no Math.random,
// so a recording is reproducible and the frame at t = LOOP is the frame at t = 0.

export const LOOP = 6;
export const FPS = 50 / 3; // 60 ms frames, like the other kkdoestech banners

export const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);
export const lerp = (a, b, k) => a + (b - a) * k;
// Progress through [a, b], clamped to 0..1.
export const seg = (t, a, b) => clamp01((t - a) / (b - a));
export const smooth = (k) => k * k * (3 - 2 * k);
export const easeOut = (k) => 1 - (1 - k) ** 3;
export const easeIn = (k) => k ** 3;
export const easeInOut = (k) => (k < 0.5 ? 4 * k ** 3 : 1 - (-2 * k + 2) ** 3 / 2);
// Rises over [a, b] and falls over [c, d].
export const pulse = (t, a, b, c, d) => smooth(seg(t, a, b)) * (1 - smooth(seg(t, c, d)));
// A wave with n whole cycles per loop, so it joins up at the loop point.
export const wave = (t, n, phase = 0) => Math.sin((2 * Math.PI * n * t) / LOOP + phase);

export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let x = a;
    x = Math.imul(x ^ (x >>> 15), x | 1);
    x ^= x + Math.imul(x ^ (x >>> 7), x | 61);
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

// The beats of the loop, in seconds (see banner/README.md for the storyboard).
export const BEAT = {
  toss: 0.5, // the deck leaves his hands
  pages: 0.85, // the first page turns
  ignite: 1.05, // the pulsar lights up
  eat: 1.3, // the first card is pulled in; the last is gone by `implode`
  implode: 3.4, // the pulsar collapses...
  boom: 3.6, // ...and explodes
  deal: 3.95, // the first of the four cards lands in its slot, then one every DEAL_GAP
  solved: 4.8, // all four are dealt
  reset: 5.35, // every card flies home
};
export const DEAL_GAP = 0.25;

// Short bursts of glitch, [start, end, strength]: the title, the avatar and the whole screen.
const BURSTS = [
  [1.9, 1.98, 0.45],
  [2.75, 2.8, 0.35],
  [3.58, 3.9, 0.9],
  [5.05, 5.12, 0.35],
];
export function glitchAt(t) {
  let g = 0;
  for (const [a, b, s] of BURSTS) if (t >= a && t < b) g = Math.max(g, s);
  return g;
}
