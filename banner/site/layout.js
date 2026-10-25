import * as THREE from 'three';

// The banner is designed at 900×300 px: the magic on the left, the words on the right. Positions
// are given in those pixels (y down) and turned into world positions through the design camera,
// so the text overlay and the 3D cards line up.
export const W = 900;
export const H = 300;
export const ASPECT = W / H;
export const FOV = 22.5;
export const CAMERA_POS = new THREE.Vector3(0, 2.3, 13);
export const CAMERA_TARGET = new THREE.Vector3(0, 2.05, 0);

const design = new THREE.PerspectiveCamera(FOV, ASPECT, 0.1, 100);
design.position.copy(CAMERA_POS);
design.lookAt(CAMERA_TARGET);
design.updateMatrixWorld();
const ray = new THREE.Vector3();

// The world point at depth z that the design camera shows at banner pixel (px, py).
export function px2world(px, py, z = 0, out = new THREE.Vector3()) {
  ray.set((px / W) * 2 - 1, 1 - (py / H) * 2, 0.5).unproject(design).sub(design.position).normalize();
  return out.copy(design.position).addScaledVector(ray, (z - design.position.z) / ray.z);
}

// World units per banner pixel at depth z, for sizing things in pixels.
export function unitsPerPx(z) {
  return px2world(W / 2 + 50, H / 2, z).distanceTo(px2world(W / 2 - 50, H / 2, z)) / 100;
}

// Left half: the avatar, and the pulsar in front of the magic circle.
export const AVATAR = { x: 78, feet: 283, height: 236 };
export const CENTER = { x: 290, y: 150 };

// Right half: the words, left-aligned on one column.
export const COLUMN = 440;
export const TITLE = { x: COLUMN, y: 90 };
export const TAGLINE = { x: COLUMN + 2, y: 139 };
export const SUBLINE = { x: COLUMN + 2, y: 166 };
export const SLOT = { w: 32, h: 45 };
export const SLOTS = [0, 1, 2, 3].map((j) => ({ x: COLUMN + 17 + j * 46, y: 224 }));
export const ODDS_Y = 262;
export const STATUS = { x: COLUMN + 202, y: 224 };

// Corners.
export const PROMPT = { x: 18, y: 22 };
export const REPO = { x: 882, y: 22 };
export const BARS = { y: 287, left: [14, 120], right: [780, 886] };
