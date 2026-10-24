"use client";

import { createContext, useContext } from "react";
import type { Claim } from "@/lib/types";
import { OriginTag } from "../ui";
import styles from "@/components/InsightView.module.scss";
import common from "@/styles/common.module.scss";

// Карточка на правилах: рассуждения агента построены правилами, а не моделью, — и подписаны так же.
export const RulesMode = createContext(false);
// Сноска [n] раскрывает свернутый блок источников и прокручивает к источнику n.
export const OpenSource = createContext<(n?: number) => void>(() => {});

/** Номер источника в списке «На чем основан вывод» по его source_id. */
export type SourceIndex = Map<string, number>;

function SourceRefs({ ids, index }: { ids: string[]; index: SourceIndex }) {
  const openSource = useContext(OpenSource);
  // Несколько тезисов одного документа — одна сноска.
  const refs = [...new Set(ids.map((id) => index.get(id)).filter((n): n is number => n !== undefined))].sort((a, b) => a - b);
  if (!refs.length) return null;
  return (
    <span className={styles.refs}>
      {refs.map((n) => (
        <a key={n} href={`#src-${n}`} title="Перейти к источнику" aria-label={`Источник ${n}`}
          onClick={(e) => { e.preventDefault(); openSource(n); }}>{n}</a>
      ))}
    </span>
  );
}

/** Утверждения разбора с меткой происхождения («факт новости», «позиция банка», «вывод AI»…) и сносками. */
export default function ClaimList({ items, index, empty = "Нет данных" }: { items: Claim[]; index: SourceIndex; empty?: string }) {
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
