import type { Insight } from "@/lib/types";
import type { ReactNode } from "react";
import { Card } from "../ui";
import ClaimList, { type SourceIndex } from "./ClaimList";
import styles from "@/components/InsightView.module.scss";

/** «Как это оценивает Альфа-Банк»: резюме и тезисы из материалов банка, расхождения между материалами. */
export default function BankPosition({ view, index, actions }: { view: Insight["bank_view"]; index: SourceIndex; actions: ReactNode }) {
  return (
    <Card title="5. Как это оценивает Альфа-Банк" actions={actions} className={styles.bankCard}>
      {view.available ? (
        <>
          {view.summary && <p className={styles.bankSummary}>{view.summary}</p>}
          <ClaimList items={view.theses.slice(view.summary ? 1 : 0)} index={index} />
        </>
      ) : <p className={styles.muted}>По этой новости аналитики Альфа-Банка нет. Выводы построены на самой новости и данных компании — позиция банка не подставляется.</p>}
      {view.conflicts.map((c) => <p key={c} className={styles.conflict}>{c}</p>)}
    </Card>
  );
}
