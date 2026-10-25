"use client";

import { useEffect, useState, type CSSProperties } from "react";
import styles from "@/components/Clock.module.scss";

/** Текущее время в рамке: аналоговый циферблат и цифры. При загрузке страницы стрелки делают полный оборот и встают на реальное время. */
export default function Clock() {
  const [now, setNow] = useState<Date | null>(null);

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

  return (
    <div className={styles.clock} role="timer" aria-label={`Сейчас ${text}, ${date}`}>
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
    </div>
  );
}
