"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorBox, Icon, OriginTag, Score, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { date, IMPORTANT_SCORE as IMPORTANT } from "@/lib/format";
import { useFeed } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { BankDocument, FeedItem } from "@/lib/types";

function plural(n: number, forms: [string, string, string]) {
  const m10 = n % 10, m100 = n % 100;
  return forms[m10 === 1 && m100 !== 11 ? 0 : m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? 1 : 2];
}

function topicCounts(items: FeedItem[]) {
  const map = new Map<string, { topic: string; name: string; total: number; important: number }>();
  for (const it of items) {
    for (const t of it.news.topics) {
      const row = map.get(t.topic) ?? { topic: t.topic, name: t.name, total: 0, important: 0 };
      row.total += 1;
      if (it.relevance.score >= IMPORTANT) row.important += 1;
      map.set(t.topic, row);
    }
  }
  return [...map.values()].sort((a, b) => b.important - a.important || b.total - a.total);
}

/** Полукруглый индикатор, как «Индикатор риска» на главной Альфа-Бизнеса. */
function Gauge({ value }: { value: number }) {
  const angle = Math.PI * (1 - Math.max(0, Math.min(100, value)) / 100);
  const x = 100 + 80 * Math.cos(angle), y = 100 - 80 * Math.sin(angle);
  return (
    <svg viewBox="0 0 200 112" className="gauge" aria-hidden="true">
      <defs>
        <linearGradient id="g-arc" x1="0" x2="1">
          <stop offset="0" stopColor="#21a038" /><stop offset=".55" stopColor="#ffb800" /><stop offset="1" stopColor="#ef3124" />
        </linearGradient>
      </defs>
      <path d="M20 100a80 80 0 0 1 160 0" fill="none" stroke="#eceef1" strokeWidth="10" strokeLinecap="round" />
      <path d="M20 100a80 80 0 0 1 160 0" fill="none" stroke="url(#g-arc)" strokeWidth="10" strokeLinecap="round"
        strokeDasharray={`${(Math.PI * 80 * value) / 100} 999`} />
      <circle cx={x} cy={y} r="8" fill="#fff" stroke="#0b1f35" strokeWidth="3" />
    </svg>
  );
}

