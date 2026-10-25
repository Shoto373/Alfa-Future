import { Hint } from "@/components/counterparties/Hint";
import { KeyNews, type KeyState } from "@/components/counterparties/KeyNews";
import { isKnown, label, pct, plural, shareLevel } from "@/components/counterparties/utils";
import { Icon } from "@/components/ui";
import { useState } from "react";
import { money } from "@/lib/format";
import type { Counterparty, CounterpartyEvent } from "@/lib/types";
import styles from "@/components/counterparties/analytics.module.scss";
import common from "@/styles/common.module.scss";

type Side = "supplier" | "customer";
type Severity = "high" | "medium" | "info";

const NO_SECTOR = "Отрасль не определена";

const SIDE = {
  supplier: { who: "Поставщик", whoPl: "поставщики", of: "закупок", title: "Закупки", noun: "поставщика", loss: "сбой у него сорвет поставки или поднимет цены", step: "найдите запасного поставщика и зафиксируйте цену и сроки договором" },
  customer: { who: "Покупатель", whoPl: "покупатели", of: "продаж", title: "Продажи", noun: "покупателя", loss: "потеря этого клиента ударит по выручке", step: "расширяйте круг клиентов и проверьте условия и сроки оплаты" },
} as const;

const SEVERITY: Record<Severity, { text: string; icon: string; cls: string }> = {
  high: { text: "Высокий риск", icon: "risk", cls: styles.high },
  medium: { text: "Внимание", icon: "risk", cls: styles.medium },
  info: { text: "К сведению", icon: "check", cls: styles.info },
};

const level = (share: number): Severity => { const l = shareLevel(share); return l === "low" ? "info" : l; };

interface SideStat {
  side: Side;
  list: Counterparty[];
  top1: Counterparty | undefined;
  top3: number;
  total: number;
  sectors: { name: string; share: number; known: boolean }[];
}

function sideStat(top: Counterparty[], side: Side): SideStat {
  const list = top.filter((c) => c.relation === side).sort((a, b) => b.weight - a.weight);
  const by = new Map<string, number>();
  for (const c of list) by.set(c.sector ?? NO_SECTOR, (by.get(c.sector ?? NO_SECTOR) ?? 0) + c.weight);
  const sectors = [...by.entries()].map(([name, share]) => ({ name, share, known: name !== NO_SECTOR })).sort((a, b) => b.share - a.share);
  return {
    side, list, top1: list[0], top3: list.slice(0, 3).reduce((s, c) => s + c.weight, 0),
    total: list.reduce((s, c) => s + c.weight, 0), sectors,
  };
}

interface Insight { severity: Severity; text: string; step: string }

function buildInsights(stats: SideStat[], top: Counterparty[], events: CounterpartyEvent[]): Insight[] {
  const out: Insight[] = [];
  for (const s of stats) {
    const d = SIDE[s.side];
    if (!s.top1) continue;
    const sev = level(s.top1.weight);
    if (sev !== "info") {
      out.push({ severity: sev, text: `${d.who} ${label(s.top1)} даёт ${pct(s.top1.weight)} ${d.of}: ${d.loss}.`, step: d.step });
    } else if (s.list.length >= 3 && s.top3 >= 0.7) {
      out.push({ severity: "medium", text: `На три крупнейших контрагента приходится ${pct(s.top3)} ${d.of}: замена любого из них займет время.`, step: "проверьте условия с каждым из них и заранее подготовьте замену" });
    }
    const sector = s.sectors.find((x) => x.known);
    if (sector && sector.share >= 0.5) {
      out.push({ severity: "medium", text: `${pct(sector.share)} ${d.of} приходится на отрасль «${sector.name}»: новости этой отрасли заденут вас сильнее всего.`, step: "читайте новости этой отрасли в ленте и держите запас по срокам" });
    }
  }
  const anon = top.filter((c) => !isKnown(c)).length;
  if (anon) out.push({ severity: "info", text: `${anon} из ${top.length} ${plural(top.length, "контрагента", "контрагентов", "контрагентов")} без названия: по ним считаем только платежи, новости не отслеживаем.`, step: "добавьте реквизиты (ИНН, название), и мы начнем следить за новостями" });
  if (events.length) out.push({ severity: "high", text: `За две недели вышло ${events.length} ${plural(events.length, "новость", "новости", "новостей")} о ваших контрагентах: смотрите блок выше.`, step: "откройте новости и оцените, как это влияет на поставки и спрос" });
  if (!out.length && top.length) out.push({ severity: "info", text: "Выраженной зависимости от одного контрагента или отрасли не видно: платежи распределены ровно.", step: "просто следите за новостями и пересматривайте картину раз в квартал" });
  const rank: Record<Severity, number> = { high: 0, medium: 1, info: 2 };
  return out.sort((a, b) => rank[a.severity] - rank[b.severity]).slice(0, 4);
}

