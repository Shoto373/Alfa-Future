import type { CSSProperties, ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { ORIGIN_LABEL } from "@/lib/format";
import styles from "@/components/ui.module.scss";
import common from "@/styles/common.module.scss";

export { AlfaMark, Icon } from "./icons";

const TILE_COLORS = [styles.tileLime, styles.tileSky, styles.tileAmber, styles.tileViolet, styles.tileMint, styles.tilePink];
const ORIGIN_STYLES: Record<string, string | undefined> = {
  fact: styles.originFact,
  client_data: styles.originClientData,
  bank: styles.originBank,
  ai: styles.originAi,
  rules: styles.originRules,
};

/** Плитка-логотип организации, как в переключателе компаний Альфа-Бизнеса. */
export function CompanyTile({ id, name, size = 40 }: { id: string; name: string; size?: number }) {
  const hash = [...id].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) >>> 0, 7);
  const letter = (name.replace(/^(ООО|АО|ПАО|Компания)\s*[«"№]?/i, "").trim()[0] ?? "К").toUpperCase();
  return (
    <span className={`${styles.companyTile} ${TILE_COLORS[hash % TILE_COLORS.length]}`} style={{ "--tile-size": `${size}px` } as CSSProperties}>
      {/\d/.test(letter) ? "№" : letter}
    </span>
  );
}

export function OriginTag({ origin }: { origin: string }) {
  return <span className={`${styles.origin} ${ORIGIN_STYLES[origin] ?? ""}`}>{ORIGIN_LABEL[origin] ?? origin}</span>;
}

// Метка понятна без подсказки: стрелка показывает направление, текст — что это значит для компании.
const EFFECTS: Record<string, { label: string; icon: string; className?: string }> = {
  neg: { label: "Риск для компании", icon: "↓", className: styles.effectNeg },
  pos: { label: "Выгода для компании", icon: "↑", className: styles.effectPos },
  mixed: { label: "Есть риски и выгоды для компании", icon: "↕", className: styles.effectMixed },
  unclear: { label: "Зависит от операций компании", icon: "?", className: styles.effectUnclear },
};

// Итог разбора для компании по готовому разбору; без влияния на бизнес или без разбора — не показывается.
export function EffectBadge({ effect, className = "" }: { effect?: string | null; className?: string }) {
  const e = effect ? EFFECTS[effect] : undefined;
  if (!e) return null;
  return (
    <span className={`${styles.effect} ${e.className ?? ""} ${className}`}
      title="Итог разбора для вашей компании: риски и выгоды подробно — в разделе «Какие последствия возможны»">
      <span aria-hidden="true">{e.icon}</span>{e.label}
    </span>
  );
}

export function Score({ value }: { value: number }) {
  const level = value >= 70 ? styles.scoreHigh : value >= 40 ? styles.scoreMid : styles.scoreLow;
  return (
    <span className={`${styles.score} ${level}`} title="Релевантность для компании и роли, 0–100">
      <span className={styles.scoreBar}><span style={{ "--score-width": `${Math.max(4, Math.min(100, value))}%` } as CSSProperties} /></span>
      {Math.round(value)}
    </span>
  );
}

export function Card({ title, children, actions, className = "" }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`${common.card} ${className}`}>
      {(title || actions) && (
        <header className={common.cardHead}>
          {title && <h2>{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

/** Ошибка загрузки или действия. Текст — понятный по коду ошибки сервера; «Повторить» — только если
 *  повтор может помочь (retryable): при «нет прав» или «неверный пароль» кнопка бесполезна. */
export function ErrorState({ error, onRetry, fallback }: { error: unknown; onRetry?: () => void; fallback?: string }) {
  const text = typeof error === "string" ? error : errorText(error, fallback);
  const retry = onRetry && !(error instanceof ApiError && !error.retryable);
  return (
    <div className={styles.errorBox} role="alert">
      <span>{text}</span>
      {retry && <button type="button" className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} onClick={onRetry}>Повторить</button>}
    </div>
  );
}

/** Пустой список или результат: одинаково на всех страницах. */
export function EmptyState({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <p className={`${common.muted} ${className}`}>{children}</p>;
}

export function Loading({ text }: { text: string }) {
  return <div className={styles.loading} role="status"><span className={styles.spinner} aria-hidden="true" /> {text}</div>;
}

/** Заглушка на время загрузки: полоски видны глазам, экранный диктор слышит «Загрузка». */
export function Skeleton({ lines = 3, label = "Загрузка" }: { lines?: number; label?: string }) {
  return (
    <div className={styles.skeleton} role="status" aria-label={label}>
      {Array.from({ length: lines }).map((_, i) => <span key={i} aria-hidden="true" style={{ "--line-width": `${90 - i * 12}%` } as CSSProperties} />)}
    </div>
  );
}
