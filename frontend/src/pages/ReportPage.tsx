import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { api, errorText, isApiError } from '../api/client';
import type { PhotoStatus, ReportFull, ReviewEdit } from '../api/types';
import { LlmCallsPanel, Pass2Panel, RetrievalPanel } from '../components/DiagnosticsPanels';
import { PhotoOverlay } from '../components/PhotoOverlay';
import { ProgressTimeline } from '../components/ProgressTimeline';
import { ReportTable } from '../components/ReportTable';
import { ReviewActions, ReviewDecision, type Busy } from '../components/ReviewActions';
import { FlagsList, SummaryCards } from '../components/SummaryCards';
import { Alert, Loading, Panel, Spinner, StatusBadge } from '../components/ui';
import { usePending } from '../hooks/pending';
import { usePageTitle } from '../hooks/usePageTitle';
import { MAX_UPLOAD_MB } from '../lib/domain';
import { diffEdits, draftFromRows, validateDraft, type DraftRow } from '../lib/edits';
import { fmtDateTime } from '../lib/format';
import { matchBoxesToRows } from '../lib/match';
import { isActive } from '../lib/status';
import { buildTimeline } from '../lib/timeline';

const POLL_MS = 1500;
const ERROR_RETRY_MS = 4000;
/** a fresh upload may wait in the worker queue before its graph state exists (status -> 404) */
const FRESH_404_LIMIT = 400;
/** no progress and nothing running for this long -> hint that the run is stuck */
const STALL_MS = 90_000;
const REVIEWER_KEY = 'shelf-audit.reviewer';

function readLS(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeLS(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private mode */
  }
}

/** Photo without overlay (rejected photos have no boxes). */
function PlainPhoto({ src }: { src: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className="photo-frame">
      {failed ? (
        <div className="photo-missing">Фото недоступно</div>
      ) : (
        <div className="photo-stage">
          <img src={src} alt="Отклонённое фото" onError={() => setFailed(true)} />
        </div>
      )}
    </div>
  );
}

export function ReportRoute() {
  const { id = '' } = useParams();
  return <ReportPage key={id} id={id} />;
}

