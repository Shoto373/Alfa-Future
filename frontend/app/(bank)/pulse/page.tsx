"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import AddNews from "@/components/AddNews";
import NewsCard from "@/components/NewsCard";
import { Card, ErrorState, Icon, Loading } from "@/components/ui";
import { useFeedWithTopics } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { StoryChip, TopicCount } from "@/lib/types";
import common from "@/styles/common.module.scss";
import styles from "@/app/(bank)/pulse/page.module.scss";

const TOPICS_SHOWN = 10;

export default function PulsePage() {
  return <Suspense fallback={<Loading text="Загружаем ленту…" />}><PulseFeed /></Suspense>;
}

function PulseFeed() {
  const { session } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const topic = searchParams.get("topic") || undefined;
  const story = searchParams.get("story") || undefined;
  // Тема и сюжет — взаимоисключающие фильтры: выбор одного сбрасывает другой.
  const setFilter = (key: "topic" | "story", value?: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("topic");
    params.delete("story");
    if (value) params.set(key, value);
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };
  const setTopic = (value?: string) => setFilter("topic", value);
  const setStory = (value?: string) => setFilter("story", value);
  const page = useFeedWithTopics(session!.companyId, topic, story);
  const feed = { ...page, data: page.data?.items ?? null };
  const [allTopics, setAllTopics] = useState(false);

  // Только темы, по которым у компании есть новости; первые 10 видны сразу, остальные — по кнопке.
  // Счетчики приходят с сервером и не меняются при выборе темы, поэтому список не «прыгает».
  // Пока грузится лента по новому фильтру, остаются прежние чипы этой же компании.
  const companyId = session!.companyId;
  const [chips, setChips] = useState<{ source: object; companyId: string; topics: TopicCount[]; stories: StoryChip[] } | null>(null);
  if (page.data && chips?.source !== page.data) {
    setChips({ source: page.data, companyId, topics: page.data.topic_counts, stories: page.data.stories ?? [] });
  }
  const topics = chips?.companyId === companyId ? chips.topics : [];
  const stories = chips?.companyId === companyId ? chips.stories : [];
  const visibleTopics = allTopics ? topics : topics.filter((t, i) => i < TOPICS_SHOWN || t.topic === topic);
  const hiddenCount = topics.length - topics.filter((t, i) => i < TOPICS_SHOWN || t.topic === topic).length;

  return (
    <div className={common.page}>
      <div className={common.pageHead}>
        <div>
          <span className={common.eyebrow}><Icon name="spark" /> Альфа.Пульс</span>
          <h1>Лента {session!.companyName}</h1>
        </div>
      </div>

      <div className={styles.feedTop}>
        <section className={`${common.card} ${styles.topicsCard}`}>
          {stories.length > 0 && (
            <>
              <h2>Сюжеты</h2>
              <div className={`${styles.chips} ${styles.storyChips}`} role="toolbar" aria-label="Фильтр по сюжетам">
                {stories.map((s) => (
                  <button key={s.story_id} className={story === s.story_id ? `${styles.chip} ${styles.on}` : styles.chip}
                    aria-pressed={story === s.story_id} onClick={() => setStory(story === s.story_id ? undefined : s.story_id)}
                    title={`Одно событие: ${s.size} сообщений разных источников`}>
                    {s.label} <span className={styles.chipCount}>{s.size}</span>
                  </button>
                ))}
              </div>
            </>
          )}
          <h2>Темы</h2>
          <div className={styles.chips} role="toolbar" aria-label="Фильтр по темам">
            <button className={!topic && !story ? `${styles.chip} ${styles.on}` : styles.chip} aria-pressed={!topic && !story} onClick={() => setTopic(undefined)}>Все темы</button>
            {visibleTopics.map((t) => (
              <button key={t.topic} className={topic === t.topic ? `${styles.chip} ${styles.on}` : styles.chip} aria-pressed={topic === t.topic} onClick={() => setTopic(t.topic)}>
                {t.name} <span className={styles.chipCount}>{t.count}</span>
              </button>
            ))}
            {hiddenCount > 0 && (
              <button className={`${styles.chip} ${styles.chipMore}`} onClick={() => setAllTopics((v) => !v)} aria-expanded={allTopics}>
                {allTopics ? "Свернуть" : `Ещё ${hiddenCount}`}
              </button>
            )}
          </div>
        </section>
        <div id="add-news" className={styles.anchor}><AddNews onAdded={feed.reload} compact /></div>
      </div>

      <div className={styles.feed}>
        {feed.loading && <Loading text="Подбираем новости под компанию…" />}
        {feed.error && <ErrorState error={feed.error} onRetry={feed.reload} />}
        {feed.data?.length === 0 && <Card><p>По этой теме новостей нет. Выберите другую тему или добавьте новость.</p></Card>}
        {feed.data?.map((item) => <NewsCard key={item.news.news_id} item={item} />)}
      </div>
    </div>
  );
}
