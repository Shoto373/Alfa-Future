"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Hint } from "@/components/counterparties/Hint";
import { isKnown, pct, quote } from "@/components/counterparties/utils";
import { Score } from "@/components/ui";
import { date } from "@/lib/format";
import { useFeedWithTopics } from "@/lib/hooks";
import type { Counterparty, CounterpartyEvent, FeedItem } from "@/lib/types";
import styles from "@/components/counterparties/analytics.module.scss";

const SHOWN = 5;
const OF = { supplier: "закупок", customer: "продаж" } as const;
const WHO = { supplier: "поставщика", customer: "покупателя" } as const;

export interface Key {
  id: string;
  title: string;
  published: string;
  /** Важность для компании из ленты; у событий-мониторинга оценки нет. */
  score: number | null;
  kind: "direct" | "sector";
  /** Кого касается: для прямого упоминания — компания, для отрасли — сторона и отрасль. */
  companyId?: string;
  side: "supplier" | "customer";
  sector?: string;
  who: string;
  chip: string | null;
  why: string;
}

/** Главные новости по главным контрагентам из уже ранжированной ленты компании.
 *  Только готовые признаки бэкенда: прямое упоминание контрагента (news.mentions) и отрасль контрагентов
 *  по платежам (причина «supply_chain»). Своего подбора на клиенте нет. */
export function pickKeys(items: FeedItem[], top: Counterparty[], events: CounterpartyEvent[] = []): Key[] {
  const byId = new Map(top.map((c) => [c.company_id, c]));
  const out: Key[] = [];
  // События мониторинга: новость назвала прямого контрагента, сопоставление сделал бэкенд.
  for (const e of [...events].sort((a, b) => b.strength - a.strength)) {
    if (e.level !== 1 || (e.relation !== "supplier" && e.relation !== "customer")) continue;
    const cp = byId.get(e.counterparty_id);
    out.push({
      id: e.news_id, title: e.title, published: e.published_at, score: null, kind: "direct", companyId: e.counterparty_id,
      side: e.relation, who: e.counterparty_name, chip: cp ? `${pct(cp.weight)} ${OF[e.relation]}` : null,
      why: `Новость называет вашего ${WHO[e.relation]} по имени: его проблемы быстро дойдут до вас.`,
    });
  }
  const seen = new Set(out.map((k) => k.id));
  for (const it of items) {
    const { news, relevance } = it;
    const mention = (news.mentions ?? [])
      .filter((m): m is typeof m & { relation: "supplier" | "customer" } => m.relation === "supplier" || m.relation === "customer")
      .map((m) => ({ m, cp: m.company_id ? byId.get(m.company_id) : undefined }))
      .sort((a, b) => (b.cp?.weight ?? 0) - (a.cp?.weight ?? 0))[0];
    if (seen.has(news.news_id)) continue;
    const base = { id: news.news_id, title: news.title, published: news.published_at, score: relevance.score };
    if (mention) {
      out.push({
        ...base, kind: "direct", companyId: mention.m.company_id ?? undefined, side: mention.m.relation,
        who: mention.m.name, chip: mention.cp ? `${pct(mention.cp.weight)} ${OF[mention.m.relation]}` : null,
        why: `Новость называет вашего ${WHO[mention.m.relation]} по имени: его проблемы быстро дойдут до вас.`,
      });
      continue;
    }
    const sc = relevance.reasons.filter((r) => r.kind === "supply_chain").sort((a, b) => b.weight - a.weight)[0];
    if (!sc) continue;
    const side = sc.feature.startsWith("suppliers") ? "supplier" : "customer";
    const sector = /«(.+)»/.exec(sc.text)?.[1];
    const named = top.filter((c) => c.relation === side && c.sector === sector && isKnown(c)).slice(0, 2).map((c) => quote(c.name));
    out.push({
      ...base, kind: "sector", side, sector,
      who: `Ваши ${side === "supplier" ? "поставщики" : "покупатели"}${sector ? `: отрасль «${sector}»` : ""}`,
      chip: `${pct(sc.weight)} ${OF[side]}`,
      why: named.length ? `Новость про отрасль, в которой работают ваши контрагенты, например ${named.join(", ")}.` : "Новость про отрасль, в которой работают ваши контрагенты.",
    });
  }
  // Сначала прямые упоминания, внутри группы — по важности для компании
  return out.sort((a, b) => (a.kind === b.kind ? (b.score ?? 0) - (a.score ?? 0) : a.kind === "direct" ? -1 : 1));
}

