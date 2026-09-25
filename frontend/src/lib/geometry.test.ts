import { describe, expect, it } from 'vitest';
import { scaleBox } from './geometry';

describe('scaleBox', () => {
  it('maps [ymin,xmin,ymax,xmax] 0..1000 to pixels', () => {
    expect(scaleBox([81, 308, 174, 353], 1000, 500)).toEqual({ x: 308, y: 40.5, width: 45, height: 46.5 });
  });
  it('scales with the displayed size', () => {
    const r = scaleBox([0, 0, 500, 250], 800, 600);
    expect(r).toEqual({ x: 0, y: 0, width: 200, height: 300 });
  });
  it('clamps out-of-range values and fixes inverted boxes', () => {
    expect(scaleBox([1200, 900, -5, 700], 100, 100)).toEqual({ x: 70, y: 0, width: 20, height: 100 });
  });
});
