import type { DetectedBox, ReportRow } from '../api/types';
import { isForeign } from './domain';

/** Same as the backend's shelf_of(): a positive integer, anything else is shelf 0 («не определена»). */
export function normShelf(v: unknown): number {
  const n = typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN;
  return Number.isInteger(n) && n > 0 ? n : 0;
}

/** The backend treats "" and missing as null (`b.get("subtype") or None`). */
export function normOpt(v: string | null | undefined): string | null {
  return v == null || v === '' ? null : v;
}

export function boxKey(b: DetectedBox): string {
  return JSON.stringify([normShelf(b.shelf_index), b.label, normOpt(b.subtype), normOpt(b.format)]);
}

export function rowKey(r: Pick<ReportRow, 'shelf_index' | 'brand' | 'subtype' | 'package_format'>): string {
  return JSON.stringify([normShelf(r.shelf_index), r.brand, normOpt(r.subtype), normOpt(r.package_format)]);
}

/**
 * For every box, the index of its report row, or -1 (competitor / no matching row).
 * Match rule: shelf_index + label == brand + subtype + format, where null == null.
 */
export function matchBoxesToRows(boxes: readonly DetectedBox[], rows: readonly ReportRow[]): number[] {
  const index = new Map<string, number>();
  rows.forEach((r, i) => {
    const k = rowKey(r);
    if (!index.has(k)) index.set(k, i);
  });
  return boxes.map((b) => (isForeign(b.label) ? -1 : (index.get(boxKey(b)) ?? -1)));
}

export interface ShelfGroup {
  shelf: number;
  rows: { row: ReportRow; index: number }[];
  total: number;
}

/** Rows grouped by shelf (ascending, unknown shelf 0 last), keeping each row's index in report.rows. */
export function groupRowsByShelf(rows: readonly ReportRow[]): ShelfGroup[] {
  const groups = new Map<number, ShelfGroup>();
  rows.forEach((row, index) => {
    const shelf = normShelf(row.shelf_index);
    let g = groups.get(shelf);
    if (!g) {
      g = { shelf, rows: [], total: 0 };
      groups.set(shelf, g);
    }
    g.rows.push({ row, index });
    g.total += row.front_facing_count || 0;
  });
  return [...groups.values()].sort((a, b) => {
    if (a.shelf === 0) return 1;
    if (b.shelf === 0) return -1;
    return a.shelf - b.shelf;
  });
}
