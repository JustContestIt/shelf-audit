import type { TimelineItem } from '../lib/timeline';
import { fmtSeconds, fmtTime } from '../lib/format';
import { Spinner } from './ui';

const STATE_TEXT: Record<TimelineItem['state'], string> = {
  done: 'выполнено',
  current: 'выполняется',
  waiting: 'ожидает решения',
  pending: 'впереди',
};

function Marker({ item, n }: { item: TimelineItem; n: number }) {
  if (item.state === 'done') return <span aria-hidden="true">✓</span>;
  if (item.state === 'current') return <Spinner label="Выполняется" />;
  if (item.state === 'waiting') return <span aria-hidden="true">⏸</span>;
  return <span aria-hidden="true">{n}</span>;
}

/** Vertical timeline over the graph nodes; repeats (after a retake) are listed as they came. */
export function ProgressTimeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol className="timeline" aria-label="Ход обработки">
      {items.map((it, i) => (
        <li key={it.key} className={`tl-${it.state}`} aria-current={it.state === 'current' ? 'step' : undefined}>
          <span className="tl-marker">
            <Marker item={it} n={i + 1} />
          </span>
          <div className="tl-body">
            <div className="tl-title">
              <span className="tl-label">{it.label}</span>
              <span className="visually-hidden">— {STATE_TEXT[it.state]}</span>
              <span className="tl-node">{it.node}</span>
              {it.at && (
                <span className="tl-time">
                  {fmtTime(it.at)}
                  {it.durationS != null && it.durationS >= 0.05 ? ` · +${fmtSeconds(it.durationS)}` : ''}
                </span>
              )}
            </div>
            {it.info && <div className="tl-info">{it.info}</div>}
            {it.state === 'waiting' && <div className="tl-info">Ждёт решения: утвердить, исправить или переснять</div>}
          </div>
        </li>
      ))}
    </ol>
  );
}
