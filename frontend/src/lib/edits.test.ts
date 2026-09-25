import { describe, expect, it } from 'vitest';
import type { ReportRow } from '../api/types';
import { diffEdits, draftFromRows, draftTotal, parseCount, validateDraft } from './edits';

const row = (p: Partial<ReportRow>): ReportRow => ({
  shelf_index: 1,
  position: 'центр',
  brand: 'AI TEA',
  subtype: 'AI TEA малина',
  package_format: 'банка 0,45 л',
  front_facing_count: 2,
  needs_review: false,
  review_reason: null,
  group_keys: [],
  ...p,
});

describe('edits', () => {
  const rows = [row({}), row({ subtype: null, needs_review: true }), row({ front_facing_count: 3 })];

  it('an untouched draft produces no edits', () => {
    expect(diffEdits(rows, draftFromRows(rows))).toEqual([]);
  });

  it('sends only the changed rows with only the changed fields', () => {
    const d = draftFromRows(rows);
    d[1] = { ...d[1], subtype: 'AI TEA ревень' };
    d[2] = { ...d[2], count: '5', package_format: 'ПЭТ 1 л' };
    expect(diffEdits(rows, d)).toEqual([
      { row: 1, subtype: 'AI TEA ревень' },
      { row: 2, package_format: 'ПЭТ 1 л', front_facing_count: 5 },
    ]);
  });

  it('marks deleted rows with delete: true only', () => {
    const d = draftFromRows(rows);
    d[0] = { ...d[0], deleted: true, count: '9' };
    expect(diffEdits(rows, d)).toEqual([{ row: 0, delete: true }]);
  });

  it('allows resetting a subtype to null', () => {
    const d = draftFromRows(rows);
    d[0] = { ...d[0], subtype: null };
    expect(diffEdits(rows, d)).toEqual([{ row: 0, subtype: null }]);
  });

  it('validates counts and ignores deleted rows', () => {
    const d = draftFromRows(rows);
    d[0] = { ...d[0], count: '' };
    d[1] = { ...d[1], count: '0', deleted: true };
    d[2] = { ...d[2], count: '1.5' };
    expect(validateDraft(d)).toHaveLength(2);
    expect(validateDraft(d)[0]).toContain('Строка 1');
  });

  it('parseCount accepts positive integers only', () => {
    expect(parseCount(' 4 ')).toBe(4);
    expect(parseCount('0')).toBeNull();
    expect(parseCount('-1')).toBeNull();
    expect(parseCount('abc')).toBeNull();
  });

  it('draftTotal sums non-deleted valid counts', () => {
    const d = draftFromRows(rows);
    d[0] = { ...d[0], deleted: true };
    expect(draftTotal(d)).toBe(5);
  });
});
