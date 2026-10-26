import { Icon } from "../ui";
import { activeIndex, FIX_LABEL, PHASES, percent, type ProgressState } from "./progress";
import styles from "@/components/InsightView.module.scss";
import common from "@/styles/common.module.scss";

/** Индикатор хода модели: полоса по завершенным этапам и список этапов. Позиция меняется только по событиям сервера. */
export default function UpgradeProgress({ state: live, completed = false }: { state: ProgressState; completed?: boolean }) {
  // completed — «замороженный» итог перед уходом плашки: все этапы пройдены, полоса полная.
  const state = completed ? { started: PHASES.length, done: PHASES.length, fixing: false } : live;
  const value = percent(state);
  const active = activeIndex(state);
  const current = active ?? Math.min(state.done + 1, PHASES.length);
  const label = (i: number) => (i === 2 && state.fixing ? FIX_LABEL : PHASES[i].label);
  const text = completed ? "Все этапы выполнены" : `Этап ${current} из ${PHASES.length}: ${label(current - 1)}`;
  return (
    <div className={styles.progress}>
      <p className={styles.progressStage} aria-live={completed ? undefined : "polite"}>{text}</p>
      <div className={styles.progressTrack} role="progressbar" aria-label="Ход подготовки AI-разбора"
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={value} aria-valuetext={`${value}%. ${text}`}>
        <div className={`${styles.progressFill} ${completed ? styles.progressFillDone : ""}`} style={{ width: `${value}%` }} />
        {active !== undefined && (
          <div className={styles.progressActive} style={{ left: `${value}%`, width: `${100 - value}%` }} />
        )}
      </div>
      <ol className={styles.progressSteps}>
        {PHASES.map((p, i) => {
          const done = i + 1 <= state.done;
          const now = i + 1 === active;
          return (
            <li key={p.id} className={done ? styles.stepDone : now ? styles.stepNow : styles.stepWait} aria-current={now ? "step" : undefined}>
              <span className={styles.stepMark} aria-hidden="true">{done ? <Icon name="check" size={12} /> : i + 1}</span>
              <span>{label(i)}<span className={common.srOnly}>{done ? " — готово" : now ? " — выполняется" : " — ожидает"}</span></span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
