import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, errorText } from '../api/client';
import { Alert, Loading, Spinner } from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { usePageTitle } from '../hooks/usePageTitle';
import { MAX_UPLOAD_MB as MAX_MB } from '../lib/domain';
import { fmtNum } from '../lib/format';

const AGENT_KEY = 'shelf-audit.agent_id';
const STORE_KEY = 'shelf-audit.store_code';

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

export function UploadPage() {
  usePageTitle('Загрузить фото');
  const navigate = useNavigate();
  const stores = useAsync(() => api.stores(), []);

  const [storeCode, setStoreCode] = useState(() => readLS(STORE_KEY) ?? '');
  const [manualName, setManualName] = useState('');
  const [agentId, setAgentId] = useState(() => readLS(AGENT_KEY) || 'A001');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const list = useMemo(() => stores.data ?? [], [stores.data]);
  const manual = !stores.loading && list.length === 0;
  const store = list.find((s) => s.store_code === storeCode);

  // default to the first store when nothing (valid) is remembered
  useEffect(() => {
    if (list.length && !list.some((s) => s.store_code === storeCode)) setStoreCode(list[0].store_code);
  }, [list, storeCode]);

  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const sizeMb = file ? file.size / 1024 / 1024 : 0;
  const fileProblem = !file
    ? null
    : file.type && !file.type.startsWith('image/')
      ? 'Это не изображение'
      : sizeMb > MAX_MB
        ? `Файл больше ${MAX_MB} МБ`
        : null;
  const canSubmit = Boolean(file && !fileProblem && storeCode.trim() && agentId.trim() && !submitting);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file || !canSubmit) return;
    setSubmitting(true);
    setError(null);
    writeLS(AGENT_KEY, agentId.trim());
    writeLS(STORE_KEY, storeCode.trim());
    try {
      const res = await api.uploadPhoto({
        file,
        store_code: storeCode.trim(),
        store_name: store?.store_name ?? manualName.trim(),
        route_code: store?.route_code ?? '',
        agent_id: agentId.trim(),
      });
      navigate(`/reports/${encodeURIComponent(res.report_id)}`, { state: { fresh: true } });
    } catch (err) {
      setError(errorText(err));
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Загрузить фото полки</h1>
          <p className="sub">Фото уйдёт в обработку; отчёт откроется сразу, с ходом обработки по шагам.</p>
        </div>
      </div>

      <div className="upload-grid">
        <form className="card form" onSubmit={onSubmit} noValidate>
          <div className="field">
            <label htmlFor="store">Торговая точка</label>
            {stores.loading && !stores.data ? (
              <Loading text="Загрузка точек…" />
            ) : manual ? (
              <>
                {stores.error && <Alert tone="warn">Список точек не загрузился: {stores.error}. Введите точку вручную.</Alert>}
                <input
                  id="store"
                  className="input"
                  value={storeCode}
                  onChange={(e) => setStoreCode(e.target.value)}
                  placeholder="Код точки, например 00-0000001"
                  required
                  autoComplete="off"
                />
                <label htmlFor="store-name" className="visually-hidden">
                  Название точки
                </label>
                <input
                  id="store-name"
                  className="input"
                  value={manualName}
                  onChange={(e) => setManualName(e.target.value)}
                  placeholder="Название точки (необязательно)"
                  autoComplete="off"
                />
              </>
            ) : (
              <>
                <select
                  id="store"
                  className="select"
                  value={storeCode}
                  onChange={(e) => setStoreCode(e.target.value)}
                  required
                >
                  {list.map((s) => (
                    <option key={s.store_code} value={s.store_code}>
                      {s.store_name} — {s.store_code}
                    </option>
                  ))}
                </select>
                {store && (
                  <span className="hint">
                    {store.address || 'адрес не указан'}
                    {store.route_code ? ` · маршрут ${store.route_code}` : ''}
                  </span>
                )}
              </>
            )}
          </div>

          <div className="field">
            <label htmlFor="agent">Код агента</label>
            <input
              id="agent"
              className="input"
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              required
              autoComplete="off"
              style={{ maxWidth: 220 }}
            />
          </div>

          <div className="field">
            <label htmlFor="photo">Фото полки</label>
            <input
              id="photo"
              className="input"
              type="file"
              accept="image/*"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setDims(null);
              }}
              aria-describedby="photo-hint"
              aria-invalid={Boolean(fileProblem)}
            />
            <span id="photo-hint" className="hint">
              JPEG / PNG / HEIC, до {MAX_MB} МБ.
            </span>
            {fileProblem && <Alert tone="danger">{fileProblem}</Alert>}
          </div>

          {preview ? (
            <div className="dropzone">
              <img
                className="preview"
                src={preview}
                alt="Предпросмотр выбранного фото"
                onLoad={(e) => setDims({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
              />
              <span className="hint">
                {file?.name} · {fmtNum(sizeMb, 1)} МБ{dims ? ` · ${dims.w}×${dims.h}` : ''}
              </span>
            </div>
          ) : (
            <div className="dropzone muted small">Выберите фото — здесь появится предпросмотр.</div>
          )}

          {error && (
            <Alert tone="danger" title="Не удалось отправить фото">
              {error}
            </Alert>
          )}

          <div>
            <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
              {submitting && <Spinner label="Отправка" />}
              {submitting ? 'Отправка…' : 'Отправить на анализ'}
            </button>
          </div>
        </form>

        <aside className="card prose small" aria-labelledby="tips-title">
          <h2 id="tips-title">Как снять полку</h2>
          <ul>
            <li>Встаньте прямо напротив полки, держите телефон ровно.</li>
            <li>В кадр должна попасть вся полка целиком — все ряды и края.</li>
            <li>Без бликов, размытия и пальцев в кадре; достаточно света.</li>
            <li>Одно фото — один стеллаж; полки на нём система разделит сама.</li>
          </ul>
          <p className="muted">
            После анализа отчёт попадёт в «Очередь на проверку»: супервайзер утвердит его, исправит или попросит
            переснять.
          </p>
        </aside>
      </div>
    </>
  );
}
