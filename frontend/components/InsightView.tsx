"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { Insight, Role } from "@/lib/types";
import Chat from "./Chat";
import BankOffers from "./insight/BankOffers";
import BankPosition from "./insight/BankPosition";
import ClaimList, { OpenSource, RulesMode } from "./insight/ClaimList";
import Feedback from "./insight/Feedback";
import ImpactMap from "./insight/ImpactMap";
import InsightHeader from "./insight/InsightHeader";
import SourceList from "./insight/SourceList";
import { groupSources } from "./insight/sources";
import { chatSuggestions } from "./insight/suggestions";
import TraceView from "./insight/TraceView";
import { track, useFlags } from "@/lib/track";
import { Card } from "./ui";
import styles from "@/components/InsightView.module.scss";
import common from "@/styles/common.module.scss";

/** Источник из ссылки вида …#src-3: такая ссылка открывает разбор сразу на нужном источнике. */
function sourceFromHash(): number | null {
  if (typeof window === "undefined") return null;
  const m = /^#src-(\d+)$/.exec(window.location.hash);
  return m ? Number(m[1]) : null;
}

const scrollToSource = (n: number) =>
  // Блок раскрывается в этом же кадре — прокрутка после отрисовки.
  requestAnimationFrame(() => document.getElementById(`src-${n}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));

export default function InsightView({ insight: ins, onRefresh, refreshing, upgrading = false, upgradeFailed = false, upgradeStage,
  perspective, ownRole, onPerspective, mentions }: {
  insight: Insight; onRefresh: () => void; refreshing: boolean; upgrading?: boolean; upgradeFailed?: boolean; upgradeStage?: string;
  perspective?: Role; ownRole?: Role; onPerspective?: (role: Role) => void; mentions?: ReactNode;
}) {
  const { groups, index } = groupSources(ins);
  const [showTrace, setShowTrace] = useState(false);
  // «Ход анализа» раскрывается плавно: после первого открытия он остается в разметке, чтобы и сворачиваться плавно;
  // каждое открытие — новый ключ, шаги заново проявляются по очереди.
  const [traceOpens, setTraceOpens] = useState(0);
  const [showSources, setShowSources] = useState(() => sourceFromHash() !== null);
  const [focused, setFocused] = useState<number | null>(sourceFromHash);

  const flags = useFlags(ins.company_id);
  // Эксперимент SPR4-07: вариант actions_first ставит «Что можно сделать» перед последствиями.
  const actionsFirst = flags?.insight_section_order?.variant === "actions_first";

  const openSource = useCallback((n?: number) => {
    track("source_click", { kind: n ? "claim" : "list" });
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
  const consequences = (
    <Card title={`${actionsFirst ? 4 : 3}. Какие последствия возможны`} actions={fb("consequences")} className={styles.span2}>
      <div className={styles.twoCol}>
        <div><h4 className={styles.neg}>Риски</h4><ClaimList items={ins.risks} index={index} empty="Существенных рисков не выявлено" anchor="risk" /></div>
        <div><h4 className={styles.pos}>Возможности</h4><ClaimList items={ins.opportunities} index={index} empty="Явных возможностей не выявлено" anchor="opp" /></div>
      </div>
    </Card>
  );
  const actionsCard = (
    <Card title={`${actionsFirst ? 3 : 4}. Что можно сделать`} actions={fb("actions")} className={actionsFirst ? styles.span2 : ""}>
      <ClaimList items={ins.actions} index={index} anchor="act" />
      {ins.questions.length > 0 && (<><h4>Вопросы для дополнительного анализа</h4><ul className={common.plain}>{ins.questions.map((q) => <li key={q}>{q}</li>)}</ul></>)}
      <BankOffers insightId={ins.insight_id} />
    </Card>
  );

  return (
    <RulesMode.Provider value={ins.mode === "rules"}>
    <OpenSource.Provider value={openSource}>
    <div className={styles.insight}>
      <InsightHeader ins={ins} onRefresh={onRefresh} refreshing={refreshing} upgrading={upgrading} upgradeFailed={upgradeFailed}
        upgradeStage={upgradeStage}
        showTrace={showTrace} onToggleTrace={() => {
          if (!showTrace) { track("section_expand", { section: "trace" }); setTraceOpens((n) => n + 1); }
          setShowTrace((v) => !v);
        }}
        perspective={perspective} ownRole={ownRole} onPerspective={onPerspective} />

      <div className={`${styles.traceWrap} ${showTrace ? styles.traceOpen : ""}`} inert={!showTrace}>
        <div className={styles.traceInner}>
          {traceOpens > 0 && <TraceView key={traceOpens} trace={ins.trace} checks={ins.quality.checks} />}
        </div>
      </div>
      {mentions}
      <ImpactMap ins={ins} />

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
          <ClaimList items={ins.why_important} index={index} anchor="why" />
          {ins.features_used.length > 0 && (
            <div className={styles.features}>
              <h4>Признаки компании, повлиявшие на вывод</h4>
              <ul className={styles.kv}>{ins.features_used.map((f) => <li key={f.name}><span>{f.label}</span><strong>{f.value}</strong></li>)}</ul>
            </div>
          )}
        </Card>

        {actionsFirst ? <>{actionsCard}{consequences}</> : <>{consequences}{actionsCard}</>}

        <BankPosition view={ins.bank_view} index={index} actions={fb("bank_view")} />

        <SourceList groups={groups} reasons={ins.relevance.reasons} open={showSources}
          onToggle={() => { if (!showSources) track("section_expand", { section: "sources" }); setShowSources((v) => !v); }} focused={focused} />
      </div>

      {flags?.dialog?.enabled !== false && <Chat insightId={ins.insight_id} suggestions={chatSuggestions(ins)} />}
    </div>
    </OpenSource.Provider>
    </RulesMode.Provider>
  );
}
