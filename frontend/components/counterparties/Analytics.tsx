import { Hint } from "@/components/counterparties/Hint";
import { KeyNews, type KeyState } from "@/components/counterparties/KeyNews";
import { isKnown, label, pct, plural, shareLevel } from "@/components/counterparties/utils";
import { Icon } from "@/components/ui";
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

/** Аналитика по платежам компании: зависимость от крупных контрагентов. Считается на клиенте из `top` и событий. */
export function Analytics({ news, top, events }: { news: KeyState; top: Counterparty[]; events: CounterpartyEvent[] }) {
  const stats = (["supplier", "customer"] as Side[]).map((s) => sideStat(top, s));
  const insights = buildInsights(stats, top, events);
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
        </>
      )}
    </section>
  );
}
