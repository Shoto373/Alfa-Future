"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Chain, anonId } from "@/components/counterparties/Chain";
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
const HIDE_KEY = "counterparties:how-hidden";
const TOP_SHOWN = 6;
const SECOND_SHOWN = 5;
const EVENTS_SHOWN = 5;

/** Новости ищутся только по компаниям с названием: у безымянных (в данных лишь идентификатор) совпасть нечему. */
const isKnown = (c: Counterparty) => !anonId(c.name, c.company_id);

const NO_NAME_HINT = "В данных кейса у такой компании есть только идентификатор, без названия. Новость нельзя сопоставить с компанией, поэтому мы считаем только платежи. С реальными данными банка (ИНН, название) новости будут находиться и для них.";

const pct = (w: number) => (w > 0 && w < 0.01 ? "<1%" : `${Math.round(w * 100)}%`);
const plural = (n: number, one: string, few: string, many: string) => {
  const m = n % 100, d = n % 10;
  return m > 10 && m < 15 ? many : d === 1 ? one : d >= 2 && d <= 4 ? few : many;
};

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

const STEPS = [
  { icon: "wallet", title: "Берем ваши платежи", text: "Смотрим, кому вы платите и кто платит вам, по данным компании." },
  { icon: "users", title: "Находим главных", text: "Выбираем крупнейших поставщиков и покупателей и их контрагентов (второй уровень)." },
  { icon: "search", title: "Ищем новости о них", text: "Только о тех, чье название известно. Если компания в данных безымянная, считаем лишь платежи." },
];

function HowItWorks() {
  const [open, setOpen] = useState(true);
  useEffect(() => {
    try { if (localStorage.getItem(HIDE_KEY) === "1") setOpen(false); } catch { /* хранилище недоступно — оставляем открытым */ }
  }, []);
  const toggle = () => {
    setOpen((v) => {
      try { localStorage.setItem(HIDE_KEY, v ? "1" : "0"); } catch { /* не критично */ }
      return !v;
    });
  };
  return (
    <section className={styles.how} aria-labelledby="how-title">
      <div className={styles.howHead}>
        <h2 id="how-title"><Icon name="spark" size={18} /> Как это работает</h2>
        <button type="button" className={styles.howToggle} aria-expanded={open} aria-controls="how-body" onClick={toggle}>
          {open ? "Свернуть" : "Показать"} <span className={open ? styles.flip : ""}><Icon name="chevron" size={16} /></span>
        </button>
      </div>
      {open && (
        <div id="how-body">
          <ol className={styles.steps}>
            {STEPS.map((s, i) => (
              <li key={s.title}>
                <span className={styles.stepIcon}><Icon name={s.icon} size={20} /></span>
                <div><b>{i + 1}. {s.title}</b><p>{s.text}</p></div>
              </li>
            ))}
          </ol>
          <p className={styles.why}><b>Почему это важно.</b> Сбой у поставщика вашего поставщика бьет по марже раньше, чем появляются новости о вас.</p>
        </div>
      )}
    </section>
  );
}

function Stats({ data }: { data: CounterpartiesView }) {
  const sup = data.top.filter((c) => c.relation === "supplier");
  const cus = data.top.filter((c) => c.relation === "customer");
  const sum = (a: Counterparty[]) => a.reduce((s, c) => s + c.weight, 0);
  const cover: [string, string][] = [];
  if (sup.length) cover.push([pct(sum(sup)), "закупок"]);
  if (cus.length) cover.push([pct(sum(cus)), "продаж"]);
  const n = data.top.length, ev = data.events.length, sl = data.second_level.length;
  return (
    <ul className={styles.stats}>
      <li>
        <span>Главных контрагентов</span>
        <strong>{n}</strong>
        <small>{sup.length} {plural(sup.length, "поставщик", "поставщика", "поставщиков")}, {cus.length} {plural(cus.length, "покупатель", "покупателя", "покупателей")}</small>
        <small className={styles.watch}>Новости отслеживаем: {data.top.filter(isKnown).length} из {n}</small>
      </li>
      <li>
        <span>Покрывают платежи</span>
        <strong>{cover.length ? cover.map((c) => <span key={c[1]} className={styles.cover}>{c[0]} <small>{c[1]}</small></span>) : "—"}</strong>
        <small>доля платежей, на которую приходятся главные</small>
      </li>
      <li>
        <span>Событий за 2 недели</span>
        <strong>{ev}</strong>
        <small>{ev ? "новости о ваших контрагентах" : "пока спокойно"}</small>
      </li>
      <li>
        <span>Цепочек 2-го уровня</span>
        <strong>{sl}</strong>
        <small>контрагенты ваших контрагентов</small>
      </li>
    </ul>
  );
}