function ReportPage({ id }: { id: string }) {
  usePageTitle(`Отчёт ${id}`);
  const location = useLocation();
  const fresh = Boolean((location.state as { fresh?: boolean } | null)?.fresh);
  const { refresh: refreshPending } = usePending();

  const [status, setStatus] = useState<PhotoStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [queued, setQueued] = useState(false);
  const [stalled, setStalled] = useState(false);
  const [report, setReport] = useState<ReportFull | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [reportLoaded, setReportLoaded] = useState(false);
  const [pollGen, setPollGen] = useState(0);

  const [selectedRow, setSelectedRow] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<DraftRow[]>([]);
  const [busy, setBusy] = useState<Busy>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [comment, setComment] = useState('');
  const [reviewer, setReviewer] = useState(() => readLS(REVIEWER_KEY) ?? '');
  const [subtypeOptions, setSubtypeOptions] = useState<Record<string, string[]>>({});
  const [catalogError, setCatalogError] = useState<string | null>(null);

  const loadReport = useCallback(async () => {
    try {
      const r = await api.report(id);
      setReport(r);
      setReportError(null);
    } catch (e) {
      if (isApiError(e, 404)) setReport(null);
      else setReportError(errorText(e));
    } finally {
      setReportLoaded(true);
    }
  }, [id]);

  // Poll /status while the graph works, then load the report.
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let misses = 0;
    let lastLen = -1;
    let lastChange = Date.now();
    const schedule = (ms: number) => {
      timer = window.setTimeout(tick, ms);
    };

    async function tick() {
      try {
        const st = await api.status(id);
        if (cancelled) return;
        misses = 0;
        setQueued(false);
        setNotFound(false);
        setStatusError(null);
        setStatus(st);
        const len = st.progress?.length ?? 0;
        if (len !== lastLen) {
          lastLen = len;
          lastChange = Date.now();
        }
        if (isActive(st)) {
          setStalled(!st.running && Date.now() - lastChange > STALL_MS);
          schedule(POLL_MS);
          return;
        }
        setStalled(false);
        await loadReport();
      } catch (e) {
        if (cancelled) return;
        if (isApiError(e, 404)) {
          misses += 1;
          if (misses <= (fresh ? FRESH_404_LIMIT : 2)) {
            setQueued(fresh);
            schedule(POLL_MS);
            return;
          }
          setQueued(false);
          setNotFound(true);
          return;
        }
        setStatusError(errorText(e));
        schedule(ERROR_RETRY_MS);
      }
    }

    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [id, pollGen, fresh, loadReport]);

  const body = report?.body ?? {};
  const data = body.report ?? null;
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const boxes = useMemo(() => body.boxes ?? [], [body.boxes]);
  const slivers = useMemo(() => body.slivers ?? [], [body.slivers]);
  const matches = useMemo(() => matchBoxesToRows(boxes, rows), [boxes, rows]);

  const active = queued || isActive(status);
  const st = status?.status ?? report?.status ?? null;
  const waiting = status?.waiting_review === true && !active;
  const progress = status?.progress?.length ? status.progress : (body.progress ?? []);
  const timeline = buildTimeline(progress, {
    active,
    next: status?.next,
    status: st,
    waitingReview: status?.waiting_review,
  });

  // Subtype options for the edit form: /catalog filtered by every brand present in the report.
  useEffect(() => {
    if (!editing) return;
    const brands = [...new Set(rows.map((r) => r.brand))].filter((b) => !(b in subtypeOptions));
    if (brands.length === 0) return;
    let cancelled = false;
    Promise.all(
      brands.map((brand) =>
        api.catalog({ brand }).then(
          (items) => [brand, items.filter((i) => i.brand === brand).map((i) => i.canon_name)] as const,
          (e: unknown) => {
            if (!cancelled) setCatalogError(errorText(e));
            return null;
          },
        ),
      ),
    ).then((pairs) => {
      if (cancelled) return;
      const ok = pairs.filter((p): p is readonly [string, string[]] => p !== null);
      if (ok.length) setSubtypeOptions((o) => ({ ...o, ...Object.fromEntries(ok) }));
    });
    return () => {
      cancelled = true;
    };
  }, [editing, rows, subtypeOptions]);

  const edits = useMemo<ReviewEdit[]>(() => (editing ? diffEdits(rows, draft) : []), [editing, rows, draft]);
  const validationErrors = useMemo(() => (editing ? validateDraft(draft) : []), [editing, draft]);

  // do not lose unsaved edits on reload / tab close
  useEffect(() => {
    if (!editing || edits.length === 0) return;
    const h = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  }, [editing, edits.length]);

  const onReviewerChange = (v: string) => {
    setReviewer(v);
    writeLS(REVIEWER_KEY, v);
  };

  const submitReview = async (action: 'approve' | 'edit', list: ReviewEdit[]) => {
    setBusy(action);
    setActionError(null);
    try {
      const r = await api.review(id, {
        action,
        edits: list,
        reviewer: reviewer.trim() || undefined,
        comment: comment.trim() || undefined,
      });
      setReport(r);
      setEditing(false);
      setSelectedRow(null);
      setComment('');
      refreshPending();
      setPollGen((g) => g + 1);
    } catch (e) {
      setActionError(errorText(e));
      if (isApiError(e, 409)) setPollGen((g) => g + 1);
    } finally {
      setBusy(null);
    }
  };

  const onRetake = async (file: File) => {
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setActionError(`Файл больше ${MAX_UPLOAD_MB} МБ — выберите фото поменьше`);
      return;
    }
    setBusy('retake');
    setActionError(null);
    try {
      await api.retake(id, file);
      setEditing(false);
      setSelectedRow(null);
      setStatus((s) => (s ? { ...s, running: true, waiting_review: false } : s));
      setPollGen((g) => g + 1);
      refreshPending();
    } catch (e) {
      setActionError(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  const selectFromPhoto = (row: number | null) => {
    setSelectedRow(row);
    if (row !== null) {
      window.requestAnimationFrame(() =>
        document.getElementById(`report-row-${row}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }),
      );
    }
  };

  // ------------------------------------------------------------------ render
  const head = (
    <div className="page-head">
      <div style={{ minWidth: 0 }}>
        <Link className="back-link" to={st === 'awaiting_review' ? '/queue' : '/reports'}>
          ← {st === 'awaiting_review' ? 'Очередь на проверку' : 'Отчёты'}
        </Link>
        <h1 className="id-title">
          Отчёт <span className="mono">{id}</span>
        </h1>
        {report && (
          <p className="sub">
            {[
              report.store_name,
              report.store_code && `код ${report.store_code}`,
              report.agent_id && `агент ${report.agent_id}`,
              fmtDateTime(report.created_at),
              report.source && `источник: ${report.source}`,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        )}
        {report?.prompt_version && (
          <p className="sub small">
            промпт <span className="mono">{report.prompt_version}</span>
            {report.models ? <> · {report.models}</> : null}
          </p>
        )}
      </div>
      {(st || queued) && <StatusBadge status={queued ? 'new' : st} large />}
    </div>
  );

  if (notFound) {
    return (
      <>
        {head}
        <Alert tone="danger" title="Отчёт не найден">
          Такого отчёта нет. <Link to="/reports">Вернуться к списку</Link>
        </Alert>
      </>
    );
  }

  if (!status && !queued) {
    return (
      <>
        {head}
        {statusError ? (
          <Alert tone="danger" title="Не удалось получить статус">
            {statusError}. Повторяем…
          </Alert>
        ) : (
          <Loading />
        )}
      </>
    );
  }

  if (active) {
    const retakes = status?.retakes ?? 0;
    return (
      <>
        {head}
        <section className="card processing" aria-live="polite">
          <div className="card-head">
            <h2>Обработка фото</h2>
            <span className="muted small row">
              <Spinner label="Обновление" /> обновляется каждые 1,5 с
            </span>
          </div>
          <div className="stack" style={{ gap: 12 }}>
            {queued && <p className="muted">Фото принято и ждёт свободного обработчика…</p>}
            {retakes > 0 && <Alert tone="info">Повторный анализ после пересъёмки ({retakes}).</Alert>}
            {stalled && (
              <Alert tone="warn" title="Обработка не продвигается">
                Шаги не меняются больше полутора минут, и задача не выполняется — возможно, API перезапускался.
              </Alert>
            )}
            {statusError && <Alert tone="warn">Нет связи с API: {statusError}. Повторяем…</Alert>}
            <ProgressTimeline items={timeline} />
          </div>
        </section>
      </>
    );
  }

  if (st === 'rejected') {
    const reason = status?.reject_reason ?? report?.reject_reason ?? 'причина не указана';
    return (
      <>
        {head}
        <div className="grid-2">
          <div className="stack">
            <section className="card reject-card" role="alert">
              <h2>Фото отклонено</h2>
              <p className="reject-reason">{reason}</p>
              <p>
                Переснимите полку: встаньте прямо напротив, чтобы в кадр попала вся полка целиком; без бликов, размытия
                и сильного наклона. Затем загрузите новое фото.
              </p>
              <div className="actions" style={{ marginTop: 14 }}>
                <Link className="btn btn-primary" to="/upload">
                  Загрузить новое фото
                </Link>
              </div>
            </section>
            {reportLoaded && report && (
              <section className="card">
                <h2 style={{ marginBottom: 10 }}>Отклонённое фото</h2>
                <PlainPhoto src={api.photoUrl(id, body.photo?.sha256)} />
              </section>
            )}
          </div>
          <section className="card">
            <h2 style={{ marginBottom: 12 }}>Ход обработки</h2>
            <ProgressTimeline items={timeline} />
          </section>
        </div>
      </>
    );
  }

  if (!report) {
    return (
      <>
        {head}
        {reportError ? (
          <Alert tone="danger" title="Не удалось загрузить отчёт">
            {reportError}{' '}
            <button type="button" className="link-btn" onClick={() => void loadReport()}>
              Повторить
            </button>
          </Alert>
        ) : reportLoaded ? (
          <Alert tone="warn" title="Отчёт ещё не сохранён">
            Статус: {st ?? '—'}. {status?.reject_reason}
          </Alert>
        ) : (
          <Loading text="Загрузка отчёта…" />
        )}
      </>
    );
  }

  if (!data) {
    return (
      <>
        {head}
        <div className="stack">
          <Alert tone="danger" title={st === 'failed' ? 'Ошибка обработки' : 'В отчёте нет данных'}>
            {report.reject_reason ?? status?.reject_reason ?? 'Граф завершился без отчёта.'}
            {report.flags?.length ? <div className="small">Флаги: {report.flags.join(', ')}</div> : null}
          </Alert>
          <Panel title="Ход обработки" meta={`${progress.length} шагов`} defaultOpen>
            <ProgressTimeline items={timeline} />
          </Panel>
        </div>
      </>
    );
  }

  const flags = data.flags?.length ? data.flags : (report.flags ?? []);

  return (
    <>
      {head}
      <div className="report-grid">
        <div className="photo-col">
          <section className="card" aria-label="Фото с разметкой">
            <PhotoOverlay
              src={api.photoUrl(id, body.photo?.sha256)}
              boxes={boxes}
              slivers={slivers}
              rows={rows}
              matches={matches}
              selectedRow={selectedRow}
              onSelectRow={selectFromPhoto}
              photo={body.photo}
              edited={st === 'edited'}
            />
          </section>
        </div>

        <div className="stack">
          {waiting ? (
            <ReviewActions
              editing={editing}
              busy={busy}
              changes={edits.length}
              validationErrors={validationErrors}
              error={actionError ?? (editing ? catalogError && `Каталог не загрузился: ${catalogError}` : null)}
              comment={comment}
              reviewer={reviewer}
              retakes={status?.retakes ?? 0}
              onCommentChange={setComment}
              onReviewerChange={onReviewerChange}
              onApprove={() => void submitReview('approve', [])}
              onStartEdit={() => {
                setDraft(draftFromRows(rows));
                setEditing(true);
                setActionError(null);
              }}
              onCancelEdit={() => {
                setEditing(false);
                setActionError(null);
              }}
              onSaveEdits={() => void submitReview('edit', edits)}
              onRetake={(f) => void onRetake(f)}
            />
          ) : st === 'approved' || st === 'edited' ? (
            <ReviewDecision status={st} review={report.review} />
          ) : st === 'awaiting_review' ? (
            <Alert tone="warn" title="Действия недоступны">
              Отчёт ждёт проверки, но граф сейчас не в состоянии ожидания (API перезапускался?). Решение принять нельзя.
            </Alert>
          ) : st === 'failed' ? (
            <Alert tone="danger" title="Ошибка обработки">
              {report.reject_reason ?? 'Граф завершился с ошибкой.'}
            </Alert>
          ) : null}

          <section className="card" aria-labelledby="summary-title">
            <div className="card-head">
              <h2 id="summary-title">Итоги</h2>
            </div>
            <SummaryCards report={data} />
            {flags.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <FlagsList flags={flags} />
              </div>
            )}
          </section>

          <section className="card" aria-labelledby="rows-title">
            <div className="card-head">
              <h2 id="rows-title">Состав полки</h2>
              <span className="muted small">
                {rows.length} строк · нажмите строку, чтобы подсветить её рамки
              </span>
            </div>
            <ReportTable
              rows={rows}
              selectedRow={selectedRow}
              onSelectRow={setSelectedRow}
              editing={editing}
              draft={draft}
              onDraftChange={(i, patch) => setDraft((d) => d.map((x, j) => (j === i ? { ...x, ...patch } : x)))}
              subtypeOptions={subtypeOptions}
            />
          </section>
        </div>
      </div>

      <div className="panels">
        <Panel title="Ход обработки" meta={`${progress.length} шагов`}>
          <ProgressTimeline items={timeline} />
        </Panel>
        <RetrievalPanel retrieval={body.retrieval} />
        <Pass2Panel pass2={body.pass2} />
        <LlmCallsPanel calls={body.llm_calls} />
      </div>
    </>
  );
}
