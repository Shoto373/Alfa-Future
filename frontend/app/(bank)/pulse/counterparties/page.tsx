"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { Analytics } from "@/components/counterparties/Analytics";
import { CounterpartyDrawer } from "@/components/counterparties/CounterpartyDrawer";
import { Chain } from "@/components/counterparties/Chain";
import { newsFor, useKeyNews, type Key } from "@/components/counterparties/KeyNews";
import { RISK_RANK, RISK_TEXT, isKnown, pct, plural, riskOf } from "@/components/counterparties/utils";
import { Hint } from "@/components/counterparties/Hint";
import { CompanyTile, Icon, ErrorState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { date, money } from "@/lib/format";
import { useQuery } from "@/lib/query";
import { useSession } from "@/lib/session";
import type { CounterpartiesView, Counterparty, CounterpartyEvent } from "@/lib/types";
import styles from "@/app/(bank)/pulse/counterparties/page.module.scss";
import common from "@/styles/common.module.scss";

const ROLE: Record<Counterparty["relation"], string> = { supplier: "Поставщик", customer: "Покупатель", person: "Возможная связь" };
const SHARE_OF: Record<string, string> = { supplier: "закупок", customer: "продаж" };
const TOP_SHOWN = 6;
const EVENTS_SHOWN = 5;

/** Одна строка «почему это важно для вас» из роли, уровня и веса связи. */
function whyImportant(e: CounterpartyEvent): string {
  const w = e.weight ? ` (${pct(e.weight)})` : "";
  if (e.relation === "person") return "Связь через общих физлиц — слабый признак. Проверьте, касается ли это вас на самом деле.";
  if (e.level === 2) {
    return e.relation === "supplier"
      ? `Это поставщик вашего поставщика${w}: сбой дойдет до вас через цены и сроки, обычно позже прямых новостей.`
      : `Это покупатель вашего покупателя${w}: может измениться спрос на то, что вы продаете.`;
  }
  return e.relation === "supplier"
    ? `Ваш прямой поставщик${w}: новость может сорвать поставки или поднять цены закупок.`
    : `Ваш прямой покупатель${w}: новость может повлиять на спрос и сроки оплаты.`;
}

function Events({ events, watched, total, sectorNews }: { events: CounterpartyEvent[]; watched: number; total: number; sectorNews: number }) {
  const [all, setAll] = useState(false);
  const shown = all ? events : events.slice(0, EVENTS_SHOWN);
  return (
    <section className={common.card} aria-labelledby="ev-title">
      <header className={styles.secHead}>
        <h2 id="ev-title">Что произошло у контрагентов</h2>
        <p>Новости за последние две недели: что случилось, с кем и как это связано с вами.</p>
      </header>
      {!events.length ? (
        <div className={styles.empty}>
          <span className={styles.emptyIcon}><Icon name="check" size={22} /></span>
          <div>
            <b>{sectorNews ? "За две недели новостей о самих контрагентах нет" : "За две недели новостей о ваших контрагентах нет"}</b>
            {sectorNews > 0 && <p>Зато есть {sectorNews} {plural(sectorNews, "новость", "новости", "новостей")} об отраслях, где они работают: смотрите «Главные новости по главным контрагентам» ниже.</p>}
            {watched ? (
              <p>Сейчас отслеживаем новости о {watched} из {total} контрагентов: у остальных в данных нет названия. Проверка идет каждые 5 минут, и как только появится новость, здесь будет карточка: что произошло, как контрагент связан с вами и почему это важно.</p>
            ) : (
              <p>Пока ни об одном контрагенте новости искать не по чему: в данных у них нет названий, только идентификаторы и платежи. С реальными данными банка (ИНН, название) проверка пойдет каждые 5 минут.</p>
            )}
          </div>
        </div>
      ) : (
        <>
          <ul className={styles.events} data-testid="counterparty-events">
            {shown.map((e) => (
              <li key={`${e.news_id}:${e.counterparty_id}`}>
                <div className={styles.evMeta}>
                  <span className={`${styles.badge} ${e.level === 2 ? styles.badgeSecond : styles.badgeDirect}`}>{e.level === 2 ? "Второй уровень" : "Прямой контрагент"}</span>
                  <time dateTime={e.published_at}>{date(e.published_at)}</time>
                </div>
                <Link href={`/pulse/n/${encodeURIComponent(e.news_id)}`} className={styles.evTitle}>{e.title}</Link>
                <Chain text={e.chain} fallbackName={e.counterparty_name} label={`Связь с компанией ${e.counterparty_name}`} />
                <p className={styles.evWhy}><Icon name="risk" size={16} /> <span><b>Почему важно для вас.</b> {whyImportant(e)}</span></p>
              </li>
            ))}
          </ul>
          {events.length > EVENTS_SHOWN && (
            <button type="button" className={styles.more} onClick={() => setAll((v) => !v)}>{all ? "Свернуть" : `Показать все (${events.length})`}</button>
          )}
        </>
      )}
    </section>
  );
}

type Tab = "all" | "supplier" | "customer";

function TopList({ top, keys, onOpen }: { top: Counterparty[]; keys: Key[]; onOpen: (c: Counterparty) => void }) {
  const [tab, setTab] = useState<Tab>("all");
  const [sort, setSort] = useState<"share" | "risk">("share");
  const [all, setAll] = useState(false);
  const count = (t: Tab) => (t === "all" ? top.length : top.filter((c) => c.relation === t).length);
  const tabs: [Tab, string][] = [["all", "Все"], ["supplier", "Поставщики"], ["customer", "Покупатели"]];
  const rows = top.filter((c) => tab === "all" || c.relation === tab)
    .map((c) => ({ c, risk: riskOf(c, newsFor(c, keys).direct.length > 0) }))
    .sort((a, b) => (sort === "risk" ? RISK_RANK[b.risk] - RISK_RANK[a.risk] || b.c.weight - a.c.weight : 0));
  const shown = all ? rows : rows.slice(0, TOP_SHOWN);
  const max = Math.max(0.0001, ...rows.map((r) => r.c.weight));
  return (
    <section className={common.card} aria-labelledby="top-title">
      <header className={styles.secHead}>
        <h2 id="top-title">С кем вы связаны
          <Hint label="доля платежей и риск">Доля — часть всех ваших закупок (у поставщиков) или продаж (у покупателей), которая приходится на контрагента. Риск растёт с долей: от 25% средний, от 40% высокий; свежая новость о самом контрагенте поднимает уровень на ступень.</Hint>
        </h2>
        <p>Крупнейшие по сумме платежей: чем выше доля, тем сильнее вы зависите. Нажмите на строку, чтобы увидеть детали и что делать.</p>
      </header>
      {!top.length ? (
        <p className={common.muted}>Платежей в данных компании нет, поэтому главных контрагентов определить не из чего.</p>
      ) : (
        <>
          <div className={styles.controls}>
            <div className={styles.seg} role="group" aria-label="Показать">
              {tabs.map(([k, label]) => (
                <button key={k} type="button" aria-pressed={tab === k} className={tab === k ? styles.segOn : ""}
                  onClick={() => { setTab(k); setAll(false); }}>{label} <span>{count(k)}</span></button>
              ))}
            </div>
            <div className={styles.seg} role="group" aria-label="Сортировка">
              {([["share", "По доле"], ["risk", "По риску"]] as const).map(([k, label]) => (
                <button key={k} type="button" aria-pressed={sort === k} className={sort === k ? styles.segOn : ""} onClick={() => setSort(k)}>{label}</button>
              ))}
            </div>
          </div>
          {!rows.length ? <p className={common.muted}>В этой группе контрагентов нет.</p> : (
            <ul className={styles.top}>
              {shown.map(({ c, risk }) => (
                <li key={`${c.company_id}:${c.relation}`}>
                  <button type="button" className={styles.topRow} onClick={() => onOpen(c)} aria-haspopup="dialog"
                    aria-label={`${isKnown(c) ? c.name : `Компания без названия ${c.company_id}`}: подробнее`}>
                    <CompanyTile id={c.company_id} name={c.name} size={40} />
                    <span className={styles.topName}>
                      {isKnown(c) ? <strong>{c.name}</strong> : <strong className={styles.anonName}>Компания не определена <small>({c.company_id})</small></strong>}
                      <span>
                        <span className={`${styles.badge} ${c.relation === "supplier" ? styles.badgeSupplier : styles.badgeCustomer}`}>{ROLE[c.relation]}</span>
                        <span className={`${styles.badge} ${styles[`risk_${risk}`]}`}>{RISK_TEXT[risk]}</span>
                        <span className={`${styles.badge} ${isKnown(c) ? styles.badgeWatch : styles.badgeNoWatch}`}>{isKnown(c) ? "Отслеживаем новости" : "Только платежи"}</span>
                        {c.sector && <small>{c.sector}</small>}
                      </span>
                    </span>
                    <span className={styles.topShare}>
                      <span className={styles.shareHead}><b>{pct(c.weight)}</b> <small>{SHARE_OF[c.relation]}</small></span>
                      <span className={styles.bar} role="img" aria-label={`${pct(c.weight)} ${SHARE_OF[c.relation]}`}><i style={{ width: `${Math.max(4, (c.weight / max) * 100)}%` }} /></span>
                    </span>
                    <span className={styles.topAmount}>{c.amount ? money(c.amount) : "—"}</span>
                    <span className={styles.topGo} aria-hidden="true"><Icon name="chevronRight" size={18} /></span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {rows.length > TOP_SHOWN && (
            <button type="button" className={styles.more} onClick={() => setAll((v) => !v)}>{all ? "Свернуть" : `Показать все (${rows.length})`}</button>
          )}
        </>
      )}
    </section>
  );
}

function PossibleLinks({ items }: { items: Counterparty[] }) {
  return (
    <section className={`${common.card} ${styles.links}`} aria-labelledby="pl-title">
      <header className={styles.secHead}>
        <h2 id="pl-title">Возможные связи через общих физлиц</h2>
        <p>Слабый признак: в данных есть общие физические лица. Это не вывод о юридической аффилированности.</p>
      </header>
      <ul className={styles.chips}>
        {items.map((c) => <li key={c.company_id}><b>{c.name}</b>{c.sector && <small>{c.sector}</small>}</li>)}
      </ul>
    </section>
  );
}

function Content({ data, companyId }: { data: CounterpartiesView; companyId: string }) {
  const news = useKeyNews(companyId, data.top, data.events);
  const [open, setOpen] = useState<Counterparty | null>(null);
  const close = useCallback(() => setOpen(null), []);
  const known = data.top.filter(isKnown).length;
  return (
    <>
      <TopList top={data.top} keys={news.keys} onOpen={setOpen} />
      <Events events={data.events} watched={known} total={data.top.length} sectorNews={news.keys.filter((k) => k.kind === "sector").length} />
      <Analytics news={news} top={data.top} events={data.events} />
      {data.possible_links.length > 0 && <PossibleLinks items={data.possible_links} />}
      {open && <CounterpartyDrawer c={open} keys={news.keys} onClose={close} />}
    </>
  );
}

/** Контрагенты (SPR4-01): от кого зависит бизнес, чем это грозит и что с этим делать. */
export default function CounterpartiesPage() {
  const { session } = useSession();
  const companyId = session!.companyId;
  const { data, error, reload } = useQuery(`counterparties:${companyId}`, () => api.counterparties(companyId), { staleMs: 5 * 60_000 });

  return (
    <div className={`${common.page} ${styles.page}`}>
      <div className={common.pageHead}>
        <div>
          <span className={common.eyebrow}><Icon name="link" /> Цепочка поставок</span>
          <h1>Контрагенты {session!.companyName}</h1>
        </div>
      </div>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && !error && <Skeleton lines={8} />}
      {data && <Content data={data} companyId={companyId} />}
    </div>
  );
}
