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
  const text = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;

  return (
    <div className={styles.clock} role="timer" aria-label={`Сейчас ${text}`}>
      <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden>
        <circle cx="16" cy="16" r="14.5" className={styles.face} />
        {[0, 90, 180, 270].map((a) => (
          <line key={a} x1="16" y1="3.8" x2="16" y2="5.6" className={styles.tick} transform={`rotate(${a} 16 16)`} />
        ))}
        <line x1="16" y1="16" x2="16" y2="9.6" className={`${styles.hand} ${styles.hour}`} style={{ "--a": `${hourAngle}deg` } as CSSProperties} />
        <line x1="16" y1="16" x2="16" y2="6.4" className={`${styles.hand} ${styles.minute}`} style={{ "--a": `${minuteAngle}deg` } as CSSProperties} />
        <circle cx="16" cy="16" r="1.7" className={styles.pin} />
      </svg>
      <span className={styles.time}>{text}</span>
    </div>
  );
}
