import type { LLMCall, Pass2Info, Retrieval, RetrievalGroup } from '../api/types';
import { compareGroupKeys, fmtInt, fmtMoney, fmtNum, fmtSeconds } from '../lib/format';
import { JsonBlock, Panel } from './ui';

function isGroup(v: unknown): v is RetrievalGroup {
  return typeof v === 'object' && v !== null && Array.isArray((v as RetrievalGroup).candidates);
}

export function RetrievalPanel({ retrieval }: { retrieval: Retrieval | undefined }) {
  const r = retrieval ?? {};
  const groups = Object.entries(r)
    .filter((e): e is [string, RetrievalGroup] => !e[0].startsWith('_') && isGroup(e[1]))
    .sort((a, b) => compareGroupKeys(a[0], b[0]));
  const mode = r._mode ?? '—';
  const meta = `режим ${mode}${r._backend ? ` · ${r._backend}` : ''} · групп: ${groups.length}`;
  return (
    <Panel title="RAG: кандидаты по группам" meta={meta}>
      {groups.length === 0 ? (
        <p className="muted small">
          {mode === 'all'
            ? 'Режим «all»: поиск по индексу не выполнялся — во второй проход отправлены все активные эталоны.'
            : 'Поиск эталонов не запускался (неуверенных групп не было).'}
        </p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Группа</th>
                <th scope="col">Бренд</th>
                <th scope="col">Проход 1</th>
                <th scope="col" className="num">
                  Боксов
                </th>
                <th scope="col">Кандидаты (score · SigLIP · HSV · эталонов)</th>
              </tr>
            </thead>
            <tbody>
              {groups.map(([key, g]) => {
                const top = g.candidates[0]?.canon_name;
                return (
                  <tr key={key}>
                    <td className="mono">{key}</td>
                    <td className="nowrap">{g.brand}</td>
                    <td>{g.pass1 ?? <span className="faint">не опознано</span>}</td>
                    <td className="num">{fmtInt(g.size)}</td>
                    <td>
                      <ol className="cand-list">
                        {g.candidates.map((c, i) => (
                          <li key={c.canon_name + i} className={i === 0 ? 'top' : undefined}>
                            <span>{c.canon_name}</span>
                            <span className="chip">{fmtNum(c.score, 3)}</span>
                            {c.s_siglip != null && <span className="chip">SigLIP {fmtNum(c.s_siglip, 3)}</span>}
                            {c.s_hsv != null && <span className="chip">HSV {fmtNum(c.s_hsv, 3)}</span>}
                            <span className="chip" title={c.refs.join(', ')}>
                              эталонов: {c.refs.length}
                            </span>
                            {i === 0 && top && g.pass1 && top !== g.pass1 && (
                              <span className="badge tone-warn">≠ проход 1</span>
                            )}
                          </li>
                        ))}
                      </ol>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

export function Pass2Panel({ pass2 }: { pass2: Pass2Info | null | undefined }) {
  if (!pass2) {
    return (
      <Panel title="Проход 2" meta="не запускался">
        <p className="muted small">Второй проход не запускался — неуверенных групп не было или он выключен.</p>
      </Panel>
    );
  }
  return (
    <Panel
      title="Проход 2"
      meta={`${pass2.version} · изменено ${fmtInt(pass2.subtypes_changed)} · не уверен ${fmtInt(pass2.needs_review)}`}
    >
      <div className="kv">
        <span>
          Версия: <b className="mono">{pass2.version}</b>
        </span>
        <span>
          Изменено подвидов: <b>{fmtInt(pass2.subtypes_changed)}</b>
        </span>
        <span>
          Не уверен: <b>{fmtInt(pass2.needs_review)}</b>
        </span>
        {pass2.shelves_total != null && (
          <span>
            Полок применено: <b>{fmtInt(pass2.shelves_applied ?? null)}</b> из <b>{fmtInt(pass2.shelves_total)}</b>
          </span>
        )}
      </div>
      {pass2.usage && (
        <div className="kv small muted">
          {Object.entries(pass2.usage).map(([k, v]) => (
            <span key={k}>
              {k}: <b>{fmtInt(v)}</b>
            </span>
          ))}
        </div>
      )}
      <div>
        <div className="field-label" style={{ marginBottom: 6 }}>
          detail
        </div>
        <JsonBlock value={pass2.detail} />
      </div>
    </Panel>
  );
}

export function LlmCallsPanel({ calls }: { calls: LLMCall[] | undefined }) {
  const list = calls ?? [];
  const sum = (f: (c: LLMCall) => number | null | undefined) => list.reduce((s, c) => s + (f(c) ?? 0), 0);
  return (
    <Panel title="Вызовы модели" meta={`${list.length} · ${fmtMoney(sum((c) => c.cost_usd))}`}>
      {list.length === 0 ? (
        <p className="muted small">Вызовов модели не было.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Проход</th>
                <th scope="col">Модель</th>
                <th scope="col" className="hide-sm">
                  Провайдер
                </th>
                <th scope="col" className="num">
                  Токены вход
                </th>
                <th scope="col" className="num">
                  выход
                </th>
                <th scope="col" className="num">
                  кэш
                </th>
                <th scope="col" className="num">
                  $
                </th>
                <th scope="col" className="num">
                  Время
                </th>
                <th scope="col">Replay</th>
                <th scope="col">Fallback</th>
              </tr>
            </thead>
            <tbody>
              {list.map((c, i) => (
                <tr key={i}>
                  <td>{c.pass}</td>
                  <td className="mono nowrap">{c.model}</td>
                  <td className="hide-sm">{c.provider}</td>
                  <td className="num">{fmtInt(c.input_tokens)}</td>
                  <td className="num">{fmtInt(c.output_tokens)}</td>
                  <td className="num">{fmtInt(c.cached_tokens)}</td>
                  <td className="num">{fmtMoney(c.cost_usd)}</td>
                  <td className="num">{fmtSeconds(c.latency_s)}</td>
                  <td>{c.replayed ? <span aria-label="да">✓</span> : <span className="faint">—</span>}</td>
                  <td className="mono small">
                    {c.fallback_from?.length ? c.fallback_from.join(' → ') : <span className="faint">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={2}>Итого</td>
                <td className="hide-sm" />
                <td className="num">{fmtInt(sum((c) => c.input_tokens))}</td>
                <td className="num">{fmtInt(sum((c) => c.output_tokens))}</td>
                <td className="num">{fmtInt(sum((c) => c.cached_tokens))}</td>
                <td className="num">{fmtMoney(sum((c) => c.cost_usd))}</td>
                <td className="num">{fmtSeconds(sum((c) => c.latency_s))}</td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </Panel>
  );
}
