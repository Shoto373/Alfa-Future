"use client";

import { useEffect, useState } from "react";
import { Card, ErrorBox, Icon, Loading } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { pct } from "@/lib/format";

const CHECK: Record<string, string> = {
  completeness: "Полнота разделов", sources_linked: "Выводы со ссылкой на источник", bank_view_grounded: "Позиция банка из материалов банка",
  bank_view_found: "Найдена аналитика банка", numbers_grounded: "Цифры подтверждены", consistent_with_client: "Без противоречий с данными",
  personalized: "Персонализация",
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return <div className="stat"><span className="stat-value">{value}</span><span className="stat-label">{label}</span>{hint && <span className="muted small">{hint}</span>}</div>;
}

export default function QualityPage() {
  const [m, setM] = useState<Record<string, any> | null>(null);
  const [audit, setAudit] = useState<Record<string, any>[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    setError(null);
    Promise.all([api.metrics(), api.audit()])
      .then(([metrics, a]) => { setM(metrics); setAudit(a.items.reverse()); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Ошибка"));
  }, [tick]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="eyebrow"><Icon name="check" /> Мониторинг</span>
          <h1>Качество и аудит</h1>
          <p className="muted">Метрики контента, персонализации и AI-компонента; журнал обращений агента к инструментам.</p>
        </div>
        <button className="btn btn-secondary" onClick={() => setTick((t) => t + 1)}><Icon name="refresh" /> Обновить</button>
      </div>
      {error && <ErrorBox message={error} onRetry={() => setTick((t) => t + 1)} />}
      {!m && !error && <Loading text="Считаем метрики…" />}
      {m && (
        <>
          <div className="grid-3">
            <Card title="Контент">
              <div className="stats">
                <Stat label="Разборов" value={String(m.content.insights)} />
                <Stat label="Прошли самопроверку с 1-й попытки" value={pct(m.content.first_pass_rate)} />
                <Stat label="Выводов со ссылкой на источник" value={pct(m.content.claims_with_sources)} />
              </div>
            </Card>
            <Card title="Персонализация">
              <div className="stats">
                <Stat label="Открытий ленты" value={String(m.personalization.feed_views)} />
                <Stat label="Открытий разборов" value={String(m.personalization.insight_opens)} />
                <Stat label="Оценка «полезно»" value={m.personalization.useful_rate === null ? "—" : pct(m.personalization.useful_rate)}
                  hint={`👍 ${m.personalization.feedback.up} · 👎 ${m.personalization.feedback.down}`} />
              </div>
            </Card>
            <Card title="AI-компонент">
              <div className="stats">
                <Stat label="LLM" value={m.ai.llm_connected ? "подключена" : "не подключена"} />
                <Stat label="Токенов сегодня" value={`${m.ai.llm_usage.tokens} / ${m.ai.llm_usage.limit}`} />
                <Stat label="Средняя длительность" value={m.ai.avg_latency_ms ? `${Math.round(m.ai.avg_latency_ms)} мс` : "—"} />
              </div>
            </Card>
          </div>
          <Card title="Проверки агента">
            <ul className="bars">
              {Object.entries(m.content.checks_pass_rate as Record<string, number>).map(([k, v]) => (
                <li key={k} className="bar-row"><span>{CHECK[k] ?? k}</span><span className="bar"><span style={{ width: `${v * 100}%` }} /></span><span className="num">{pct(v)}</span></li>
              ))}
            </ul>
          </Card>
          <Card title="Журнал обращений к инструментам">
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Время</th><th>Инструмент</th><th>Статус</th><th>мс</th><th>request_id</th></tr></thead>
                <tbody>
                  {audit.map((a, i) => (
                    <tr key={i}><td>{new Date(a.ts).toLocaleTimeString("ru-RU")}</td><td><code>{a.tool}</code></td>
                      <td className={a.status === "ok" ? "" : "neg"}>{a.status}</td><td>{a.duration_ms}</td><td className="muted small">{a.request_id}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
