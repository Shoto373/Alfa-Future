"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { glow } from "@/lib/glow";
import type { Load } from "@/lib/hooks";
import { ANALYTICS_SCOPE, useRead } from "@/lib/notifications";
import type { BankDocument, FeedItem } from "@/lib/types";
import { ErrorState, Icon, Skeleton } from "../ui";
import styles from "@/app/(bank)/page.module.scss";

export type TopicRow = { topic: string; name: string; count: number; important: number };

function plural(n: number, forms: [string, string, string]) {
  const m10 = n % 10, m100 = n % 100;
  return forms[m10 === 1 && m100 !== 11 ? 0 : m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? 1 : 2];
}

/** Верхний блок главной Альфа-Бизнеса: заметная точка входа в Альфа.Пульс — число событий, темы, свежая аналитика банка.
 *  total — число событий всей ленты компании (то же, что «Все темы» в ленте). */
export default function HomeHero({ feed, total, topics, userId }: {
  feed: Load<FeedItem[]>; total: number; topics: TopicRow[]; userId: string;
}) {
  const [latest, setLatest] = useState<BankDocument | null>(null);
  // Баннер исчезает, когда материал открыт (в разделе аналитики) или скрыт крестиком — и не возвращается.
  const seen = useRead(userId, ANALYTICS_SCOPE);

  // Самый свежий актуальный материал банка — для зеленого баннера «НОВОЕ».
  useEffect(() => {
    api.analytics()
      .then((r) => setLatest([...r.documents].filter((d) => !d.stale).sort((a, b) => b.date.localeCompare(a.date))[0] ?? null))
      .catch(() => setLatest(null));
  }, []);

  return (
      <section className={styles.hero} aria-label="Альфа.Пульс на главной" {...glow}>
        <div className={styles.heroMain}>
          <span className={styles.heroLabel}>Альфа.Пульс</span>
          {feed.loading ? <Skeleton lines={2} /> : (
            <>
              <p className={styles.heroAmount}>
                {total} {plural(total, ["событие", "события", "событий"])} для вас
              </p>
            </>
          )}
          {feed.error && <ErrorState error={feed.error} onRetry={feed.reload} />}
          <div className={styles.heroTopics}>
            {topics.slice(0, 3).map((t) => <span key={t.topic}>{t.name}</span>)}
            {topics.length > 3 && <span className={styles.heroMore}>+{topics.length - 3}</span>}
          </div>
          {latest && !seen.read.has(latest.doc_id) && (
            <div className={styles.heroBanner}>
              <span className={styles.heroBannerDot}><Icon name="plus" size={14} /></span>
              <Link href={`/pulse/analytics?doc=${encodeURIComponent(latest.doc_id)}`} title={latest.title}>Новая аналитика: <strong>{latest.title}</strong></Link>
              <span className={styles.badgeGreen}>НОВОЕ</span>
              <button className={styles.iconBtn} onClick={() => seen.mark([latest.doc_id])} aria-label="Скрыть"><Icon name="close" size={16} /></button>
            </div>
          )}
          <div className={styles.heroTiles}>
            <Link href="/pulse" className={styles.heroTile}>
              <span className={styles.heroTileIcon}><Icon name="list" /></span>
              <span><strong>Открыть ленту</strong><small>{total} {plural(total, ["событие", "события", "событий"])} с причинами отбора</small></span>
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
                  <span className={`${styles.count} ${t.important ? `${styles.countRed}` : ""}`}
                    title={t.important ? `Событий: ${t.count}, из них важных: ${t.important}` : `Событий: ${t.count}`}>
                    {t.count}
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
              <path id="pr-line" pathLength="100" d="M4 72H78c4 0 6-6 9-6s5 6 9 6h6l9-44c1-4 4-4 5 0l12 66c1 4 4 4 5 0l7-34c1-3 3-3 4 0l3 12h85"
                fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </defs>
            <use href="#pr-line" stroke="#ef3124" strokeWidth="9" opacity=".75" filter="url(#pr-glow)" />
            <use href="#pr-line" stroke="#ff6a5c" strokeWidth="4.5" opacity=".9" />
            <use href="#pr-line" stroke="url(#pr-fade)" strokeWidth="2.2" />
            {/* Бегущий световой импульс по линии пульса. */}
            <use href="#pr-line" stroke="#fff" strokeWidth="3" className={styles.promoRun} />
          </svg>
        </Link>
      </section>

  );
}
