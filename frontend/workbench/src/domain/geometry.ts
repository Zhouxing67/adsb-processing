export type LngLat = readonly [number, number];

/**
 * Returns the CSS clockwise rotation angle in degrees for a right-pointing arrow (`▶`),
 * accounting for Mercator longitude scaling at the segment's midpoint latitude.
 * 0° = East, -90° = North, 90° = South, ±180° = West.
 */
export function segmentScreenAngleDegrees(from: LngLat, to: LngLat): number {
  const meanLatRad = ((from[1] + to[1]) / 2) * (Math.PI / 180);
  const dx = (to[0] - from[0]) * Math.cos(meanLatRad);
  const dy = -(to[1] - from[1]);
  if (dx === 0 && dy === 0) return 0;
  const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
  return Object.is(angle, -0) ? 0 : angle;
}

const METERS_PER_DEG_LAT = 111_320;

function coordKey(point: LngLat): string {
  return `${point[0].toFixed(6)},${point[1].toFixed(6)}`;
}

/**
 * Returns an undirected canonical key for a polyline segment and whether the segment's
 * orientation is reversed relative to the canonical direction (start <= end lexicographically).
 */
export function canonicalSegmentKey(coordinates: ReadonlyArray<LngLat>): { key: string; reversed: boolean } {
  if (coordinates.length < 2) return { key: '', reversed: false };
  const a = coordKey(coordinates[0]);
  const b = coordKey(coordinates[coordinates.length - 1]);
  return a <= b ? { key: `${a}|${b}`, reversed: false } : { key: `${b}|${a}`, reversed: true };
}

/**
 * Offsets the interior of a polyline perpendicularly by `offsetMeters` while keeping
 * its start and end vertices strictly pinned to the original graph nodes.
 */
export function offsetSegmentWithPinnedEndpoints(
  coordinates: ReadonlyArray<LngLat>,
  offsetMeters: number,
  canonicalReversed = false,
): Array<[number, number]> {
  if (coordinates.length < 2 || Math.abs(offsetMeters) < 0.01) {
    return coordinates.map(([lng, lat]) => [lng, lat]);
  }
  const first = coordinates[0];
  const last = coordinates[coordinates.length - 1];
  const meanLatRad = ((first[1] + last[1]) / 2) * (Math.PI / 180);
  const metersPerDegLng = METERS_PER_DEG_LAT * Math.max(0.1, Math.cos(meanLatRad));
  const signedOffset = canonicalReversed ? -offsetMeters : offsetMeters;

  const shift = (point: LngLat, from: LngLat, to: LngLat): [number, number] => {
    const dx = (to[0] - from[0]) * metersPerDegLng;
    const dy = (to[1] - from[1]) * METERS_PER_DEG_LAT;
    const len = Math.hypot(dx, dy);
    if (len < 1e-6) return [point[0], point[1]];
    const nx = -dy / len;
    const ny = dx / len;
    return [
      point[0] + (nx * signedOffset) / metersPerDegLng,
      point[1] + (ny * signedOffset) / METERS_PER_DEG_LAT,
    ];
  };

  if (coordinates.length === 2) {
    const p1: LngLat = [first[0] + (last[0] - first[0]) * 0.18, first[1] + (last[1] - first[1]) * 0.18];
    const p2: LngLat = [first[0] + (last[0] - first[0]) * 0.82, first[1] + (last[1] - first[1]) * 0.82];
    return [
      [first[0], first[1]],
      shift(p1, first, last),
      shift(p2, first, last),
      [last[0], last[1]],
    ];
  }

  return coordinates.map((point, index) => {
    if (index === 0 || index === coordinates.length - 1) {
      return [point[0], point[1]];
    }
    return shift(point, coordinates[index - 1], coordinates[index + 1]);
  });
}
