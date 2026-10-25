"use client";

import Link from "next/link";
import Gauge from "@/components/home/Gauge";
import HomeHero, { type TopicRow } from "@/components/home/HomeHero";
import { EmptyState, Icon, Score, Skeleton } from "@/components/ui";
import { date, IMPORTANT_SCORE as IMPORTANT } from "@/lib/format";
import { glow } from "@/lib/glow";
import { cardReasons } from "@/lib/reasons";
import { useFeedWithTopics } from "@/lib/hooks";
import { useRead } from "@/lib/notifications";
import { useSession } from "@/lib/session";
import type { FeedItem, TopicCount } from "@/lib/types";
import styles from "@/app/(bank)/page.module.scss";
import common from "@/styles/common.module.scss";

/** Счетчики тем — те же, что у фильтра в ленте (с сервера); важные считаются по той же ленте. */
function topicCounts(counts: TopicCount[], items: FeedItem[]): TopicRow[] {
  return counts.map((t) => ({
    ...t,
    important: items.filter((i) => i.relevance.score >= IMPORTANT && i.news.topics.some((x) => x.topic === t.topic)).length,
  }));
}

export default function HomePage() {
  const { session } = useSession();
  const page = useFeedWithTopics(session!.companyId);
  const feed = { ...page, data: page.data?.items ?? null };
  const items = feed.data ?? [];
  const total = page.data?.total ?? 0;
  const important = items.filter((i) => i.relevance.score >= IMPORTANT);
  const topics = topicCounts(page.data?.topic_counts ?? [], items).slice(0, 7);
  // Новостной фон — по еще не прочитанному: прочитанное уже учтено, и после разбора важных новостей фон спокойнее.
  const { read } = useRead(session!.user.user_id, session!.companyId);
  const top5 = items.filter((i) => !read.has(i.news.news_id)).slice(0, 5);
  const recent = items.filter((i) => read.has(i.news.news_id)).slice(0, 3);
  const level = top5.length ? top5.reduce((a, i) => a + i.relevance.score, 0) / top5.length : 0;
  const levelText = !top5.length && items.length ? "Все прочитано" : level >= 70 ? "Требует внимания" : level >= 45 ? "Умеренный фон" : "Спокойный фон";

  return (
    <div className={common.page}>
      <HomeHero feed={feed} total={total} topics={topics} userId={session!.user.user_id} />

      <h2 className={styles.summaryTitle}>Сводка</h2>

      <div className={styles.homeGrid}>
        <section className={common.card}>
          <header className={common.cardHead}>
            <h2>Главное для вас {important.length > 0 && <span className={styles.count}>{important.length}</span>}</h2>
          </header>
          {feed.loading && <Skeleton lines={5} />}
          {items.length === 0 && !feed.loading && !feed.error && <EmptyState>Пока нет новостей. Добавьте новость в ленте.</EmptyState>}
          <ul className={styles.topList} data-testid="top-news">
            {items.slice(0, 3).map((it) => (
              <li key={it.news.news_id}>
                <Link href={`/pulse/n/${encodeURIComponent(it.news.news_id)}`}>
                  <span className={styles.topTitle}>{it.news.title}</span>
                  <span className={styles.topMeta}>{it.news.source} · {date(it.news.published_at)}</span>
                  {cardReasons(it.relevance.reasons, 1).map((r) => <span key={r.text} className={styles.topReason}>{r.text}</span>)}
                </Link>
                <Score value={it.relevance.score} />
              </li>
            ))}
          </ul>
        </section>

        <section className={`${common.card} ${styles.gaugeCard}`}>
          <header className={common.cardHead}>
            <h2>Новостной фон</h2>
          </header>
          <Gauge value={level} />
          <p className={styles.gaugeValue}>{feed.loading ? "…" : levelText}</p>
          <p className={`${common.muted} ${common.small} ${common.center}`}>{top5.length ? <>Средняя релевантность {top5.length} самых важных непрочитанных новостей: {Math.round(level)} из 100</>
            : "Непрочитанных новостей нет"}</p>
        </section>

        <section className={styles.story} aria-label="Недавно прочитанное" {...glow}>
          <strong>Недавно прочитанное</strong>
          <span className={styles.storyLead}>Можно вернуться к разбору</span>
          {recent.length === 0 ? (
            <span className={styles.storyLead}>Вы пока ничего не открывали. Откройте новость в ленте, и она появится здесь.</span>
          ) : (
            <ul className={styles.quickLinks}>
              {recent.map((it) => (
                <li key={it.news.news_id}>
                  <Link href={`/pulse/n/${encodeURIComponent(it.news.news_id)}`}>
                    <span><b>{it.news.title}</b><small>{it.news.source} · {date(it.news.published_at)}</small></span>
                    <Icon name="chevronRight" size={16} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <Link href="/pulse" className={styles.storyCta}>Открыть ленту <Icon name="chevronRight" size={16} /></Link>
        </section>
      </div>
    </div>
  );
}
