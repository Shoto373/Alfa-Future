"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { newsFor, type Key } from "@/components/counterparties/KeyNews";
import { RISK_TEXT, isKnown, pct, riskOf, shareLevel } from "@/components/counterparties/utils";
import { Icon, Score } from "@/components/ui";
import { date, money } from "@/lib/format";
import type { Counterparty } from "@/lib/types";
import styles from "@/components/counterparties/drawer.module.scss";

const ROLE = { supplier: "Поставщик", customer: "Покупатель", person: "Возможная связь" } as const;
const OF = { supplier: "закупок", customer: "продаж", person: "" } as const;

/** Короткие подсказки «что делать» по правилам: роль, доля платежей, есть ли название и новости. Без выдуманных фактов. */
export function suggestions(c: Counterparty, hasDirect: boolean): string[] {
  const out: string[] = [];
  const lvl = shareLevel(c.weight);
  if (c.relation === "supplier") {
    if (lvl === "high") out.push(`Рассмотрите второго поставщика: сейчас на этого приходится ${pct(c.weight)} закупок.`, "Зафиксируйте цену и сроки поставки договором.");
    else if (lvl === "medium") out.push("Проверьте, кем можно заменить этого поставщика, если поставки сорвутся.");
    else out.push("Критичной зависимости нет: достаточно следить за новостями.");
  } else if (c.relation === "customer") {
    if (lvl === "high") out.push(`Расширяйте круг клиентов: на этого покупателя приходится ${pct(c.weight)} продаж.`, "Проверьте условия и сроки оплаты, чтобы не копить долг одного клиента.");
    else if (lvl === "medium") out.push("Держите под контролем условия оплаты и график отгрузок этому покупателю.");
    else out.push("Критичной зависимости нет: достаточно следить за новостями.");
  }
  if (hasDirect) out.push("Откройте новость ниже и оцените, как она влияет на ваши поставки или спрос.");
  if (!isKnown(c)) out.push("Добавьте реквизиты (ИНН, название): тогда мы начнем следить за новостями об этой компании.");
  return out.slice(0, 3);
}

function why(c: Counterparty, hasDirect: boolean): string {
  const base = `Доля ${pct(c.weight)} ${OF[c.relation]} (порог: от 25% средний риск, от 40% высокий).`;
  return hasDirect ? `${base} Плюс свежая новость называет этого контрагента, поэтому уровень повышен.` : base;
}

function NewsItem({ k }: { k: Key }) {
  return (
    <li>
      <div className={styles.nMeta}>{k.score !== null && <Score value={k.score} />}<time dateTime={k.published}>{date(k.published)}</time></div>
      <Link href={`/pulse/n/${encodeURIComponent(k.id)}`}>{k.title}</Link>
    </li>
  );
}

/** Панель с деталями контрагента: справа на десктопе, листом снизу на телефоне. Esc закрывает, Tab не выходит наружу. */
export function CounterpartyDrawer({ c, keys, onClose }: { c: Counterparty; keys: Key[]; onClose: () => void }) {
  const panel = useRef<HTMLElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const news = newsFor(c, keys);
  const hasDirect = news.direct.length > 0;
  const risk = riskOf(c, hasDirect);
  const known = isKnown(c);
  const tips = suggestions(c, hasDirect);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key !== "Tab" || !panel.current) return;
      const f = panel.current.querySelectorAll<HTMLElement>("a[href], button:not([disabled])");
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
      opener?.focus({ preventScroll: true });
    };
  }, [onClose]);

  const title = known ? c.name : "Компания не определена";
  return (
    <div className={styles.backdrop} onClick={onClose}>
      <aside ref={panel} className={styles.panel} role="dialog" aria-modal="true" aria-label={`Контрагент: ${title}`} onClick={(e) => e.stopPropagation()}>
        <button ref={close} type="button" className={styles.close} onClick={onClose} aria-label="Закрыть"><Icon name="close" size={20} /></button>
        <div className={styles.head}>
          <h2>{title}</h2>
          <p className={styles.sub}>{known ? (c.sector ?? "Отрасль не указана") : `Идентификатор ${c.company_id}: в данных нет названия`}</p>
          <div className={styles.badges}>
            <span className={styles.role}>{ROLE[c.relation]}</span>
            <span className={`${styles.risk} ${styles[risk]}`}><Icon name={risk === "low" ? "check" : "risk"} size={14} /> {RISK_TEXT[risk]}</span>
            <span className={known ? styles.watch : styles.noWatch}>{known ? "Отслеживаем новости" : "Только платежи"}</span>
          </div>
        </div>

        <dl className={styles.facts}>
          <div><dt>Доля {OF[c.relation]}</dt><dd>{pct(c.weight)}</dd></div>
          <div><dt>Сумма платежей</dt><dd>{c.amount ? money(c.amount) : "нет данных"}</dd></div>
          {c.count ? <div><dt>Платежей</dt><dd>{c.count}</dd></div> : null}
        </dl>
        <p className={styles.why}>{why(c, hasDirect)}</p>

        <section aria-labelledby="cd-do">
          <h3 id="cd-do">Что стоит сделать</h3>
          <ul className={styles.tips}>{tips.map((t) => <li key={t}><Icon name="check" size={16} /> <span>{t}</span></li>)}</ul>
        </section>

        <section aria-labelledby="cd-news">
          <h3 id="cd-news">Новости об этом контрагенте</h3>
          {!known && <p className={styles.muted}>Без названия новость нельзя сопоставить с компанией. С реквизитами (ИНН, название) мы начнем искать новости о ней.</p>}
          {known && !news.direct.length && !news.sector.length && <p className={styles.muted}>Новостей про этого контрагента и его отрасль в вашей ленте сейчас нет. Проверка идет каждые 5 минут.</p>}
          {news.direct.length > 0 && (
            <>
              <h4>Прямое упоминание</h4>
              <ul className={styles.news}>{news.direct.slice(0, 4).map((k) => <NewsItem key={k.id} k={k} />)}</ul>
            </>
          )}
          {news.sector.length > 0 && (
            <>
              <h4>Новости его отрасли «{c.sector}»</h4>
              <ul className={styles.news}>{news.sector.slice(0, 4).map((k) => <NewsItem key={k.id} k={k} />)}</ul>
            </>
          )}
        </section>
      </aside>
    </div>
  );
}
