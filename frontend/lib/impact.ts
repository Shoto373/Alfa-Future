import type { Insight } from "./types";

/** «Путь влияния» в разборе: событие → каналы, через которые оно касается компании → компания и итог в рублях. */
export type Channel = { key: string; title: string; detail: string; tone: "neg" | "pos" | "neutral"; target: string };

// Разделы разбора и их якоря (ClaimList anchor): ветка ведет к первому выводу, который опирается на ее признак.
const SECTIONS = [["why_important", "why"], ["risks", "risk"], ["opportunities", "opp"], ["actions", "act"]] as const;

/** Якорь вывода, где объясняется канал: по признаку компании, иначе — первый вывод «Почему это важно». */
export function targetOf(ins: Insight, feature: string): string {
  for (const [section, anchor] of SECTIONS) {
    const i = (ins[section] ?? []).findIndex((c) => (c.features ?? []).includes(feature));
    if (i >= 0) return `${anchor}-${i}`;
  }
  return "why-0";
}
export type Impact = { event: string; channels: Channel[]; effect: string; amount: string | null; amountSign: "neg" | "pos" | null };

const FEATURE_TITLE: Record<string, string> = {
  "products.loans": "Кредиты", "products.leasing": "Лизинг", "products.deposits": "Депозиты", "products.factoring": "Факторинг",
  "products.guarantees": "Гарантии", "products.payroll": "Зарплатный проект", fts_flag: "ВЭД", fts_countries: "Страны ВЭД",
  sector: "Отрасль", revenue: "Масштаб бизнеса", market: "Место в отрасли", workers_fns: "Персонал", group: "Группа компаний",
  "suppliers.by_sector": "Поставщики", "customers.by_sector": "Покупатели", "suppliers.top1_share": "Крупный поставщик",
};
const KIND_TITLE: Record<string, string> = {
  sector_mention: "Ваша отрасль", country: "Страны ВЭД", region: "Регион", group: "Группа компаний",
  mention: "Компания в новости", counterparty: "Контрагент в новости",
};
const SKIP = new Set(["role", "feedback", "magnitude"]);
const MAX = 4;

function detail(text: string): string {
  const after = text.includes(": ") ? text.split(": ").slice(1).join(": ") : text;
  const clean = after.replace(/^Отрасль «[^»]+»:\s*/, "").trim();
  return clean.length > 64 ? `${clean.slice(0, 62).trimEnd()}…` : clean;
}

function title(r: Insight["relevance"]["reasons"][number]): string {
  // Покупатели и поставщики — и из цепочки поставок, и из признаков компании («…от покупателей — отрасль «X»: …»).
  if (r.kind === "supply_chain" || r.feature.endsWith(".by_sector")) {
    const sector = /отрасль «([^»]+)»/.exec(r.text)?.[1];
    const side = r.feature.startsWith("customers") ? "Покупатели" : "Поставщики";
    return sector ? `${side}: ${sector}` : side;
  }
  if (r.kind === "exposure") {
    return FEATURE_TITLE[r.feature] ?? (r.feature.startsWith("extra.") ? "Сведения компании" : "Профиль компании");
  }
  return KIND_TITLE[r.kind] ?? "Связь с компанией";
}

/** Сумма из расчета «что если» в разделах разбора (утверждение со ссылкой на client:scenario:*). */
function scenarioAmount(ins: Insight): { amount: string; sign: "neg" | "pos" } | null {
  for (const [list, sign] of [[ins.risks, "neg"], [ins.opportunities, "pos"]] as const) {
    for (const c of list) {
      if (!c.source_ids.some((s) => s.startsWith("client:scenario:"))) continue;
      const m = /≈\s*([\d\s,.]+\s*(?:млн|млрд)\s*₽)/.exec(c.text);
      if (m) return { amount: m[1].replace(/\s+/g, " ").trim(), sign };
    }
  }
  return null;
}

export function impactOf(ins: Insight): Impact {
  const seen = new Set<string>();
  const channels: Channel[] = [];
  for (const r of ins.relevance.reasons) {
    if (SKIP.has(r.kind)) continue;
    const t = title(r);
    if (seen.has(t)) continue;
    seen.add(t);
    channels.push({ key: `${r.kind}:${r.feature}:${channels.length}`, title: t, detail: detail(r.text),
      tone: ins.effect === "neg" ? "neg" : ins.effect === "pos" ? "pos" : "neutral", target: targetOf(ins, r.feature) });
    if (channels.length >= MAX) break;
  }
  const amount = scenarioAmount(ins);
  const event = ins.title.length > 90 ? `${ins.title.slice(0, 88).trimEnd()}…` : ins.title;
  return { event, channels, effect: ins.effect ?? "unclear", amount: amount?.amount ?? null, amountSign: amount?.sign ?? null };
}
