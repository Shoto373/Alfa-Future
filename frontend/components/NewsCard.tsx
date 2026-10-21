import Link from "next/link";
import { date } from "@/lib/format";
import type { FeedItem } from "@/lib/types";
import { Score } from "./ui";

const KIND: Record<string, string> = { seed: "Демо-лента", rss: "RSS", user: "Добавлено вами", external: "Внешний источник" };

export default function NewsCard({ item, compact = false }: { item: FeedItem; compact?: boolean }) {
  const { news, relevance } = item;
  return (
    <article className={`news-card ${compact ? "compact" : ""}`}>
      <div className="news-meta">
        <Score value={relevance.score} />
        <span>{news.source}</span>
        <span>·</span>
        <span>{date(news.published_at)}</span>
        <span className="kind">{KIND[news.kind] ?? news.kind}</span>
        {news.duplicates > 0 && <span className="kind">+{news.duplicates} источн.</span>}
      </div>
      <h3><Link href={`/pulse/n/${encodeURIComponent(news.news_id)}`}>{news.title}</Link></h3>
      {!compact && <p className="lead">{news.lead}</p>}
      <div className="reasons" aria-label="Почему эта новость важна для вас">
        {relevance.reasons.slice(0, compact ? 2 : 4).map((r, i) => (
          <span key={i} className={`reason reason-${r.origin}`} title={r.text}>{r.text}</span>
        ))}
      </div>
      {!compact && (
        <div className="news-foot">
          <div className="tags">{news.topics.map((t) => <span key={t.topic} className="tag">{t.name}</span>)}</div>
          <Link className="btn btn-primary btn-sm" href={`/pulse/n/${encodeURIComponent(news.news_id)}`}>
            {item.cached_insight_id ? "Открыть разбор" : "Разобрать для компании"}
          </Link>
        </div>
      )}
    </article>
  );
}
