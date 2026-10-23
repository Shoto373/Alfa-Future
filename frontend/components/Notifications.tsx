"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { IMPORTANT_SCORE as IMPORTANT } from "@/lib/format";
import { useRead } from "@/lib/notifications";
import { useSession } from "@/lib/session";
import type { FeedItem } from "@/lib/types";
import { Icon, Score } from "./ui";
import styles from "@/components/Notifications.module.scss";
import common from "@/styles/common.module.scss";

const REFRESH_MS = 60_000;
const SHOWN = 10;

/**
 * Колокольчик шапки: важные для компании события (оценка релевантности не ниже порога).
 * Счётчик показывает только непрочитанные. Прочитанным считается событие, которое открыли
 * (из списка или из ленты); оно остаётся в списке как история, но уже не горит.
 * Список обновляется раз в минуту и при открытии.
 */
export default function Notifications() {
  const { session } = useSession();
  const companyId = session!.companyId;
  const { read, mark } = useRead(session!.user.user_id, companyId);
  const [items, setItems] = useState<FeedItem[] | null>(null);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  const refresh = useCallback((signal?: AbortSignal) => {
    api.feed(companyId, undefined, signal)
      .then((r) => setItems(r.items.filter((i) => i.relevance.score >= IMPORTANT)))
      .catch(() => { /* оставляем прежний список, повторим при следующем обновлении */ });
  }, [companyId]);

  useEffect(() => {
    setItems(null);
    const c = new AbortController();
    refresh(c.signal);
    const timer = setInterval(() => refresh(c.signal), REFRESH_MS);
    return () => { c.abort(); clearInterval(timer); };
  }, [refresh]);

  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, []);

  const all = items ?? [];
  const unread = all.filter((i) => !read.has(i.news.news_id));
  const history = all.filter((i) => read.has(i.news.news_id));
  const shown = [...unread, ...history].slice(0, SHOWN);

  return (
    <div className={styles.notif} ref={box}>
      <button className={styles.iconBtn} onClick={() => { setOpen((v) => !v); if (!open) refresh(); }} aria-expanded={open}
        aria-label={`Уведомления Альфа.Пульс: ${unread.length ? `непрочитанных ${unread.length}` : "нет новых"}`} title="Уведомления">
        <Icon name="bell" size={20} />
        {unread.length > 0 && <span className={styles.notifDot}>{unread.length}</span>}
      </button>
      {open && (
        <div className={styles.notifPop} role="dialog" aria-label="Важные события">
          <div className={styles.notifHead}>
            <p className={common.popTitle}>Важно для {session!.companyName}</p>
            {unread.length > 0 && (
              <button type="button" className={styles.notifReadall} onClick={() => mark(unread.map((i) => i.news.news_id))}>Прочитать все</button>
            )}
          </div>
          {items === null && <p className={`${common.muted} ${common.small}`}>Загружаем…</p>}
          {items !== null && all.length === 0 && <p className={`${common.muted} ${common.small}`}>Сейчас нет событий с высокой релевантностью.</p>}
          {items !== null && all.length > 0 && unread.length === 0 && <p className={`${common.muted} ${common.small}`}>Новых событий нет. Ниже история.</p>}
          <ul>
            {shown.map((i) => {
              const isRead = read.has(i.news.news_id);
              return (
                <li key={i.news.news_id} className={isRead ? styles.isRead : ""}>
                  <Link href={`/pulse/n/${encodeURIComponent(i.news.news_id)}`}
                    onClick={() => { mark([i.news.news_id]); setOpen(false); }}>
                    <Score value={i.relevance.score} />
                    <span>{i.news.title}</span>
                    {!isRead && <span className={styles.notifNew} aria-label="Не прочитано" />}
                  </Link>
                </li>
              );
            })}
          </ul>
          <Link href="/pulse" className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} onClick={() => setOpen(false)}>Вся лента</Link>
        </div>
      )}
    </div>
  );
}
