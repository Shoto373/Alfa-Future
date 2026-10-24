"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { invalidate } from "@/lib/query";
import { Card, ErrorState } from "./ui";
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
  return (
    <Card title="Проверить свою новость" className={compact ? styles.addNewsCompact : ""}>
      {!compact && <p className={`${common.muted} ${common.small}`}>Вставьте текст или ссылку на любую новость — сервис разберет ее для вашей компании.</p>}
      <div className={styles.seg}>
        <button className={mode === "text" ? styles.on : ""} onClick={() => setMode("text")}>Текст</button>
        <button className={mode === "url" ? styles.on : ""} onClick={() => setMode("url")}>Ссылка</button>
      </div>
      {mode === "text" ? (
        <textarea className={forms.textarea} rows={compact ? 2 : 3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Например: Минфин предложил повысить НДС…" maxLength={20000} />
      ) : (
        <input className={forms.input} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" maxLength={2000} />
      )}
      {error && <ErrorState error={error} />}
      {note && <p className={`${common.muted} ${common.small}`}>{note}</p>}
      <button className={`${styles.btn} ${common.btnPrimary}`} disabled={!valid || busy} onClick={submit}>{busy ? "Анализируем…" : "Разобрать"}</button>
    </Card>
  );
}
