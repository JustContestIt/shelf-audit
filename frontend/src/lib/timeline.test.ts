import { describe, expect, it } from 'vitest';
import type { ProgressEntry } from '../api/types';
import { PIPELINE_NODES, buildTimeline, nodeLabel } from './timeline';

const p = (node: string, sec: number, info = ''): ProgressEntry => ({
  node,
  at: `2026-09-25T11:33:${String(sec).padStart(2, '0')}+00:00`,
  info,
});

const view = (items: ReturnType<typeof buildTimeline>) => items.map((i) => `${i.node}:${i.state}`);

describe('buildTimeline', () => {
  it('shows the first node as current before any progress', () => {
    const items = buildTimeline([], { active: true, status: 'new' });
    expect(items[0]).toMatchObject({ node: 'validate_input', state: 'current' });
    expect(items.slice(1).every((i) => i.state === 'pending')).toBe(true);
    expect(items).toHaveLength(PIPELINE_NODES.length);
  });

  it('uses `next` for the current node and computes step durations', () => {
    const items = buildTimeline([p('validate_input', 0, '1600×1200'), p('input_guard', 2), p('detect', 9)], {
      active: true,
      next: ['postprocess'],
      status: 'detecting',
    });
    expect(view(items)).toEqual([
      'validate_input:done',
      'input_guard:done',
      'detect:done',
      'postprocess:current',
      'retrieve_refs:pending',
      'verify_subtypes:pending',
      'build_report:pending',
      'human_review:pending',
      'persist:pending',
    ]);
    expect(items[0].info).toBe('1600×1200');
    expect(items[0].durationS).toBeNull();
    expect(items[2].durationS).toBe(7);
  });

  it('falls back to the successor of the last step when `next` is empty', () => {
    const items = buildTimeline([p('validate_input', 0)], { active: true, next: [], status: 'detecting' });
    expect(items[1]).toMatchObject({ node: 'input_guard', state: 'current' });
  });

  it('marks human_review as waiting when the graph is interrupted', () => {
    const progress = ['validate_input', 'input_guard', 'detect', 'postprocess', 'build_report'].map((n, i) => p(n, i));
    const items = buildTimeline(progress, { active: false, waitingReview: true, next: ['human_review'], status: 'awaiting_review' });
    expect(view(items).slice(-2)).toEqual(['human_review:waiting', 'persist:pending']);
  });

  it('shows repeats in order after a retake', () => {
    const progress = [
      p('validate_input', 0),
      p('input_guard', 1),
      p('detect', 2),
      p('postprocess', 3),
      p('build_report', 4),
      p('human_review', 5, 'retake'),
      p('validate_input', 6),
    ];
    const items = buildTimeline(progress, { active: true, next: ['input_guard'], status: 'detecting' });
    expect(view(items).slice(0, 8)).toEqual([
      'validate_input:done',
      'input_guard:done',
      'detect:done',
      'postprocess:done',
      'build_report:done',
      'human_review:done',
      'validate_input:done',
      'input_guard:current',
    ]);
    expect(new Set(items.map((i) => i.key)).size).toBe(items.length);
  });

  it('loops back to validate_input after human_review when status is retake', () => {
    const items = buildTimeline([p('build_report', 0), p('human_review', 1, 'retake')], { active: true, status: 'retake' });
    expect(items[2]).toMatchObject({ node: 'validate_input', state: 'current' });
  });

  it('adds nothing after a finished run', () => {
    const items = buildTimeline([p('build_report', 0), p('human_review', 1, 'approve'), p('persist', 2, 'approved')], {
      active: false,
      status: 'approved',
    });
    expect(view(items)).toEqual(['build_report:done', 'human_review:done', 'persist:done']);
  });

  it('ends at reject for a rejected photo', () => {
    const items = buildTimeline([p('validate_input', 0), p('input_guard', 1), p('reject', 2, 'не полка')], {
      active: false,
      status: 'rejected',
    });
    expect(view(items)).toEqual(['validate_input:done', 'input_guard:done', 'reject:done']);
    expect(items[2].label).toBe(nodeLabel('reject'));
  });

  it('labels unknown nodes by their name', () => {
    expect(nodeLabel('detect')).toBe('Детекция (проход 1)');
    expect(nodeLabel('new_node')).toBe('new_node');
  });
});
