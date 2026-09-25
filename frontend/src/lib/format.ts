/** Number / date / metric formatting for a Russian UI (decimal comma, non-breaking spaces). */

export const DASH = '—';
export const NBSP = ' ';

function isNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

function groupThousands(intPart: string): string {
  return intPart.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
}

/** 1234.5 -> "1 234,5" (NBSP). `trim` removes trailing zeros of the fraction. */
export function fmtNum(v: number | null | undefined, digits = 1, trim = false): string {
  if (!isNum(v)) return DASH;
  let s = Math.abs(v).toFixed(digits);
  if (trim && s.includes('.')) s = s.replace(/\.?0+$/, '');
  const [i, f] = s.split('.');
  const neg = v < 0 && Number(s) !== 0;
  return (neg ? '−' : '') + groupThousands(i) + (f ? ',' + f : '');
}

export function fmtInt(v: number | null | undefined): string {
  return isNum(v) ? fmtNum(Math.round(v), 0) : DASH;
}

/** Fraction 0..1 -> "90 %". */
export function fmtPercent(v: number | null | undefined, digits = 0): string {
  return isNum(v) ? `${fmtNum(v * 100, digits)}${NBSP}%` : DASH;
}

/** USD with precision that suits LLM costs: $12,50 · $0,100 · $0,0032. */
export function fmtMoney(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  const a = Math.abs(v);
  const digits = a === 0 || a >= 1 ? 2 : a >= 0.01 ? 3 : 4;
  return `$${fmtNum(v, digits)}`;
}

/** Seconds: "2,5 с", "12 с", "1 мин 5 с". */
export function fmtSeconds(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  if (Math.abs(v) < 10) return `${fmtNum(v, 1)}${NBSP}с`;
  if (Math.abs(v) < 60) return `${fmtNum(v, 0)}${NBSP}с`;
  const total = Math.round(v);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return s ? `${m}${NBSP}мин ${s}${NBSP}с` : `${m}${NBSP}мин`;
}

function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Local date + time, e.g. "25.09.2026, 16:33". */
export function fmtDateTime(iso: string | null | undefined): string {
  const d = parseDate(iso);
  if (!d) return DASH;
  return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/** Local time with seconds, e.g. "16:33:50". */
export function fmtTime(iso: string | null | undefined): string {
  const d = parseDate(iso);
  if (!d) return DASH;
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/** Seconds between two ISO timestamps, or null. */
export function secondsBetween(a: string | null | undefined, b: string | null | undefined): number | null {
  const da = parseDate(a);
  const db = parseDate(b);
  if (!da || !db) return null;
  return (db.getTime() - da.getTime()) / 1000;
}

/** Natural order for "shelf.group" keys: 1.2 < 1.10 < 2.1. */
export function compareGroupKeys(a: string, b: string): number {
  const pa = a.split('.');
  const pb = b.split('.');
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i];
    const y = pb[i];
    if (x === undefined) return -1;
    if (y === undefined) return 1;
    const nx = Number(x);
    const ny = Number(y);
    const c = Number.isFinite(nx) && Number.isFinite(ny) ? nx - ny : x.localeCompare(y);
    if (c !== 0) return c;
  }
  return 0;
}

// ------------------------------------------------------------------ eval metrics

/** Known summary keys in display order, with Russian labels. */
export const METRIC_LABELS: Readonly<Record<string, string>> = {
  count_exact_shelf_rate: 'Доля полок с точным счётом',
  count_mae: 'MAE счёта на полку',
  subtype_acc: 'Точность подвида',
  subtype_acc_pink: 'Точность подвида (розовая зона)',
  contamination: 'Чужие в счёте',
  pack_acc: 'Точность тары',
  stability_sigma_subtype_err: 'σ ошибок подвида',
  cost_usd_per_photo: '$ на фото',
  latency_p50_s: 'p50, с',
  latency_p95_s: 'p95, с',
  guardrail_precision: 'Guardrail precision',
  guardrail_recall: 'Guardrail recall',
  n_frames: 'Кадров',
  n_shelves: 'Полок',
  n_units: 'Единиц',
};

const METRIC_ORDER = Object.keys(METRIC_LABELS);

export function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key;
}

/** *_rate, *_acc (also *_acc_<slice>), *precision*, *recall* are fractions shown as percentages. */
export function isPercentMetric(key: string): boolean {
  return /(^|_)(rate|acc)(_|$)/.test(key) || /(precision|recall)/.test(key);
}

/** Known keys first (in the canonical order), then unknown ones alphabetically. */
export function orderMetricKeys(keys: Iterable<string>): string[] {
  const set = new Set(keys);
  const known = METRIC_ORDER.filter((k) => set.has(k));
  const unknown = [...set].filter((k) => !(k in METRIC_LABELS)).sort();
  return [...known, ...unknown];
}

export function formatMetric(key: string, v: unknown): string {
  if (v === null || v === undefined) return DASH;
  if (typeof v === 'boolean') return v ? 'да' : 'нет';
  if (typeof v !== 'number') return String(v);
  if (!Number.isFinite(v)) return DASH;
  if (isPercentMetric(key)) {
    // fractions are expected; a value > 1 is taken as already being a percentage
    return Math.abs(v) <= 1 ? fmtPercent(v, 1) : `${fmtNum(v, 1)}${NBSP}%`;
  }
  if (key.startsWith('n_')) return fmtInt(v);
  if (key.includes('cost') || key.includes('usd')) return fmtMoney(v);
  if (key.includes('latency') || key.endsWith('_s')) return `${fmtNum(v, 2, true)}${NBSP}с`;
  if (Number.isInteger(v)) return fmtInt(v);
  return fmtNum(v, 3, true);
}
