import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { EvalFrame, EvalResult } from '../api/types';
import { Alert, Badge, Empty, JsonBlock, Loading, Panel } from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { usePageTitle } from '../hooks/usePageTitle';
import { DASH, fmtDateTime, fmtInt, fmtMoney, fmtSeconds, formatMetric, metricLabel, orderMetricKeys } from '../lib/format';

function runTitle(r: EvalResult): string {
  return r.name || r.file;
}

function ModeBadge({ mode }: { mode?: string }) {
  if (!mode) return <span className="faint">{DASH}</span>;
  return <Badge tone={mode === 'live' ? 'info' : 'neutral'}>{mode}</Badge>;
}

function frameHasProblem(f: EvalFrame): boolean {
  return (
    (f.errors?.length ?? 0) > 0 ||
    (f.subtype_errors ?? 0) > 0 ||
    (f.contamination ?? 0) > 0 ||
    (f.pack_errors ?? 0) > 0 ||
    (f.units_gt != null && f.units_pred != null && f.units_gt !== f.units_pred)
  );
}

function FramesTable({ frames }: { frames: EvalFrame[] }) {
  if (!frames.length) return <p className="muted small">Покадровых результатов нет.</p>;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Кадр</th>
            <th scope="col">Вариант</th>
            <th scope="col">Тир</th>
            <th scope="col" className="num">
              Полок
            </th>
            <th scope="col" className="num">
              Ед. эталон
            </th>
            <th scope="col" className="num">
              Ед. модель
            </th>
            <th scope="col" className="num">
              Полок с точным счётом
            </th>
            <th scope="col" className="num">
              Ошибки подвида
            </th>
            <th scope="col" className="num">
              Чужие в счёте
            </th>
            <th scope="col" className="num">
              Ошибки тары
            </th>
            <th scope="col" className="num">
              $
            </th>
            <th scope="col" className="num">
              Время
            </th>
            <th scope="col">Ошибки</th>
          </tr>
        </thead>
        <tbody>
          {frames.map((f, i) => {
            const bad = frameHasProblem(f);
            const unitsOff = f.units_gt != null && f.units_pred != null && f.units_gt !== f.units_pred;
            return (
              <tr key={`${f.frame_id}-${f.variant ?? ''}-${i}`} className={bad ? 'row-warn' : undefined}>
                <td className="mono nowrap">
                  {bad && (
                    <span className="unknown" aria-label="есть ошибки">
                      ⚠{' '}
                    </span>
                  )}
                  {f.frame_id}
                </td>
                <td>{f.variant ?? DASH}</td>
                <td>{f.tier ?? DASH}</td>
                <td className="num">{fmtInt(f.shelves)}</td>
                <td className="num">{fmtInt(f.units_gt)}</td>
                <td className={`num${unitsOff ? ' unknown' : ''}`}>{fmtInt(f.units_pred)}</td>
                <td className="num">{fmtInt(f.count_exact_shelves)}</td>
                <td className="num">{fmtInt(f.subtype_errors)}</td>
                <td className="num">{fmtInt(f.contamination)}</td>
                <td className="num">{fmtInt(f.pack_errors)}</td>
                <td className="num">{fmtMoney(f.cost_usd)}</td>
                <td className="num">{fmtSeconds(f.latency_s)}</td>
                <td className="small" style={{ minWidth: 160 }}>
                  {f.errors?.length ? f.errors.map((e, j) => <div key={j}>{e}</div>) : <span className="faint">{DASH}</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SlicesTable({ slices }: { slices: Record<string, Record<string, number | null>> }) {
  const names = Object.keys(slices);
  const keys = orderMetricKeys(names.flatMap((n) => Object.keys(slices[n] ?? {})));
  if (!names.length) return <p className="muted small">Срезов нет.</p>;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Срез</th>
            {keys.map((k) => (
              <th key={k} scope="col" className="num metric-head" title={k}>
                {metricLabel(k)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {names.map((n) => (
            <tr key={n}>
              <th scope="row" className="mono" style={{ fontWeight: 500 }}>
                {n}
              </th>
              {keys.map((k) => (
                <td key={k} className="num">
                  {formatMetric(k, slices[n]?.[k])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EvalsPage() {
  usePageTitle('Evals');
  const evals = useAsync(() => api.evals(), []);
  const [params, setParams] = useSearchParams();
  const selectedFile = params.get('file');

  const runs = useMemo(() => evals.data ?? [], [evals.data]);
  const metricKeys = useMemo(() => orderMetricKeys(runs.flatMap((r) => Object.keys(r.summary ?? {}))), [runs]);
  const selected = runs.find((r) => r.file === selectedFile) ?? null;

  const select = (file: string | null) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        if (file) n.set('file', file);
        else n.delete('file');
        return n;
      },
      { replace: true },
    );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Evals</h1>
          <p className="sub">
            Результаты прогонов на золотом наборе, новые сверху. Нажмите строку, чтобы увидеть покадровые результаты и
            срезы.
          </p>
        </div>
        <button type="button" className="btn btn-sm" onClick={evals.reload} disabled={evals.loading}>
          Обновить
        </button>
      </div>

      {evals.error && (
        <Alert tone="danger" title="Не удалось загрузить результаты">
          {evals.error}
        </Alert>
      )}

      {evals.loading && !evals.data ? (
        <Loading />
      ) : runs.length === 0 ? (
        !evals.error && (
          <div className="card">
            <Empty>
              Результатов пока нет — запустите <code>make eval</code>
            </Empty>
          </div>
        )
      ) : (
        <div className="table-wrap">
          <table className="table table-click">
            <thead>
              <tr>
                <th scope="col">Прогон</th>
                <th scope="col">Режим</th>
                <th scope="col">Дата</th>
                {metricKeys.map((k) => (
                  <th key={k} scope="col" className="num metric-head" title={k}>
                    {metricLabel(k)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const isSel = r.file === selectedFile;
                return (
                  <tr
                    key={r.file}
                    data-clickable=""
                    className={isSel ? 'is-selected' : undefined}
                    onClick={(e) => {
                      if ((e.target as HTMLElement).closest('button')) return;
                      select(isSel ? null : r.file);
                    }}
                  >
                    <td>
                      <button
                        type="button"
                        className="link-btn"
                        aria-expanded={isSel}
                        onClick={() => select(isSel ? null : r.file)}
                      >
                        {runTitle(r)}
                      </button>
                      {r.name && r.name !== r.file && <div className="faint small mono">{r.file}</div>}
                    </td>
                    <td>
                      <ModeBadge mode={r.mode} />
                    </td>
                    <td className="nowrap">{fmtDateTime(r.created_at)}</td>
                    {metricKeys.map((k) => (
                      <td key={k} className="num">
                        {formatMetric(k, r.summary?.[k])}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {runs.length > 0 && !selected && (
        <p className="muted small" style={{ marginTop: 12 }}>
          Выберите прогон, чтобы увидеть покадровые результаты.
        </p>
      )}

      {selected && (
        <section aria-labelledby="run-title">
          <h2 id="run-title" className="section-title">
            {runTitle(selected)} <ModeBadge mode={selected.mode} />
          </h2>
          <div className="stack">
            {selected.notes && (
              <div className="card">
                <h3 style={{ marginBottom: 6 }}>Заметки</h3>
                <p style={{ whiteSpace: 'pre-wrap' }}>{selected.notes}</p>
              </div>
            )}
            <div>
              <h3 style={{ marginBottom: 8 }}>По кадрам ({selected.per_frame?.length ?? 0})</h3>
              <FramesTable frames={selected.per_frame ?? []} />
            </div>
            <div>
              <h3 style={{ marginBottom: 8 }}>Срезы</h3>
              <SlicesTable slices={selected.slices ?? {}} />
            </div>
            {selected.config && (
              <Panel title="Конфигурация прогона" meta={selected.file}>
                <JsonBlock value={selected.config} />
              </Panel>
            )}
          </div>
        </section>
      )}
    </>
  );
}
