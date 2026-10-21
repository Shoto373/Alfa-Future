import type { ReactNode } from "react";
import { ORIGIN_LABEL } from "@/lib/format";

const PATHS: Record<string, string> = {
  home: "M3 11 12 4l9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  pulse: "M3 12h4l2-6 4 12 2-6h6",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  check: "M4 12l5 5L20 6",
  wallet: "M3 7h18v12H3zM3 7l3-3h12l3 3M16 13h2",
  send: "M3 12 21 4l-6 17-3-7z",
  credit: "M3 6h18v12H3zM3 10h18",
  globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18",
  menu: "M4 7h16M4 12h16M4 17h16",
  logout: "M15 12H4M8 8l-4 4 4 4M13 4h6v16h-6",
  chevron: "M7 10l5 5 5-5",
  refresh: "M20 11a8 8 0 1 0-2 5.5M20 5v6h-6",
  plus: "M12 5v14M5 12h14",
  up: "M7 14l5-5 5 5",
  thumbUp: "M7 11v9H4v-9zM7 11l4-7a2 2 0 0 1 2 2v4h5a2 2 0 0 1 2 2l-2 7H7",
  thumbDown: "M7 13V4H4v9zM7 13l4 7a2 2 0 0 0 2-2v-4h5a2 2 0 0 0 2-2l-2-7H7",
  link: "M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1",
  spark: "M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z",
};

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="icon">
      <path d={PATHS[name] ?? PATHS.doc} />
    </svg>
  );
}

export function OriginTag({ origin }: { origin: string }) {
  return <span className={`origin origin-${origin}`}>{ORIGIN_LABEL[origin] ?? origin}</span>;
}

export function Score({ value }: { value: number }) {
  const level = value >= 70 ? "high" : value >= 40 ? "mid" : "low";
  return (
    <span className={`score score-${level}`} title="Релевантность для компании и роли, 0–100">
      <span className="score-bar"><span style={{ width: `${Math.max(4, Math.min(100, value))}%` }} /></span>
      {Math.round(value)}
    </span>
  );
}

export function Card({ title, children, actions, className = "" }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <span>{message}</span>
      {onRetry && <button className="btn btn-secondary btn-sm" onClick={onRetry}>Повторить</button>}
    </div>
  );
}

export function Loading({ text }: { text: string }) {
  return <div className="loading" role="status"><span className="spinner" /> {text}</div>;
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => <span key={i} style={{ width: `${90 - i * 12}%` }} />)}
    </div>
  );
}