export default function HomePage() {
  const { session } = useSession();
  const feed = useFeed(session!.companyId);
  const items = feed.data ?? [];
  const important = items.filter((i) => i.relevance.score >= IMPORTANT);
  const topics = topicCounts(items).slice(0, 7);
  const top5 = items.slice(0, 5);
  const level = top5.length ? top5.reduce((a, i) => a + i.relevance.score, 0) / top5.length : 0;
  const levelText = level >= 70 ? "Требует внимания" : level >= 45 ? "Умеренный фон" : "Спокойный фон";

  const [latest, setLatest] = useState<BankDocument | null>(null);
  const [bannerClosed, setBannerClosed] = useState(false);

  // Самый свежий актуальный материал банка — для зеленого баннера «НОВОЕ».
  useEffect(() => {
    api.analytics()
      .then((r) => setLatest([...r.documents].filter((d) => !d.stale).sort((a, b) => b.date.localeCompare(a.date))[0] ?? null))
      .catch(() => setLatest(null));
  }, []);

  return (
    <div className="page home">
      <section className="hero" aria-label="Альфа.Пульс на главной">
        <div className="hero-main">
          <span className="hero-label">Альфа.Пульс</span>
          {feed.loading ? <Skeleton lines={2} /> : (
            <>
              <p className="hero-amount">
                {important.length} {plural(important.length, ["событие", "события", "событий"])} для вас
              </p>
            </>
          )}
          {feed.error && <ErrorBox message={feed.error.message} onRetry={feed.reload} />}
          <div className="hero-topics">
            {topics.slice(0, 3).map((t) => <span key={t.topic}>{t.name}</span>)}
            {topics.length > 3 && <span className="hero-more">+{topics.length - 3}</span>}
          </div>
          {latest && !bannerClosed && (
            <div className="hero-banner">
              <span className="hero-banner-dot"><Icon name="plus" size={14} /></span>
              <Link href="/pulse/analytics" title={latest.title}>Новая аналитика: <strong>{latest.title}</strong></Link>
              <span className="badge-green">НОВОЕ</span>
              <button className="icon-btn" onClick={() => setBannerClosed(true)} aria-label="Скрыть"><Icon name="close" size={16} /></button>
            </div>
          )}
          <div className="hero-tiles">
            <Link href="/pulse" className="hero-tile">
              <span className="hero-tile-icon"><Icon name="list" /></span>
              <span><strong>Открыть ленту</strong><small>{items.length} новостей с причинами отбора</small></span>
            </Link>
            <Link href="/pulse/analytics" className="hero-tile">
              <span className="hero-tile-icon"><Icon name="doc" /></span>
              <span><strong>Аналитика банка</strong><small>Тезисы ЦМА и Альфа-КИБ</small></span>
            </Link>
          </div>
        </div>

        <div className="hero-list">
          <h2>Пульс по темам</h2>
          {feed.loading && <Skeleton lines={5} />}
          <ul>
            {topics.map((t) => (
              <li key={t.topic}>
                <Link href={{ pathname: "/pulse", query: { topic: t.topic } }}>
                  <span>{t.name}</span>
                  <span className={`count ${t.important ? "count-red" : ""}`} title={t.important ? "Важных событий" : "Новостей"}>
                    {t.important || t.total}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>

        <Link href="/pulse" className="hero-promo">
          <strong>AI-аналитик для руководителя</strong>
          <span>Что произошло, почему это важно именно вам, риски, возможности и позиция Альфа-Банка</span>
          <svg viewBox="0 0 240 120" className="promo-art" aria-hidden="true">
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

      <div className="tabs" role="tablist" aria-label="Разделы главной">
        <span className="tab on" role="tab" aria-selected="true">Сводка</span>
        <Link href="/pulse" className="tab" role="tab" aria-selected="false">Лента Пульса</Link>
        <Link href="/pulse/analytics" className="tab hide-sm" role="tab" aria-selected="false">Аналитика банка</Link>
      </div>

      <div className="home-grid">
        <section className="card top-news">
          <header className="card-head">
            <h2>Главное для вас {important.length > 0 && <span className="count">{important.length}</span>}</h2>
          </header>
          {feed.loading && <Skeleton lines={5} />}
          {items.length === 0 && !feed.loading && !feed.error && <p className="muted">Пока нет новостей. Добавьте новость в ленте.</p>}
          <ul className="top-list">
            {items.slice(0, 3).map((it) => (
              <li key={it.news.news_id} className="news-card compact">
                <Link href={`/pulse/n/${encodeURIComponent(it.news.news_id)}`}>
                  <span className="top-title">{it.news.title}</span>
                  <span className="top-meta">{it.news.source} · {date(it.news.published_at)}</span>
                  {it.relevance.reasons[0] && <span className="top-reason">{it.relevance.reasons[0].text}</span>}
                </Link>
                <Score value={it.relevance.score} />
              </li>
            ))}
          </ul>
        </section>

        <section className="card gauge-card">
          <header className="card-head">
            <h2>Новостной фон</h2>
          </header>
          <Gauge value={level} />
          <p className="gauge-value">{feed.loading ? "…" : levelText}</p>
          <p className="muted small center">Средняя релевантность топ-5 новостей для компании и роли: {Math.round(level)} из 100</p>
        </section>

        <Link href="/pulse" className="story">
          <strong>Как читать разбор</strong>
          <span className="story-lead">У каждого вывода видно, откуда он взят</span>
          <span className="story-legend">
            {["fact", "client_data", "bank", "ai"].map((o) => <OriginTag key={o} origin={o} />)}
          </span>
          <span className="story-cta">Открыть ленту <Icon name="chevronRight" size={16} /></span>
        </Link>
      </div>
    </div>
  );
}
