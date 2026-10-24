"use client";

import Link from "next/link";
import { useFeed } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { EffectBadge, Score } from "./ui";
import styles from "@/components/FeedRail.module.scss";

const RAIL_LIMIT = 30;

/** Лента рядом с разбором на планшете: следующую новость открывают, не возвращаясь назад.
 *  Данные — из общего кэша ленты (lib/query), повторного запроса при переходе из ленты нет. */
export default function FeedRail({ activeId }: { activeId: string }) {
  const { session } = useSession();
  const feed = useFeed(session!.companyId);
  if (!feed.data?.length) return null;
  return (
    <aside className={styles.rail} aria-label="Лента рядом с разбором">
      <h2>Лента</h2>
      <ol>
        {feed.data.slice(0, RAIL_LIMIT).map(({ news, relevance, cached_effect }) => {
          const active = news.news_id === activeId;
          return (
            <li key={news.news_id} className={active ? styles.active : undefined}>
              <Link href={`/pulse/n/${encodeURIComponent(news.news_id)}`} aria-current={active ? "page" : undefined}>
                <span className={styles.meta}><Score value={relevance.score} /><EffectBadge effect={cached_effect} /></span>
                <span className={styles.title}>{news.title}</span>
              </Link>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
