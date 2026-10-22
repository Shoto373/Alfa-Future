"use client";

import { useEffect, useState } from "react";
import { ErrorBox, Icon, Loading } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { date } from "@/lib/format";
import type { BankDocument } from "@/lib/types";

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
      <ol className="theses">
        {d.theses.map((t) => (
          <li key={t.id} className="thesis">
            <p>
              {t.stance === "forecast" && <span className="thesis-flag">Прогноз</span>}
              {t.stale && <span className="tag tag-warn">архивный тезис</span>}
              {t.text}
            </p>
            <span className="thesis-page">стр. {t.page}</span>
          </li>
        ))}
      </ol>
      {d.pdf_available && (
        <a className="btn btn-secondary drawer-pdf" href={api.pdfUrl(d.doc_id)} target="_blank" rel="noreferrer">
          <Icon name="file" size={16} /> Открыть PDF
        </a>
      )}
    </>
  );
}

function DocRow({ d, open, inline, onToggle }: { d: BankDocument; open: boolean; inline: boolean; onToggle: () => void }) {
  const forecasts = d.theses.filter((t) => t.stance === "forecast").length;
  return (
    <div className={open && inline ? "doc-item is-open" : "doc-item"}>
      <button className="doc-row" onClick={onToggle} aria-expanded={open}>
        <span className="doc-date">{date(d.date)}</span>
        <span className="doc-row-main">
          <span className="doc-row-title">{d.title}</span>
          <span className="doc-row-sub">
            {d.author}
            <span className="doc-row-count"> · {d.theses.length} {plural(d.theses.length, "тезис", "тезиса", "тезисов")}</span>
            {forecasts > 0 && <span className="doc-stat-forecast"> · {forecasts} {plural(forecasts, "прогноз", "прогноза", "прогнозов")}</span>}
          </span>
        </span>
        {d.stale && <span className="tag tag-warn">устарел</span>}
        <Icon name={inline ? "chevron" : "chevronRight"} size={20} />
      </button>
      {open && inline && <div className="doc-panel"><Theses d={d} /></div>}
    </div>
  );
}

function DocDrawer({ d, onClose }: { d: BankDocument; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={d.title} onClick={(e) => e.stopPropagation()}>
        <button className="drawer-close" onClick={onClose} aria-label="Закрыть"><Icon name="close" size={20} /></button>
        <div className="doc-meta">
          <span className="doc-date">{date(d.date)}</span>
          <span className="doc-author">{d.author}</span>
          {d.stale && <span className="tag tag-warn">устарел</span>}
        </div>
        <h2 className="doc-title">{d.title}</h2>
        <Theses d={d} />
      </aside>
    </div>
  );
}

export default function AnalyticsPage() {
  const [docs, setDocs] = useState<BankDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [activeId, setActiveId] = useState<string | null>(null);
  const desktop = useDesktop();
  const active = docs?.find((d) => d.doc_id === activeId) ?? null;

  useEffect(() => {
    setError(null);
    api.analytics().then((r) => setDocs([...r.documents].sort((a, b) => b.date.localeCompare(a.date)))).catch((e) => setError(e instanceof ApiError ? e.message : "Ошибка"));
  }, [tick]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="eyebrow"><Icon name="doc" /> База знаний</span>
          <h1>Аналитика Альфа-Банка</h1>
          <p className="muted">Материалы Центра макроэкономического анализа и Альфа-КИБ из кейса. Агент цитирует тезисы с указанием страницы.</p>
        </div>
      </div>
      {error && <ErrorBox message={error} onRetry={() => setTick((t) => t + 1)} />}
      {!docs && !error && <Loading text="Загружаем материалы…" />}
      <div className="docs">
        {docs?.map((d) => (
          <DocRow key={d.doc_id} d={d} inline={desktop} open={activeId === d.doc_id}
            onToggle={() => setActiveId((id) => (id === d.doc_id ? null : d.doc_id))} />
        ))}
      </div>
      {active && !desktop && <DocDrawer d={active} onClose={() => setActiveId(null)} />}
    </div>
  );
}
