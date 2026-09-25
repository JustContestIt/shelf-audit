export function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="7" fill="var(--primary)" />
      <g fill="none" stroke="var(--primary-contrast)" strokeWidth="2.2" strokeLinecap="round">
        <path d="M6 11h20M6 21h20" />
        <rect x="8" y="5" width="4" height="6" rx="1" />
        <rect x="14" y="6" width="4" height="5" rx="1" />
        <rect x="9" y="15" width="4" height="6" rx="1" />
        <rect x="17" y="14" width="5" height="7" rx="1" strokeDasharray="2 1.6" />
      </g>
    </svg>
  );
}
