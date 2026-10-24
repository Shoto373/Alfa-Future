"use client";

import { useState } from "react";
import { Card, ErrorState, Icon, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { date } from "@/lib/format";
import { useLoad } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import styles from "@/app/(bank)/quality/page.module.scss";
import common from "@/styles/common.module.scss";

const PERIODS = [{ hours: 24, label: "Сутки" }, { hours: 24 * 7, label: "Неделя" }, { hours: 24 * 30, label: "Месяц" }];
const SECTION_NAMES: Record<string, string> = {
  what_happened: "Что произошло", why_important: "Почему важно", risks: "Риски", opportunities: "Возможности",
  actions: "Действия", bank_view: "Позиция банка", card: "Карточка целиком",
};
const LEVEL_ICON = { ok: "✓", warn: "!", info: "i" } as const;

function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statValue}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
      {hint && <small className={common.muted}>{hint}</small>}
    </div>
  );
}

/** Мониторинг качества контента, персонализации и AI-компонента — с выводами, что улучшить. */
export default function QualityPage() {
  const { session } = useSession();
  // Сводные показатели всех компаний — только сотрудникам банка (как /metrics на сервере).
  const operator = !!session!.user.is_operator;
  const [hours, setHours] = useState(24 * 7);
  const { data, error, reload } = useLoad(
    (signal) => operator ? api.qualityOverview(hours, signal) : Promise.resolve(null), [hours, operator]);

  if (!operator) {
    return (
      <div className={common.page}>
        <h1>Качество</h1>
        <Card><p>Мониторинг доступен сотрудникам банка.</p></Card>
      </div>
    );
  }

  const p = data?.period;
  const t = data?.totals;
  const rss = p?.pipeline?.rss;
  const checks = Object.entries(t?.content.checks_pass_rate ?? {}).sort((a, b) => a[1] - b[1]);

  return (
    <div className={common.page}>
      <div className={common.pageHead}>
        <div>
          <span className={common.eyebrow}><Icon name="shield" /> Мониторинг</span>
          <h1>Качество Альфа.Пульса</h1>
        </div>
        <div className={styles.periods} role="toolbar" aria-label="Период">
          {PERIODS.map((x) => (
            <button key={x.hours} className={`${common.chip} ${hours === x.hours ? styles.on : ""}`} aria-pressed={hours === x.hours}
              onClick={() => setHours(x.hours)}>{x.label}</button>
          ))}
        </div>
      </div>

      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && !error && <Card><Skeleton lines={6} /></Card>}

      {data && p && t && (
        <>
          <Card title="Выводы">
            <ul className={styles.findings}>
              {data.findings.map((f, i) => (
                <li key={i} className={styles[f.level]}>
                  <span className={styles.findingIcon} aria-hidden>{LEVEL_ICON[f.level]}</span>
                  <span>{f.text}</span>
                </li>
              ))}
            </ul>
          </Card>

          <div className={styles.grid}>
            <Card title="Контент">
              <div className={styles.stats}>
                <Stat label="Разборов за период" value={String(p.insights)} hint={`с моделью: ${p.llm_attempted}`} />
                <Stat label="AI-версия дошла до пользователя" value={pct(p.llm_share)} />
                <Stat label="Прошли проверки с первой попытки" value={pct(p.first_pass)} />
                <Stat label="Утверждений с источником" value={pct(p.grounded)} />
                <Stat label="Разборов с позицией банка" value={pct(p.bank_coverage)} />
              </div>
            </Card>
            <Card title="Персонализация">
              <div className={styles.stats}>
                <Stat label="Просмотров ленты" value={String(p.feed_views)} />
                <Stat label="Открытий разборов" value={String(p.insight_opens)}
                  hint={p.feed_views ? `${pct(p.insight_opens / p.feed_views)} от просмотров` : undefined} />
                <Stat label="Уточняющих вопросов" value={String(p.questions)} />
                <Stat label="Полезно по оценкам" value={pct(p.feedback.useful_rate)} hint={`👍 ${p.feedback.up} · 👎 ${p.feedback.down}`} />
              </div>
            </Card>
            <Card title="AI-компонент">
              <div className={styles.stats}>
                <Stat label="Модель" value={t.ai.llm_connected ? "подключена" : "не подключена"} />
                <Stat label="Время AI-разбора, p50 / p90" value={`${p.latency_p50 ?? "—"} / ${p.latency_p90 ?? "—"} с`} />
                <Stat label="Токенов сегодня" value={`${(t.ai.llm_usage?.tokens ?? 0).toLocaleString("ru-RU")}`}
                  hint={t.ai.llm_usage?.limit ? `лимит ${t.ai.llm_usage.limit.toLocaleString("ru-RU")}` : undefined} />
                <Stat label="Расход сегодня" value={`${(t.ai.llm_usage?.cost ?? 0).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`}
                  hint={t.ai.llm_usage?.cost_limit ? `лимит ${t.ai.llm_usage.cost_limit} ₽` : undefined} />
              </div>
            </Card>
            <Card title="Конвейер новостей">
              <div className={styles.stats}>
                <Stat label="Последний цикл" value={p.pipeline?.started_at ? date(p.pipeline.started_at) : "—"} />
                <Stat label="Новых новостей" value={String(rss?.added ?? "—")} hint={rss ? `отсеяно как не деловые: ${rss.skipped}` : undefined} />
                <Stat label="Быстрых разборов" value={String(p.pipeline?.rules_built ?? "—")} />
                <Stat label="AI-разборов" value={String(p.pipeline?.llm_built ?? "—")} />
              </div>
              {rss?.failed && rss.failed.length > 0 && <p className={styles.warnText}>Недоступны: {rss.failed.join(", ")}</p>}
            </Card>
          </div>

          <div className={styles.grid}>
            <Card title="Самопроверки (за всё время)">
              {checks.length === 0 && <p className={common.muted}>Разборов пока нет.</p>}
              <ul className={styles.bars}>
                {checks.map(([name, rate]) => (
                  <li key={name}>
                    <span>{data.check_labels[name] ?? name}</span>
                    <span className={styles.bar}><span style={{ width: `${Math.round(rate * 100)}%` }} className={rate < 0.9 ? styles.barWarn : ""} /></span>
                    <strong>{pct(rate)}</strong>
                  </li>
                ))}
              </ul>
            </Card>
            <Card title="Оценки по разделам (за всё время)">
              {Object.keys(t.personalization.by_section).length === 0 && <p className={common.muted}>Оценок пока нет.</p>}
              <ul className={styles.sections}>
                {Object.entries(t.personalization.by_section).map(([k, v]) => (
                  <li key={k}><span>{SECTION_NAMES[k] ?? k}</span><span>👍 {v.up} · 👎 {v.down}</span></li>
                ))}
              </ul>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
