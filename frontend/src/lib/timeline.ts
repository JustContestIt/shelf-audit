import type { ProgressEntry } from '../api/types';
import { FINAL_STATUSES } from './status';
import { secondsBetween } from './format';

/** Graph nodes in pipeline order with their Russian labels. */
export const PIPELINE_NODES: ReadonlyArray<readonly [string, string]> = [
  ['validate_input', 'Проверка фото'],
  ['input_guard', 'Это полка?'],
  ['detect', 'Детекция (проход 1)'],
  ['postprocess', 'Постобработка и счёт'],
  ['retrieve_refs', 'Поиск эталонов (RAG)'],
  ['verify_subtypes', 'Проверка подвидов (проход 2)'],
  ['build_report', 'Сборка отчёта'],
  ['human_review', 'Проверка супервайзером'],
  ['persist', 'Сохранение'],
];

const EXTRA_LABELS: Readonly<Record<string, string>> = { reject: 'Фото отклонено' };
const ORDER = PIPELINE_NODES.map(([n]) => n);

export function nodeLabel(node: string): string {
  return PIPELINE_NODES.find(([n]) => n === node)?.[1] ?? EXTRA_LABELS[node] ?? node;
}

export type TimelineState = 'done' | 'current' | 'waiting' | 'pending';

export interface TimelineItem {
  key: string;
  node: string;
  label: string;
  state: TimelineState;
  info?: string;
  at?: string;
  /** seconds since the previous finished step */
  durationS?: number | null;
}

export interface TimelineOptions {
  /** the graph is working (poll condition) */
  active: boolean;
  /** LangGraph `next` from /status */
  next?: readonly string[];
  status?: string | null;
  waitingReview?: boolean;
}

/** Node that follows `node` in the canonical order (human_review loops back to validate_input on retake). */
function successor(node: string | undefined, status?: string | null): string | undefined {
  if (!node) return ORDER[0];
  if (node === 'human_review' && status === 'retake') return 'validate_input';
  const i = ORDER.indexOf(node);
  return i >= 0 ? ORDER[i + 1] : undefined;
}

/**
 * Timeline = every progress entry in order (repeats included, e.g. validate_input after a retake),
 * then the current node (spinner) or the waiting human_review, then the remaining nodes as pending.
 */
export function buildTimeline(progress: readonly ProgressEntry[], opts: TimelineOptions): TimelineItem[] {
  const items: TimelineItem[] = progress.map((p, i) => ({
    key: `${i}:${p.node}`,
    node: p.node,
    label: nodeLabel(p.node),
    state: 'done',
    info: p.info,
    at: p.at,
    durationS: i > 0 ? secondsBetween(progress[i - 1].at, p.at) : null,
  }));
  const last = progress.length ? progress[progress.length - 1].node : undefined;
  const terminal = FINAL_STATUSES.has(opts.status ?? '') || last === 'reject' || last === 'persist';

  let current: string | undefined;
  let currentState: TimelineState = 'current';
  if (opts.active) {
    current = opts.next?.[0] ?? successor(last, opts.status);
  } else if (opts.waitingReview) {
    current = 'human_review';
    currentState = 'waiting';
  }
  if (current && !(terminal && !opts.active)) {
    items.push({ key: `current:${current}`, node: current, label: nodeLabel(current), state: currentState });
    const from = ORDER.indexOf(current);
    if (from >= 0) {
      for (const n of ORDER.slice(from + 1)) {
        items.push({ key: `pending:${n}`, node: n, label: nodeLabel(n), state: 'pending' });
      }
    }
  }
  return items;
}
