import type { CSSProperties } from "react";
import { money, pct, PRODUCT_NAMES } from "@/lib/format";
import type { CompanyProfile, Counterparties, Exposure } from "@/lib/types";
import { Card } from "./ui";
import styles from "@/components/CompanyPanel.module.scss";
import common from "@/styles/common.module.scss";

function Flow({ title, d, sectors }: { title: string; d: Counterparties; sectors: Record<string, string> }) {
  return (
    <div className={styles.flow}>
      <h4>{title} <span className={common.muted}>({d.counterparties})</span></h4>
      {d.by_sector.length === 0 && <p className={`${common.muted} ${common.small}`}>Нет платежей в выборке</p>}
      {d.by_sector.slice(0, 4).map((s) => (
        <div key={s.sector} className={styles.barRow}>
          <span>{sectors[s.sector] ?? (s.sector === "unknown" ? "Вне выборки" : s.sector)}</span>
          <span className={styles.bar}><span style={{ "--bar-width": `${Math.round(s.share * 100)}%` } as CSSProperties} /></span>
          <span className={styles.num}>{pct(s.share)}</span>
        </div>
      ))}
    </div>
  );
}

export default function CompanyPanel({ profile: p, exposures, sectors, title = "Контекст компании" }: { profile: CompanyProfile; exposures: Exposure[]; sectors: Record<string, string>; title?: string }) {
  const topExposures = [...exposures].sort((a, b) => b.weight - a.weight).slice(0, 5);
  return (
    <Card title={title} className={styles.companyPanel}>
      <ul className={styles.kv}>
        <li><span>ОКВЭД</span><strong>{p.okved_code} · {p.okved_name}</strong></li>
        <li><span>Выручка</span><strong>{money(p.revenue)}</strong></li>
        <li><span>Место в отрасли</span><strong>{p.market.okved_rank ? `№${p.market.okved_rank} из ${p.market.okved_peers} (доля ${pct(p.market.okved_share, 1)})` : "нет данных"}</strong></li>
        <li><span>Регион</span><strong>{p.region ?? "нет данных"}</strong></li>
        <li><span>Персонал (ФНС)</span><strong>{p.workers_fns ?? "нет данных"}</strong></li>
        <li><span>ВЭД (ФТС)</span><strong>{p.fts_flag ? (p.fts_countries.join(", ") || "страны не указаны") : "нет"}</strong></li>
        <li><span>Тип клиента</span><strong>{p.client_type ?? "—"}</strong></li>
      </ul>
      <p className={`${common.muted} ${common.small}`}>{p.market.note}</p>
      <div className={common.tags}>
        {Object.entries(p.products).map(([k, v]) => (
          <span key={k} className={`${common.tag} ${v ? common.tagOn : v === null ? common.tagUnknown : ""}`} title={v === null ? "нет данных" : ""}>
            {PRODUCT_NAMES[k] ?? k}{v === null ? " ?" : ""}
          </span>
        ))}
      </div>
      <Flow title="Поставщики" d={p.suppliers} sectors={sectors} />
      <Flow title="Покупатели" d={p.customers} sectors={sectors} />
      <h4>Чувствительность к событиям</h4>
      <ul className={styles.exposures}>
        {topExposures.map((e, i) => <li key={i}><span className={`${styles.dot} ${e.sign === -1 ? styles.negative : e.sign === 1 ? styles.positive : ""}`} />{e.why}</li>)}
      </ul>
      {p.data_quality.length > 0 && (
        <details className={styles.qualityNote}>
          <summary>Качество данных: {p.data_quality.length}</summary>
          <ul>{p.data_quality.map((q) => <li key={q}>{q}</li>)}</ul>
        </details>
      )}
    </Card>
  );
}
