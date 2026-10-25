"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import styles from "@/components/TimeField.module.scss";

type Props = {
  id?: string;
  /** "HH:MM" */
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  /** Шаг минут в списке; сохраненное значение с другими минутами тоже показывается и выбирается. */
  step?: number;
  presets?: string[];
};

const pad = (n: number) => String(n).padStart(2, "0");
const HOURS = Array.from({ length: 24 }, (_, i) => i);
const DEFAULT_PRESETS = ["07:00", "08:30", "09:00", "22:00"];

function parse(value: string): [number, number] {
  const m = /^(\d{1,2}):(\d{2})/.exec(value);
  if (!m) return [0, 0];
  return [Math.min(23, Number(m[1])), Math.min(59, Number(m[2]))];
}

/** Свое поле времени вместо нативного `<input type="time">`: кнопка + поповер с колонками часов и минут. */
export default function TimeField({
  id, value, onChange, disabled, step = 5, presets = DEFAULT_PRESETS, ...aria
}: Props) {
  const [open, setOpen] = useState(false);
  const [up, setUp] = useState(false);
  const [alignRight, setAlignRight] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const popId = useId();
  const [h, m] = parse(value);
  const minutes = (() => {
    const list = Array.from({ length: Math.ceil(60 / step) }, (_, i) => i * step).filter((x) => x < 60);
    if (!list.includes(m)) list.push(m);
    return list.sort((a, b) => a - b);
  })();

  const close = useCallback((focusBack: boolean) => {
    setOpen(false);
    if (focusBack) button.current?.focus();
  }, []);

  // Позиция: вниз, если места хватает, иначе вверх; по правому краю, если справа не помещается.
  useLayoutEffect(() => {
    if (!open || !root.current || !pop.current) return;
    const r = root.current.getBoundingClientRect();
    const ph = pop.current.offsetHeight;
    const pw = pop.current.offsetWidth;
    setUp(window.innerHeight - r.bottom < ph + 12 && r.top > window.innerHeight - r.bottom);
    setAlignRight(r.left + pw > document.documentElement.clientWidth - 8);
  }, [open]);

  // Выбранные пункты в видимую область + фокус на выбранный час.
  useEffect(() => {
    if (!open || !pop.current) return;
    pop.current.querySelectorAll<HTMLElement>("[data-sel='1']").forEach((el) => {
      const col = el.parentElement!;
      col.scrollTop = el.offsetTop - col.clientHeight / 2 + el.offsetHeight / 2;
    });
    pop.current.querySelector<HTMLElement>("[data-col='h'][data-sel='1']")?.focus({ preventScroll: true });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent | TouchEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", down);
    document.addEventListener("touchstart", down);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("touchstart", down);
    };
  }, [open]);

  const emit = (nh: number, nm: number) => onChange(`${pad(nh)}:${pad(nm)}`);

  const focusItem = (col: "h" | "m", idx: number) => {
    const els = pop.current?.querySelectorAll<HTMLElement>(`[data-col='${col}']`);
    els?.[Math.max(0, Math.min(els.length - 1, idx))]?.focus();
  };

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close(true);
      return;
    }
    const t = e.target as HTMLElement;
    const col = t.dataset.col as "h" | "m" | undefined;
    if (!col) return;
    const idx = Number(t.dataset.idx);
    if (e.key === "ArrowDown") focusItem(col, idx + 1);
    else if (e.key === "ArrowUp") focusItem(col, idx - 1);
    else if (e.key === "Home") focusItem(col, 0);
    else if (e.key === "End") focusItem(col, 999);
    else if (e.key === "ArrowRight" && col === "h") focusItem("m", minutes.indexOf(m));
    else if (e.key === "ArrowLeft" && col === "m") focusItem("h", h);
    else return;
    e.preventDefault();
  };

  return (
    <div className={styles.root} ref={root}>
      <button
        ref={button}
        id={id}
        type="button"
        className={styles.control}
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? popId : undefined}
        aria-label={aria["aria-label"] ? `${aria["aria-label"]}: ${value}` : undefined}
        aria-labelledby={aria["aria-labelledby"]}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && !open) { e.preventDefault(); setOpen(true); }
        }}
      >
        <span className={styles.time}>{value || "--:--"}</span>
        <svg className={styles.icon} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
        </svg>
      </button>
      {open && !disabled && (
        <div
          ref={pop}
          id={popId}
          role="dialog"
          aria-label="Выбор времени"
          className={`${styles.pop} ${up ? styles.up : ""} ${alignRight ? styles.right : ""}`}
          onKeyDown={onKey}
        >
          <div className={styles.cols}>
            <div className={styles.colWrap}>
              <span className={styles.colTitle}>Часы</span>
              <div className={styles.col} role="group" aria-label="Часы">
                {HOURS.map((x) => (
                  <button key={x} type="button" data-col="h" data-idx={x} data-sel={x === h ? "1" : "0"}
                    tabIndex={x === h ? 0 : -1} aria-pressed={x === h}
                    className={`${styles.item} ${x === h ? styles.sel : ""}`}
                    onClick={() => { emit(x, m); focusItem("m", minutes.indexOf(m)); }}>{pad(x)}</button>
                ))}
              </div>
            </div>
            <div className={styles.colWrap}>
              <span className={styles.colTitle}>Минуты</span>
              <div className={styles.col} role="group" aria-label="Минуты">
                {minutes.map((x, i) => (
                  <button key={x} type="button" data-col="m" data-idx={i} data-sel={x === m ? "1" : "0"}
                    tabIndex={x === m ? 0 : -1} aria-pressed={x === m}
                    className={`${styles.item} ${x === m ? styles.sel : ""}`}
                    onClick={() => { emit(h, x); close(true); }}>{pad(x)}</button>
                ))}
              </div>
            </div>
          </div>
          {presets.length > 0 && (
            <div className={styles.presets}>
              {presets.map((p) => (
                <button key={p} type="button" className={`${styles.chip} ${p === value ? styles.chipSel : ""}`}
                  onClick={() => { onChange(p); close(true); }}>{p}</button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
