"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Answer } from "@/lib/types";
import { ErrorBox, Icon, OriginTag } from "./ui";

// Помощник по разбору: круглая кнопка справа снизу, по клику — панель вопросов к аналитику.
// История вопросов сохраняется, пока открыт этот разбор (панель только скрывается).
export default function Chat({ insightId, suggestions }: { insightId: string; suggestions: string[] }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [history, setHistory] = useState<Answer[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const log = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" });
  }, [history.length, busy]);

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
      // Поле было заблокировано на время ответа — курсор возвращается для следующего вопроса.
      requestAnimationFrame(() => input.current?.focus());
    }
  };

  return (
    <>
      {open && (
        <section className="assistant-panel" role="dialog" aria-label="Уточнить у аналитика">
          <header className="assistant-head">
            <div>
              <strong>Уточнить у аналитика</strong>
              <span className="muted small">Ответы по этому разбору и его источникам</span>
            </div>
            <button type="button" className="icon-btn" aria-label="Свернуть" onClick={() => setOpen(false)}>
              <Icon name="close" size={18} />
            </button>
          </header>
          <div className="assistant-body chat" ref={log} aria-live="polite">
            <div className="chips">
              {suggestions.map((s) => <button key={s} className="chip" onClick={() => ask(s)} disabled={busy}>{s}</button>)}
            </div>
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
                </div>
              </div>
            ))}
            {busy && <p className="muted">Ищем ответ…</p>}
            {error && <ErrorBox message={error} />}
          </div>
          <form className="chat-form assistant-form" onSubmit={(e) => { e.preventDefault(); void ask(q); }}>
            <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} maxLength={1000} disabled={busy} aria-busy={busy}
              placeholder={busy ? "Аналитик готовит ответ…" : "Например: а если рубль ослабнет еще сильнее?"} />
            <button className="btn btn-primary" disabled={busy || q.trim().length < 2} aria-label="Спросить">
              <Icon name="send" size={18} />
            </button>
          </form>
        </section>
      )}
      {!open && (
        <button type="button" className="assistant-fab" aria-expanded={false}
          aria-label="Уточнить у аналитика" title="Уточнить у аналитика" onClick={() => setOpen(true)}>
          <Icon name="chat" size={26} />
          {history.length > 0 && <span className="assistant-badge">{history.length}</span>}
        </button>
      )}
    </>
  );
}
