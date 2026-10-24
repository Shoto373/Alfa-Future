"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { track } from "@/lib/track";
import { Icon } from "../ui";
import styles from "@/components/InsightView.module.scss";
import common from "@/styles/common.module.scss";

/** Оценка раздела разбора: влияет на темы ленты для этой роли. */
export default function Feedback({ insightId, section }: { insightId: string; section: string }) {
  const [sent, setSent] = useState<1 | -1 | null>(null);
  const send = (r: 1 | -1) => {
    track("feedback", { rating: r, section });
    return api.feedback(insightId, r, section).then(() => setSent(r)).catch(() => setSent(null));
  };
  return (
    <span className={styles.feedback} aria-label="Оцените раздел">
      {sent ? <span className={`${styles.muted} ${common.small}`} role="status">Спасибо за оценку</span> : (
        <>
          <button type="button" className={common.iconBtn} onClick={() => send(1)} aria-label="Полезно"><Icon name="thumbUp" size={16} /></button>
          <button type="button" className={common.iconBtn} onClick={() => send(-1)} aria-label="Не полезно"><Icon name="thumbDown" size={16} /></button>
        </>
      )}
    </span>
  );
}
