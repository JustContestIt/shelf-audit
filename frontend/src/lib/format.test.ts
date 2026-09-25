import { describe, expect, it } from 'vitest';
import {
  DASH,
  compareGroupKeys,
  fmtInt,
  fmtMoney,
  fmtNum,
  fmtPercent,
  fmtSeconds,
  formatMetric,
  isPercentMetric,
  metricLabel,
  orderMetricKeys,
  secondsBetween,
} from './format';

// normalise non-breaking spaces so expectations stay readable
const n = (s: string) => s.replace(/ /g, ' ');

describe('numbers', () => {
  it('fmtNum uses a decimal comma and groups thousands', () => {
    expect(n(fmtNum(1234.56, 1))).toBe('1 234,6');
    expect(fmtNum(0.5, 2)).toBe('0,50');
    expect(fmtNum(2.5, 3, true)).toBe('2,5');
    expect(fmtNum(3, 3, true)).toBe('3');
    expect(fmtNum(-1.25, 1)).toBe('−1,3');
    expect(fmtNum(null)).toBe(DASH);
    expect(fmtNum(Number.NaN)).toBe(DASH);
  });
  it('fmtInt rounds', () => {
    expect(n(fmtInt(50000))).toBe('50 000');
    expect(fmtInt(2.6)).toBe('3');
    expect(fmtInt(undefined)).toBe(DASH);
  });
  it('fmtPercent', () => {
    expect(n(fmtPercent(0.9))).toBe('90 %');
    expect(n(fmtPercent(0.8567, 1))).toBe('85,7 %');
  });
  it('fmtMoney picks the precision by magnitude', () => {
    expect(fmtMoney(0.1)).toBe('$0,100');
    expect(fmtMoney(0.0032)).toBe('$0,0032');
    expect(fmtMoney(12.5)).toBe('$12,50');
    expect(fmtMoney(0)).toBe('$0,00');
    expect(fmtMoney(null)).toBe(DASH);
  });
  it('fmtSeconds', () => {
    expect(n(fmtSeconds(2))).toBe('2,0 с');
    expect(n(fmtSeconds(12.4))).toBe('12 с');
    expect(n(fmtSeconds(65))).toBe('1 мин 5 с');
    expect(n(fmtSeconds(120))).toBe('2 мин');
  });
  it('secondsBetween', () => {
    expect(secondsBetween('2026-09-25T11:33:50+00:00', '2026-09-25T11:33:52.500+00:00')).toBe(2.5);
    expect(secondsBetween('bad', '2026-09-25T11:33:52+00:00')).toBeNull();
  });
});

describe('compareGroupKeys', () => {
  it('sorts shelf.group keys naturally', () => {
    expect(['2.1', '1.10', '1.2', '1.1'].sort(compareGroupKeys)).toEqual(['1.1', '1.2', '1.10', '2.1']);
  });
});

describe('eval metrics', () => {
  it('detects percentage metrics', () => {
    for (const k of ['count_exact_shelf_rate', 'subtype_acc', 'subtype_acc_pink', 'pack_acc', 'guardrail_precision', 'guardrail_recall']) {
      expect(isPercentMetric(k), k).toBe(true);
    }
    for (const k of ['count_mae', 'contamination', 'cost_usd_per_photo', 'latency_p50_s', 'n_frames', 'accuracy_like', 'stability_sigma_subtype_err']) {
      expect(isPercentMetric(k), k).toBe(false);
    }
  });
  it('labels known keys in Russian and shows unknown keys as is', () => {
    expect(metricLabel('subtype_acc')).toBe('Точность подвида');
    expect(metricLabel('latency_p95_s')).toBe('p95, с');
    expect(metricLabel('my_new_metric')).toBe('my_new_metric');
  });
  it('orders known keys canonically, unknown keys after them alphabetically', () => {
    expect(orderMetricKeys(['zeta', 'n_units', 'subtype_acc', 'alpha', 'count_exact_shelf_rate'])).toEqual([
      'count_exact_shelf_rate',
      'subtype_acc',
      'n_units',
      'alpha',
      'zeta',
    ]);
  });
  it('formats metric values', () => {
    expect(n(formatMetric('subtype_acc', 0.9234))).toBe('92,3 %');
    expect(n(formatMetric('pack_acc', 97.5))).toBe('97,5 %');
    expect(formatMetric('subtype_acc', null)).toBe(DASH);
    expect(formatMetric('count_mae', 0.4567)).toBe('0,457');
    expect(formatMetric('cost_usd_per_photo', 0.0123)).toBe('$0,012');
    expect(n(formatMetric('latency_p50_s', 3.5))).toBe('3,5 с');
    expect(n(formatMetric('n_units', 1234))).toBe('1 234');
    expect(formatMetric('contamination', 0)).toBe('0');
    expect(formatMetric('whatever', 'text')).toBe('text');
  });
});
