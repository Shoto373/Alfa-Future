"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { Card, ErrorBox } from "./ui";

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
    <Card title="Проверить свою новость" className={`add-news ${compact ? "add-news-compact" : ""}`}>
      {!compact && <p className="muted small">Вставьте текст или ссылку на любую новость — сервис разберет ее для вашей компании.</p>}
      <div className="seg">
        <button className={mode === "text" ? "on" : ""} onClick={() => setMode("text")}>Текст</button>
        <button className={mode === "url" ? "on" : ""} onClick={() => setMode("url")}>Ссылка</button>
      </div>
      {mode === "text" ? (
        <textarea rows={compact ? 2 : 3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Например: Минфин предложил повысить НДС…" maxLength={20000} />
      ) : (
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" maxLength={2000} />
      )}
      {error && <ErrorBox message={error} />}
      {note && <p className="muted small">{note}</p>}
      <button className="btn btn-primary" disabled={!valid || busy} onClick={submit}>{busy ? "Анализируем…" : "Разобрать"}</button>
    </Card>
  );
}
