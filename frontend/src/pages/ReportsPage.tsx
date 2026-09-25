import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { ReportBrief } from '../api/types';
import { Alert, Empty, Loading, StatusBadge } from '../components/ui';
import { useAsync, useInterval } from '../hooks/useAsync';
import { usePageTitle } from '../hooks/usePageTitle';
import { fmtDateTime, fmtInt, fmtMoney, fmtPercent, fmtSeconds } from '../lib/format';
import { STATUS_FILTER_OPTIONS } from '../lib/status';

type Mode = 'all' | 'queue';

const LIMITS = [50, 100, 200, 500];

function ReportsTable({ items }: { items: ReportBrief[] }) {
  const navigate = useNavigate();
  return (
    <div className="table-wrap">
      <table className="table table-click">
        <thead>
          <tr>
            <th scope="col">Создан</th>
            <th scope="col">Отчёт</th>
            <th scope="col">Точка</th>
            <th scope="col" className="hide-sm">
              Агент
            </th>
            <th scope="col">Статус</th>
            <th scope="col" className="num">
              Ед.
            </th>
            <th scope="col" className="num">
              На проверку
            </th>
            <th scope="col" className="num hide-sm">
              Не опознано
            </th>
            <th scope="col" className="num hide-sm">
              Уверенность
            </th>
            <th scope="col" className="num hide-sm">
              $
            </th>
            <th scope="col" className="num hide-sm">
              Время
            </th>
            <th scope="col" className="hide-sm">
              Флаги
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => {
            const warnReview = (r.needs_review_units ?? 0) > 0;
            return (
              <tr
                key={r.report_id}
                data-clickable=""
                className={warnReview ? 'row-warn' : undefined}
                onClick={(e) => {
                  if ((e.target as HTMLElement).closest('a, button')) return;
                  navigate(`/reports/${encodeURIComponent(r.report_id)}`);
                }}
              >
                <td className="nowrap">{fmtDateTime(r.created_at)}</td>
                <td className="mono nowrap">
                  <Link to={`/reports/${encodeURIComponent(r.report_id)}`}>{r.report_id}</Link>
                </td>
                <td>
                  <div>{r.store_name || <span className="faint">—</span>}</div>
                  {r.store_code && <div className="faint small mono">{r.store_code}</div>}
                </td>
                <td className="hide-sm">{r.agent_id || <span className="faint">—</span>}</td>
                <td>
                  <StatusBadge status={r.status} />
                  {r.status === 'rejected' && r.reject_reason && (
                    <div className="faint small" style={{ maxWidth: 220 }}>
                      {r.reject_reason}
                    </div>
                  )}
                </td>
                <td className="num">{fmtInt(r.total_units)}</td>
                <td className="num">
                  {warnReview ? (
                    <span className="unknown">
                      <span aria-hidden="true">⚠</span>
                      {fmtInt(r.needs_review_units)}
                    </span>
                  ) : (
                    fmtInt(r.needs_review_units)
                  )}
                </td>
                <td className="num hide-sm">{fmtInt(r.unknown_units)}</td>
                <td className="num hide-sm">
                  {fmtPercent(r.overall_confidence)}
                  {r.low_confidence && (
                    <span className="unknown" title="низкая уверенность">
                      {' '}
                      <span aria-hidden="true">⚠</span>
                      <span className="visually-hidden">низкая</span>
                    </span>
                  )}
                </td>
                <td className="num hide-sm">{fmtMoney(r.cost_usd)}</td>
                <td className="num hide-sm">{fmtSeconds(r.latency_s)}</td>
                <td className="hide-sm small">
                  {r.flags?.length ? r.flags.map((f, i) => <div key={i}>⚑ {f}</div>) : <span className="faint">—</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** /reports (all, filterable) and /queue (= /reviews/pending). */
export function ReportsPage({ mode }: { mode: Mode }) {
  const queue = mode === 'queue';
  usePageTitle(queue ? 'Очередь на проверку' : 'Отчёты');
  const [params, setParams] = useSearchParams();
  const status = queue ? '' : (params.get('status') ?? '');
  const storeCode = params.get('store_code') ?? '';
  const limit = Number(params.get('limit')) || 100;
  const [storeInput, setStoreInput] = useState(storeCode);

  // debounce the free-text store filter into the URL
  useEffect(() => {
    const t = window.setTimeout(() => {
      if (storeInput.trim() === storeCode) return;
      setParams(
        (p) => {
          const n = new URLSearchParams(p);
          if (storeInput.trim()) n.set('store_code', storeInput.trim());
          else n.delete('store_code');
          return n;
        },
        { replace: true },
      );
    }, 400);
    return () => window.clearTimeout(t);
  }, [storeInput, storeCode, setParams]);

  const setParam = (key: string, value: string) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        if (value) n.set(key, value);
        else n.delete(key);
        return n;
      },
      { replace: true },
    );

  const list = useAsync(
    () =>
      queue
        ? api.pendingReviews({ store_code: storeCode || undefined, limit })
        : api.reports({ status: status || undefined, store_code: storeCode || undefined, limit }),
    [queue, status, storeCode, limit],
  );
  useInterval(list.reload, queue ? 15_000 : 30_000);

  const items = list.data ?? [];
  const filtered = Boolean(status || storeCode);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{queue ? 'Очередь на проверку' : 'Отчёты'}</h1>
          <p className="sub">
            {queue
              ? 'Отчёты, которые ждут решения супервайзера. Откройте отчёт, проверьте рамки и утвердите, исправьте или отправьте на пересъёмку.'
              : 'Все отчёты по фото полок. Нажмите строку, чтобы открыть отчёт.'}
          </p>
        </div>
        <button type="button" className="btn btn-sm" onClick={list.reload} disabled={list.loading}>
          Обновить
        </button>
      </div>

      <form className="filters" role="search" onSubmit={(e) => e.preventDefault()}>
        {!queue && (
          <div className="field">
            <label htmlFor="f-status">Статус</label>
            <select id="f-status" className="select" value={status} onChange={(e) => setParam('status', e.target.value)}>
              <option value="">Все статусы</option>
              {STATUS_FILTER_OPTIONS.map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="f-store">Код точки</label>
          <input
            id="f-store"
            className="input"
            value={storeInput}
            onChange={(e) => setStoreInput(e.target.value)}
            placeholder="например, 00-0000001"
            autoComplete="off"
          />
        </div>
        <div className="field" style={{ flex: '0 1 120px', minWidth: 100 }}>
          <label htmlFor="f-limit">Показать</label>
          <select id="f-limit" className="select" value={limit} onChange={(e) => setParam('limit', e.target.value)}>
            {LIMITS.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </div>
        {filtered && (
          <button
            type="button"
            className="btn"
            onClick={() => {
              setStoreInput('');
              setParams(new URLSearchParams(), { replace: true });
            }}
          >
            Сбросить
          </button>
        )}
      </form>

      {list.error && (
        <div style={{ marginBottom: 12 }}>
          <Alert tone="danger" title="Не удалось загрузить список">
            {list.error}
          </Alert>
        </div>
      )}

      {list.loading && !list.data ? (
        <Loading />
      ) : items.length === 0 ? (
        !list.error && (
          <div className="card">
            <Empty>
              {queue
                ? 'Очередь пуста — все отчёты проверены.'
                : filtered
                  ? 'По этим фильтрам отчётов нет.'
                  : 'Отчётов пока нет — загрузите фото полки.'}
              {!queue && !filtered && (
                <div style={{ marginTop: 12 }}>
                  <Link className="btn btn-primary" to="/upload">
                    Загрузить фото
                  </Link>
                </div>
              )}
            </Empty>
          </div>
        )
      ) : (
        <>
          <p className="muted small" style={{ marginBottom: 8 }} aria-live="polite">
            Показано: {items.length}
            {items.length >= limit ? ` (лимит ${limit})` : ''}
          </p>
          <ReportsTable items={items} />
        </>
      )}
    </>
  );
}
