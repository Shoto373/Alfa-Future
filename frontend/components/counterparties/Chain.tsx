import { Icon } from "@/components/ui";
import styles from "@/components/counterparties/parts.module.scss";

/** Контрагент без профиля: бэкенд отдает ему имя «Контрагент U_121» (graph.name), без отрасли. Новости по такому не найти. */
export const anonId = (name: string, companyId?: string): string | null => {
  const m = /^Контрагент (\S+)$/.exec(name.trim());
  return m && (!companyId || m[1] === companyId) ? m[1] : null;
};

export interface ChainNode { role: string; name: string; pct?: string }

const STEP = /^(его )?(поставщик|покупатель) (.+?)(?: \((.+)\))?$/;
const PERSON = /^(.+?): возможная связь/;

/** Разбирает текст цепочки с сервера («вы → поставщик А (12% закупок) → его поставщик Б (15%)») в узлы для схемы. */
export function parseChain(text: string, fallbackName?: string): ChainNode[] {
  const nodes: ChainNode[] = [];
  for (const seg of text.split(" → ").slice(1)) {
    const s = STEP.exec(seg.trim());
    if (s) {
      const supplier = s[2] === "поставщик";
      const role = s[1] ? (supplier ? "Поставщик поставщика" : "Покупатель покупателя") : (supplier ? "Поставщик" : "Покупатель");
      nodes.push({ role, name: s[3], pct: s[4] });
      continue;
    }
    const p = PERSON.exec(seg.trim());
    nodes.push(p ? { role: "Возможная связь", name: p[1] } : { role: "Контрагент", name: seg.trim() });
  }
  if (!nodes.length && fallbackName) nodes.push({ role: "Контрагент", name: fallbackName });
  return nodes;
}

/** Схема «Вы → Поставщик → Поставщик поставщика»: последний узел — тот, о ком новость или кто важен. */
export function Chain({ text, fallbackName, label }: { text: string; fallbackName?: string; label?: string }) {
  const nodes = parseChain(text, fallbackName);
  return (
    <ol className={styles.chain} aria-label={label ?? "Цепочка связи"}>
      <li className={`${styles.node} ${styles.nodeYou}`}><small>Вы</small><b>Ваша компания</b></li>
      {nodes.map((n, i) => (
        <li key={i} className={`${styles.link}`}>
          <span className={styles.arrow}><Icon name="chevronRight" size={16} /></span>
          <span className={`${styles.node} ${i === nodes.length - 1 ? styles.nodeLast : ""}`}>
            <small>{n.role}</small>
            {anonId(n.name) ? <b className={styles.anon} title={`Идентификатор ${anonId(n.name)}`}>Компания не определена</b> : <b>{n.name}</b>}
            {n.pct && <em>{n.pct}</em>}
          </span>
        </li>
      ))}
    </ol>
  );
}
