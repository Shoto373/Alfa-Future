"use client";

import { useAnimatedNumber } from "@/lib/motion";
import styles from "@/app/(bank)/page.module.scss";

/** Полукруглый индикатор, как «Индикатор риска» на главной Альфа-Бизнеса.
 *  При открытии стрелка плавно поднимается от нуля к значению, дуга заполняется вслед за ней. */
export default function Gauge({ value }: { value: number }) {
  const shown = useAnimatedNumber(Math.max(0, Math.min(100, value)), 1600, 0);
  const angle = Math.PI * (1 - shown / 100);
  const x = 100 + 80 * Math.cos(angle), y = 100 - 80 * Math.sin(angle);
  return (
    <svg viewBox="0 0 200 112" className={styles.gauge} aria-hidden="true">
      <defs>
        <linearGradient id="g-arc" x1="0" x2="1">
          <stop offset="0" stopColor="#21a038" /><stop offset=".55" stopColor="#ffb800" /><stop offset="1" stopColor="#ef3124" />
        </linearGradient>
      </defs>
      <path d="M20 100a80 80 0 0 1 160 0" fill="none" stroke="#eceef1" strokeWidth="10" strokeLinecap="round" />
      <path d="M20 100a80 80 0 0 1 160 0" fill="none" stroke="url(#g-arc)" strokeWidth="10" strokeLinecap="round"
        strokeDasharray={`${(Math.PI * 80 * shown) / 100} 999`} />
      <circle cx={x} cy={y} r="8" fill="#fff" stroke="#0b1f35" strokeWidth="3" className={styles.gaugeKnob} />
    </svg>
  );
}
