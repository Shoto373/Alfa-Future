"use client";

import Link from "next/link";
import { Card, EmptyState, ErrorState, Icon, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { date, money } from "@/lib/format";
import { useQuery } from "@/lib/query";
import { useSession } from "@/lib/session";
import type { Counterparty } from "@/lib/types";
import styles from "@/app/(bank)/pulse/counterparties/page.module.scss";
import common from "@/styles/common.module.scss";

const RELATION: Record<Counterparty["relation"], string> = { supplier: "Поставщик", customer: "Покупатель", person: "Возможная связь" };

/** Контрагенты (SPR4-01): кому компания платит и кто платит ей, цепочки второго уровня и события у контрагентов. */
export default function CounterpartiesPage() {
  const { session } = useSession();
  const companyId = session!.companyId;
  const { data, error, reload } = useQuery(`counterparties:${companyId}`, () => api.counterparties(companyId), { staleMs: 5 * 60_000 });

  return (
    <div className={common.page}>
      <div className={common.pageHead}>
        <div>
          <span className={common.eyebrow}><Icon name="link" /> Цепочка поставок</span>
          <h1>Контрагенты {session!.companyName}</h1>
          <p className={common.muted}>По платежам из данных кейса: главные поставщики и покупатели, их контрагенты (второй уровень)
            и новости о них. Сбой у поставщика вашего поставщика бьет по марже раньше прямых новостей о вас.</p>
        </div>
      </div>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && !error && <Skeleton lines={8} />}
      {data && (
        <>
          <Card title="События у контрагентов">
            {!data.events.length ? <EmptyState>Новостей о ваших контрагентах за две недели нет — сервис проверяет их каждые 5 минут.</EmptyState> : (
              <ul className={styles.events} data-testid="counterparty-events">
                {data.events.map((e) => (
                  <li key={`${e.news_id}:${e.counterparty_id}`}>
                    <Link href={`/pulse/n/${encodeURIComponent(e.news_id)}`}><strong>{e.title}</strong></Link>
                    <span className={styles.chain}>{e.chain}</span>
                    <small className={common.muted}>{date(e.published_at)} · {e.level === 2 ? "второй уровень" : "прямой контрагент"}</small>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Главные контрагенты по платежам">
            {!data.top.length ? <EmptyState>Платежей в данных кейса нет.</EmptyState> : (
              <table className={styles.table}>
                <thead><tr><th>Контрагент</th><th>Отрасль</th><th>Связь</th><th className={styles.num}>Доля</th><th className={styles.num}>Сумма</th></tr></thead>
                <tbody>
                  {data.top.map((c) => (
                    <tr key={`${c.company_id}:${c.relation}`}>
                      <td>{c.name}</td><td>{c.sector ?? "—"}</td><td>{RELATION[c.relation]}</td>
                      <td className={styles.num}>{Math.round(c.weight * 100)}%</td>
                      <td className={styles.num}>{c.amount ? money(c.amount) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card title="Второй уровень цепочки">
            {!data.second_level.length ? <EmptyState>Заметных цепочек второго уровня нет (порог — 2% платежей).</EmptyState> : (
              <ul className={styles.chains}>
                {data.second_level.map((c) => <li key={`${c.company_id}:${c.relation}`}>{c.text} <small className={common.muted}>· вес {Math.round(c.weight * 100)}%</small></li>)}
              </ul>
            )}
          </Card>
          {data.possible_links.length > 0 && (
            <Card title="Возможные связи через общих физлиц">
              <p className={common.muted}>Общие физические лица в данных кейса. Это не вывод о юридической аффилированности.</p>
              <ul className={styles.chains}>{data.possible_links.map((c) => <li key={c.company_id}>{c.name}{c.sector ? ` · ${c.sector}` : ""}</li>)}</ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
