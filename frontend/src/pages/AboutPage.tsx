import { useEffect, useState } from 'react';
import { api, errorText } from '../api/client';
import { Alert, JsonBlock, Loading, Panel } from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { usePageTitle } from '../hooks/usePageTitle';
import { PIPELINE_NODES } from '../lib/timeline';

function usePrefersDark(): boolean {
  const query = '(prefers-color-scheme: dark)';
  const [dark, setDark] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const h = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener('change', h);
    return () => mq.removeEventListener('change', h);
  }, []);
  return dark;
}

let renderSeq = 0;

/** Renders the LangGraph mermaid text; the mermaid package is loaded lazily (own chunk). */
function MermaidGraph({ text }: { text: string }) {
  const dark = usePrefersDark();
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    (async () => {
      try {
        const { default: mermaid } = await import('mermaid');
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: dark ? 'dark' : 'default',
          flowchart: { useMaxWidth: true },
        });
        const { svg: out } = await mermaid.render(`graph-${++renderSeq}`, text);
        if (!cancelled) setSvg(out);
      } catch (e) {
        if (!cancelled) setError(errorText(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [text, dark]);

  if (error) {
    return (
      <Alert tone="warn" title="Не удалось отрисовать граф">
        {error}
      </Alert>
    );
  }
  if (!svg) return <Loading text="Рисуем граф…" />;
  // mermaid output is sanitised (securityLevel: strict) and comes from our own API
  return <div className="mermaid-view" dangerouslySetInnerHTML={{ __html: svg }} />;
}

export function AboutPage() {
  usePageTitle('О системе');
  const graph = useAsync(() => api.mermaid(), []);
  const health = useAsync(() => api.health(), []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>О системе</h1>
          <p className="sub">Как фото полки превращается в отчёт.</p>
        </div>
      </div>

      <div className="grid-2">
        <section className="card" aria-labelledby="graph-title">
          <div className="card-head">
            <h2 id="graph-title">Граф обработки (LangGraph)</h2>
          </div>
          {graph.error ? (
            <Alert tone="danger" title="Граф недоступен">
              {graph.error}
            </Alert>
          ) : graph.data ? (
            <>
              <MermaidGraph text={graph.data} />
              <Panel title="Исходный текст mermaid">
                <pre>{graph.data}</pre>
              </Panel>
            </>
          ) : (
            <Loading />
          )}
        </section>

        <div className="stack">
          <section className="card prose" aria-labelledby="pipeline-title">
            <h2 id="pipeline-title">Пайплайн</h2>
            <p>
              Торговый агент фотографирует полку с напитками («Буратино», «AI TEA», Chino, «Компотай», Tamga). API
              (FastAPI) запускает граф LangGraph: модель находит каждую единицу первого ряда, называет подвид и тару,
              постобработка группирует единицы в строки отчёта по полкам.
            </p>
            <p>
              Неуверенные группы проходят через визуальный RAG: для их кропов ищутся похожие эталоны, и второй проход
              модели перепроверяет подвид. Затем граф останавливается на шаге проверки человеком: супервайзер
              сверяет рамки на фото и нажимает «Утвердить», «Исправить» или «Переснять».
            </p>
            <p>
              Товары с меткой «ЧУЖОЙ» — конкуренты: они показываются на фото для диагностики и никогда не попадают в
              счёт. Узкие рамки («щепки») отсеиваются постобработкой; их можно показать на фото.
            </p>
            <h3>Шаги</h3>
            <ol>
              {PIPELINE_NODES.map(([node, label]) => (
                <li key={node}>
                  {label} <span className="faint mono small">{node}</span>
                </li>
              ))}
            </ol>
          </section>

          <section className="card" aria-labelledby="health-title">
            <div className="card-head">
              <h2 id="health-title">Состояние API</h2>
              <button type="button" className="btn btn-sm" onClick={health.reload} disabled={health.loading}>
                Обновить
              </button>
            </div>
            {health.error ? (
              <Alert tone="danger" title="API недоступен">
                {health.error}
              </Alert>
            ) : health.data ? (
              <JsonBlock value={health.data} />
            ) : (
              <Loading />
            )}
          </section>
        </div>
      </div>
    </>
  );
}
