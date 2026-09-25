import type { ReportRow, ReviewEdit } from '../api/types';

/** Editable copy of a report row. `count` is a string so the input can be empty while typing. */
export interface DraftRow {
  subtype: string | null;
  package_format: string | null;
  count: string;
  deleted: boolean;
}

export function draftFromRows(rows: readonly ReportRow[]): DraftRow[] {
  return rows.map((r) => ({
    subtype: r.subtype ?? null,
    package_format: r.package_format ?? null,
    count: String(r.front_facing_count),
    deleted: false,
  }));
}

/** Positive integer from an input value, else null. */
export function parseCount(s: string): number | null {
  const t = s.trim();
  if (!/^\d+$/.test(t)) return null;
  const n = Number(t);
  return n >= 1 ? n : null;
}

/** Human-readable problems that block saving (1-based row numbers as in the table). */
export function validateDraft(draft: readonly DraftRow[]): string[] {
  const errors: string[] = [];
  draft.forEach((d, i) => {
    if (!d.deleted && parseCount(d.count) === null) {
      errors.push(`Строка ${i + 1}: количество должно быть целым числом не меньше 1`);
    }
  });
  return errors;
}

/** Only the rows that changed, with only the changed fields; deleted rows -> {row, delete: true}. */
export function diffEdits(rows: readonly ReportRow[], draft: readonly DraftRow[]): ReviewEdit[] {
  const edits: ReviewEdit[] = [];
  rows.forEach((r, i) => {
    const d = draft[i];
    if (!d) return;
    if (d.deleted) {
      edits.push({ row: i, delete: true });
      return;
    }
    const e: ReviewEdit = { row: i };
    let changed = false;
    if ((d.subtype ?? null) !== (r.subtype ?? null)) {
      e.subtype = d.subtype;
      changed = true;
    }
    if ((d.package_format ?? null) !== (r.package_format ?? null)) {
      e.package_format = d.package_format;
      changed = true;
    }
    const n = parseCount(d.count);
    if (n !== null && n !== r.front_facing_count) {
      e.front_facing_count = n;
      changed = true;
    }
    if (changed) edits.push(e);
  });
  return edits;
}

/** Units after the edits (invalid counts count as 0). */
export function draftTotal(draft: readonly DraftRow[]): number {
  return draft.reduce((s, d) => s + (d.deleted ? 0 : (parseCount(d.count) ?? 0)), 0);
}