function Concentration({ s }: { s: SideStat }) {
  const d = SIDE[s.side];
  if (!s.top1) return null;
  const sev = level(s.top1.weight);
  const first3 = s.list.slice(0, 3);
  const rest = Math.max(0, 1 - first3.reduce((a, c) => a + c.weight, 0));
  const shades = [styles.seg1, styles.seg2, styles.seg3];
  const verdict = sev === "high" ? `Высокая зависимость: один ${d.who.toLowerCase()} даёт ${pct(s.top1.weight)}`
    : sev === "medium" ? `Средняя зависимость: крупнейший даёт ${pct(s.top1.weight)}` : `Низкая зависимость: крупнейший даёт ${pct(s.top1.weight)}`;
  return (
    <div className={styles.block}>
      <h4>{d.title}: от кого зависите</h4>
      <p className={`${styles.verdict} ${SEVERITY[sev].cls}`}><Icon name={SEVERITY[sev].icon} size={16} /> {verdict}</p>
      <div className={styles.stack} role="img" aria-label={`Структура ${d.of}: ${first3.map((c, i) => `${i + 1}-й ${pct(c.weight)}`).join(", ")}, остальные ${pct(rest)}`}>
        {first3.map((c, i) => <i key={c.company_id} className={shades[i]} style={{ width: `${c.weight * 100}%` }} />)}
        <i className={styles.segRest} style={{ width: `${rest * 100}%` }} />
      </div>
      <ul className={styles.legend}>
        {first3.map((c, i) => (
          <li key={c.company_id}><span className={`${styles.dot} ${shades[i]}`} aria-hidden="true" /><span className={styles.legendName}>{isKnown(c) ? c.name : `Без названия (${c.company_id})`}</span><b>{pct(c.weight)}</b></li>
        ))}
        <li><span className={`${styles.dot} ${styles.segRest}`} aria-hidden="true" /><span className={styles.legendName}>Остальные</span><b>{pct(rest)}</b></li>
      </ul>
    </div>
  );
}

function Sectors({ s }: { s: SideStat }) {
  const d = SIDE[s.side];
  if (!s.list.length) return null;
  const shown = s.sectors.slice(0, 5);
  const max = Math.max(0.0001, ...shown.map((x) => x.share));
  return (
    <div className={styles.block}>
      <h4>{d.title} по отраслям</h4>
      <ul className={styles.sectors}>
        {shown.map((x) => (
          <li key={x.name}>
            <div className={styles.sectorHead}><span className={x.known ? "" : styles.unknown}>{x.name}</span><b>{pct(x.share)}</b></div>
            <div className={styles.track} role="img" aria-label={`${x.name}: ${pct(x.share)} ${d.of}`}><i className={x.known ? "" : styles.unknownBar} style={{ width: `${Math.max(3, (x.share / max) * 100)}%` }} /></div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Balance({ top }: { top: Counterparty[] }) {
  const bought = top.filter((c) => c.relation === "supplier").reduce((s, c) => s + (c.amount ?? 0), 0);
  const sold = top.filter((c) => c.relation === "customer").reduce((s, c) => s + (c.amount ?? 0), 0);
  if (!bought && !sold) return null;
  const max = Math.max(bought, sold);
  const rows = [{ k: "Закупки у главных поставщиков", v: bought, cls: styles.barBuy }, { k: "Продажи главным покупателям", v: sold, cls: styles.barSell }];
  return (
    <div className={`${styles.block} ${styles.sep}`}>
      <h4>Баланс закупок и продаж</h4>
      <ul className={styles.balance}>
        {rows.map((r) => (
          <li key={r.k}>
            <div className={styles.sectorHead}><span>{r.k}</span><b>{r.v ? money(r.v) : "—"}</b></div>
            <div className={styles.track} role="img" aria-label={`${r.k}: ${r.v ? money(r.v) : "нет данных"}`}><i className={r.cls} style={{ width: `${Math.max(2, (r.v / max) * 100)}%` }} /></div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Аналитика по платежам компании: зависимость от крупных контрагентов, отрасли, баланс. Считается на клиенте из `top` и событий. */
export function Analytics({ news, top, events }: { news: KeyState; top: Counterparty[]; events: CounterpartyEvent[] }) {
  const stats = (["supplier", "customer"] as Side[]).map((s) => sideStat(top, s));
  const insights = buildInsights(stats, top, events);
  const [charts, setCharts] = useState(false);
  return (
    <section className={common.card} aria-labelledby="an-title">
      <header className={styles.head}>
        <h2 id="an-title">Аналитика: от кого вы зависите
          <Hint label="пороги зависимости">Если один контрагент даёт 40% закупок или продаж и больше, зависимость высокая; от 25% до 40% — средняя; меньше — низкая. Чем выше доля, тем больнее его потерять.</Hint>
        </h2>
        <p>Считаем по платежам вашей компании из данных, без данных третьих лиц.</p>
      </header>
      {!top.length ? (
        <p className={common.muted}>Платежей в данных компании нет, поэтому считать зависимость не из чего.</p>
      ) : (
        <>
          {insights.length > 0 && (
            <div className={styles.insightsWrap}>
              <h3>На что обратить внимание</h3>
              <ul className={styles.insights}>
                {insights.map((i) => (
                  <li key={i.text}>
                    <span className={`${styles.insIcon} ${SEVERITY[i.severity].cls}`}><Icon name={SEVERITY[i.severity].icon} size={18} /></span>
                    <div><small className={SEVERITY[i.severity].cls}>{SEVERITY[i.severity].text}</small><p>{i.text}</p><p className={styles.step}><b>Что делать:</b> {i.step}</p></div>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <KeyNews state={news} top={top} />
          <button type="button" className={styles.chartsToggle} aria-expanded={charts} aria-controls="an-charts" onClick={() => setCharts((v) => !v)}>
            {charts ? "Скрыть расчёты" : "Показать расчёты: концентрация, отрасли, баланс"}
            <span className={charts ? styles.flip : ""}><Icon name="chevron" size={16} /></span>
          </button>
          {charts && (
            <div id="an-charts">
              <div className={styles.grid}>{stats.map((s) => <Concentration key={s.side} s={s} />)}</div>
              <div className={styles.grid}>{stats.map((s) => <Sectors key={s.side} s={s} />)}</div>
              <Balance top={top} />
              <p className={styles.note}>Доли и суммы взяты по главным контрагентам из списка ниже. Отрасль известна только у компаний с названием.</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
