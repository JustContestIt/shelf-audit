import type { Box2D } from '../api/types';

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/**
 * box_2d [ymin, xmin, ymax, xmax] in 0..1000 -> pixel rect on an image displayed at width × height.
 * Coordinates are clamped to the image and swapped if min/max come inverted.
 */
export function scaleBox(box: Box2D | readonly number[], width: number, height: number): Rect {
  const [a, b, c, d] = box.map((v) => clamp(Number(v) || 0, 0, 1000));
  const ymin = Math.min(a, c);
  const ymax = Math.max(a, c);
  const xmin = Math.min(b, d);
  const xmax = Math.max(b, d);
  return {
    x: (xmin / 1000) * width,
    y: (ymin / 1000) * height,
    width: ((xmax - xmin) / 1000) * width,
    height: ((ymax - ymin) / 1000) * height,
  };
}
