"use client";

import { useEffect, useRef, useState } from "react";
import { ErrorState, Icon, Loading } from "@/components/ui";
import { api } from "@/lib/api";
import { useLoad } from "@/lib/hooks";
import { date } from "@/lib/format";
import type { BankDocument } from "@/lib/types";
import styles from "@/app/(bank)/pulse/analytics/page.module.scss";
import common from "@/styles/common.module.scss";

function plural(n: number, one: string, few: string, many: string) {
  const m = n % 100, d = n % 10;
  if (m >= 11 && m <= 14) return many;
  return d === 1 ? one : d >= 2 && d <= 4 ? few : many;
}

function useDesktop() {
  const [desktop, setDesktop] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 861px)");
    const sync = () => setDesktop(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return desktop;
}

function Theses({ d }: { d: BankDocument }) {
  return (
    <>
      <ol className={styles.theses}>
        {d.theses.map((t) => (
          <li key={t.id} className={styles.thesis}>
            <p>
              {t.stance === "forecast" && <span className={styles.thesisFlag}>Прогноз</span>}
              {t.stale && <span className={`${common.tag} ${common.tagWarn}`}>архивный тезис</span>}
              {t.text}
            </p>
            <span className={styles.thesisPage}>стр. {t.page}</span>
          </li>
        ))}
      </ol>
      {d.pdf_available && (
        <a className={`${common.btn} ${common.btnSecondary} ${styles.drawerPdf}`} href={api.pdfUrl(d.doc_id)} target="_blank" rel="noreferrer">
          <Icon name="file" size={16} /> Открыть PDF
        </a>
      )}
    </>
  );
}

function DocRow({ d, open, inline, onToggle }: { d: BankDocument; open: boolean; inline: boolean; onToggle: () => void }) {
  const forecasts = d.theses.filter((t) => t.stance === "forecast").length;
  return (
    <div className={open && inline ? `${styles.docItem} ${styles.isOpen}` : styles.docItem}>
      <button type="button" className={styles.docRow} onClick={onToggle} aria-expanded={open}>
        <span className={styles.docDate}>{date(d.date)}</span>
        <span className={styles.docRowMain}>
          <span className={styles.docRowTitle}>{d.title}</span>
          <span className={styles.docRowSub}>
            {d.author}
            <span> · {d.theses.length} {plural(d.theses.length, "тезис", "тезиса", "тезисов")}</span>
            {forecasts > 0 && <span className={styles.docStatForecast}> · {forecasts} {plural(forecasts, "прогноз", "прогноза", "прогнозов")}</span>}
          </span>
        </span>
        {d.stale && <span className={`${common.tag} ${common.tagWarn}`}>устарел</span>}
        <Icon name={inline ? "chevron" : "chevronRight"} size={20} />
      </button>
      {open && inline && <div className={styles.docPanel}><Theses d={d} /></div>}
    </div>
  );
}

function DocDrawer({ d, onClose }: { d: BankDocument; onClose: () => void }) {
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  // Модальное окно: фокус — внутрь, на «Закрыть»; после закрытия — обратно на строку документа.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    close.current?.focus();
    return () => opener?.focus({ preventScroll: true });
  }, []);
  return (
    <div className={styles.drawerBackdrop} onClick={onClose}>
      <aside className={styles.drawer} role="dialog" aria-modal="true" aria-label={d.title} onClick={(e) => e.stopPropagation()}>
        <button ref={close} type="button" className={styles.drawerClose} onClick={onClose} aria-label="Закрыть"><Icon name="close" size={20} /></button>
        <div className={styles.docMeta}>
          <span className={styles.docDate}>{date(d.date)}</span>
          <span className={styles.docAuthor}>{d.author}</span>
          {d.stale && <span className={`${common.tag} ${common.tagWarn}`}>устарел</span>}
        </div>
        <h2 className={styles.docTitle}>{d.title}</h2>
        <Theses d={d} />
      </aside>
    </div>
  );
}

export default function AnalyticsPage() {
  const { data: docs, error, reload } = useLoad(
    () => api.analytics().then((r) => [...r.documents].sort((a, b) => b.date.localeCompare(a.date))), []);
  const [activeId, setActiveId] = useState<string | null>(null);
  const desktop = useDesktop();
  const active = docs?.find((d) => d.doc_id === activeId) ?? null;

  return (
    <div className={common.page}>
      <div className={common.pageHead}>
        <div>
          <span className={common.eyebrow}><Icon name="doc" /> База знаний</span>
          <h1>Аналитика Альфа-Банка</h1>
        </div>
      </div>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!docs && !error && <Loading text="Загружаем материалы…" />}
      <div className={styles.docs}>
        {docs?.map((d) => (
          <DocRow key={d.doc_id} d={d} inline={desktop} open={activeId === d.doc_id}
            onToggle={() => setActiveId((id) => (id === d.doc_id ? null : d.doc_id))} />
        ))}
      </div>
      {active && !desktop && <DocDrawer d={active} onClose={() => setActiveId(null)} />}
    </div>
  );
}
