import type { PhotoStatus, ReportStatus } from '../api/types';

export const STATUS_LABELS: Readonly<Record<ReportStatus, string>> = {
  new: 'В очереди',
  detecting: 'В работе',
  verifying: 'В работе',
  awaiting_review: 'На проверке',
  approved: 'Утверждено',
  edited: 'Исправлено',
  rejected: 'Отклонено',
  failed: 'Ошибка',
  retake: 'Пересъёмка',
};

/** Options for the status filter (every backend status, distinguishable labels). */
export const STATUS_FILTER_OPTIONS: ReadonlyArray<[ReportStatus, string]> = [
  ['awaiting_review', 'На проверке'],
  ['approved', 'Утверждено'],
  ['edited', 'Исправлено'],
  ['rejected', 'Отклонено'],
  ['failed', 'Ошибка'],
  ['new', 'В очереди'],
  ['detecting', 'В работе — детекция'],
  ['verifying', 'В работе — проход 2'],
  ['retake', 'Пересъёмка'],
];

export type Tone = 'info' | 'warn' | 'ok' | 'danger' | 'neutral';

export function statusLabel(status: string | null | undefined): string {
  if (!status) return '—';
  return STATUS_LABELS[status as ReportStatus] ?? status;
}

export function statusTone(status: string | null | undefined): Tone {
  switch (status) {
    case 'awaiting_review':
      return 'warn';
    case 'approved':
    case 'edited':
      return 'ok';
    case 'rejected':
    case 'failed':
      return 'danger';
    case 'new':
    case 'detecting':
    case 'verifying':
    case 'retake':
      return 'info';
    default:
      return 'neutral';
  }
}

/** Statuses during which the graph is still working. */
export const ACTIVE_STATUSES: ReadonlySet<string> = new Set(['new', 'detecting', 'verifying', 'retake']);

/** Keep polling /photos/{id}/status while this is true. */
export function isActive(st: Pick<PhotoStatus, 'running' | 'status'> | null | undefined): boolean {
  if (!st) return false;
  return Boolean(st.running) || ACTIVE_STATUSES.has(st.status);
}

export const FINAL_STATUSES: ReadonlySet<string> = new Set(['approved', 'edited', 'rejected', 'failed']);
