"use client";

import { useEffect, useState } from "react";
import { Card, ErrorBox, Icon, Loading } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { date } from "@/lib/format";
import type { BankDocument } from "@/lib/types";

export default function AnalyticsPage() {
  const [docs, setDocs] = useState<BankDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    setError(null);
    api.analytics().then((r) => setDocs(r.documents)).catch((e) => setError(e instanceof ApiError ? e.message : "Ошибка"));
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
          <Card key={d.doc_id} title={d.title}
            actions={d.pdf_available ? <a className="btn btn-link btn-sm" href={api.pdfUrl(d.doc_id)} target="_blank" rel="noreferrer"><Icon name="link" size={14} /> PDF</a> : undefined}>
            <p className="muted small">{d.author} · {date(d.date)} {d.stale && <span className="tag tag-warn">устарел</span>}</p>
            <ul className="theses">
              {d.theses.map((t) => (
                <li key={t.id}>
                  <span className="thesis-page">стр. {t.page}</span>
                  <span>{t.text}</span>
                  {t.stance === "forecast" && <span className="tag">прогноз</span>}
                  {t.stale && <span className="tag tag-warn">архивный тезис</span>}
                </li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
    </div>
  );
}
