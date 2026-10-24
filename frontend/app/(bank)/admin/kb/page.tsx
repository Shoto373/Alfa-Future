"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Card, EmptyState, ErrorState, Icon, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { date } from "@/lib/format";
import { useLoad } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { STATUS } from "@/app/(bank)/admin/kb/status";
import styles from "@/app/(bank)/admin/kb/page.module.scss";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";

const POLL_MS = 3000;

/** Аналитик банка: загрузка PDF обзора на распознавание и список документов с очередью проверки (SPR3-03). */
export default function KbPage() {
  const { session } = useSession();
  const operator = !!session!.user.is_operator;
  const [tick, setTick] = useState(0);
  const list = useLoad((signal) => operator ? api.kbDocuments(signal) : Promise.resolve({ items: [] }), [operator, tick]);
  const busy = list.data?.items.some((d) => d.status === "queued" || d.status === "processing");

  // Пока воркер распознает документ — обновляем список, чтобы аналитик увидел готовые черновики.
  useEffect(() => {
    if (!busy) return;
    const t = setTimeout(() => setTick((n) => n + 1), POLL_MS);
    return () => clearTimeout(t);
  }, [busy, list.data]);

  if (!operator) {
    return <div className={common.page}><h1>Тезисы аналитики</h1><Card><p>Раздел доступен аналитикам банка.</p></Card></div>;
  }
  return (
    <div className={common.page}>
      <div className={common.pageHead}>
        <div>
          <span className={common.eyebrow}><Icon name="check" /> База знаний банка</span>
          <h1>Тезисы аналитики</h1>
          <p className={common.muted}>Новый обзор: загрузка PDF → распознавание → черновики с автоматическими проверками →
            ваша проверка. В разборы попадают только опубликованные тезисы.</p>
        </div>
      </div>
      <Upload onDone={() => setTick((n) => n + 1)} />
      <Card title="Документы">
        {list.error && <ErrorState error={list.error} onRetry={list.reload} />}
        {!list.data && !list.error && <Skeleton lines={3} />}
        {list.data && !list.data.items.length && <EmptyState>Загруженных документов пока нет.</EmptyState>}
        {list.data && list.data.items.length > 0 && (
          <ul className={styles.docs}>
            {list.data.items.map((d) => (
              <li key={d.doc_id}>
                <div>
                  <Link href={`/admin/kb/${encodeURIComponent(d.doc_id)}`}><strong>{d.title || d.filename}</strong></Link>
                  <small className={common.muted}>{d.filename} · {d.pages ?? "?"} стр. · загружен {date(d.created_at)}
                    {d.date ? ` · дата обзора ${date(d.date)}` : ""}</small>
                  {d.error && <small className={styles.error}>{d.error}</small>}
                </div>
                <span className={`${styles.status} ${styles[d.status]}`}>{STATUS[d.status]}</span>
                <span className={styles.counts} aria-label="Черновики">
                  <b>{d.drafts.draft}</b> ждут · <b>{d.drafts.approved}</b> опубликовано · <b>{d.drafts.rejected}</b> отклонено
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Upload({ onDone }: { onDone: () => void }) {
  const file = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [docDate, setDocDate] = useState("");
  const [state, setState] = useState<{ busy: boolean; message?: string; error?: string }>({ busy: false });

  const submit = async () => {
    const f = file.current?.files?.[0];
    if (!f) return setState({ busy: false, error: "Выберите PDF" });
    setState({ busy: true });
    try {
      const r = await api.kbUpload(f, { title: title || undefined, date: docDate || undefined });
      setState({ busy: false, message: r.created ? "Документ поставлен на распознавание" : "Этот файл уже загружен" });
      if (file.current) file.current.value = "";
      onDone();
    } catch (e) {
      setState({ busy: false, error: errorText(e) });
    }
  };

  return (
    <Card title="Загрузить обзор">
      <div className={styles.upload}>
        <label className={forms.field}>PDF (до 20 МБ)
          <input ref={file} type="file" accept="application/pdf,.pdf" className={forms.input} />
        </label>
        <label className={forms.field}>Название (если не распознается)
          <input className={forms.input} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} />
        </label>
        <label className={forms.field}>Дата обзора
          <input className={forms.input} type="date" value={docDate} onChange={(e) => setDocDate(e.target.value)} />
        </label>
        <button type="button" className={`${common.btn} ${common.btnPrimary}`} disabled={state.busy} onClick={submit}>
          {state.busy ? "Загружаем…" : "Загрузить"}
        </button>
      </div>
      {state.message && <p className={common.muted} role="status">{state.message}</p>}
      {state.error && <ErrorState error={state.error} />}
    </Card>
  );
}
