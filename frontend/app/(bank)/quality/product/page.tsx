"use client";

import { useState } from "react";
import AccessDenied from "@/components/AccessDenied";
import { Card, ErrorState, Icon, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { useLoad } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Interval } from "@/lib/types";
import styles from "@/app/(bank)/quality/product/page.module.scss";
import common from "@/styles/common.module.scss";

const ROLE: Record<string, string> = { owner: "Собственник", ceo: "Ген. директор", cfo: "Фин. директор", accountant: "Гл. бухгалтер",
  treasurer: "Казначей", clevel: "Другой C-level" };
const EVENT: Record<string, string> = { feed_view: "Открыли ленту", insight_open: "Открыли разбор", section_expand: "Раскрыли раздел",
  source_click: "Перешли к источнику", question_ask: "Задали вопрос", feedback: "Оценили раздел", offer_click: "Нажали на предложение" };

function pct(i: Interval): string {
  if (i.rate === null) return "нет данных";
  return `${Math.round(i.rate * 100)}% (95%: ${Math.round(i.low! * 100)}–${Math.round(i.high! * 100)}%, n=${i.n})`;
}

/** Дашборд пилота (SPR4-07): активность руководителей, доля «полезно», возвраты, воронка и эксперименты. */
export default function ProductPage() {
  const { session } = useSession();
  const [days, setDays] = useState(28);
  const report = useLoad((s) => api.productReport(days, s), [days]);
  const flags = useLoad((s) => api.flagSettings(s), []);
  const [saveError, setSaveError] = useState<string | null>(null);
  if (!session!.user.is_operator) return <AccessDenied />;

  const savePercent = async (key: string, percent: number) => {
    setSaveError(null);
    try {
      await api.saveFlag(key, { percent });
      flags.reload();
    } catch (e) {
      setSaveError(errorText(e));
    }
  };
  const r = report.data;
  const top = r ? Math.max(1, ...r.funnel.map((f) => f.users)) : 1;

  return (
    <div className={common.page}>
      <div className={common.pageHead}>
        <div>
          <span className={common.eyebrow}><Icon name="spark" /> Продукт и эксперименты</span>
          <h1>Метрики пилота</h1>
          <p className={common.muted}>События пишутся на нашем сервере, без внешних систем и без персональных данных: псевдоним
            пользователя, роль и коды действий. Интервалы — 95%, метод Уилсона.</p>
        </div>
        <label className={styles.period}>Период
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 28, 90].map((d) => <option key={d} value={d}>{d} дней</option>)}
          </select>
        </label>
      </div>
      {report.error && <ErrorState error={report.error} onRetry={report.reload} />}
      {!r && !report.error && <Skeleton lines={6} />}
      {r && (
        <>
          <div className={styles.kpis} data-testid="product-kpis">
            <div><span>Активные руководители за 7 дней</span><strong>{r.wau}</strong>
              <small>{Object.entries(r.wau_by_role).map(([k, v]) => `${ROLE[k] ?? k}: ${v}`).join(" · ") || "—"}</small></div>
            <div><span>Доля «полезно»</span><strong>{r.useful.rate === null ? "—" : `${Math.round(r.useful.rate * 100)}%`}</strong>
              <small>{pct(r.useful)}</small></div>
            <div><span>Возвраты на 7-й день</span><strong>{r.retention_d7.rate === null ? "—" : `${Math.round(r.retention_d7.rate * 100)}%`}</strong>
              <small>{pct(r.retention_d7)}</small></div>
          </div>
          <Card title="Воронка «сводка → разбор → вопрос»">
            <ul className={styles.funnel}>
              {r.funnel.map((f) => (
                <li key={f.step}><span>{f.label}</span>
                  <span className={styles.bar} style={{ width: `${(f.users / top) * 100}%` }} /><b>{f.users}</b></li>
              ))}
            </ul>
            <p className={`${common.muted} ${common.small}`}>Активность по неделям: {r.wau_weeks.map((w) => `${w.week_end.slice(5)} — ${w.users}`).join(", ")}.</p>
          </Card>
          <Card title="Эксперименты">
            {r.experiments.map((e) => (
              <div key={e.key} className={styles.experiment}>
                <h4>{e.description}</h4>
                <table>
                  <thead><tr><th>Вариант</th><th>Пользователи</th><th>Открытия разборов</th><th>Доля «полезно»</th></tr></thead>
                  <tbody>{e.variants.map((v) => (
                    <tr key={v.variant}><td>{v.variant}</td><td>{v.users}</td><td>{v.opens}</td><td>{pct(v.useful)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            ))}
            <p className={`${common.muted} ${common.small}`}>Пересекающиеся интервалы — разницы пока не видно: нужно больше оценок.</p>
          </Card>
          <Card title="События за период">
            <ul className={styles.events}>{Object.entries(r.events).map(([k, v]) => <li key={k}><span>{EVENT[k] ?? k}</span><b>{v}</b></li>)}</ul>
          </Card>
        </>
      )}
      <Card title="Фичефлаги и раскатка">
        {flags.error && <ErrorState error={flags.error} onRetry={flags.reload} />}
        {flags.data && (
          <ul className={styles.flags}>
            {Object.entries(flags.data.flags).map(([key, f]) => (
              <li key={key}>
                <span><b>{key}</b><small className={common.muted}>{f.description}{f.variants ? ` · варианты: ${f.variants.join(", ")}` : ""}
                  {f.companies.length ? ` · пилот: ${f.companies.join(", ")}` : ""}</small></span>
                <label>Раскатка, %
                  <input type="number" min={0} max={100} defaultValue={f.percent} aria-label={`Раскатка ${key}`}
                    onBlur={(e) => Number(e.target.value) !== f.percent && savePercent(key, Math.max(0, Math.min(100, Number(e.target.value) || 0)))} />
                </label>
              </li>
            ))}
          </ul>
        )}
        {saveError && <p role="alert" className={common.small}>{saveError}</p>}
      </Card>
    </div>
  );
}
