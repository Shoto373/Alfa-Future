"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { date } from "@/lib/format";
import type { Claim, Insight, Role, Source } from "@/lib/types";
import Chat from "./Chat";
import { Card, Icon, OriginTag, Score } from "./ui";

const STAGE: Record<string, string> = { plan: "План", tool: "Инструмент", compose: "Черновик", check: "Самопроверка", adapt: "Коррекция", finalize: "Итог" };
const CHECK: Record<string, string> = {
  completeness: "Все разделы заполнены",
  sources_linked: "У каждого вывода есть источник",
  bank_view_grounded: "Позиция банка — только из материалов банка",
  bank_view_found: "Проверен результат поиска аналитики банка",
  numbers_grounded: "Цифры подтверждены источниками",
  consistent_with_client: "Нет противоречий с данными компании",
  personalized: "Вывод опирается на признаки компании",
  evidence_boundaries: "Проверены источники и доступность признаков",
  headline_grounded: "Проверен заголовок",
  bank_summary_grounded: "Резюме банка сверено с тезисом",
};

function SourceRefs({ ids, index }: { ids: string[]; index: Map<string, number> }) {
  const refs = ids.filter((id) => index.has(id));
  if (!refs.length) return null;
  return (
    <span className="refs">
      {refs.map((id) => <a key={id} href={`#src-${index.get(id)}`} title="Перейти к источнику">[{index.get(id)}]</a>)}
    </span>
  );
}

function ClaimList({ items, index, empty = "Нет данных" }: { items: Claim[]; index: Map<string, number>; empty?: string }) {
  if (!items.length) return <p className="muted">{empty}</p>;
  return (
    <ul className="claims">
      {items.map((c, i) => (
        <li key={i}>
          <OriginTag origin={c.origin} />
          <span>{c.text}</span>
          <SourceRefs ids={c.source_ids} index={index} />
        </li>
      ))}
    </ul>
  );
}

function Feedback({ insightId, section, role }: { insightId: string; section: string; role: Role }) {
  const [sent, setSent] = useState<1 | -1 | null>(null);
  const send = (r: 1 | -1) => api.feedback(insightId, r, section, role).then(() => setSent(r)).catch(() => setSent(null));
  return (
    <span className="feedback" aria-label="Оцените раздел">
      {sent ? <span className="muted small">Спасибо за оценку</span> : (
        <>
          <button className="icon-btn" onClick={() => send(1)} aria-label="Полезно"><Icon name="thumbUp" size={16} /></button>
          <button className="icon-btn" onClick={() => send(-1)} aria-label="Не полезно"><Icon name="thumbDown" size={16} /></button>
        </>
      )}
    </span>
  );
}

function sourceLink(s: Source): string | null {
  if (s.kind === "news") return s.url;
  if (s.kind === "bank_analytics" && s.doc_id) return api.pdfUrl(s.doc_id, s.page);
  return null;
}

