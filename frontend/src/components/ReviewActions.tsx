import { useRef } from 'react';
import type { ReviewRecord } from '../api/types';
import { fmtDateTime } from '../lib/format';
import { Alert, Spinner, StatusBadge } from './ui';

export type Busy = null | 'approve' | 'edit' | 'retake';

interface Props {
  editing: boolean;
  busy: Busy;
  changes: number;
  validationErrors: string[];
  error: string | null;
  comment: string;
  reviewer: string;
  retakes: number;
  onCommentChange: (v: string) => void;
  onReviewerChange: (v: string) => void;
  onApprove: () => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdits: () => void;
  onRetake: (file: File) => void;
}

/** «Утвердить» / «Исправить» / «Переснять» — shown only while the graph waits for the supervisor. */
export function ReviewActions(p: Props) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const disabled = p.busy !== null;

  return (
    <section className="card" aria-labelledby="review-title">
      <div className="card-head">
        <h2 id="review-title">Решение супервайзера</h2>
        <StatusBadge status="awaiting_review" />
      </div>

      <div className="form" style={{ gap: 10 }}>
        <div className="row" style={{ alignItems: 'stretch' }}>
          <div className="field" style={{ flex: '1 1 160px' }}>
            <label htmlFor="reviewer">Проверяющий</label>
            <input
              id="reviewer"
              className="input input-sm"
              value={p.reviewer}
              onChange={(e) => p.onReviewerChange(e.target.value)}
              placeholder="например, S001"
              autoComplete="off"
            />
          </div>
          <div className="field" style={{ flex: '3 1 220px' }}>
            <label htmlFor="review-comment">Комментарий</label>
            <input
              id="review-comment"
              className="input input-sm"
              value={p.comment}
              onChange={(e) => p.onCommentChange(e.target.value)}
              placeholder="необязательно"
              autoComplete="off"
            />
          </div>
        </div>

        {p.editing ? (
          <>
            <p className="hint">
              Режим правки: измените подвид, тару или количество прямо в таблице, лишние строки удалите. Отправятся
              только изменённые строки.
            </p>
            <div className="actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={p.onSaveEdits}
                disabled={disabled || p.changes === 0 || p.validationErrors.length > 0}
              >
                {p.busy === 'edit' && <Spinner label="Сохранение" />}
                Сохранить правки{p.changes ? ` (${p.changes})` : ''}
              </button>
              <button type="button" className="btn" onClick={p.onCancelEdit} disabled={disabled}>
                Отменить
              </button>
            </div>
            {p.validationErrors.length > 0 && (
              <ul className="errors-list">
                {p.validationErrors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            )}
          </>
        ) : (
          <div className="actions">
            <button type="button" className="btn btn-ok" onClick={p.onApprove} disabled={disabled}>
              {p.busy === 'approve' ? <Spinner label="Отправка" /> : <span aria-hidden="true">✓</span>}
              Утвердить
            </button>
            <button type="button" className="btn" onClick={p.onStartEdit} disabled={disabled}>
              <span aria-hidden="true">✎</span>
              Исправить
            </button>
            <button type="button" className="btn" onClick={() => fileRef.current?.click()} disabled={disabled}>
              {p.busy === 'retake' ? <Spinner label="Загрузка" /> : <span aria-hidden="true">↻</span>}
              Переснять
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="visually-hidden"
              tabIndex={-1}
              aria-label="Новое фото для пересъёмки"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = '';
                if (f) p.onRetake(f);
              }}
            />
          </div>
        )}
        {p.retakes > 0 && !p.editing && <p className="hint">Пересъёмок уже было: {p.retakes}.</p>}
        {p.error && <Alert tone="danger">{p.error}</Alert>}
      </div>
    </section>
  );
}

const ACTION_TEXT: Record<string, string> = { approve: 'утверждено', edit: 'исправлено', retake: 'пересъёмка' };

/** Final decision card after approve / edit. */
export function ReviewDecision({ status, review }: { status: string; review: ReviewRecord | null }) {
  return (
    <section className="card" aria-labelledby="decision-title">
      <div className="card-head">
        <h2 id="decision-title">Решение</h2>
        <StatusBadge status={status} large />
      </div>
      {review ? (
        <dl className="review-meta">
          <dt>Действие</dt>
          <dd>{ACTION_TEXT[review.action] ?? review.action}</dd>
          <dt>Когда</dt>
          <dd>{fmtDateTime(review.at)}</dd>
          {review.reviewer && (
            <>
              <dt>Проверяющий</dt>
              <dd>{review.reviewer}</dd>
            </>
          )}
          {review.edits?.length > 0 && (
            <>
              <dt>Правок</dt>
              <dd>{review.edits.length}</dd>
            </>
          )}
          {review.comment && (
            <>
              <dt>Комментарий</dt>
              <dd>{review.comment}</dd>
            </>
          )}
        </dl>
      ) : (
        <p className="muted small">Подробности решения не сохранены.</p>
      )}
    </section>
  );
}
