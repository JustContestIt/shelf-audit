import { describe, expect, it } from 'vitest';
import { detailMessage, statusMessage } from './errors';

describe('detailMessage', () => {
  it('reads a string detail', () => {
    expect(detailMessage({ detail: 'пересъёмка уже была (1)' }, 'x')).toBe('пересъёмка уже была (1)');
  });
  it('joins FastAPI validation errors', () => {
    expect(
      detailMessage(
        { detail: [{ loc: ['body', 'action'], msg: 'Field required', type: 'missing' }, { msg: 'bad' }] },
        'x',
      ),
    ).toBe('action: Field required; bad');
  });
  it('falls back when there is no detail', () => {
    expect(detailMessage(null, 'fallback')).toBe('fallback');
    expect(detailMessage({}, 'fallback')).toBe('fallback');
    expect(detailMessage('  ', 'fallback')).toBe('fallback');
    expect(detailMessage('plain text', 'fallback')).toBe('plain text');
  });
  it('stringifies an object detail', () => {
    expect(detailMessage({ detail: { code: 1 } }, 'x')).toBe('{"code":1}');
  });
});

describe('statusMessage', () => {
  it('describes common statuses in Russian', () => {
    expect(statusMessage(0)).toMatch(/недоступен/);
    expect(statusMessage(409)).toMatch(/Конфликт/);
    expect(statusMessage(502)).toMatch(/502/);
  });
});
