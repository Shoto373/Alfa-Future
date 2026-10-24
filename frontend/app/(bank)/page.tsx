"use client";

import Link from "next/link";
import Gauge from "@/components/home/Gauge";
import HomeHero, { type TopicRow } from "@/components/home/HomeHero";
import { EmptyState, Icon, OriginTag, Score, Skeleton } from "@/components/ui";
import { date, IMPORTANT_SCORE as IMPORTANT } from "@/lib/format";
import { useFeedWithTopics } from "@/lib/hooks";
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
  const top5 = items.slice(0, 5);
  const level = top5.length ? top5.reduce((a, i) => a + i.relevance.score, 0) / top5.length : 0;
  const levelText = level >= 70 ? "Требует внимания" : level >= 45 ? "Умеренный фон" : "Спокойный фон";

  return (
    <div className={common.page}>
      <HomeHero feed={feed} total={total} topics={topics} userId={session!.user.user_id} />

      <div className={styles.tabs} role="tablist" aria-label="Разделы главной">
        <span className={`${styles.tab} ${styles.on}`} role="tab" aria-selected="true">Сводка</span>
        <Link href="/pulse" className={styles.tab} role="tab" aria-selected="false">Лента Пульса</Link>
        <Link href="/pulse/analytics" className={`${styles.tab} ${common.hideSm}`} role="tab" aria-selected="false">Аналитика банка</Link>
      </div>

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
                  {it.relevance.reasons[0] && <span className={styles.topReason}>{it.relevance.reasons[0].text}</span>}
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
          <p className={`${common.muted} ${common.small} ${common.center}`}>Средняя релевантность топ-5 новостей для компании и роли: {Math.round(level)} из 100</p>
        </section>

        <Link href="/pulse" className={styles.story}>
          <strong>Как читать разбор</strong>
          <span className={styles.storyLead}>У каждого вывода видно, откуда он взят</span>
          <span className={styles.storyLegend}>
            {["fact", "client_data", "bank", "ai"].map((o) => <OriginTag key={o} origin={o} />)}
          </span>
          <span className={styles.storyCta}>Открыть ленту <Icon name="chevronRight" size={16} /></span>
        </Link>
      </div>
    </div>
  );
}
