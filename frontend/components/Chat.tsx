"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Answer } from "@/lib/types";
import { Card, ErrorBox, OriginTag } from "./ui";
import styles from "@/components/Chat.module.scss";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";

export default function Chat({ insightId, suggestions }: { insightId: string; suggestions: string[] }) {
  const [q, setQ] = useState("");
  const [history, setHistory] = useState<Answer[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const a = await api.ask(insightId, question.trim());
      setHistory((h) => [...h, a]);
      setQ("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось получить ответ");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Уточнить у аналитика" className={styles.chat}>
      <div className={styles.chips}>
        {suggestions.map((s) => <button key={s} className={styles.chip} onClick={() => ask(s)} disabled={busy}>{s}</button>)}
      </div>
      <div className={styles.chatLog} aria-live="polite">
        {history.map((a, i) => (
          <div key={i} data-testid="chat-turn">
            <p className={styles.chatQ}>{a.question}</p>
            <div className={`${styles.chatA} ${a.refused ? styles.refused : ""}`}>
              <p>{a.answer}</p>
              {a.claims.length > 0 && (
                <ul className={common.claims}>
                  {a.claims.map((c, j) => <li key={j}><OriginTag origin={c.origin} /><span>{c.text}</span></li>)}
                </ul>
              )}
              {a.sources.length > 0 && <p className={`${common.muted} ${common.small}`}>Источники: {a.sources.map((s) => s.title + (s.page ? `, стр. ${s.page}` : "")).join("; ")}</p>}
              <p className={`${common.muted} ${common.small}`}>{a.mode === "llm" ? "Ответ модели" : "Ответ на правилах"}</p>
            </div>
          </div>
        ))}
        {busy && <p className={common.muted}>Ищем ответ…</p>}
      </div>
      {error && <ErrorBox message={error} />}
      <form className={styles.chatForm} onSubmit={(e) => { e.preventDefault(); void ask(q); }}>
        <input className={forms.input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Например: а если рубль ослабнет еще сильнее?" maxLength={1000} />
        <button className={`${common.btn} ${common.btnPrimary}`} disabled={busy || q.trim().length < 2}>Спросить</button>
      </form>
    </Card>
  );
}
