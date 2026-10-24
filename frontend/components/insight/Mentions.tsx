"use client";

import { api } from "@/lib/api";
import { RELATION_LABEL } from "@/lib/format";
import { useQuery } from "@/lib/query";
import styles from "@/components/InsightView.module.scss";

/** Организации в новости (SPR3-02): своя компания и контрагенты — первыми и с пометкой. */
export default function Mentions({ newsId, companyId }: { newsId: string; companyId: string }) {
  const { data } = useQuery(`news:${companyId}:${newsId}`, () => api.newsMentions(newsId, companyId), { staleMs: 10 * 60_000 });
  const mentions = [...(data?.mentions ?? [])].sort((a, b) => Number(a.relation === "other") - Number(b.relation === "other"));
  if (!mentions.length) return null;
  return (
    <section className={styles.mentions} aria-label="Организации в новости">
      <h3>Упоминаются в новости</h3>
      <ul>
        {mentions.map((m) => (
          <li key={m.company_id ?? m.name} className={m.relation !== "other" ? styles.mentionRelated : undefined}>
            <span>{m.name}</span>
            {m.relation !== "other" && <em>{RELATION_LABEL[m.relation]}</em>}
          </li>
        ))}
      </ul>
    </section>
  );
}
