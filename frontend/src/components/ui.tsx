import type { ReactNode } from 'react';
import { statusLabel, statusTone, type Tone } from '../lib/status';

export function Spinner({ label = 'Загрузка' }: { label?: string }) {
  return <span className="spinner" role="status" aria-label={label} />;
}

export function Loading({ text = 'Загрузка…' }: { text?: string }) {
  return (
    <div className="loading" aria-live="polite">
      <Spinner /> {text}
    </div>
  );
}

export function Badge({ tone = 'neutral', children, large }: { tone?: Tone; children: ReactNode; large?: boolean }) {
  return <span className={`badge tone-${tone}${large ? ' badge-lg' : ''}`}>{children}</span>;
}

const STATUS_ICON: Record<Tone, string> = { ok: '✓', warn: '●', danger: '✕', info: '↻', neutral: '•' };

/** Status badge: Russian label + an icon, so the colour is never the only signal. */
export function StatusBadge({ status, large }: { status: string | null | undefined; large?: boolean }) {
  const tone = statusTone(status);
  return (
    <Badge tone={tone} large={large}>
      <span aria-hidden="true">{STATUS_ICON[tone]}</span>
      {statusLabel(status)}
    </Badge>
  );
}

export function Alert({
  tone = 'danger',
  title,
  children,
}: {
  tone?: Tone;
  title?: ReactNode;
  children?: ReactNode;
}) {
  const icon = tone === 'danger' ? '!' : tone === 'warn' ? '⚠' : tone === 'ok' ? '✓' : 'i';
  return (
    <div className={`alert tone-${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
      <span className="alert-icon" aria-hidden="true">
        {icon}
      </span>
      <div>
        {title && <div className="alert-title">{title}</div>}
        {children}
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

/** Collapsible panel on top of <details>/<summary> (keyboard accessible out of the box). */
export function Panel({
  title,
  meta,
  children,
  defaultOpen,
}: {
  title: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details className="panel" open={defaultOpen}>
      <summary>
        <span>{title}</span>
        {meta != null && <span className="panel-meta">{meta}</span>}
      </summary>
      <div className="panel-body">{children}</div>
    </details>
  );
}

export function JsonBlock({ value }: { value: unknown }) {
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}