function Events({ events, watched, total }: { events: CounterpartyEvent[]; watched: number; total: number }) {
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
            <b>За две недели новостей о ваших контрагентах нет</b>
            {watched ? (
              <p>Сейчас отслеживаем новости о {watched} из {total} контрагентов (включая второй уровень): у остальных в данных нет названия. Проверка идет каждые 5 минут, и как только появится новость, здесь будет карточка: что произошло, как контрагент связан с вами и почему это важно.</p>
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

function TopList({ top }: { top: Counterparty[] }) {
  const [tab, setTab] = useState<Tab>("all");
  const [all, setAll] = useState(false);
  const count = (t: Tab) => (t === "all" ? top.length : top.filter((c) => c.relation === t).length);
  const tabs: [Tab, string][] = [["all", "Все"], ["supplier", "Поставщики"], ["customer", "Покупатели"]];
  const list = top.filter((c) => tab === "all" || c.relation === tab);
  const shown = all ? list : list.slice(0, TOP_SHOWN);
  const max = Math.max(0.0001, ...list.map((c) => c.weight));
  return (
    <section className={common.card} aria-labelledby="top-title">
      <header className={styles.secHead}>
        <h2 id="top-title">С кем вы связаны
          <Hint label="доля платежей">Доля — это часть всех ваших закупок (у поставщиков) или продаж (у покупателей), которая приходится на контрагента. Чем она больше, тем сильнее вы от него зависите.</Hint>
        </h2>
        <p>Крупнейшие по сумме платежей. Именно поэтому они в списке: чем выше доля, тем сильнее вы зависите от контрагента. Новости ищем только о тех, чье название известно.</p>
      </header>
      {!top.length ? (
        <p className={common.muted}>Платежей в данных компании нет, поэтому главных контрагентов определить не из чего.</p>
      ) : (
        <>
          <div className={styles.seg} role="group" aria-label="Показать">
            {tabs.map(([k, label]) => (
              <button key={k} type="button" aria-pressed={tab === k} className={tab === k ? styles.segOn : ""}
                onClick={() => { setTab(k); setAll(false); }}>{label} <span>{count(k)}</span></button>
            ))}
          </div>
          {!list.length ? <p className={common.muted}>В этой группе контрагентов нет.</p> : (
            <ul className={styles.top}>
              {shown.map((c) => (
                <li key={`${c.company_id}:${c.relation}`}>
                  <CompanyTile id={c.company_id} name={c.name} size={40} />
                  <div className={styles.topName}>
                    {isKnown(c) ? <strong>{c.name}</strong> : <strong className={styles.anonName}>Компания не определена <small>({c.company_id})</small></strong>}
                    <span>
                      <span className={`${styles.badge} ${c.relation === "supplier" ? styles.badgeSupplier : styles.badgeCustomer}`}>{ROLE[c.relation]}</span>
                      {isKnown(c)
                        ? <span className={`${styles.badge} ${styles.badgeWatch}`}>Отслеживаем новости</span>
                        : <span className={`${styles.badge} ${styles.badgeNoWatch}`}>Только платежи<Hint label="почему новости не отслеживаются">{NO_NAME_HINT}</Hint></span>}
                      {c.sector && <small>{c.sector}</small>}
                    </span>
                  </div>
                  <div className={styles.topShare}>
                    <div className={styles.shareHead}><b>{pct(c.weight)}</b> <small>{SHARE_OF[c.relation]}</small></div>
                    <div className={styles.bar} role="img" aria-label={`${pct(c.weight)} ${SHARE_OF[c.relation]}`}><i style={{ width: `${Math.max(4, (c.weight / max) * 100)}%` }} /></div>
                  </div>
                  <div className={styles.topAmount}>{c.amount ? money(c.amount) : "—"}</div>
                </li>
              ))}
            </ul>
          )}
          {list.length > TOP_SHOWN && (
            <button type="button" className={styles.more} onClick={() => setAll((v) => !v)}>{all ? "Свернуть" : `Показать все (${list.length})`}</button>
          )}
        </>
      )}
    </section>
  );
}

function SecondLevel({ items }: { items: Counterparty[] }) {
  const [all, setAll] = useState(false);
  const list = [...items].sort((a, b) => b.weight - a.weight);
  const shown = all ? list : list.slice(0, SECOND_SHOWN);
  const max = Math.max(0.0001, ...list.map((c) => c.weight));
  return (
    <section className={common.card} aria-labelledby="sl-title">
      <header className={styles.secHead}>
        <h2 id="sl-title">Второй уровень: контрагенты ваших контрагентов
          <Hint label="второй уровень и вес">Второй уровень — это поставщик вашего поставщика или покупатель вашего покупателя. Вес цепочки — доля первого звена, умноженная на долю второго. Показываем цепочки с весом от 2%.</Hint>
        </h2>
        <p>Влияют на вас не напрямую, а через того, с кем вы работаете. Показаны цепочки с весом от 2%. Если у компании в цепочке нет названия, новости о ней не отслеживаем.</p>
      </header>
      {!list.length ? (
        <p className={common.muted}>Заметных цепочек второго уровня нет: ни одна не дотягивает до порога в 2% платежей.</p>
      ) : (
        <>
          <ul className={styles.second}>
            {shown.map((c) => (
              <li key={`${c.company_id}:${c.relation}`}>
                <Chain text={c.text} fallbackName={c.name} label={`Цепочка до ${c.name}`} />
                <div className={styles.weight}>
                  <span>вес <b>{pct(c.weight)}</b></span>
                  <div className={styles.bar} aria-hidden="true"><i style={{ width: `${Math.max(6, (c.weight / max) * 100)}%` }} /></div>
                </div>
              </li>
            ))}
          </ul>
          {list.length > SECOND_SHOWN && (
            <button type="button" className={styles.more} onClick={() => setAll((v) => !v)}>{all ? "Свернуть" : `Показать все (${list.length})`}</button>
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

/** Контрагенты (SPR4-01): от кого зависит бизнес, чем это грозит и на чем это основано. */
export default function CounterpartiesPage() {
  const { session } = useSession();
  const companyId = session!.companyId;
  const { data, error, reload } = useQuery(`counterparties:${companyId}`, () => api.counterparties(companyId), { staleMs: 5 * 60_000 });

  const all = data ? [...data.top, ...data.second_level] : [];
  const total = new Set(all.map((c) => c.company_id));
  const watched = new Set(all.filter(isKnown).map((c) => c.company_id));

  return (
    <div className={`${common.page} ${styles.page}`}>
      <div className={common.pageHead}>
        <div>
          <span className={common.eyebrow}><Icon name="link" /> Цепочка поставок</span>
          <h1>Контрагенты {session!.companyName}</h1>
          <p className={common.muted}>Мы следим за новостями о тех, от кого зависит ваш бизнес: поставщиках, покупателях и их партнерах.</p>
        </div>
      </div>
      <HowItWorks />
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && !error && <Skeleton lines={8} />}
      {data && (
        <>
          <Stats data={data} />
          <Events events={data.events} watched={watched.size} total={total.size} />
          <TopList top={data.top} />
          <SecondLevel items={data.second_level} />
          {data.possible_links.length > 0 && <PossibleLinks items={data.possible_links} />}
        </>
      )}
    </div>
  );
}
