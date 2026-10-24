import type { Insight, TraceStep } from "@/lib/types";
import { Card } from "../ui";
import styles from "@/components/InsightView.module.scss";
import common from "@/styles/common.module.scss";

const STAGE: Record<string, string> = {
  plan: "Планирование", tool: "Сбор данных", compose: "Черновик", check: "Проверка", adapt: "Исправления", finalize: "Итог",
};
// Технические имена шагов трассы — понятными словами.
const STEP: Record<string, string> = {
  plan: "План анализа",
  llm_queries: "Уточняющие вопросы",
  get_company_profile: "Профиль компании",
  get_exposures: "Связь события с компанией",
  get_counterparties: "Поставщики и покупатели",
  search_bank_analytics: "Аналитика Альфа-Банка",
  check_forecast_conflicts: "Сверка прогнозов банка",
  get_story_history: "Похожие события в прошлом",
  get_story_coverage: "Другие источники",
  get_bank_products: "Продукты банка",
  llm_compose: "Черновик AI",
  rules_compose: "Быстрый разбор",
  llm_repair: "Исправление AI",
  safe_fallback: "Возврат к быстрому разбору",
  semantic_review: "Смысловая проверка",
  finalize: "Результат",
};
const STATUS_ICON: Record<string, string> = { ok: "✓", warning: "!", error: "✕", skipped: "–" };
const TRACE_STYLES: Record<string, string | undefined> = {
  warning: styles.traceWarning,
  error: styles.traceError,
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

function stepTitle(name: string): string {
  const round = /^(self_check|adapt)_(\d+)$/.exec(name);
  if (round) return `${round[1] === "self_check" ? "Проверка" : "Исправление"}, раунд ${round[2]}`;
  return STEP[name] ?? name;
}

// Имена инструментов и проверок внутри текста шага тоже переводятся.
function humanize(text: string): string {
  return text.replace(/\b[a-z]+(?:_[a-z]+)+\b/g, (t) => STEP[t] ?? CHECK[t] ?? t);
}

function seconds(ms: number): string {
  return `${(ms / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} с`;
}

function Step({ s, repeat }: { s: TraceStep; repeat: boolean }) {
  // У инструмента текст вида «зачем: что получено»; цель видна из названия шага,
  // а у повторного поиска (уточняющий вопрос модели) она выводится отдельной строкой.
  const sep = s.stage === "tool" ? s.detail.indexOf(": ") : -1;
  const why = sep > 0 ? s.detail.slice(0, sep) : "";
  const result = sep > 0 ? s.detail.slice(sep + 2) : s.detail;
  const queries = s.output?.queries as { query: string; why: string }[] | undefined;
  return (
    <li className={TRACE_STYLES[s.status]}>
      <span className={styles.traceIcon} aria-hidden>{STATUS_ICON[s.status] ?? "•"}</span>
      <div className={styles.traceBody}>
        <div>
          <strong>{stepTitle(s.name)}</strong>
          {result && <> — {humanize(result)}</>}
        </div>
        {repeat && why && <div className={`${styles.muted} ${common.small}`}>{why}</div>}
        {queries && queries.length > 0 && (
          <ul className={styles.traceQueries}>
            {queries.map((q, i) => (
              <li key={i}>«{q.query}»<span className={styles.muted}> — {q.why}</span></li>
            ))}
          </ul>
        )}
      </div>
      {s.duration_ms >= 1000 && <span className={`${styles.muted} ${common.small}`}>{seconds(s.duration_ms)}</span>}
    </li>
  );
}

/** «Как получен вывод»: шаги агента по этапам (план, сбор данных, черновик, проверки, исправления) и самопроверка. */
export default function TraceView({ trace, checks }: { trace: Insight["trace"]; checks: Insight["quality"]["checks"] }) {
  const total = trace.find((s) => s.stage === "finalize")?.output?.total_duration_ms;
  // Подряд идущие шаги одного этапа — одной группой.
  const groups: { stage: string; steps: TraceStep[] }[] = [];
  for (const s of trace) {
    if (groups.at(-1)?.stage === s.stage) groups.at(-1)!.steps.push(s);
    else groups.push({ stage: s.stage, steps: [s] });
  }
  const seen = new Set<string>();
  return (
    <Card title="Ход анализа агента">
      <div className={styles.trace} data-testid="analysis-trace">
        {typeof total === "number" && <p className={`${styles.muted} ${common.small}`}>Весь анализ занял {seconds(total)}</p>}
        {groups.map((g, gi) => (
          <section key={gi} className={styles.traceGroup}>
            <h4>{STAGE[g.stage] ?? g.stage}</h4>
            <ul>
              {g.steps.map((s) => {
                const repeat = seen.has(s.name);
                seen.add(s.name);
                return <Step key={s.step} s={s} repeat={repeat} />;
              })}
            </ul>
          </section>
        ))}
      </div>
      <h4>Самопроверка</h4>
      <ul className={styles.checks} data-testid="quality-checks">
        {checks.map((c) => (
          <li key={c.name} className={c.passed ? styles.ok : styles.warn}>
            <span aria-label={c.passed ? "Пройдена" : "Не пройдена"}>{c.passed ? "✓" : "!"}</span> {CHECK[c.name] ?? c.name}
            <span className={`${styles.muted} ${common.small}`}> — {c.detail}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
