"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { api } from "@/lib/api";
import { importantWord, inDays, nextDigest, taxDeadline } from "@/lib/day";
import { IMPORTANT_SCORE } from "@/lib/format";
import { loadFeed } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { NotificationSettings } from "@/lib/types";
import { Icon } from "./ui";
import styles from "@/components/Clock.module.scss";

type Day = { important: number | null; settings: NotificationSettings | null };

/** Часы в шапке. По нажатию — «Ваш день»: новые важные события, следующая сводка и срок налогового платежа.
 *  При загрузке страницы стрелки делают полный оборот и встают на реальное время. */
export default function Clock() {
  const [now, setNow] = useState<Date | null>(null);
  const [open, setOpen] = useState(false);
  const [day, setDay] = useState<Day>({ important: null, settings: null });
  const box = useRef<HTMLDivElement>(null);
  const { session } = useSession();
  const companyId = session?.memberships.length ? session.companyId : null;

  // Данные дня — при открытии: лента берется из кэша, настройки сводки — с сервера.
  useEffect(() => {
    if (!open || !companyId) return;
    const startOfToday = new Date();
    startOfToday.setHours(0, 0, 0, 0);
    loadFeed(companyId).then((r) => setDay((d) => ({ ...d, important: r.items.filter((i) => i.relevance.score >= IMPORTANT_SCORE
      && new Date(i.news.published_at) >= startOfToday).length }))).catch(() => { /* без счетчика */ });
    api.notificationSettings(companyId).then((s) => setDay((d) => ({ ...d, settings: s }))).catch(() => { /* без сводки */ });
  }, [open, companyId]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  useEffect(() => {
    const tick = () => setNow(new Date());
    tick();
    const id = setInterval(tick, 10_000);
    return () => clearInterval(id);
  }, []);

  // До монтирования время неизвестно: рамка того же размера, чтобы шапка не прыгала и не было расхождения с сервером.
  if (!now) return <div className={styles.clock} aria-hidden />;

  const h = now.getHours();
  const m = now.getMinutes();
  const hourAngle = ((h % 12) + m / 60) * 30;
  const minuteAngle = m * 6;
  const hh = String(h).padStart(2, "0");
  const mm = String(m).padStart(2, "0");
  const text = `${hh}:${mm}`;
  const date = now.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "short" }).replace(/\./g, "");

  const tax = taxDeadline(now);
  const digest = nextDigest(now, day.settings);
  const long = now.toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long" });
  const taxDate = tax.date.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });

  return (
    <div className={styles.wrap} ref={box}>
    <button type="button" className={styles.clock} aria-expanded={open} aria-haspopup="dialog"
      aria-label={`Сейчас ${text}, ${date}. Ваш день`} onClick={() => setOpen((v) => !v)}>
      <span className={styles.dial}>
        <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden>
          {Array.from({ length: 12 }, (_, i) => {
            const major = i % 3 === 0;
            return (
              <line
                key={i}
                x1="16"
                y1={major ? 3.6 : 3.9}
                x2="16"
                y2={major ? 6.2 : 5.4}
                className={major ? styles.tickMajor : styles.tick}
                transform={`rotate(${i * 30} 16 16)`}
              />
            );
          })}
          <circle cx="16" cy="2.6" r="0.9" className={styles.marker} />
          <polygon
            points="14.7,17.2 16,9.6 17.3,17.2"
            className={`${styles.hand} ${styles.hour}`}
            style={{ "--a": `${hourAngle}deg` } as CSSProperties}
          />
          <polygon
            points="15.3,17.6 16,5.8 16.7,17.6"
            className={`${styles.hand} ${styles.minute}`}
            style={{ "--a": `${minuteAngle}deg` } as CSSProperties}
          />
          <circle cx="16" cy="16" r="2" className={styles.pin} />
          <circle cx="16" cy="16" r="0.8" className={styles.pinDot} />
        </svg>
      </span>
      <span className={styles.digits}>
        <span className={styles.time}>
          {hh}
          <span className={styles.colon}>:</span>
          {mm}
        </span>
        <span className={styles.date}>{date}</span>
      </span>
    </button>
    {open && (
      <div className={styles.pop} role="dialog" aria-label="Ваш день">
        <p className={styles.popTitle}>{long.charAt(0).toUpperCase() + long.slice(1)}</p>
        <ul className={styles.rows}>
          {companyId && (
            <li>
              <span className={styles.rowIcon}><Icon name="bell" size={16} /></span>
              <span><b>{day.important === null ? "…" : day.important ? `${day.important} ${importantWord(day.important)} сегодня` : "Важных событий сегодня нет"}</b>
                <Link href="/pulse" onClick={() => setOpen(false)}>Открыть ленту</Link></span>
            </li>
          )}
          {companyId && (
            <li>
              <span className={styles.rowIcon}><Icon name="mail" size={16} /></span>
              <span><b>{digest ? `Утренняя сводка — ${digest.today ? "сегодня" : "завтра"} в ${digest.time}`
                : day.settings ? "Утренняя сводка выключена" : "Утренняя сводка"}</b>
                <Link href="/profile#notifications" onClick={() => setOpen(false)}>Настроить</Link></span>
            </li>
          )}
          <li>
            <span className={styles.rowIcon}><Icon name="card" size={16} /></span>
            <span><b>Единый налоговый платеж — {taxDate}, {inDays(tax.days)}</b>
              <small>Срок уплаты — 28-е число; с выходного переносится на понедельник</small></span>
          </li>
        </ul>
      </div>
    )}
    </div>
  );
}
