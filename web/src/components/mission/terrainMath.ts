import type { TerrainData } from '../../science-types';

export type GroundSample = {
  x: number; z: number; elevation: number; y: number;
  normal: [number, number, number]; slopeDeg: number;
  row: number; col: number;
};
export type MissionPoint = GroundSample & { feet: [number, number, number][] };

export function validTerrain(data: TerrainData): boolean {
  return data.measured_dem === true && Number.isInteger(data.width) && Number.isInteger(data.height)
    && data.width > 1 && data.height > 1 && data.pixel_size_m > 0 && Number.isFinite(data.pixel_size_m)
    && Number.isFinite(data.median_elevation_m)
    && data.elevations.length === data.width * data.height && data.roi_mask.length === data.elevations.length;
}

/** Exact barycentric interpolation of the same two triangles used by the rendered DEM. */
export function sampleTerrain(data: TerrainData, x: number, z: number): GroundSample | null {
  if (!validTerrain(data) || !Number.isFinite(x) || !Number.isFinite(z)) return null;
  const step = data.pixel_size_m;
  const gx = x / step + (data.width - 1) / 2;
  const gz = z / step + (data.height - 1) / 2;
  if (gx < 0 || gz < 0 || gx > data.width - 1 || gz > data.height - 1) return null;
  const col = Math.min(Math.floor(gx), data.width - 2), row = Math.min(Math.floor(gz), data.height - 2);
  const u = gx - col, v = gz - row;
  const a = row * data.width + col, b = a + 1, c = a + data.width, d = c + 1;
  const indices = u + v <= 1 ? [a, b, c] : [b, c, d];
  if (indices.some(i => !data.roi_mask[i] || data.elevations[i] === null || !Number.isFinite(data.elevations[i]))) return null;
  let elevation: number, dx: number, dz: number;
  if (u + v <= 1) {
    const av = data.elevations[a]!, bv = data.elevations[b]!, cv = data.elevations[c]!;
    elevation = av + (bv - av) * u + (cv - av) * v;
    dx = (bv - av) / step; dz = (cv - av) / step;
  } else {
    const bv = data.elevations[b]!, cv = data.elevations[c]!, dv = data.elevations[d]!;
    elevation = bv * (1 - v) + cv * (1 - u) + dv * (u + v - 1);
    dx = (dv - cv) / step; dz = (dv - bv) / step;
  }
  const length = Math.hypot(dx, 1, dz);
  return { x, z, elevation, y: elevation - data.median_elevation_m, normal: [-dx / length, 1 / length, -dz / length], slopeDeg: Math.atan(Math.hypot(dx, dz)) * 180 / Math.PI, row, col };
}

/** All feet must sit on measured, rendered triangles; missing data is never bridged. */
export function missionPoint(data: TerrainData, x: number, z: number, radius = 3.2): MissionPoint | null {
  const center = sampleTerrain(data, x, z);
  if (!center) return null;
  const offsets: [number, number][] = [[-radius,-radius],[-radius,radius],[radius,-radius],[radius,radius]];
  const samples = offsets.map(([dx,dz]) => sampleTerrain(data,x+dx,z+dz));
  if (samples.some(sample => !sample)) return null;
  return { ...center, feet: samples.map((sample,i) => [offsets[i][0],sample!.y-center.y,offsets[i][1]]) };
}

export function initialMissionPoint(data: TerrainData, radius = 3.2): MissionPoint | null {
  const origin = missionPoint(data,0,0,radius);
  if (origin) return origin;
  if (!validTerrain(data)) return null;
  let nearest: MissionPoint | null = null, distance = Infinity;
  for (let row=0;row<data.height-1;row++) for (let col=0;col<data.width-1;col++) {
    const x=(col+.5-(data.width-1)/2)*data.pixel_size_m,z=(row+.5-(data.height-1)/2)*data.pixel_size_m;
    const d=x*x+z*z;
    if(d>=distance)continue;
    const point=missionPoint(data,x,z,radius);
    if(point){nearest=point;distance=d;}
  }
  return nearest;
}
