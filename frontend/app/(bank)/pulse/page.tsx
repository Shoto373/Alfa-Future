"use client";

import { useEffect, useState } from "react";
import AddNews from "@/components/AddNews";
import NewsCard from "@/components/NewsCard";
import { Card, ErrorBox, Icon, Loading } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useFeedWithTopics } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { TopicCount } from "@/lib/types";

const TOPICS_SHOWN = 10;

export default function PulsePage() {
  const { session } = useSession();
  const [topic, setTopic] = useState<string | undefined>();
  const page = useFeedWithTopics(session!.companyId, topic);
  const feed = { ...page, data: page.data?.items ?? null };
  const [refreshing, setRefreshing] = useState(false);
  const [allTopics, setAllTopics] = useState(false);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

  useEffect(() => setTopic(undefined), [session!.companyId]);
  // Переход с главной по теме: /pulse?topic=key_rate.
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("topic");
    if (t) setTopic(t);
  }, []);

  // Только темы, по которым у компании есть новости; первые 10 видны сразу, остальные — по кнопке.
  // Счетчики приходят с сервером и не меняются при выборе темы, поэтому список не «прыгает».
  const [topics, setTopics] = useState<TopicCount[]>([]);
  useEffect(() => { if (page.data) setTopics(page.data.topic_counts); }, [page.data]);
  useEffect(() => setTopics([]), [session!.companyId]);
  const visibleTopics = allTopics ? topics : topics.filter((t, i) => i < TOPICS_SHOWN || t.topic === topic);
  const hiddenCount = topics.length - topics.filter((t, i) => i < TOPICS_SHOWN || t.topic === topic).length;

  const refresh = async () => {
    setRefreshing(true);
    setRefreshNote(null);
    try {
      const r = await api.refreshNews();
      const failed = r.sources.filter((s) => s.error).map((s) => s.name);
      setRefreshNote(`Новых: ${r.added}, дубликатов: ${r.duplicates}${failed.length ? `. Недоступны: ${failed.join(", ")}` : ""}`);
      feed.reload();
    } catch (e) {
      setRefreshNote(e instanceof ApiError ? e.message : "Не удалось обновить ленту");
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="eyebrow"><Icon name="spark" /> Альфа.Пульс</span>
          <h1>Лента {session!.companyName}</h1>
        </div>
        <button className="btn btn-white" onClick={refresh} disabled={refreshing}>
          <Icon name="refresh" /> {refreshing ? "Собираем новости…" : "Обновить из RSS"}
        </button>
      </div>
      {refreshNote && <p className="muted small">{refreshNote}</p>}

      <div className="feed-top">
        <section className="card topics-card">
          <h2>Темы</h2>
          <div className="chips" role="toolbar" aria-label="Фильтр по темам">
            <button className={!topic ? "chip on" : "chip"} onClick={() => setTopic(undefined)}>Все темы</button>
            {visibleTopics.map((t) => (
              <button key={t.topic} className={topic === t.topic ? "chip on" : "chip"} onClick={() => setTopic(t.topic)}>
                {t.name} <span className="chip-count">{t.count}</span>
              </button>
            ))}
            {hiddenCount > 0 && (
              <button className="chip chip-more" onClick={() => setAllTopics((v) => !v)} aria-expanded={allTopics}>
                {allTopics ? "Свернуть" : `Ещё ${hiddenCount}`}
              </button>
            )}
          </div>
        </section>
        <div id="add-news" className="anchor"><AddNews onAdded={feed.reload} compact /></div>
      </div>

      <div className="feed">
        {feed.loading && <Loading text="Подбираем новости под компанию…" />}
        {feed.error && <ErrorBox message={feed.error.message} onRetry={feed.reload} />}
        {feed.data?.length === 0 && <Card><p>По этой теме новостей нет. Выберите другую тему или добавьте новость.</p></Card>}
        {feed.data?.map((item) => <NewsCard key={item.news.news_id} item={item} />)}
      </div>
    </div>
  );
}
