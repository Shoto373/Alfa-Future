"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Answer } from "@/lib/types";
import { Card, ErrorBox, OriginTag } from "./ui";

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
    <Card title="Уточнить у аналитика" className="chat">
      <div className="chips">
        {suggestions.map((s) => <button key={s} className="chip" onClick={() => ask(s)} disabled={busy}>{s}</button>)}
      </div>
      <div className="chat-log" aria-live="polite">
        {history.map((a, i) => (
          <div key={i} className="chat-turn">
            <p className="chat-q">{a.question}</p>
            <div className={`chat-a ${a.refused ? "refused" : ""}`}>
              <p>{a.answer}</p>
              {a.claims.length > 0 && (
                <ul className="claims">
                  {a.claims.map((c, j) => <li key={j}><OriginTag origin={c.origin} /><span>{c.text}</span></li>)}
                </ul>
              )}
              {a.sources.length > 0 && <p className="muted small">Источники: {a.sources.map((s) => s.title + (s.page ? `, стр. ${s.page}` : "")).join("; ")}</p>}
              <p className="muted small">{a.mode === "llm" ? "Ответ модели" : "Ответ на правилах"}</p>
            </div>
          </div>
        ))}
        {busy && <p className="muted">Ищем ответ…</p>}
      </div>
      {error && <ErrorBox message={error} />}
      <form className="chat-form" onSubmit={(e) => { e.preventDefault(); void ask(q); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Например: а если рубль ослабнет еще сильнее?" maxLength={1000} />
        <button className="btn btn-primary" disabled={busy || q.trim().length < 2}>Спросить</button>
      </form>
    </Card>
  );
}
