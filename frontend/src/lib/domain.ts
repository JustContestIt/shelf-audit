import type { ReportRow } from '../api/types';

/** Our brands (the model's label enum, without the competitor label). */
export const BRANDS = ['Буратино', 'AI TEA', 'Chino', 'Компотай', 'Tamga'] as const;

/** Label the detector gives to competitor products: shown for diagnostics, never counted. */
export const FOREIGN_LABEL = 'ЧУЖОЙ';

/** Brands that have no subtypes: a null subtype there is normal, not «не опознано». */
export const SUBTYPELESS_BRANDS = new Set<string>(['Tamga']);

/** Package formats known to the backend taxonomy (used by the edit form). */
export const PACKAGE_FORMATS = [
  'банка 0,45 л',
  'банка 0,9 л',
  'ПЭТ 0,25 л',
  'ПЭТ 0,5 л',
  'ПЭТ 1 л',
  'ПЭТ 1,5 л',
  'ПЭТ 2 л',
  'ПЭТ 2,4 л',
] as const;

/** Backend `max_upload_mb` (nginx allows 25m, the API itself answers 413 above this). */
export const MAX_UPLOAD_MB = 20;

export function isForeign(label: string | null | undefined): boolean {
  return (label ?? '').trim().toUpperCase() === FOREIGN_LABEL;
}

/** Row whose subtype the pipeline could not recognise (shown as «не опознано»). */
export function isUnknownSubtype(row: Pick<ReportRow, 'brand' | 'subtype'>): boolean {
  return (row.subtype == null || row.subtype === '') && !SUBTYPELESS_BRANDS.has(row.brand);
}