/** Новости, которые касаются конкретного контрагента: сначала прямое упоминание, затем та же отрасль и сторона. */
export function newsFor(c: Counterparty, keys: Key[]): { direct: Key[]; sector: Key[] } {
  return {
    direct: keys.filter((k) => k.kind === "direct" && k.companyId === c.company_id),
    sector: c.sector ? keys.filter((k) => k.kind === "sector" && k.side === c.relation && k.sector === c.sector) : [],
  };
}

export interface KeyState { keys: Key[]; loading: boolean; error: boolean }

export function useKeyNews(companyId: string, top: Counterparty[], events: CounterpartyEvent[]): KeyState {
  const feed = useFeedWithTopics(companyId);
  const items = feed.data?.items;
  const keys = useMemo(() => (items ? pickKeys(items, top, events) : []), [items, top, events]);
  return { keys, loading: !feed.data && !feed.error, error: !!feed.error };
}

export function KeyNews({ state, top }: { state: KeyState; top: Counterparty[] }) {
  const [all, setAll] = useState(false);
  const known = top.filter(isKnown).length;
  const { keys: list } = state;
  const shown = all ? list : list.slice(0, SHOWN);
  return (
    <div className={styles.insightsWrap}>
      <h3>Главные новости по главным контрагентам
        <Hint label="как подбираем новости">Берем ленту, уже отсортированную по важности для вашей компании. «Прямое упоминание»: новость называет вашего поставщика или покупателя. «Та же отрасль»: новость про отрасль, где работают ваши контрагенты по платежам. Остальные новости ленты сюда не попадают.</Hint>
      </h3>
      {state.error ? <p className={styles.muted}>Ленту новостей загрузить не удалось, попробуйте обновить страницу.</p>
        : state.loading ? <p className={styles.muted}>Подбираем новости…</p>
        : !list.length ? (
          <p className={styles.muted}>
            Новостей про ваших главных контрагентов в ленте сейчас нет.{" "}
            {known ? `Названия известны у ${known} из ${top.length}: по ним ищем прямые упоминания и новости их отраслей.` : "Названия контрагентов в данных неизвестны, поэтому прямые упоминания искать не по чему."}
            {top.length - known > 0 && known > 0 ? ` По остальным (${top.length - known}) новости не отслеживаем.` : ""}
          </p>
        ) : (
          <>
            <ul className={styles.news}>
              {shown.map((n) => (
                <li key={n.id}>
                  <div className={styles.newsMeta}>
                    {n.score !== null && <Score value={n.score} />}
                    <span className={`${styles.tagKind} ${n.kind === "direct" ? styles.tagDirect : styles.tagSector}`}>{n.kind === "direct" ? "Прямое упоминание" : "Та же отрасль"}</span>
                    <time dateTime={n.published}>{date(n.published)}</time>
                  </div>
                  <Link href={`/pulse/n/${encodeURIComponent(n.id)}`} className={styles.newsTitle}>{n.title}</Link>
                  <p className={styles.newsWho}><b>{n.who}</b>{n.chip && <span className={styles.chip}>{n.chip}</span>}</p>
                  <p className={styles.newsWhy}>{n.why}</p>
                </li>
              ))}
            </ul>
            {list.length > SHOWN && <button type="button" className={styles.more} onClick={() => setAll((v) => !v)}>{all ? "Свернуть" : `Показать все (${list.length})`}</button>}
          </>
        )}
      <p className={styles.how}>Как подбираем: {list.some((n) => n.kind === "direct") ? "прямое упоминание контрагента в новости, затем та же отрасль по платежам" : "по отрасли контрагентов (по платежам): прямых упоминаний контрагентов сейчас нет"}.</p>
    </div>
  );
}
