import Link from "next/link";
import { date } from "@/lib/format";
import type { FeedItem } from "@/lib/types";
import { Score } from "./ui";
import styles from "@/components/NewsCard.module.scss";
import common from "@/styles/common.module.scss";

const REASON_STYLES: Record<string, string | undefined> = {
  sector_model: styles.reasonSectorModel,
  payments: styles.reasonPayments,
  user: styles.reasonUser,
};

export default function NewsCard({ item, compact = false }: { item: FeedItem; compact?: boolean }) {
  const { news, relevance } = item;
  return (
    <article className={`${styles.newsCard} ${compact ? styles.compact : ""}`} data-testid="news-card">
      <div className={styles.newsMeta}>
        <Score value={relevance.score} />
        <span>{news.source}</span>
        <span>·</span>
        <span>{date(news.published_at)}</span>
        {news.kind === "user" && <span className={styles.kind}>Добавлено вами</span>}
        {news.duplicates > 0 && <span className={styles.kind}>+{news.duplicates} источн.</span>}
      </div>
      <h3><Link href={`/pulse/n/${encodeURIComponent(news.news_id)}`}>{news.title}</Link></h3>
      {!compact && <p className={styles.lead}>{news.lead}</p>}
      <div className={styles.reasons} aria-label="Почему эта новость важна для вас">
        {relevance.reasons.slice(0, compact ? 2 : 4).map((r, i) => (
          <span key={i} className={`${styles.reason} ${REASON_STYLES[r.origin] ?? ""}`} title={r.text}>{r.text}</span>
        ))}
      </div>
      {!compact && (
        <div className={styles.newsFoot}>
          <div className={common.tags}>{news.topics.map((t) => <span key={t.topic} className={common.tag}>{t.name}</span>)}</div>
          <Link className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`} href={`/pulse/n/${encodeURIComponent(news.news_id)}`}>
            {item.cached_insight_id ? "Открыть разбор" : "Разобрать для компании"}
          </Link>
        </div>
      )}
    </article>
  );
}
