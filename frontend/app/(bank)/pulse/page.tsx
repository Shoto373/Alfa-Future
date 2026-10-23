"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import AddNews from "@/components/AddNews";
import NewsCard from "@/components/NewsCard";
import { Card, ErrorBox, Icon, Loading } from "@/components/ui";
import { useFeedWithTopics } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { TopicCount } from "@/lib/types";
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
  const setTopic = (value?: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value) params.set("topic", value);
    else params.delete("topic");
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };
  const page = useFeedWithTopics(session!.companyId, topic);
  const feed = { ...page, data: page.data?.items ?? null };
  const [allTopics, setAllTopics] = useState(false);

  // Только темы, по которым у компании есть новости; первые 10 видны сразу, остальные — по кнопке.
  // Счетчики приходят с сервером и не меняются при выборе темы, поэтому список не «прыгает».
  const [topics, setTopics] = useState<TopicCount[]>([]);
  useEffect(() => { if (page.data) setTopics(page.data.topic_counts); }, [page.data]);
  useEffect(() => setTopics([]), [session!.companyId]);
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
          <h2>Темы</h2>
          <div className={styles.chips} role="toolbar" aria-label="Фильтр по темам">
            <button className={!topic ? `${styles.chip} ${styles.on}` : styles.chip} aria-pressed={!topic} onClick={() => setTopic(undefined)}>Все темы</button>
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
        {feed.error && <ErrorBox message={feed.error.message} onRetry={feed.reload} />}
        {feed.data?.length === 0 && <Card><p>По этой теме новостей нет. Выберите другую тему или добавьте новость.</p></Card>}
        {feed.data?.map((item) => <NewsCard key={item.news.news_id} item={item} />)}
      </div>
    </div>
  );
}
