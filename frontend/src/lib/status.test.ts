import { describe, expect, it } from 'vitest';
import { STATUS_FILTER_OPTIONS, isActive, statusLabel, statusTone } from './status';

describe('status helpers', () => {
  it('labels statuses in Russian', () => {
    expect(statusLabel('awaiting_review')).toBe('На проверке');
    expect(statusLabel('approved')).toBe('Утверждено');
    expect(statusLabel('edited')).toBe('Исправлено');
    expect(statusLabel('rejected')).toBe('Отклонено');
    expect(statusLabel('failed')).toBe('Ошибка');
    expect(statusLabel('detecting')).toBe('В работе');
    expect(statusLabel('verifying')).toBe('В работе');
    expect(statusLabel('mystery')).toBe('mystery');
  });

  it('gives tones', () => {
    expect(statusTone('awaiting_review')).toBe('warn');
    expect(statusTone('approved')).toBe('ok');
    expect(statusTone('failed')).toBe('danger');
    expect(statusTone('detecting')).toBe('info');
    expect(statusTone(undefined)).toBe('neutral');
  });

  it('filter covers all nine statuses', () => {
    expect(new Set(STATUS_FILTER_OPTIONS.map(([s]) => s)).size).toBe(9);
  });

  it('isActive = running or a working status', () => {
    expect(isActive({ running: true, status: 'awaiting_review' })).toBe(true);
    expect(isActive({ running: false, status: 'detecting' })).toBe(true);
    expect(isActive({ running: false, status: 'retake' })).toBe(true);
    expect(isActive({ running: false, status: 'new' })).toBe(true);
    expect(isActive({ running: false, status: 'awaiting_review' })).toBe(false);
    expect(isActive({ running: false, status: 'approved' })).toBe(false);
    expect(isActive(null)).toBe(false);
  });
});
