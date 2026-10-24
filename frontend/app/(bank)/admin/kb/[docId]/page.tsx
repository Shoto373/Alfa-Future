"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { STATUS } from "@/app/(bank)/admin/kb/status";
import { Card, ErrorState, Icon, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { date } from "@/lib/format";
import { useLoad } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { KbDocument, KbDraft } from "@/lib/types";
import styles from "@/app/(bank)/admin/kb/page.module.scss";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";

const FILTERS = [
  { key: "draft", label: "Ждут проверки" }, { key: "approved", label: "Опубликованы" }, { key: "rejected", label: "Отклонены" },
] as const;

/** Проверка черновиков документа: страница PDF рядом с черновиками, правка, публикация и отклонение. */
export default function KbDocumentPage() {
  const { docId } = useParams<{ docId: string }>();
  const { session } = useSession();
  const [doc, setDoc] = useState<KbDocument | null>(null);
  const [filter, setFilter] = useState<KbDraft["status"]>("draft");
  const load = useLoad((signal) => api.kbDocument(decodeURIComponent(docId), signal).then((d) => { setDoc(d); return d; }), [docId]);

  if (!session!.user.is_operator) return <Card><p>Раздел доступен аналитикам банка.</p></Card>;
  if (load.error) return <ErrorState error={load.error} onRetry={load.reload} />;
  const current = doc ?? load.data;
  if (!current) return <Skeleton lines={6} />;

  const replace = (d: KbDraft) => setDoc({ ...current, drafts: current.drafts.map((x) => (x.draft_id === d.draft_id ? d : x)) });
  const shown = current.drafts.filter((d) => d.status === filter);
  const pages = [...new Set(shown.map((d) => d.page))].sort((a, b) => a - b);

  return (
    <div className={common.page}>
      <nav><Link href="/admin/kb" className={styles.back}><Icon name="chevron" size={14} /> Все документы</Link></nav>
      <DocumentHead doc={current} onSaved={setDoc} />
      <div className={styles.filters} role="toolbar" aria-label="Статус черновиков">
        {FILTERS.map((f) => (
          <button key={f.key} type="button" aria-pressed={filter === f.key} className={filter === f.key ? styles.on : undefined}
            onClick={() => setFilter(f.key)}>
            {f.label} ({current.drafts.filter((d) => d.status === f.key).length})
          </button>
        ))}
      </div>
      {!shown.length && <Card><p className={common.muted}>Здесь пусто.</p></Card>}
      {pages.map((page) => (
        <section key={page} className={styles.page} aria-label={`Страница ${page}`}>
          <PageView doc={current} page={page} />
          <div className={styles.drafts}>
            {shown.filter((d) => d.page === page).map((d) => (
              <DraftCard key={d.draft_id} draft={d} topics={current.topics} onChange={replace} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function DocumentHead({ doc, onSaved }: { doc: KbDocument; onSaved: (d: KbDocument) => void }) {
  const [title, setTitle] = useState(doc.title ?? "");
  const [docDate, setDocDate] = useState(doc.date ?? "");
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setError(null);
    try {
      onSaved(await api.kbDocumentMeta(doc.doc_id, { title, date: docDate || undefined }));
    } catch (e) {
      setError(errorText(e));
    }
  };
  return (
    <Card>
      <div className={styles.head}>
        <div>
          <h1>{doc.title || doc.filename}</h1>
          <p className={common.muted}>{doc.filename} · {doc.pages ?? "?"} стр. · {STATUS[doc.status]}
            {doc.model ? ` · распознавание: ${doc.model}` : ""}</p>
          {doc.error && <ErrorState error={doc.error} />}
        </div>
        <a className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} href={api.kbPdfUrl(doc.doc_id)} target="_blank" rel="noreferrer">
          Открыть PDF
        </a>
      </div>
      <div className={styles.upload}>
        <label className={forms.field}>Название<input className={forms.input} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
        <label className={forms.field}>Дата обзора<input className={forms.input} type="date" value={docDate.slice(0, 10)}
          onChange={(e) => setDocDate(e.target.value)} /></label>
        <button type="button" className={`${common.btn} ${common.btnSecondary}`} onClick={save}>Сохранить</button>
      </div>
      {error && <ErrorState error={error} />}
    </Card>
  );
}

function PageView({ doc, page }: { doc: KbDocument; page: number }) {
  const [noImage, setNoImage] = useState(false);
  return (
    <figure className={styles.scan}>
      <figcaption>Страница {page} · <a href={api.kbPdfUrl(doc.doc_id, page)} target="_blank" rel="noreferrer">в PDF</a></figcaption>
      {!noImage
        // eslint-disable-next-line @next/next/no-img-element -- скан страницы с API (cookie сессии), не статический ресурс
        ? <img src={api.kbPageImageUrl(doc.doc_id, page)} alt={`Скан страницы ${page}`} onError={() => setNoImage(true)} />
        : <pre>{doc.page_texts[String(page)] || "Текст страницы не распознан"}</pre>}
    </figure>
  );
}

function DraftCard({ draft, topics, onChange }: { draft: KbDraft; topics: Record<string, string>; onChange: (d: KbDraft) => void }) {
  const [edit, setEdit] = useState({ text: draft.text ?? "", value: draft.value ?? "", metric: draft.metric ?? "",
                                     horizon: draft.horizon ?? "", topic: draft.topic ?? "", sectors: (draft.sectors ?? []).join(", ") });
  const [supersede, setSupersede] = useState(true);
  const [reason, setReason] = useState("");
  const [state, setState] = useState<{ busy: boolean; error?: string }>({ busy: false });
  const open = draft.status === "draft";
  const changed = edit.text !== (draft.text ?? "") || edit.value !== (draft.value ?? "") || edit.metric !== (draft.metric ?? "")
    || edit.horizon !== (draft.horizon ?? "") || edit.topic !== (draft.topic ?? "") || edit.sectors !== (draft.sectors ?? []).join(", ");

  const run = async (action: () => Promise<KbDraft | void>) => {
    setState({ busy: true });
    try {
      const updated = await action();
      if (updated) onChange(updated);
      setState({ busy: false });
    } catch (e) {
      setState({ busy: false, error: errorText(e) });
    }
  };
  const patch = () => api.kbEditDraft(draft.draft_id, { ...edit, sectors: edit.sectors.split(",").map((s) => s.trim()).filter(Boolean) });
  const save = () => run(patch);
  // Правка, если есть, сохраняется перед публикацией: публикуется то, что аналитик видит.
  const approve = () => run(async () => {
    const saved = changed ? await patch() : draft;
    const r = await api.kbApprove(draft.draft_id, supersede ? draft.supersedes_candidate : null);
    return { ...saved, status: "approved", thesis_id: r.thesis.id };
  });
  const reject = () => run(() => api.kbReject(draft.draft_id, reason || "Не тезис банка"));

  return (
    <article className={styles.draft} data-testid="kb-draft">
      <ul className={styles.checks} aria-label="Автоматические проверки">
        {draft.checks.map((c) => <li key={c.name} className={c.ok ? styles.ok : styles.fail} title={c.detail}>{c.ok ? "✓" : "✗"} {c.detail}</li>)}
      </ul>
      {draft.quote && <blockquote className={styles.quote}>«{draft.quote}»</blockquote>}
      <label className={forms.field}>Тезис
        <textarea className={forms.textarea} rows={3} value={edit.text} disabled={!open} onChange={(e) => setEdit({ ...edit, text: e.target.value })} />
      </label>
      <div className={styles.fields}>
        <label className={forms.field}>Тема
          <select className={forms.select} value={edit.topic} disabled={!open} onChange={(e) => setEdit({ ...edit, topic: e.target.value })}>
            {Object.entries(topics).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className={forms.field}>Показатель<input className={forms.input} value={edit.metric} disabled={!open} onChange={(e) => setEdit({ ...edit, metric: e.target.value })} /></label>
        <label className={forms.field}>Значение<input className={forms.input} value={edit.value} disabled={!open} onChange={(e) => setEdit({ ...edit, value: e.target.value })} /></label>
        <label className={forms.field}>Горизонт<input className={forms.input} value={edit.horizon} disabled={!open} onChange={(e) => setEdit({ ...edit, horizon: e.target.value })} /></label>
        <label className={forms.field}>Отрасли<input className={forms.input} value={edit.sectors} disabled={!open} onChange={(e) => setEdit({ ...edit, sectors: e.target.value })} /></label>
      </div>
      {open ? (
        <div className={styles.actions}>
          {draft.supersedes_candidate && (
            <label className={forms.check}><input type="checkbox" checked={supersede} onChange={(e) => setSupersede(e.target.checked)} />
              Заменяет прежний прогноз {draft.supersedes_candidate}</label>
          )}
          <button type="button" className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} disabled={!changed || state.busy} onClick={save}>Сохранить правку</button>
          <button type="button" className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`} disabled={state.busy} onClick={approve}>Опубликовать</button>
          <input className={`${forms.input} ${styles.reason}`} placeholder="Причина отклонения" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} />
          <button type="button" className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} disabled={state.busy} onClick={reject}>Отклонить</button>
        </div>
      ) : (
        <p className={common.muted}>
          {draft.status === "approved" ? `Опубликован как ${draft.thesis_id}` : `Отклонен: ${draft.reject_reason ?? ""}`}
          {draft.reviewed_by ? ` · ${draft.reviewed_by}` : ""}{draft.reviewed_at ? ` · ${date(draft.reviewed_at)}` : ""}
        </p>
      )}
      {state.error && <ErrorState error={state.error} />}
    </article>
  );
}
