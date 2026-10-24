import { api } from "@/lib/api";
import { date } from "@/lib/format";
import type { Insight, Source } from "@/lib/types";
import { Card, Icon } from "../ui";
import styles from "@/components/InsightView.module.scss";
import common from "@/styles/common.module.scss";

const SOURCE_STYLES: Partial<Record<Source["kind"], string>> = {
  bank_analytics: styles.srcBankAnalytics,
  client_data: styles.srcClientData,
};
const SOURCE_KIND: Record<Source["kind"], string> = {
  news: "Новость", bank_analytics: "Аналитика банка", client_data: "Данные компании", bank_product: "Продукт банка",
};

function sourceLink(s: Source): string | null {
  if (s.kind === "news") return s.url;
  if (s.kind === "bank_analytics" && s.doc_id) return api.pdfUrl(s.doc_id, s.page);
  return null;
}

/** «На чем основан вывод»: источники (сворачиваются) с переходом к первоисточнику и причины отбора в ленту. */
export default function SourceList({ sources, reasons, open, onToggle, focused }: {
  sources: Source[]; reasons: Insight["relevance"]["reasons"]; open: boolean; onToggle: () => void; focused: number | null;
}) {
  return (
    <Card className={styles.span2} title={
      <button type="button" className={styles.collapseToggle} aria-expanded={open} aria-controls="insight-sources" onClick={onToggle}>
        6. На чем основан вывод <span className={styles.muted}>· {sources.length}</span>
        <Icon name="chevron" size={18} />
      </button>
    }>
      {open && <ol className={styles.sources} id="insight-sources">
        {sources.map((s, i) => {
          const link = sourceLink(s);
          return (
            <li key={s.source_id} id={`src-${i + 1}`} className={focused === i + 1 ? styles.focused : undefined}>
              <span className={`${styles.srcKind} ${SOURCE_STYLES[s.kind] ?? ""}`}>{SOURCE_KIND[s.kind]}</span>
              <div>
                <strong>{s.title}</strong>{s.page ? `, стр. ${s.page}` : ""}{s.date ? ` · ${date(s.date)}` : ""}
                {s.excerpt && <p className={`${styles.muted} ${common.small}`}>{s.excerpt}</p>}
              </div>
              {link && <a className={`${common.btn} ${common.btnLink} ${common.btnSm}`} href={link} target="_blank" rel="noreferrer"
                aria-label={`Первоисточник: ${s.title} (откроется в новой вкладке)`}><Icon name="link" size={14} /> Первоисточник</a>}
            </li>
          );
        })}
      </ol>}
      <h4>Почему новость попала в вашу ленту</h4>
      <ul className={common.plain}>{reasons.map((r, i) => <li key={i}>{r.text}</li>)}</ul>
    </Card>
  );
}