export default function InsightView({ insight: ins, onRefresh, refreshing }: { insight: Insight; onRefresh: () => void; refreshing: boolean }) {
  const index = new Map(ins.sources.map((s, i) => [s.source_id, i + 1]));
  const [showTrace, setShowTrace] = useState(false);
  const fb = (section: string) => <Feedback insightId={ins.insight_id} section={section} role={ins.role} />;

  return (
    <div className="insight">
      <div className="insight-head">
        <div className="insight-badges">
          <Score value={ins.relevance.score} />
          <span className={`mode mode-${ins.mode}`}>{ins.mode === "llm" ? `AI-агент · ${ins.model}` : "Агент на правилах"}</span>
          <span className={`quality-pill ${ins.quality.passed ? "ok" : "warn"}`}>
            {ins.quality.passed ? "Самопроверка пройдена" : "Самопроверка с замечаниями"}
            {ins.quality.attempts > 1 ? ` · попыток: ${ins.quality.attempts}` : ""}
          </span>
        </div>
        <p className="news-title">{ins.title}</p>
        <h1>{ins.headline}</h1>
        <div className="insight-actions">
          <button className="btn btn-secondary btn-sm" onClick={onRefresh} disabled={refreshing}>
            <Icon name="refresh" size={16} /> {refreshing ? "Пересчитываем…" : "Пересчитать"}
          </button>
          <button className="btn btn-secondary btn-sm" onClick={() => setShowTrace((v) => !v)}>
            {showTrace ? "Скрыть ход анализа" : "Как получен вывод"}
          </button>
          <span className="muted small">{date(ins.created_at)} · {ins.insight_id}</span>
        </div>
      </div>

      {showTrace && (
        <Card title="Ход анализа агента" className="trace-card">
          <ol className="trace">
            {ins.trace.map((s) => (
              <li key={s.step} className={`trace-${s.status}`}>
                <span className="trace-stage">{STAGE[s.stage] ?? s.stage}</span>
                <code>{s.name}</code>
                <span>{s.detail}</span>
                {s.duration_ms > 0 && <span className="muted small">{s.duration_ms} мс</span>}
              </li>
            ))}
          </ol>
          <h4>Самопроверка</h4>
          <ul className="checks">
            {ins.quality.checks.map((c) => (
              <li key={c.name} className={c.passed ? "ok" : "warn"}>{c.passed ? "✓" : "!"} {CHECK[c.name] ?? c.name}<span className="muted small"> — {c.detail}</span></li>
            ))}
          </ul>
        </Card>
      )}

      <div className="insight-grid">
        <Card title="1. Что произошло" actions={fb("what_happened")}>
          <ClaimList items={ins.what_happened.facts} index={index} />
          {(ins.what_happened.actors.length > 0 || ins.what_happened.dates.length > 0) && (
            <p className="muted small">
              {ins.what_happened.actors.length > 0 && <>Участники: {ins.what_happened.actors.join(", ")}. </>}
              {ins.what_happened.dates.length > 0 && <>Даты: {ins.what_happened.dates.join(", ")}.</>}
            </p>
          )}
          {ins.what_happened.assumptions.length > 0 && (<><h4>Предположения</h4><ClaimList items={ins.what_happened.assumptions} index={index} /></>)}
        </Card>

        <Card title="2. Почему это важно для компании" actions={fb("why_important")}>
          <ClaimList items={ins.why_important} index={index} />
          {ins.features_used.length > 0 && (
            <div className="features">
              <h4>Признаки компании, повлиявшие на вывод</h4>
              <ul className="kv">{ins.features_used.map((f) => <li key={f.name}><span>{f.label}</span><strong>{f.value}</strong></li>)}</ul>
            </div>
          )}
        </Card>

        <Card title="3. Какие последствия возможны" actions={fb("consequences")} className="span-2">
          <div className="two-col">
            <div><h4 className="neg">Риски</h4><ClaimList items={ins.risks} index={index} empty="Существенных рисков не выявлено" /></div>
            <div><h4 className="pos">Возможности</h4><ClaimList items={ins.opportunities} index={index} empty="Явных возможностей не выявлено" /></div>
          </div>
        </Card>

        <Card title="4. Что можно сделать" actions={fb("actions")}>
          <ClaimList items={ins.actions} index={index} />
          {ins.questions.length > 0 && (<><h4>Вопросы для дополнительного анализа</h4><ul className="plain">{ins.questions.map((q) => <li key={q}>{q}</li>)}</ul></>)}
          {ins.products.length > 0 && (
            <div className="offers">
              <span className="offer-label">Предложение банка</span>
              {ins.products.map((p) => (
                <div className="offer" key={p.product_id}><strong>{p.title}</strong><span>{p.text}</span></div>
              ))}
            </div>
          )}
        </Card>

        <Card title="5. Как это оценивает Альфа-Банк" actions={fb("bank_view")} className="bank-card">
          {ins.bank_view.available ? (
            <>
              {ins.bank_view.summary && <p className="bank-summary">{ins.bank_view.summary}</p>}
              <ClaimList items={ins.bank_view.theses.slice(ins.bank_view.summary ? 1 : 0)} index={index} />
            </>
          ) : <p className="muted">Материалы банка по этой теме не найдены — вывод сформирован только по данным компании и новости.</p>}
          {ins.bank_view.conflicts.map((c) => <p key={c} className="conflict">{c}</p>)}
        </Card>

        <Card title="6. На чем основан вывод" className="span-2">
          <ol className="sources">
            {ins.sources.map((s, i) => {
              const link = sourceLink(s);
              return (
                <li key={s.source_id} id={`src-${i + 1}`}>
                  <span className={`src-kind src-${s.kind}`}>{{ news: "Новость", bank_analytics: "Аналитика банка", client_data: "Данные компании", bank_product: "Продукт банка" }[s.kind]}</span>
                  <div>
                    <strong>{s.title}</strong>{s.page ? `, стр. ${s.page}` : ""}{s.date ? ` · ${date(s.date)}` : ""}
                    {s.excerpt && <p className="muted small">{s.excerpt}</p>}
                  </div>
                  {link && <a className="btn btn-link btn-sm" href={link} target="_blank" rel="noreferrer"><Icon name="link" size={14} /> Первоисточник</a>}
                </li>
              );
            })}
          </ol>
          <h4>Почему новость попала в вашу ленту</h4>
          <ul className="plain">{ins.relevance.reasons.map((r, i) => <li key={i}>{r.text}</li>)}</ul>
        </Card>
      </div>

      <Chat insightId={ins.insight_id} suggestions={["Какие источники использованы?", "Покажи в разрезе контрагентов", "Что думает банк о ставке?", "Какое место компании в отрасли?"]} />
      <p className="disclaimer">{ins.disclaimer}</p>
    </div>
  );
}
