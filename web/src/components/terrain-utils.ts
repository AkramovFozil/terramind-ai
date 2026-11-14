import * as THREE from 'three';
import type { World } from './scene-types';

const fract = (v: number) => v - Math.floor(v);
const hash = (x: number, y: number) => fract(Math.sin(x * 127.1 + y * 311.7) * 43758.5453123);
const mix = (a: number, b: number, t: number) => a + (b - a) * t;
export function smooth(a: number, b: number, v: number) {
  const t = THREE.MathUtils.clamp((v - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
}
export function noise(x: number, y: number) {
  const ix = Math.floor(x), iy = Math.floor(y);
  const fx = x - ix, fy = y - iy;
  const ux = fx * fx * (3 - 2 * fx), uy = fy * fy * (3 - 2 * fy);
  return mix(mix(hash(ix, iy), hash(ix + 1, iy), ux), mix(hash(ix, iy + 1), hash(ix + 1, iy + 1), ux), uy);
}
export function fbm(x: number, z: number, octaves = 5) {
  let sum = 0, amp = 0.5, weight = 0;
  for (let i = 0; i < octaves; i++) {
    sum += noise(x, z) * amp;
    weight += amp;
    const nx = x * 1.61 + z * 1.19 + 11.7;
    z = z * 1.61 - x * 1.19 + 8.3;
    x = nx;
    amp *= 0.49;
  }
  return sum / weight;
}

/** Deliberately illustrative landscape: never used by the scientific pipeline. */
export function terrainHeight(x: number, z: number, world: World) {
  const earth = world === 'earth';
  const warp = (fbm(x * 0.018 + 60, z * 0.018) - 0.5) * 12;
  const river = 11 + Math.sin(z * 0.023) * 18 + Math.sin(z * 0.061 + 0.8) * 4.5;
  const distance = Math.abs(x + warp - river);
  const width = 13 + fbm(x * 0.031, z * 0.024 + 18) * 7;
  const shelf1 = smooth(width, width + 7, distance) * 9.5;
  const shelf2 = smooth(width + 10, width + 14, distance) * 11.5;
  const shelf3 = smooth(width + 18, width + 25, distance) * 8;
  const erosion = fbm(x * 0.105, z * 0.105, 5);
  const gully = Math.pow(Math.abs(noise(x * 0.14 + 33, z * 0.08) - 0.5) * 2, 2);
  const rugged = smooth(width - 3, width + 9, distance);
  const cliffs = (shelf1 + shelf2 + shelf3) * (0.73 + fbm(x * 0.016, z * 0.016) * 0.45);
  const valley = -5 + fbm(x * 0.045, z * 0.045) * 2.4;
  const dunes = Math.sin(x * 0.34 + Math.sin(z * 0.045) * 2.5) * 0.32 * (1 - rugged);
  const strata = Math.sin((cliffs + valley) * 1.55) * 0.23 * rugged;
  const radius = Math.hypot(x * 0.9, z);
  const mountains = smooth(125, 285, radius) * (20 + Math.pow(fbm(x * 0.017 - 48, z * 0.017 + 17), 1.6) * 62);
  return valley + cliffs + (erosion - 0.5) * (earth ? 5 : 6.5) * rugged - gully * 2.4 * rugged + dunes + strata + mountains;
}

export function createTerrain(world: World, segments: number, size = 340, distant = false) {
  const geometry = new THREE.PlaneGeometry(size, size, segments, segments);
  geometry.rotateX(-Math.PI / 2);
  const position = geometry.attributes.position as THREE.BufferAttribute;
  const uv = geometry.attributes.uv as THREE.BufferAttribute;
  const colors = new Float32Array(position.count * 3);
  const earth = world === 'earth';
  const sand = new THREE.Color(earth ? '#c8b79b' : '#b8845b');
  const lightRock = new THREE.Color(earth ? '#e3d7bf' : '#d09b72');
  const darkRock = new THREE.Color(earth ? '#948570' : '#83513d');
  const color = new THREE.Color();
  // Reuse neighboring heights for slope colors instead of evaluating the full
  // procedural height function three times per vertex during scene switches.
  for (let i = 0; i < position.count; i++) {
    const x = position.getX(i), z = position.getZ(i);
    const height = terrainHeight(x, z, world);
    position.setY(i, height - (distant ? 1.6 : 0));
    uv.setXY(i, x * 0.105, z * 0.105);
  }
  const rowSize = segments + 1;
  const spacing = size / segments;
  for (let i = 0; i < position.count; i++) {
    const x = position.getX(i), z = position.getZ(i);
    const height = position.getY(i) + (distant ? 1.6 : 0);
    const strata = Math.sin(height * 1.12 + fbm(x * 0.024, z * 0.024) * 3.5);
    const band = smooth(-0.42, 0.14, strata);
    const nextX = i % rowSize < segments ? i + 1 : i - 1;
    const nextZ = i + rowSize < position.count ? i + rowSize : i - rowSize;
    const steepness = Math.hypot(position.getY(nextX) - position.getY(i), position.getY(nextZ) - position.getY(i)) / spacing;
    color.copy(sand).lerp(lightRock, smooth(0.15, 1.4, steepness) * 0.62);
    color.lerp(darkRock, (1 - band) * 0.33 * smooth(0.12, 0.8, steepness));
    color.multiplyScalar(0.83 + fbm(x * 0.16 + 80, z * 0.16) * 0.34);
    colors[i * 3] = color.r; colors[i * 3 + 1] = color.g; colors[i * 3 + 2] = color.b;
  }
  if (distant) {
    const original = geometry.index!;
    const indices: number[] = [];
    for (let i = 0; i < original.count; i += 3) {
      const a = original.getX(i), b = original.getX(i + 1), c = original.getX(i + 2);
      const cx = (position.getX(a) + position.getX(b) + position.getX(c)) / 3;
      const cz = (position.getZ(a) + position.getZ(b) + position.getZ(c)) / 3;
      if (Math.abs(cx) > 153 || Math.abs(cz) > 153) indices.push(a, b, c);
    }
    geometry.setIndex(indices);
  }
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return geometry;
}

export function seededRandom(seed: number) {
  let value = seed;
  return () => {
    value = (Math.imul(1664525, value) + 1013904223) | 0;
    return (value >>> 0) / 4294967296;
  };
}
