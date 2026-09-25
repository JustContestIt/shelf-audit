import type { MouseEvent } from 'react';
import type { ReportRow } from '../api/types';
import { colorForSubtype } from '../lib/colors';
import { PACKAGE_FORMATS, isUnknownSubtype } from '../lib/domain';
import { draftTotal, parseCount, type DraftRow } from '../lib/edits';
import { fmtInt } from '../lib/format';
import { groupRowsByShelf } from '../lib/match';

interface Props {
  rows: ReportRow[];
  selectedRow: number | null;
  onSelectRow: (row: number | null) => void;
  editing: boolean;
  draft: DraftRow[];
  onDraftChange: (row: number, patch: Partial<DraftRow>) => void;
  /** brand -> canon names from /catalog */
  subtypeOptions: Record<string, string[]>;
}

function withCurrent(options: readonly string[], current: string | null): string[] {
  return current && !options.includes(current) ? [current, ...options] : [...options];
}

function SubtypeCell({ row }: { row: ReportRow }) {
  if (row.subtype) return <>{row.subtype}</>;
  if (!isUnknownSubtype(row)) return <span className="faint">—</span>;
  return (
    <span className="unknown">
      <span aria-hidden="true">⚠</span>не опознано
    </span>
  );
}

function ReviewCell({ row }: { row: ReportRow }) {
  if (!row.needs_review) return null;
  return (
    <span className="review-badge">
      <span className="badge tone-warn">
        <span aria-hidden="true">⚠</span>проверить
      </span>
      {row.review_reason && <span className="reason">{row.review_reason}</span>}
    </span>
  );
}

/** Report rows grouped by shelf; in edit mode the cells become inputs. */
export function ReportTable({ rows, selectedRow, onSelectRow, editing, draft, onDraftChange, subtypeOptions }: Props) {
  const groups = groupRowsByShelf(rows);
  const total = rows.reduce((s, r) => s + (r.front_facing_count || 0), 0);
  const newTotal = editing ? draftTotal(draft) : total;
  const colCount = 7;

  const onRowClick = (e: MouseEvent<HTMLTableRowElement>, index: number) => {
    if ((e.target as HTMLElement).closest('button, input, select, a, label')) return;
    onSelectRow(selectedRow === index ? null : index);
  };

  if (rows.length === 0) {
    return <div className="empty">Строк нет — наш товар на фото не найден.</div>;
  }

  return (
    <div className="table-wrap">
      <table className="table table-click">
        <caption className="visually-hidden">Состав полки по полкам</caption>
        <thead>
          <tr>
            <th scope="col">
              <span className="visually-hidden">Показать на фото</span>
            </th>
            <th scope="col">Бренд</th>
            <th scope="col">Подвид</th>
            <th scope="col">Тара</th>
            <th scope="col" className="num">
              Кол-во
            </th>
            <th scope="col">Позиция</th>
            <th scope="col">{editing ? <span className="visually-hidden">Действия</span> : 'Проверка'}</th>
          </tr>
        </thead>
        {groups.map((g) => (
          <tbody key={g.shelf}>
            <tr className="shelf-head">
              <th colSpan={colCount} scope="rowgroup">
                {g.shelf ? `Полка ${g.shelf}` : 'Полка не определена'}{' '}
                <span className="muted">· {fmtInt(g.total)} ед.</span>
              </th>
            </tr>
            {g.rows.map(({ row, index }) => {
              const d = draft[index];
              const selected = selectedRow === index;
              const deleted = editing && d?.deleted;
              const cls = [selected ? 'is-selected' : '', row.needs_review ? 'row-warn' : '', deleted ? 'is-deleted' : '']
                .filter(Boolean)
                .join(' ');
              const color = colorForSubtype(editing && d ? d.subtype : row.subtype);
              const changedSubtype = editing && d && (d.subtype ?? null) !== (row.subtype ?? null);
              const changedFormat = editing && d && (d.package_format ?? null) !== (row.package_format ?? null);
              const changedCount = editing && d && parseCount(d.count) !== row.front_facing_count;
              const n = index + 1;
              return (
                <tr
                  key={index}
                  id={`report-row-${index}`}
                  className={cls || undefined}
                  data-clickable=""
                  onClick={(e) => onRowClick(e, index)}
                >
                  <td>
                    <button
                      type="button"
                      className="swatch-btn"
                      aria-pressed={selected}
                      aria-label={`Строка ${n}: показать рамки на фото`}
                      title="Показать на фото"
                      onClick={() => onSelectRow(selected ? null : index)}
                    >
                      <span className="swatch" style={{ background: color }} />
                    </button>
                  </td>
                  <td className="nowrap">{row.brand}</td>
                  {editing && d ? (
                    <>
                      <td className={changedSubtype ? 'changed' : undefined}>
                        <select
                          className="select select-sm"
                          aria-label={`Подвид, строка ${n}`}
                          value={d.subtype ?? ''}
                          disabled={d.deleted}
                          onChange={(e) => onDraftChange(index, { subtype: e.target.value || null })}
                        >
                          <option value="">— не опознано —</option>
                          {withCurrent(subtypeOptions[row.brand] ?? [], d.subtype).map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className={changedFormat ? 'changed' : undefined}>
                        <select
                          className="select select-sm"
                          aria-label={`Тара, строка ${n}`}
                          value={d.package_format ?? ''}
                          disabled={d.deleted}
                          onChange={(e) => onDraftChange(index, { package_format: e.target.value || null })}
                        >
                          <option value="">—</option>
                          {withCurrent(PACKAGE_FORMATS, d.package_format).map((f) => (
                            <option key={f} value={f}>
                              {f}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className={changedCount ? 'changed num' : 'num'}>
                        <input
                          className="input input-sm"
                          style={{ width: 72 }}
                          type="number"
                          inputMode="numeric"
                          min={1}
                          step={1}
                          aria-label={`Количество, строка ${n}`}
                          aria-invalid={!d.deleted && parseCount(d.count) === null}
                          value={d.count}
                          disabled={d.deleted}
                          onChange={(e) => onDraftChange(index, { count: e.target.value })}
                        />
                      </td>
                      <td>{row.position}</td>
                      <td className="actions-cell">
                        {d.deleted ? (
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => onDraftChange(index, { deleted: false })}
                            aria-label={`Вернуть строку ${n}`}
                          >
                            Вернуть
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="btn btn-sm btn-danger"
                            onClick={() => onDraftChange(index, { deleted: true })}
                            aria-label={`Удалить строку ${n}`}
                          >
                            Удалить
                          </button>
                        )}
                      </td>
                    </>
                  ) : (
                    <>
                      <td>
                        <SubtypeCell row={row} />
                      </td>
                      <td className="nowrap">{row.package_format ?? <span className="faint">—</span>}</td>
                      <td className="num">{fmtInt(row.front_facing_count)}</td>
                      <td className="nowrap">{row.position}</td>
                      <td>
                        <ReviewCell row={row} />
                      </td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        ))}
        <tfoot>
          <tr>
            <td colSpan={4}>{editing ? 'Итого после правок' : 'Итого'}</td>
            <td className="num">{fmtInt(newTotal)}</td>
            <td colSpan={2} className="muted small">
              {editing && newTotal !== total ? `было ${fmtInt(total)}` : ''}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
