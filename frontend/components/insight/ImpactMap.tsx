"use client";

import type { CSSProperties } from "react";
import { impactOf } from "@/lib/impact";
import { useSession } from "@/lib/session";
import type { Insight } from "@/lib/types";
import { Icon } from "../ui";
import styles from "@/components/insight/ImpactMap.module.scss";
import view from "@/components/InsightView.module.scss";

const EFFECT_TEXT: Record<string, string> = {
  neg: "Риск для компании", pos: "Выгода для компании", mixed: "Есть риски и выгоды", unclear: "Зависит от операций", none: "Влияние слабое",
};

/** Ветка ведет к выводу в разборе: плавная прокрутка и мягкая подсветка. */
function goTo(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove(view.flash);
  void el.offsetWidth;  // перезапуск подсветки при повторном нажатии
  el.classList.add(view.flash);
  window.setTimeout(() => el.classList.remove(view.flash), 1900);
}

/** «Путь влияния»: событие → каналы, через которые оно касается именно этой компании → компания и итог в рублях.
 *  Линии рисуются на глазах, по ним бегут импульсы от события к компании; нажатие на ветку — к выводу в разборе. */
export default function ImpactMap({ ins }: { ins: Insight }) {
  const { session } = useSession();
  const m = impactOf(ins);
  if (!m.channels.length) return null;
  const n = m.channels.length;
  const y = (i: number) => ((i + 0.5) / n) * 100;
  const tone = m.effect === "neg" ? styles.neg : m.effect === "pos" ? styles.pos : m.effect === "mixed" ? styles.mixed : styles.neutral;

  return (
    <section className={`${styles.map} ${tone}`} aria-label="Путь влияния события на компанию" data-testid="impact-map">
      <header className={styles.head}>
        <h2><Icon name="pulse" size={18} /> Путь влияния</h2>
        <span>как это событие доходит до {session?.companyName ?? "компании"} · нажмите на ветку, чтобы перейти к выводу</span>
      </header>
      <div className={styles.stage} style={{ "--n": n } as CSSProperties}>
        <svg className={styles.wires} viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {m.channels.map((c, i) => {
            const into = `M29 50 C33 50 32 ${y(i)} 36 ${y(i)}`;
            const out = `M64 ${y(i)} C68 ${y(i)} 67 50 71 50`;
            return (
              <g key={c.key} style={{ "--d": `${0.35 + i * 0.12}s` } as CSSProperties}>
                <path d={into} pathLength={100} className={styles.wire} />
                <path d={into} pathLength={100} className={styles.flow} />
                <path d={out} pathLength={100} className={`${styles.wire} ${styles.wireOut}`} />
                <path d={out} pathLength={100} className={`${styles.flow} ${styles.flowOut}`} />
              </g>
            );
          })}
        </svg>

        <div className={styles.event}>
          <span className={styles.kicker}>Событие</span>
          <p>{m.event}</p>
        </div>

        <ul className={styles.channels}>
          {m.channels.map((c, i) => (
            <li key={c.key} style={{ "--d": `${0.45 + i * 0.12}s` } as CSSProperties}>
              <button type="button" onClick={() => goTo(c.target)} title="Перейти к выводу в разборе">
                <strong>{c.title}</strong>
                <span>{c.detail}</span>
              </button>
            </li>
          ))}
        </ul>

        <div className={styles.company}>
          <span className={styles.ring} aria-hidden="true" />
          <span className={styles.kicker}>Ваша компания</span>
          <strong>{EFFECT_TEXT[m.effect] ?? EFFECT_TEXT.unclear}</strong>
          {m.amount && (
            <p className={styles.amount}>≈ {m.amountSign === "neg" ? "−" : "+"}{m.amount}<small> в год, по формуле</small></p>
          )}
        </div>
      </div>
    </section>
  );
}
