/** Turn a FastAPI error body into a human-readable message.
 *
 * FastAPI returns `{"detail": "text"}` for HTTPException and
 * `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` for validation errors (422).
 */
export function detailMessage(body: unknown, fallback: string): string {
  if (body == null) return fallback;
  if (typeof body === 'string') return body.trim() || fallback;
  if (typeof body !== 'object') return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === 'string') return detail || fallback;
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      if (d && typeof d === 'object') {
        const item = d as { msg?: unknown; loc?: unknown };
        const loc = Array.isArray(item.loc) ? item.loc.filter((x) => x !== 'body').join('.') : '';
        const msg = typeof item.msg === 'string' ? item.msg : JSON.stringify(d);
        return loc ? `${loc}: ${msg}` : msg;
      }
      return String(d);
    });
    return parts.join('; ') || fallback;
  }
  if (detail != null) return JSON.stringify(detail);
  return fallback;
}

/** Default Russian message for an HTTP status when the body has no detail. */
export function statusMessage(status: number): string {
  if (status === 0) return 'Сервер недоступен — проверьте, что API запущен';
  if (status === 401 || status === 403) return 'Нет доступа к API (проверьте токен)';
  if (status === 404) return 'Не найдено';
  if (status === 409) return 'Конфликт состояния';
  if (status === 413) return 'Файл слишком большой';
  if (status === 422) return 'Некорректный запрос';
  if (status >= 500) return `Ошибка сервера (${status})`;
  return `Ошибка запроса (${status})`;
}
