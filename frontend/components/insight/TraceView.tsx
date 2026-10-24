import type { Insight } from "@/lib/types";
import { Card } from "../ui";
import styles from "@/components/InsightView.module.scss";
import common from "@/styles/common.module.scss";

const STAGE: Record<string, string> = { plan: "План", tool: "Инструмент", compose: "Черновик", check: "Самопроверка", adapt: "Коррекция", finalize: "Итог" };
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

/** «Как получен вывод»: шаги агента (план, инструменты, черновик, проверки, коррекция) и самопроверка. */
export default function TraceView({ trace, checks }: { trace: Insight["trace"]; checks: Insight["quality"]["checks"] }) {
  return (
    <Card title="Ход анализа агента">
      <ol className={styles.trace} data-testid="analysis-trace">
        {trace.map((s) => (
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
