"use client";

import { useCallback, useEffect, useState } from "react";
import type { Insight, Role } from "@/lib/types";
import Chat from "./Chat";
import BankPosition from "./insight/BankPosition";
import ClaimList, { OpenSource, RulesMode } from "./insight/ClaimList";
import Feedback from "./insight/Feedback";
import InsightHeader from "./insight/InsightHeader";
import SourceList from "./insight/SourceList";
import { groupSources } from "./insight/sources";
import TraceView from "./insight/TraceView";
import { Card } from "./ui";
import styles from "@/components/InsightView.module.scss";
import common from "@/styles/common.module.scss";

const CHAT_SUGGESTIONS = ["Какие источники использованы?", "Покажи в разрезе контрагентов", "Что думает банк о ставке?", "Какое место компании в отрасли?"];

/** Источник из ссылки вида …#src-3: такая ссылка открывает разбор сразу на нужном источнике. */
function sourceFromHash(): number | null {
  if (typeof window === "undefined") return null;
  const m = /^#src-(\d+)$/.exec(window.location.hash);
  return m ? Number(m[1]) : null;
}

const scrollToSource = (n: number) =>
  // Блок раскрывается в этом же кадре — прокрутка после отрисовки.
  requestAnimationFrame(() => document.getElementById(`src-${n}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));

export default function InsightView({ insight: ins, onRefresh, refreshing, upgrading = false, upgradeFailed = false,
  perspective, ownRole, onPerspective }: {
  insight: Insight; onRefresh: () => void; refreshing: boolean; upgrading?: boolean; upgradeFailed?: boolean;
  perspective?: Role; ownRole?: Role; onPerspective?: (role: Role) => void;
}) {
  const { groups, index } = groupSources(ins);
  const [showTrace, setShowTrace] = useState(false);
  const [showSources, setShowSources] = useState(() => sourceFromHash() !== null);
  const [focused, setFocused] = useState<number | null>(sourceFromHash);

  const openSource = useCallback((n?: number) => {
    setShowSources(true);
    if (!n) return;
    setFocused(n);
    history.replaceState(null, "", `#src-${n}`);
    scrollToSource(n);
  }, []);

  useEffect(() => {
    const n = sourceFromHash();
    if (n) scrollToSource(n);
  }, [ins.insight_id]);
  const fb = (section: string) => <Feedback insightId={ins.insight_id} section={section} />;

  return (
    <RulesMode.Provider value={ins.mode === "rules"}>
    <OpenSource.Provider value={openSource}>
    <div className={styles.insight}>
      <InsightHeader ins={ins} onRefresh={onRefresh} refreshing={refreshing} upgrading={upgrading} upgradeFailed={upgradeFailed}
        showTrace={showTrace} onToggleTrace={() => setShowTrace((v) => !v)}
        perspective={perspective} ownRole={ownRole} onPerspective={onPerspective} />

      {showTrace && <TraceView trace={ins.trace} checks={ins.quality.checks} />}

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

        <BankPosition view={ins.bank_view} index={index} actions={fb("bank_view")} />

        <SourceList groups={groups} reasons={ins.relevance.reasons} open={showSources}
          onToggle={() => setShowSources((v) => !v)} focused={focused} />
      </div>

      <Chat insightId={ins.insight_id} suggestions={CHAT_SUGGESTIONS} />
    </div>
    </OpenSource.Provider>
    </RulesMode.Provider>
  );
}
