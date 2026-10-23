"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { date } from "@/lib/format";
import type { Claim, Insight, Source } from "@/lib/types";
import Chat from "./Chat";
import { Card, EffectBadge, Icon, OriginTag, Score } from "./ui";
import styles from "@/components/InsightView.module.scss";
import common from "@/styles/common.module.scss";

const STAGE: Record<string, string> = { plan: "План", tool: "Инструмент", compose: "Черновик", check: "Самопроверка", adapt: "Коррекция", finalize: "Итог" };
const TRACE_STYLES: Record<string, string | undefined> = {
  warning: styles.traceWarning,
  error: styles.traceError,
};
const SOURCE_STYLES: Partial<Record<Source["kind"], string>> = {
  bank_analytics: styles.srcBankAnalytics,
  client_data: styles.srcClientData,
};
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
  semantic_review: "Выводы AI проверены второй моделью по источникам",
};

// Почему показан разбор на правилах — по полю fallback_reason разбора.
const INFO_REASONS = new Set(["disabled", "paused"]);
const FALLBACK_NOTE: Record<string, string> = {
  disabled: "AI-модель не подключена — показан проверенный разбор на правилах: данные компании и аналитика банка учтены.",
  paused: "AI временно выключен банком — показан проверенный разбор на правилах: данные компании и аналитика банка учтены.",
  budget: "Дневной лимит AI исчерпан — он обновится в 03:00 по Москве. Показан проверенный разбор на правилах: данные компании и аналитика банка учтены.",
  unavailable: "AI-модель сейчас не отвечает. Показан проверенный разбор на правилах — можно нажать «Пересчитать» позже.",
  checks: "Выводы AI-модели не прошли проверку фактов, поэтому показан проверенный разбор на правилах.",
  unknown: "AI-версия сейчас недоступна. Показан проверенный разбор на правилах — можно нажать «Пересчитать» позже.",
};

function SourceRefs({ ids, index }: { ids: string[]; index: Map<string, number> }) {
  const openSource = useContext(OpenSource);
  const refs = ids.filter((id) => index.has(id));
  if (!refs.length) return null;
  return (
    <span className={styles.refs}>
      {refs.map((id) => (
        <a key={id} href={`#src-${index.get(id)}`} title="Перейти к источнику"
          onClick={(e) => { e.preventDefault(); openSource(index.get(id)); }}>[{index.get(id)}]</a>
      ))}
    </span>
  );
}

// Карточка на правилах: рассуждения агента построены правилами, а не моделью, — и подписаны так же.
const RulesMode = createContext(false);
// Сноска [n] раскрывает свернутый блок источников и прокручивает к источнику n.
const OpenSource = createContext<(n?: number) => void>(() => {});

function ClaimList({ items, index, empty = "Нет данных" }: { items: Claim[]; index: Map<string, number>; empty?: string }) {
  const rules = useContext(RulesMode);
  if (!items.length) return <p className={styles.muted}>{empty}</p>;
  return (
    <ul className={common.claims}>
      {items.map((c, i) => (
        <li key={i}>
          <OriginTag origin={rules && c.origin === "ai" ? "rules" : c.origin} />
          <span>{c.text}</span>
          <SourceRefs ids={c.source_ids} index={index} />
        </li>
      ))}
    </ul>
  );
}

