import { date } from "@/lib/format";
import type { Insight, Source } from "@/lib/types";
import { Card, Icon } from "../ui";
import { reasonLines, type SourceGroup } from "./sources";
import styles from "@/components/InsightView.module.scss";
import common from "@/styles/common.module.scss";

const SOURCE_STYLES: Partial<Record<Source["kind"], string>> = {
  bank_analytics: styles.srcBankAnalytics,
  client_data: styles.srcClientData,
};
const SOURCE_KIND: Record<Source["kind"], string> = {
  news: "Новость", bank_analytics: "Аналитика банка", client_data: "Данные компании", bank_product: "Продукт банка",
};

/** «На чем основан вывод»: источники (сворачиваются) с переходом к первоисточнику и причины отбора в ленту. */
export default function SourceList({ groups, reasons, open, onToggle, focused }: {
  groups: SourceGroup[]; reasons: Insight["relevance"]["reasons"]; open: boolean; onToggle: () => void; focused: number | null;
}) {
  return (
    <Card className={styles.span2} title={
      <button type="button" className={styles.collapseToggle} aria-expanded={open} aria-controls="insight-sources" onClick={onToggle}>
        6. На чем основан вывод <span className={styles.muted}>· {groups.length}</span>
        <Icon name="chevron" size={18} />
      </button>
    }>
      {open && <ol className={styles.sources} id="insight-sources">
        {groups.map((g, i) => {
          const pages = [...new Set(g.items.map((s) => s.page).filter((p): p is number => !!p))];
          return (
            <li key={g.key} id={`src-${i + 1}`} className={focused === i + 1 ? styles.focused : undefined}>
              <span className={`${styles.srcKind} ${SOURCE_STYLES[g.kind] ?? ""}`}>{SOURCE_KIND[g.kind]}</span>
              <div>
                <strong>{g.title}</strong>
                {pages.length > 0 && `, стр. ${pages.join(", ")}`}{g.date ? ` · ${date(g.date)}` : ""}
                {g.items.length === 1 && g.items[0].excerpt && <p className={`${styles.muted} ${common.small}`}>{g.items[0].excerpt}</p>}
                {g.items.length > 1 && (
                  <ul className={styles.srcQuotes}>
                    {g.items.map((s) => (
                      <li key={s.source_id} className={`${styles.muted} ${common.small}`}>
                        {s.page && <span className={styles.srcPage}>стр. {s.page}</span>}{s.excerpt}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              {g.url && <a className={`${common.btn} ${common.btnLink} ${common.btnSm}`} href={g.url} target="_blank" rel="noreferrer"
                aria-label={`Первоисточник: ${g.title} (откроется в новой вкладке)`}><Icon name="link" size={14} /> Первоисточник</a>}
            </li>
          );
        })}
      </ol>}
      <h4>Почему новость попала в вашу ленту</h4>
      <dl className={styles.reasonList}>
        {reasonLines(reasons).map((r) => (
          <div key={r.label}><dt>{r.label}</dt><dd>{r.text}</dd></div>
        ))}
      </dl>
    </Card>
  );
}
