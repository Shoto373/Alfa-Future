import { date } from "@/lib/format";
import type { Insight, Role } from "@/lib/types";
import { EffectBadge, Icon, Score } from "../ui";
import RoleMenu from "./RoleMenu";
import styles from "@/components/InsightView.module.scss";
import common from "@/styles/common.module.scss";

// Почему показан быстрый разбор — по полю fallback_reason разбора.
const INFO_REASONS = new Set(["disabled", "paused"]);
const FALLBACK_NOTE: Record<string, string> = {
  disabled: "AI-модель не подключена — показан проверенный быстрый разбор: данные компании и аналитика банка учтены.",
  paused: "AI временно выключен банком — показан проверенный быстрый разбор: данные компании и аналитика банка учтены.",
  budget: "Дневной лимит AI исчерпан — он обновится в 03:00 по Москве. Показан проверенный быстрый разбор: данные компании и аналитика банка учтены.",
  company_budget: "Лимит AI для вашей компании на сегодня исчерпан — он обновится в 03:00 по Москве. Показан проверенный быстрый разбор: данные компании и аналитика банка учтены.",
  unavailable: "AI-модель сейчас не отвечает. Показан проверенный быстрый разбор — можно нажать «Пересчитать» позже.",
  checks: "Выводы AI-модели не прошли проверку фактов, поэтому показан проверенный быстрый разбор.",
  unknown: "AI-версия сейчас недоступна. Показан проверенный быстрый разбор — можно нажать «Пересчитать» позже.",
};

/** Заголовок новости в шапке — ссылкой на первоисточник (если он есть). */
function NewsLink({ ins }: { ins: Insight }) {
  const news = ins.sources.find((s) => s.source_id === `news:${ins.news_id}`);
  if (!news?.url) return <p className={styles.newsTitle}>{ins.title}</p>;
  let host = "";
  try { host = new URL(news.url).hostname.replace(/^www\./, ""); } catch { /* относительная или битая ссылка */ }
  return (
    <a className={`${styles.newsTitle} ${styles.newsLink}`} href={news.url} target="_blank" rel="noreferrer">
      <span>{ins.title}</span>
      <span className={styles.newsHost}>{host || "Открыть новость"} <Icon name="link" size={14} /></span>
    </a>
  );
}

/** Шапка разбора: релевантность, метка эффекта, вывод, действия и пояснение о режиме (быстрый разбор или модель).
 *  perspective — «другой разрез»: тот же разбор глазами другой роли компании. */
export default function InsightHeader({ ins, onRefresh, refreshing, upgrading, upgradeFailed, showTrace, onToggleTrace,
  perspective, ownRole, onPerspective }: {
  ins: Insight; onRefresh: () => void; refreshing: boolean; upgrading: boolean; upgradeFailed: boolean;
  showTrace: boolean; onToggleTrace: () => void;
  perspective?: Role; ownRole?: Role; onPerspective?: (role: Role) => void;
}) {
  return (
    <div className={styles.insightHead} data-testid="insight-header">
      <div className={styles.insightBadges}>
        <Score value={ins.relevance.score} />
        <EffectBadge effect={ins.effect} />
      </div>
      <NewsLink ins={ins} />
      <h1>{ins.headline}</h1>
      <div className={styles.insightActions}>
        <button type="button" className={`${common.btn} ${styles.btnSecondary} ${common.btnSm}`} onClick={onRefresh} disabled={refreshing || upgrading}>
          <Icon name="refresh" size={16} /> {refreshing ? "Пересчитываем…" : "Пересчитать"}
        </button>
        <button type="button" className={`${common.btn} ${styles.btnSecondary} ${common.btnSm}`} onClick={onToggleTrace} aria-expanded={showTrace}>
          {showTrace ? "Скрыть ход анализа" : "Как получен вывод"}
        </button>
        {onPerspective && perspective && (
          <RoleMenu value={perspective} own={ownRole} disabled={refreshing || upgrading} onChange={onPerspective} />
        )}
        <span className={`${styles.muted} ${common.small}`}>{date(ins.created_at)}</span>
      </div>
      {upgrading && (
        <p className={styles.upgradeNote} role="status">
          Это быстрый разбор: данные компании и аналитика банка уже учтены. AI-модель дополняет выводы — карточка обновится сама.
        </p>
      )}
      {!upgrading && upgradeFailed && ins.mode === "rules" && (
        // Модель не подключена или выключена банком — штатный режим, не сбой: без предупреждающего оформления.
        <p className={`${styles.upgradeNote} ${INFO_REASONS.has(ins.fallback_reason ?? "") ? styles.upgradeNoteInfo : styles.upgradeNoteWarn}`} role="status">
          {FALLBACK_NOTE[ins.fallback_reason ?? ""] ?? FALLBACK_NOTE.unknown}
        </p>
      )}
    </div>
  );
}