function Feedback({ insightId, section }: { insightId: string; section: string }) {
  const [sent, setSent] = useState<1 | -1 | null>(null);
  const send = (r: 1 | -1) => api.feedback(insightId, r, section).then(() => setSent(r)).catch(() => setSent(null));
  return (
    <span className={styles.feedback} aria-label="Оцените раздел">
      {sent ? <span className={`${styles.muted} ${common.small}`}>Спасибо за оценку</span> : (
        <>
          <button className={common.iconBtn} onClick={() => send(1)} aria-label="Полезно"><Icon name="thumbUp" size={16} /></button>
          <button className={common.iconBtn} onClick={() => send(-1)} aria-label="Не полезно"><Icon name="thumbDown" size={16} /></button>
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

export default function InsightView({ insight: ins, onRefresh, refreshing, upgrading = false, upgradeFailed = false }: {
  insight: Insight; onRefresh: () => void; refreshing: boolean; upgrading?: boolean; upgradeFailed?: boolean;
}) {
  const index = new Map(ins.sources.map((s, i) => [s.source_id, i + 1]));
  const [showTrace, setShowTrace] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const [focused, setFocused] = useState<number | null>(null);

  const openSource = useCallback((n?: number) => {
    setShowSources(true);
    if (!n) return;
    setFocused(n);
    history.replaceState(null, "", `#src-${n}`);
    // Блок раскрывается в этом же кадре — прокрутка после отрисовки.
    requestAnimationFrame(() => document.getElementById(`src-${n}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }, []);

  // Переход по ссылке вида …#src-3 открывает источники сразу.
  useEffect(() => {
    const m = /^#src-(\d+)$/.exec(window.location.hash);
    if (m) openSource(Number(m[1]));
  }, [openSource, ins.insight_id]);
  const fb = (section: string) => <Feedback insightId={ins.insight_id} section={section} />;

  return (
    <RulesMode.Provider value={ins.mode === "rules"}>
    <OpenSource.Provider value={openSource}>
    <div className={styles.insight}>
      <div className={styles.insightHead} data-testid="insight-header">
        <div className={styles.insightBadges}>
          <Score value={ins.relevance.score} />
          <EffectBadge effect={ins.effect} />
        </div>
        <p className={styles.newsTitle}>{ins.title}</p>
        <h1>{ins.headline}</h1>
        <div className={styles.insightActions}>
          <button className={`${common.btn} ${styles.btnSecondary} ${common.btnSm}`} onClick={onRefresh} disabled={refreshing || upgrading}>
            <Icon name="refresh" size={16} /> {refreshing ? "Пересчитываем…" : "Пересчитать"}
          </button>
          <button className={`${common.btn} ${styles.btnSecondary} ${common.btnSm}`} onClick={() => setShowTrace((v) => !v)}>
            {showTrace ? "Скрыть ход анализа" : "Как получен вывод"}
          </button>
          <span className={`${styles.muted} ${common.small}`}>{date(ins.created_at)}</span>
        </div>
        {upgrading && (
          <p className={styles.upgradeNote} role="status">
            Это быстрый разбор на правилах: данные компании и аналитика банка уже учтены. AI-модель дополняет выводы — карточка обновится сама.
          </p>
        )}
        {!upgrading && upgradeFailed && ins.mode === "rules" && (
          // Модель не подключена или выключена банком — штатный режим, не сбой: без предупреждающего оформления.
          <p className={`${styles.upgradeNote} ${INFO_REASONS.has(ins.fallback_reason ?? "") ? styles.upgradeNoteInfo : styles.upgradeNoteWarn}`} role="status">
            {FALLBACK_NOTE[ins.fallback_reason ?? ""] ?? FALLBACK_NOTE.unknown}
          </p>
        )}
      </div>

      {showTrace && (
        <Card title="Ход анализа агента">
          <ol className={styles.trace} data-testid="analysis-trace">
            {ins.trace.map((s) => (
              <li key={s.step} className={TRACE_STYLES[s.status]}>
                <span className={styles.traceStage}>{STAGE[s.stage] ?? s.stage}</span>
                <code>{s.name}</code>
                <span>{s.detail}</span>
                {s.duration_ms > 0 && <span className={`${styles.muted} ${common.small}`}>{s.duration_ms} мс</span>}
              </li>
            ))}
          </ol>
          <h4>Самопроверка</h4>
          <ul className={styles.checks} data-testid="quality-checks">
            {ins.quality.checks.map((c) => (
              <li key={c.name} className={c.passed ? styles.ok : styles.warn}>{c.passed ? "✓" : "!"} {CHECK[c.name] ?? c.name}<span className={`${styles.muted} ${common.small}`}> — {c.detail}</span></li>
            ))}
          </ul>
        </Card>
      )}

      <div className={styles.insightGrid}>
        <Card title="1. Что произошло" actions={fb("what_happened")}>
          <ClaimList items={ins.what_happened.facts} index={index} />
          {(ins.what_happened.actors.length > 0 || ins.what_happened.dates.length > 0) && (
            <p className={`${styles.muted} ${common.small}`}>
              {ins.what_happened.actors.length > 0 && <>Участники: {ins.what_happened.actors.join(", ")}. </>}
              {ins.what_happened.dates.length > 0 && <>Даты: {ins.what_happened.dates.join(", ")}.</>}
            </p>
          )}
          {ins.what_happened.assumptions.length > 0 && (<><h4>Предположения</h4><ClaimList items={ins.what_happened.assumptions} index={index} /></>)}
        </Card>

        <Card title="2. Почему это важно для компании" actions={fb("why_important")}>
          <ClaimList items={ins.why_important} index={index} />
          {ins.features_used.length > 0 && (
            <div className={styles.features}>
              <h4>Признаки компании, повлиявшие на вывод</h4>
              <ul className={styles.kv}>{ins.features_used.map((f) => <li key={f.name}><span>{f.label}</span><strong>{f.value}</strong></li>)}</ul>
            </div>
          )}
        </Card>

        <Card title="3. Какие последствия возможны" actions={fb("consequences")} className={styles.span2}>
          <div className={styles.twoCol}>
            <div><h4 className={styles.neg}>Риски</h4><ClaimList items={ins.risks} index={index} empty="Существенных рисков не выявлено" /></div>
            <div><h4 className={styles.pos}>Возможности</h4><ClaimList items={ins.opportunities} index={index} empty="Явных возможностей не выявлено" /></div>
          </div>
        </Card>

        <Card title="4. Что можно сделать" actions={fb("actions")}>
          <ClaimList items={ins.actions} index={index} />
          {ins.questions.length > 0 && (<><h4>Вопросы для дополнительного анализа</h4><ul className={common.plain}>{ins.questions.map((q) => <li key={q}>{q}</li>)}</ul></>)}
          {ins.products.length > 0 && (
            <div className={styles.offers}>
              <span className={styles.offerLabel}>Предложение банка</span>
              {ins.products.map((p) => (
                <div className={styles.offer} key={p.product_id}><strong>{p.title}</strong><span>{p.text}</span></div>
              ))}
            </div>
          )}
        </Card>

        <Card title="5. Как это оценивает Альфа-Банк" actions={fb("bank_view")} className={styles.bankCard}>
          {ins.bank_view.available ? (
            <>
              {ins.bank_view.summary && <p className={styles.bankSummary}>{ins.bank_view.summary}</p>}
              <ClaimList items={ins.bank_view.theses.slice(ins.bank_view.summary ? 1 : 0)} index={index} />
            </>
          ) : <p className={styles.muted}>Материалы банка по этой теме не найдены — вывод сформирован только по данным компании и новости.</p>}
          {ins.bank_view.conflicts.map((c) => <p key={c} className={styles.conflict}>{c}</p>)}
        </Card>

        <Card className={styles.span2} title={
          <button type="button" className={styles.collapseToggle} aria-expanded={showSources} aria-controls="insight-sources"
            onClick={() => setShowSources((v) => !v)}>
            6. На чем основан вывод <span className={styles.muted}>· {ins.sources.length}</span>
            <Icon name="chevron" size={18} />
          </button>
        }>
          {showSources && <ol className={styles.sources} id="insight-sources">
            {ins.sources.map((s, i) => {
              const link = sourceLink(s);
              return (
                <li key={s.source_id} id={`src-${i + 1}`} className={focused === i + 1 ? styles.focused : undefined}>
                  <span className={`${styles.srcKind} ${SOURCE_STYLES[s.kind] ?? ""}`}>{{ news: "Новость", bank_analytics: "Аналитика банка", client_data: "Данные компании", bank_product: "Продукт банка" }[s.kind]}</span>
                  <div>
                    <strong>{s.title}</strong>{s.page ? `, стр. ${s.page}` : ""}{s.date ? ` · ${date(s.date)}` : ""}
                    {s.excerpt && <p className={`${styles.muted} ${common.small}`}>{s.excerpt}</p>}
                  </div>
                  {link && <a className={`${common.btn} ${common.btnLink} ${common.btnSm}`} href={link} target="_blank" rel="noreferrer"><Icon name="link" size={14} /> Первоисточник</a>}
                </li>
              );
            })}
          </ol>}
          <h4>Почему новость попала в вашу ленту</h4>
          <ul className={common.plain}>{ins.relevance.reasons.map((r, i) => <li key={i}>{r.text}</li>)}</ul>
        </Card>
      </div>

      <Chat insightId={ins.insight_id} suggestions={["Какие источники использованы?", "Покажи в разрезе контрагентов", "Что думает банк о ставке?", "Какое место компании в отрасли?"]} />
    </div>
    </OpenSource.Provider>
    </RulesMode.Provider>
  );
}
