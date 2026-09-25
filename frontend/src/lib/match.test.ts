import { describe, expect, it } from 'vitest';
import type { DetectedBox, ReportRow } from '../api/types';
import { groupRowsByShelf, matchBoxesToRows, normOpt, normShelf } from './match';

const row = (p: Partial<ReportRow>): ReportRow => ({
  shelf_index: 1,
  position: 'центр',
  brand: 'AI TEA',
  subtype: 'AI TEA малина',
  package_format: 'банка 0,45 л',
  front_facing_count: 1,
  needs_review: false,
  review_reason: null,
  group_keys: [],
  ...p,
});

const box = (p: Partial<DetectedBox>): DetectedBox => ({
  box_2d: [0, 0, 100, 100],
  label: 'AI TEA',
  subtype: 'AI TEA малина',
  format: 'банка 0,45 л',
  shelf_index: 1,
  confidence: 0.9,
  ...p,
});

describe('normalisers', () => {
  it('normShelf follows the backend shelf_of()', () => {
    expect(normShelf(3)).toBe(3);
    expect(normShelf('2')).toBe(2);
    expect(normShelf(0)).toBe(0);
    expect(normShelf(-1)).toBe(0);
    expect(normShelf(null)).toBe(0);
    expect(normShelf(1.5)).toBe(0);
  });
  it('normOpt maps "" and undefined to null', () => {
    expect(normOpt('')).toBeNull();
    expect(normOpt(undefined)).toBeNull();
    expect(normOpt('x')).toBe('x');
  });
});

describe('matchBoxesToRows', () => {
  const rows = [
    row({}),
    row({ subtype: 'AI TEA ревень' }),
    row({ shelf_index: 2 }),
    row({ brand: 'Tamga', subtype: null, package_format: null }),
    row({ brand: 'AI TEA', subtype: null, package_format: 'ПЭТ 1 л', needs_review: true }),
  ];

  it('matches by shelf + brand + subtype + format', () => {
    expect(
      matchBoxesToRows(
        [box({}), box({ subtype: 'AI TEA ревень' }), box({ shelf_index: 2 }), box({ shelf_index: 3 })],
        rows,
      ),
    ).toEqual([0, 1, 2, -1]);
  });

  it('treats null, undefined and "" as equal (null == null)', () => {
    expect(
      matchBoxesToRows(
        [
          box({ label: 'Tamga', subtype: null, format: null }),
          box({ label: 'Tamga', subtype: '', format: undefined }),
          box({ subtype: undefined, format: 'ПЭТ 1 л' }),
        ],
        rows,
      ),
    ).toEqual([3, 3, 4]);
  });

  it('never matches competitor boxes', () => {
    const foreignRows = [row({ brand: 'ЧУЖОЙ', subtype: null, package_format: null })];
    expect(matchBoxesToRows([box({ label: 'ЧУЖОЙ', subtype: null, format: null })], foreignRows)).toEqual([-1]);
  });

  it('does not match when the format differs', () => {
    expect(matchBoxesToRows([box({ format: 'ПЭТ 0,5 л' })], rows)).toEqual([-1]);
  });
});

describe('groupRowsByShelf', () => {
  it('groups by shelf, keeps the original index and sums counts; shelf 0 goes last', () => {
    const groups = groupRowsByShelf([
      row({ shelf_index: 2, front_facing_count: 3 }),
      row({ shelf_index: 0, front_facing_count: 1 }),
      row({ shelf_index: 1, front_facing_count: 2 }),
      row({ shelf_index: 2, front_facing_count: 4 }),
    ]);
    expect(groups.map((g) => [g.shelf, g.total, g.rows.map((r) => r.index)])).toEqual([
      [1, 2, [2]],
      [2, 7, [0, 3]],
      [0, 1, [1]],
    ]);
  });
});
