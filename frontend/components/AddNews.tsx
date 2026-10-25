"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { invalidate } from "@/lib/query";
import { Card, ErrorState, Icon } from "./ui";
import styles from "@/components/AddNews.module.scss";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";

export default function AddNews({ onAdded, compact = false }: { onAdded: () => void; compact?: boolean }) {
  const router = useRouter();
  const [mode, setMode] = useState<"text" | "url">("url");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const r = await api.addNews(mode === "url" ? { url } : { text });
      setText("");
      setUrl("");
      invalidate("feed:");  // новая новость меняет все ленты компании
      onAdded();
      if (!r.created) setNote("Такая новость уже есть — источник добавлен к существующей записи.");
      router.push(`/pulse/n/${encodeURIComponent(r.news.news_id)}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось добавить новость");
    } finally {
      setBusy(false);
    }
  };

  const valid = mode === "url" ? /^https?:\/\/.+/.test(url) : text.trim().length >= 40;
  const left = mode === "text" ? Math.max(0, 40 - text.trim().length) : 0;
  const hint = mode === "url"
    ? (url && !valid ? "Ссылка должна начинаться с https://" : "Вставьте ссылку на статью — разберем ее для вашей компании")
    : (left > 0 ? `Еще хотя бы ${left} симв. — чтобы было что разбирать` : "Готово к разбору");
  return (
    <Card title={<><Icon name="spark" size={16} /> Проверить свою новость</>} className={`${styles.addNews} ${compact ? styles.addNewsCompact : ""}`}>
      {!compact && <p className={`${common.muted} ${common.small}`}>Вставьте текст или ссылку на любую новость — сервис разберет ее для вашей компании.</p>}
      {/* Переключатель со скользящей подложкой: она плавно переезжает под выбранный вариант. */}
      <div className={styles.seg} data-mode={mode}>
        <span className={styles.segThumb} aria-hidden="true" />
        <button type="button" className={mode === "text" ? styles.on : ""} aria-pressed={mode === "text"} onClick={() => setMode("text")}>
          <Icon name="doc" size={15} />Текст</button>
        <button type="button" className={mode === "url" ? styles.on : ""} aria-pressed={mode === "url"} onClick={() => setMode("url")}>
          <Icon name="link" size={15} />Ссылка</button>
      </div>
      <div className={styles.field}>
        <span className={styles.fieldIcon}><Icon name={mode === "url" ? "link" : "doc"} size={16} /></span>
        {mode === "text" ? (
          <textarea className={`${forms.textarea} ${styles.control}`} rows={compact ? 3 : 4} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="Например: Минфин предложил повысить НДС…" maxLength={20000} />
        ) : (
          <input className={`${forms.input} ${styles.control}`} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…"
            maxLength={2000} inputMode="url" onKeyDown={(e) => { if (e.key === "Enter" && valid && !busy) void submit(); }} />
        )}
      </div>
      <p className={`${styles.hint} ${valid ? styles.hintOk : ""}`}>{hint}</p>
      {error && <ErrorState error={error} />}
      {note && <p className={`${common.muted} ${common.small}`}>{note}</p>}
      <button className={`${styles.btn} ${common.btnPrimary} ${styles.go}`} disabled={!valid || busy} onClick={submit}>
        {busy ? <><span className={styles.spinner} aria-hidden="true" />Анализируем…</> : <>Разобрать<Icon name="chevronRight" size={16} /></>}
      </button>
    </Card>
  );
}
