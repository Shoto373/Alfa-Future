import type { ReactNode } from "react";
import { ORIGIN_LABEL } from "@/lib/format";

const PATHS: Record<string, string> = {
  home: "M3 11 12 4l9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  pulse: "M3 12h4l2-6 4 12 2-6h6",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  check: "M4 12l5 5L20 6",
  shield: "M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6zM9 12l2 2 4-4",
  wallet: "M3 7h18v12H3zM3 7l3-3h12l3 3M16 13h2",
  send: "M3 12 21 4l-6 17-3-7z",
  credit: "M3 6h18v12H3zM3 10h18",
  globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18",
  menu: "M4 7h16M4 12h16M4 17h16",
  logout: "M15 12H4M8 8l-4 4 4 4M13 4h6v16h-6",
  chevron: "M7 10l5 5 5-5",
  chevronRight: "M10 7l5 5-5 5",
  refresh: "M20 11a8 8 0 1 0-2 5.5M20 5v6h-6",
  plus: "M12 5v14M5 12h14",
  up: "M7 14l5-5 5 5",
  thumbUp: "M7 11v9H4v-9zM7 11l4-7a2 2 0 0 1 2 2v4h5a2 2 0 0 1 2 2l-2 7H7",
  thumbDown: "M7 13V4H4v9zM7 13l4 7a2 2 0 0 0 2-2v-4h5a2 2 0 0 0 2-2l-2-7H7",
  link: "M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1",
  spark: "M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z",
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM17 14v6M14 17h6",
  mail: "M3 6h18v12H3zM3 7l9 6 9-6",
  bell: "M6 16V11a6 6 0 1 1 12 0v5l2 2H4zM10 21h4",
  file: "M7 3h7l5 5v13H7zM14 3v5h5",
  list: "M5 4h14v16H5zM9 9h6M9 13h6M9 17h3",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2",
  users: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21c0-4 3-6 7-6s7 2 7 6M16 3a4 4 0 0 1 0 8M22 21c0-3-2-5-4-5.5",
  card: "M3 6h18v12H3zM3 10h18M7 15h4",
  bank: "M3 10h18M5 10v8M9 10v8M15 10v8M19 10v8M3 20h18M12 3l9 5H3z",
  settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1",
  download: "M12 4v11M7 10l5 5 5-5M5 20h14",
  upload: "M12 20V9M7 14l5-5 5 5M5 4h14",
  chat: "M4 5h16v11H9l-5 4z",
  close: "M6 6l12 12M18 6 6 18",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4",
  risk: "M12 4 2 20h20zM12 10v4M12 17v.5",
  growth: "M3 17l6-6 4 4 8-8M15 7h6v6",
  briefcase: "M3 8h18v11H3zM8 8V5h8v3",
};

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="icon">
      <path d={PATHS[name] ?? PATHS.doc} />
    </svg>
  );
}

/** Знак Альфа-Банка: белая «А» с подчеркиванием на красном. */
export function AlfaMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="alfa-mark">
      <rect width="32" height="32" rx="9" fill="#EF3124" />
      <path fill="#fff" fillRule="evenodd"
        d="M14 6.5h4.1l5.6 15h-3.9l-1.25-3.6h-5.2L12.1 21.5H8.3zm2 4.2-1.75 4.95h3.5z" />
      <rect x="8.3" y="23.4" width="15.4" height="2.6" rx=".4" fill="#fff" />
    </svg>
  );
}

const TILE_COLORS = ["#c8f560", "#7ad8ff", "#ffcf5c", "#b9a6ff", "#7ff0c4", "#ff9fb6"];

/** Плитка-логотип организации, как в переключателе компаний Альфа-Бизнеса. */
export function CompanyTile({ id, name, size = 40 }: { id: string; name: string; size?: number }) {
  const hash = [...id].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) >>> 0, 7);
  const letter = (name.replace(/^(ООО|АО|ПАО|Компания)\s*[«"№]?/i, "").trim()[0] ?? "К").toUpperCase();
  return (
    <span className="company-tile" style={{ width: size, height: size, background: TILE_COLORS[hash % TILE_COLORS.length], fontSize: size * 0.45 }}>
      {/\d/.test(letter) ? "№" : letter}
    </span>
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
