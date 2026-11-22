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
