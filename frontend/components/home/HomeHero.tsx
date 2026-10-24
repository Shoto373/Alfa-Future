"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Load } from "@/lib/hooks";
import type { BankDocument, FeedItem } from "@/lib/types";
import { ErrorState, Icon, Skeleton } from "../ui";
import styles from "@/app/(bank)/page.module.scss";

export type TopicRow = { topic: string; name: string; total: number; important: number };

function plural(n: number, forms: [string, string, string]) {
  const m10 = n % 10, m100 = n % 100;
  return forms[m10 === 1 && m100 !== 11 ? 0 : m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? 1 : 2];
}

/** Верхний блок главной Альфа-Бизнеса: заметная точка входа в Альфа.Пульс — число событий, темы, свежая аналитика банка. */
export default function HomeHero({ feed, important, topics }: { feed: Load<FeedItem[]>; important: number; topics: TopicRow[] }) {
  const items = feed.data ?? [];
  const [latest, setLatest] = useState<BankDocument | null>(null);
  const [bannerClosed, setBannerClosed] = useState(false);

  // Самый свежий актуальный материал банка — для зеленого баннера «НОВОЕ».
  useEffect(() => {
    api.analytics()
      .then((r) => setLatest([...r.documents].filter((d) => !d.stale).sort((a, b) => b.date.localeCompare(a.date))[0] ?? null))
      .catch(() => setLatest(null));
  }, []);

  return (
      <section className={styles.hero} aria-label="Альфа.Пульс на главной">
        <div className={styles.heroMain}>
          <span className={styles.heroLabel}>Альфа.Пульс</span>
          {feed.loading ? <Skeleton lines={2} /> : (
            <>
              <p className={styles.heroAmount}>
                {important} {plural(important, ["событие", "события", "событий"])} для вас
              </p>
            </>
          )}
          {feed.error && <ErrorState error={feed.error} onRetry={feed.reload} />}
          <div className={styles.heroTopics}>
            {topics.slice(0, 3).map((t) => <span key={t.topic}>{t.name}</span>)}
            {topics.length > 3 && <span className={styles.heroMore}>+{topics.length - 3}</span>}
          </div>
          {latest && !bannerClosed && (
            <div className={styles.heroBanner}>
              <span className={styles.heroBannerDot}><Icon name="plus" size={14} /></span>
              <Link href="/pulse/analytics" title={latest.title}>Новая аналитика: <strong>{latest.title}</strong></Link>
              <span className={styles.badgeGreen}>НОВОЕ</span>
              <button className={styles.iconBtn} onClick={() => setBannerClosed(true)} aria-label="Скрыть"><Icon name="close" size={16} /></button>
            </div>
          )}
          <div className={styles.heroTiles}>
            <Link href="/pulse" className={styles.heroTile}>
              <span className={styles.heroTileIcon}><Icon name="list" /></span>
              <span><strong>Открыть ленту</strong><small>{items.length} новостей с причинами отбора</small></span>
            </Link>
            <Link href="/pulse/analytics" className={styles.heroTile}>
              <span className={styles.heroTileIcon}><Icon name="doc" /></span>
              <span><strong>Аналитика банка</strong><small>Тезисы ЦМА и Альфа-КИБ</small></span>
            </Link>
          </div>
        </div>

        <div className={styles.heroList}>
          <h2>Пульс по темам</h2>
          {feed.loading && <Skeleton lines={5} />}
          <ul>
            {topics.map((t) => (
              <li key={t.topic}>
                <Link href={{ pathname: "/pulse", query: { topic: t.topic } }}>
                  <span>{t.name}</span>
                  <span className={`${styles.count} ${t.important ? `${styles.countRed}` : ""}`} title={t.important ? "Важных событий" : "Новостей"}>
                    {t.important || t.total}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>

        <Link href="/pulse" className={styles.heroPromo}>
          <strong>AI-аналитик для руководителя</strong>
          <span>Что произошло, почему это важно именно вам, риски, возможности и позиция Альфа-Банка</span>
          <svg viewBox="0 0 240 120" className={styles.promoArt} aria-hidden="true">
            <defs>
              <linearGradient id="pr-fade" gradientUnits="userSpaceOnUse" x1="0" x2="240" y1="0" y2="0">
                <stop offset="0" stopColor="#fff" stopOpacity="0" />
                <stop offset=".18" stopColor="#fff" />
                <stop offset=".82" stopColor="#fff" />
                <stop offset="1" stopColor="#fff" stopOpacity="0" />
              </linearGradient>
              <filter id="pr-glow" filterUnits="userSpaceOnUse" x="-20" y="-20" width="280" height="160">
                <feGaussianBlur stdDeviation="5" />
              </filter>
              <path id="pr-line" d="M4 72H78c4 0 6-6 9-6s5 6 9 6h6l9-44c1-4 4-4 5 0l12 66c1 4 4 4 5 0l7-34c1-3 3-3 4 0l3 12h85"
                fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </defs>
            <use href="#pr-line" stroke="#ef3124" strokeWidth="9" opacity=".75" filter="url(#pr-glow)" />
            <use href="#pr-line" stroke="#ff6a5c" strokeWidth="4.5" opacity=".9" />
            <use href="#pr-line" stroke="url(#pr-fade)" strokeWidth="2.2" />
          </svg>
        </Link>
      </section>

  );
}
