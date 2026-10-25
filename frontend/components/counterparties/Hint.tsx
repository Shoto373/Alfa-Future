"use client";

import { useId, useState, type ReactNode } from "react";
import styles from "@/components/counterparties/parts.module.scss";

/** Маленькая «?» с пояснением термина: открывается по наведению, фокусу и нажатию, закрывается по Escape. */
export function Hint({ label, children, align = "start" }: { label: string; children: ReactNode; align?: "start" | "end" }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <span className={styles.hint} onMouseLeave={() => setOpen(false)}>
      <button type="button" className={styles.hintBtn} aria-label={`Что такое: ${label}`} aria-describedby={open ? id : undefined}
        aria-expanded={open} onClick={() => setOpen((v) => !v)} onBlur={() => setOpen(false)}
        onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}>?</button>
      <span id={id} role="tooltip" className={`${styles.hintPop} ${align === "end" ? styles.hintEnd : ""} ${open ? styles.hintOpen : ""}`}>{children}</span>
    </span>
  );
}
