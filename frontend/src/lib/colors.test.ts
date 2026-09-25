import { describe, expect, it } from 'vitest';
import type { DetectedBox } from '../api/types';
import {
  FALLBACK_PALETTE,
  KNOWN_SUBTYPE_COLORS,
  NEUTRAL_COLOR,
  colorForSubtype,
  hashString,
  legendFor,
} from './colors';

const box = (subtype: string | null, label = 'AI TEA'): DetectedBox => ({
  box_2d: [0, 0, 10, 10],
  label,
  subtype,
  format: 'банка 0,45 л',
  shelf_index: 1,
  confidence: 0.9,
});

describe('colorForSubtype', () => {
  it('gives every known canon name its own colour', () => {
    const colors = Object.values(KNOWN_SUBTYPE_COLORS).map((c) => c.toLowerCase());
    expect(new Set(colors).size).toBe(colors.length);
    expect(colors.length).toBe(22);
  });

  it('uses the fixed colour for a known name', () => {
    expect(colorForSubtype('AI TEA малина')).toBe(KNOWN_SUBTYPE_COLORS['AI TEA малина']);
    expect(colorForSubtype('  AI TEA малина ')).toBe(KNOWN_SUBTYPE_COLORS['AI TEA малина']);
  });

  it('keeps the pink-zone subtypes apart', () => {
    expect(colorForSubtype('AI TEA ревень')).not.toBe(colorForSubtype('AI TEA персик-жасмин'));
  });

  it('returns the neutral colour for a missing subtype', () => {
    expect(colorForSubtype(null)).toBe(NEUTRAL_COLOR);
    expect(colorForSubtype(undefined)).toBe(NEUTRAL_COLOR);
    expect(colorForSubtype('')).toBe(NEUTRAL_COLOR);
  });

  it('is stable for unknown names and picks from the fallback palette', () => {
    const a = colorForSubtype('Новый вкус X');
    expect(a).toBe(colorForSubtype('Новый вкус X'));
    expect(FALLBACK_PALETTE).toContain(a as (typeof FALLBACK_PALETTE)[number]);
  });

  it('hashString is deterministic FNV-1a', () => {
    expect(hashString('')).toBe(0x811c9dc5);
    expect(hashString('a')).toBe(0xe40c292c);
  });
});

describe('legendFor', () => {
  it('counts our boxes per subtype, skips competitors, puts "no subtype" last', () => {
    const legend = legendFor([
      box('AI TEA малина'),
      box('AI TEA малина'),
      box('AI TEA ревень'),
      box(null, 'Tamga'),
      box(null, 'ЧУЖОЙ'),
    ]);
    expect(legend.map((l) => [l.subtype, l.count])).toEqual([
      ['AI TEA малина', 2],
      ['AI TEA ревень', 1],
      [null, 1],
    ]);
    expect(legend[2].color).toBe(NEUTRAL_COLOR);
  });
});
