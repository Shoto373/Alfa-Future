"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import AddNews from "@/components/AddNews";
import NewsCard from "@/components/NewsCard";
import TopicChips from "@/components/TopicChips";
import { Card, ErrorState, Icon, Loading } from "@/components/ui";
import { useFeedWithTopics } from "@/lib/hooks";
import { useRead } from "@/lib/notifications";
import { useSession } from "@/lib/session";
import { track } from "@/lib/track";
import type { FeedItem, TopicCount } from "@/lib/types";
import common from "@/styles/common.module.scss";
import styles from "@/app/(bank)/pulse/page.module.scss";

const PAGE_SIZE = 30;

type Sort = "priority" | "new" | "unread" | "read";
const SORTS: { key: Sort; label: string }[] = [
  { key: "priority", label: "По приоритету" },
  { key: "new", label: "Сначала новые" },
  { key: "unread", label: "Непрочитанные" },
  { key: "read", label: "Прочитанные" },
];

/** Порядок ленты; внутри групп «прочитано / нет» — по приоритету (так их отдает сервер). */
function sorted(items: FeedItem[], sort: Sort, read: Set<string>): FeedItem[] {
  if (sort === "priority") return items;
  if (sort === "new") return [...items].sort((a, b) => b.news.published_at.localeCompare(a.news.published_at));
  const first = (i: FeedItem) => read.has(i.news.news_id) === (sort === "read") ? 0 : 1;
  return [...items].sort((a, b) => first(a) - first(b));  // sort устойчивый: приоритет внутри групп сохраняется
}

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
    params.delete("topic");
    params.delete("story");
    if (value) params.set("topic", value);
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };
  const sort = (SORTS.find((s) => s.key === searchParams.get("sort"))?.key ?? "priority") as Sort;
  const setSort = (value: Sort) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value === "priority") params.delete("sort"); else params.set("sort", value);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };
  const page = useFeedWithTopics(session!.companyId, topic);
  const { read } = useRead(session!.user.user_id, session!.companyId);
  const feed = { ...page, data: page.data ? sorted(page.data.items, sort, read) : null };
  const companyId = session!.companyId;
  useEffect(() => track("feed_view", topic ? { topic } : {}), [companyId, topic]);
  // Новый фильтр, порядок или компания — снова первые 30 новостей.
  const [shown, setShown] = useState(PAGE_SIZE);
  const pageKey = `${companyId}|${topic ?? ""}|${sort}`;
  const [shownFor, setShownFor] = useState(pageKey);
  if (shownFor !== pageKey) {
    setShownFor(pageKey);
    setShown(PAGE_SIZE);
  }
  const unreadCount = page.data?.items.filter((i) => !read.has(i.news.news_id)).length ?? 0;

  // Только темы, по которым у компании есть новости; сколько видно сразу — решает TopicChips (3 строки).
  // Счетчики приходят с сервером и не меняются при выборе темы, поэтому список не «прыгает».
  // Пока грузится лента по новому фильтру, остаются прежние чипы этой же компании.
  const [chips, setChips] = useState<{ source: object; companyId: string; topics: TopicCount[] } | null>(null);
  if (page.data && chips?.source !== page.data) {
    setChips({ source: page.data, companyId, topics: page.data.topic_counts });
  }
  const topics = chips?.companyId === companyId ? chips.topics : [];

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
          <TopicChips topics={topics} topic={topic} total={page.data?.total ?? null} onSelect={setTopic} />
        </section>
        <div id="add-news" className={styles.anchor}><AddNews onAdded={feed.reload} compact /></div>
      </div>

      <div className={styles.sortBar} role="toolbar" aria-label="Порядок ленты">
        {SORTS.map((s) => (
          <button key={s.key} className={sort === s.key ? `${styles.chip} ${styles.on}` : styles.chip}
            aria-pressed={sort === s.key} onClick={() => setSort(s.key)}>
            {s.label}
            {s.key === "unread" && page.data && <span className={styles.chipCount}>{unreadCount}</span>}
            {s.key === "read" && page.data && <span className={styles.chipCount}>{page.data.items.length - unreadCount}</span>}
          </button>
        ))}
      </div>

      <div className={styles.feed}>
        {feed.loading && <Loading text="Подбираем новости под компанию…" />}
        {feed.error && <ErrorState error={feed.error} onRetry={feed.reload} />}
        {feed.data?.length === 0 && <Card><p>По этой теме новостей нет. Выберите другую тему или добавьте новость.</p></Card>}
        {feed.data?.slice(0, shown).map((item) => <NewsCard key={item.news.news_id} item={item} read={read.has(item.news.news_id)} />)}
        {feed.data && feed.data.length > shown && (
          <button className={`${common.btn} ${common.btnSecondary} ${styles.more}`} onClick={() => setShown((n) => n + PAGE_SIZE)}>
            Показать ещё {Math.min(PAGE_SIZE, feed.data.length - shown)} из {feed.data.length - shown}
          </button>
        )}
      </div>
    </div>
  );
}
