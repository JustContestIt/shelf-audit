import type { ReportData } from '../api/types';
import { fmtInt, fmtMoney, fmtPercent, fmtSeconds } from '../lib/format';

function Stat({ label, value, warn, note }: { label: string; value: string; warn?: boolean; note?: string }) {
  return (
    <div className={`stat${warn ? ' is-warn' : ''}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {note && (
        <div className="stat-note">
          <span aria-hidden="true">⚠ </span>
          {note}
        </div>
      )}
    </div>
  );
}

export function SummaryCards({ report }: { report: ReportData }) {
  return (
    <div className="stats" aria-label="Итоги отчёта">
      <Stat label="Единиц в счёте" value={fmtInt(report.total_units)} />
      <Stat label="Полок" value={fmtInt(report.shelves)} />
      <Stat
        label="На проверку"
        value={fmtInt(report.needs_review_units)}
        warn={report.needs_review_units > 0}
        note={report.needs_review_units > 0 ? 'есть сомнения' : undefined}
      />
      <Stat
        label="Не опознано"
        value={fmtInt(report.unknown_units)}
        warn={report.unknown_units > 0}
        note={report.unknown_units > 0 ? 'подвид неизвестен' : undefined}
      />
      <Stat label="Чужих (не в счёте)" value={fmtInt(report.foreign_units)} />
      <Stat label="Стоимость" value={fmtMoney(report.cost_usd)} />
      <Stat label="Время модели" value={fmtSeconds(report.latency_s)} />
      <Stat
        label="Уверенность"
        value={fmtPercent(report.overall_confidence)}
        warn={report.low_confidence}
        note={report.low_confidence ? 'низкая уверенность' : undefined}
      />
    </div>
  );
}

export function FlagsList({ flags }: { flags: string[] }) {
  if (!flags.length) return null;
  return (
    <div>
      <h3 style={{ marginBottom: 8 }}>Флаги</h3>
      <ul className="flags">
        {flags.map((f, i) => (
          <li key={i}>
            <span aria-hidden="true">⚑</span>
            {f}
          </li>
        ))}
      </ul>
    </div>
  );
}
