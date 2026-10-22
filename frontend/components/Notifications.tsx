"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { IMPORTANT_SCORE as IMPORTANT } from "@/lib/format";
import { useFeed } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { Icon, Score } from "./ui";

/** Колокольчик шапки: проактивная точка входа — важные для компании события. */
export default function Notifications() {
  const { session } = useSession();
  const feed = useFeed(session!.companyId, session!.role);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const important = (feed.data ?? []).filter((i) => i.relevance.score >= IMPORTANT);

  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  return (
    <div className="notif" ref={box}>
      <button className="icon-btn" onClick={() => setOpen((v) => !v)} aria-expanded={open}
        aria-label={`Уведомления Альфа.Пульс: ${important.length}`} title="Уведомления">
        <Icon name="bell" size={20} />
        {important.length > 0 && <span className="notif-dot">{important.length}</span>}
      </button>
      {open && (
        <div className="notif-pop" role="dialog" aria-label="Важные события">
          <p className="pop-title">Альфа.Пульс · важно для {session!.companyName}</p>
          {feed.loading && <p className="muted small">Загружаем…</p>}
          {!feed.loading && important.length === 0 && <p className="muted small">Сейчас нет событий с высокой релевантностью.</p>}
          <ul>
            {important.slice(0, 4).map((i) => (
              <li key={i.news.news_id}>
                <Link href={`/pulse/n/${encodeURIComponent(i.news.news_id)}`} onClick={() => setOpen(false)}>
                  <Score value={i.relevance.score} />
                  <span>{i.news.title}</span>
                </Link>
              </li>
            ))}
          </ul>
          <Link href="/pulse" className="btn btn-secondary btn-sm" onClick={() => setOpen(false)}>Вся лента</Link>
        </div>
      )}
    </div>
  );
}
