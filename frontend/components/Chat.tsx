"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Answer } from "@/lib/types";
import { ErrorState, Icon, OriginTag } from "./ui";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";
import styles from "@/components/Chat.module.scss";

// Помощник по разбору: круглая кнопка справа снизу, по клику — панель вопросов к аналитику.
// Диалог (SPR4-05): история хранится на сервере — при возврате к разбору прежние ответы на месте;
// после ответа — следующие вопросы под роль; у каждого ответа — оценка «полезно / нет».
export default function Chat({ insightId, suggestions }: { insightId: string; suggestions: string[] }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [history, setHistory] = useState<Answer[]>([]);
  const [next, setNext] = useState<string[] | null>(null);
  const [rated, setRated] = useState<Record<number, 1 | -1>>({});
  const loaded = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const log = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || loaded.current) return;
    loaded.current = true;
    api.dialog(insightId).then((turns) => {
      setHistory((h) => (h.length ? h : turns));
      setRated(Object.fromEntries(turns.filter((t) => t.rating).map((t) => [t.turn_id, t.rating as 1 | -1])));
    }).catch(() => { /* без истории диалог работает как раньше */ });
  }, [open, insightId]);

  const rate = (turnId: number, rating: 1 | -1) => {
    setRated((r) => ({ ...r, [turnId]: rating }));
    api.rateAnswer(insightId, turnId, rating).catch(() => setRated((r) => Object.fromEntries(Object.entries(r).filter(([k]) => Number(k) !== turnId))));
  };

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
      setNext(a.suggestions);
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
        <section className={styles.assistantPanel} role="dialog" aria-label="Уточнить у аналитика">
          <header className={styles.assistantHead}>
            <div>
              <strong>Уточнить у аналитика</strong>
              <span className={`${common.muted} ${common.small}`}>Ответы по этому разбору и его источникам</span>
            </div>
            <button type="button" className={common.iconBtn} aria-label="Свернуть" onClick={() => setOpen(false)}>
              <Icon name="close" size={18} />
            </button>
          </header>
          <div className={`${styles.assistantBody} ${styles.chat}`} ref={log} aria-live="polite">
            <div className={styles.chips}>
              {(next ?? suggestions).map((s) => <button key={s} className={styles.chip} onClick={() => ask(s)} disabled={busy}>{s}</button>)}
            </div>
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
                  {a.turn_id != null && !a.refused && (
                    <div className={styles.rate} role="group" aria-label="Оценка ответа">
                      <button type="button" aria-pressed={rated[a.turn_id] === 1} onClick={() => rate(a.turn_id!, 1)}>Полезно</button>
                      <button type="button" aria-pressed={rated[a.turn_id] === -1} onClick={() => rate(a.turn_id!, -1)}>Не помогло</button>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {busy && <p className={common.muted} role="status">Ищем ответ…</p>}
            {error && <ErrorState error={error} />}
          </div>
          <form className={`${styles.chatForm} ${styles.assistantForm}`} onSubmit={(e) => { e.preventDefault(); void ask(q); }}>
            <input className={forms.input} ref={input} value={q} onChange={(e) => setQ(e.target.value)} maxLength={1000} disabled={busy} aria-busy={busy}
              placeholder={busy ? "Аналитик готовит ответ…" : "Например: а если рубль ослабнет еще сильнее?"} />
            <button className={`${common.btn} ${common.btnPrimary} ${styles.sendButton}`} disabled={busy || q.trim().length < 2} aria-label="Спросить">
              <Icon name="send" size={18} />
            </button>
          </form>
        </section>
      )}
      {!open && (
        <button type="button" className={styles.assistantFab} aria-expanded={false}
          aria-label="Уточнить у аналитика" title="Уточнить у аналитика" onClick={() => setOpen(true)}>
          <Icon name="chat" size={26} />
          {history.length > 0 && <span className={styles.assistantBadge}>{history.length}</span>}
        </button>
      )}
    </>
  );
}
