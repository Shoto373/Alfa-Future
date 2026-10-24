"use client";

import { useLayoutEffect, useRef, useState } from "react";
import type { TopicCount } from "@/lib/types";
import styles from "@/app/(bank)/pulse/page.module.scss";

const ROWS = 3;

/** Фильтр тем ленты: в свернутом виде — ровно столько тем, сколько помещается в 3 строки вместе с «Ещё N».
 *  Сколько помещается, считается по скрытой копии всех чипов (ширина блока меняется — пересчет).
 *  На телефоне темы идут одной прокручиваемой строкой — там видны все. */
export default function TopicChips({ topics, topic, total, onSelect }: {
  topics: TopicCount[]; topic?: string; total: number | null; onSelect: (topic?: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [fit, setFit] = useState<number | null>(null);  // сколько тем (без «Все темы») влезает в 3 строки
  const measure = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const box = measure.current;
    if (!box || !bar.current) return;
    const toolbar = bar.current;
    const count = () => {
      if (getComputedStyle(toolbar).flexWrap === "nowrap") return setFit(null);  // одна строка с прокруткой
      const chips = Array.from(box.children) as HTMLElement[];
      const more = chips.pop()!;  // последний — образец кнопки «Ещё N»
      const tops = [...new Set(chips.map((c) => c.offsetTop))].sort((a, b) => a - b);
      if (tops.length <= ROWS) return setFit(chips.length - 1);  // все темы помещаются
      const limit = tops[ROWS - 1];
      const gap = parseFloat(getComputedStyle(box).columnGap) || 0;
      let n = chips.filter((c) => c.offsetTop <= limit).length;
      // Кнопке «Ещё N» нужно место в последней строке: убираем темы с конца, пока она не встанет.
      while (n > 1) {
        const last = chips[n - 1];
        if (last.offsetTop < limit || last.offsetLeft + last.offsetWidth + gap + more.offsetWidth <= box.clientWidth) break;
        n -= 1;
      }
      setFit(n - 1);
    };
    count();
    const observer = new ResizeObserver(count);
    observer.observe(box);
    return () => observer.disconnect();
  }, [topics, total]);

  const shownCount = expanded || fit === null ? topics.length : fit;
  let visible = topics.slice(0, shownCount);
  // Выбранная тема видна всегда: она встает на место последней видимой.
  const selected = topics.find((t) => t.topic === topic);
  if (selected && !visible.includes(selected)) visible = [...visible.slice(0, Math.max(shownCount - 1, 0)), selected];
  const hidden = topics.length - visible.length;

  const chip = (t: TopicCount) => (
    <button key={t.topic} className={topic === t.topic ? `${styles.chip} ${styles.on}` : styles.chip}
      aria-pressed={topic === t.topic} onClick={() => onSelect(t.topic)}>
      {t.name} <span className={styles.chipCount}>{t.count}</span>
    </button>
  );
  const all = (
    <button className={!topic ? `${styles.chip} ${styles.on}` : styles.chip} aria-pressed={!topic} onClick={() => onSelect(undefined)}>
      Все темы {total !== null && <span className={styles.chipCount}>{total}</span>}
    </button>
  );

  return (
    <div className={styles.chipsBox}>
      <div className={styles.chips} role="toolbar" aria-label="Фильтр по темам" ref={bar}>
        {all}
        {visible.map(chip)}
        {(hidden > 0 || expanded) && fit !== null && fit < topics.length && (
          <button className={`${styles.chip} ${styles.chipMore}`} onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
            {expanded ? "Свернуть" : `Ещё ${hidden}`}
          </button>
        )}
      </div>
      <div className={`${styles.chips} ${styles.chipsMeasure}`} ref={measure} aria-hidden>
        {all}
        {topics.map(chip)}
        <span className={`${styles.chip} ${styles.chipMore}`}>Ещё {topics.length}</span>
      </div>
    </div>
  );
}
