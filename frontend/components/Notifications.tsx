"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { loadFeed } from "@/lib/hooks";
import { IMPORTANT_SCORE as IMPORTANT } from "@/lib/format";
import { useRead } from "@/lib/notifications";
import { useSession } from "@/lib/session";
import type { FeedItem, InboxMessage } from "@/lib/types";
import { Icon, Score } from "./ui";
import styles from "@/components/Notifications.module.scss";
import common from "@/styles/common.module.scss";

const REFRESH_MS = 60_000;
const SHOWN = 10;

/**
 * Колокольчик шапки: сводки и алерты сервера (SPR4-04) и важные для компании события ленты.
 * Счётчик показывает только непрочитанные. Прочитанным считается событие, которое открыли
 * (из списка или из ленты); оно остаётся в списке как история, но уже не горит.
 * Список обновляется раз в минуту и при открытии.
 */
export default function Notifications() {
  const { session } = useSession();
  const companyId = session!.companyId;
  const { read, mark } = useRead(session!.user.user_id, companyId);
  // Список привязан к компании: при переключении прежний не показывается.
  const [loaded, setLoaded] = useState<{ companyId: string; items: FeedItem[] } | null>(null);
  const items = loaded?.companyId === companyId ? loaded.items : null;
  const [inbox, setInbox] = useState<{ companyId: string; items: InboxMessage[] } | null>(null);
  const messages = inbox?.companyId === companyId ? inbox.items : [];
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  const refresh = useCallback((signal?: AbortSignal) => {
    loadFeed(companyId, { signal })
      .then((r) => setLoaded({ companyId, items: r.items.filter((i) => i.relevance.score >= IMPORTANT) }))
      .catch(() => { /* оставляем прежний список, повторим при следующем обновлении */ });
    api.inbox(companyId, signal).then((r) => setInbox({ companyId, items: r.items })).catch(() => { /* то же */ });
  }, [companyId]);

  useEffect(() => {
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
  const newMessages = messages.filter((m) => !m.read);
  const total = unread.length + newMessages.length;
  const readMessages = (ids?: number[]) => {
    setInbox((v) => v && { ...v, items: v.items.map((m) => (!ids || ids.includes(m.id) ? { ...m, read: true } : m)) });
    api.inboxRead(companyId, ids).catch(() => { /* отметка повторится при следующем открытии */ });
  };

  return (
    <div className={styles.notif} ref={box}>
      <button className={styles.iconBtn} onClick={() => { setOpen((v) => !v); if (!open) refresh(); }} aria-expanded={open}
        aria-label={`Уведомления Альфа.Пульс: ${total ? `непрочитанных ${total}` : "нет новых"}`} title="Уведомления">
        <Icon name="bell" size={20} />
        {total > 0 && <span className={styles.notifDot}>{total}</span>}
      </button>
      {open && (
        <div className={styles.notifPop} role="dialog" aria-label="Важные события">
          <div className={styles.notifHead}>
            <p className={common.popTitle}>Важно для {session!.companyName}</p>
            {total > 0 && (
              <button type="button" className={styles.notifReadall}
                onClick={() => { mark(unread.map((i) => i.news.news_id)); if (newMessages.length) readMessages(); }}>Прочитать все</button>
            )}
          </div>
          <div className={styles.notifBody} role="region" aria-label="Список уведомлений" tabIndex={0}>
            {messages.length > 0 && (
              <ul aria-label="Сводки и алерты" data-testid="inbox">
                {messages.slice(0, 3).map((m) => (
                  <li key={m.id} className={m.read ? styles.isRead : ""}>
                    <Link href={m.items[0]?.href ?? "/pulse"} onClick={() => { readMessages([m.id]); setOpen(false); }}>
                      <Icon name={m.kind === "digest" ? "list" : "bell"} size={16} />
                      <span className={styles.notifTitle}>{m.title}</span>
                      {!m.read && <span className={styles.notifNew} aria-label="Не прочитано" />}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            {items === null && <p className={`${common.muted} ${common.small}`} role="status">Загружаем…</p>}
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
                      <span className={styles.notifTitle}>{i.news.title}</span>
                      {!isRead && <span className={styles.notifNew} aria-label="Не прочитано" />}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
          <div className={styles.notifFoot}>
            <Link href="/pulse" className={styles.notifFooter} onClick={() => setOpen(false)}>Вся лента</Link>
            <Link href="/settings/notifications" className={styles.notifFooter} onClick={() => setOpen(false)}>Настроить</Link>
          </div>
        </div>
      )}
    </div>
  );
}
