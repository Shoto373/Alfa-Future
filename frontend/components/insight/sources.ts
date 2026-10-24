import { api } from "@/lib/api";
import type { Insight, Source } from "@/lib/types";
import type { SourceIndex } from "./ClaimList";

export type SourceGroup = { key: string; kind: Source["kind"]; title: string; date: string | null; url: string | null;
  items: Source[] };

export function sourceLink(s: Source): string | null {
  if (s.kind === "news") return s.url;
  if (s.kind === "bank_analytics" && s.doc_id) return api.pdfUrl(s.doc_id, s.page);
  return null;
}

/** Источники для раздела «На чем основан вывод»: только те, на которые ссылаются выводы (и сама новость);
 *  тезисы одного документа банка с разных страниц — одна запись со списком страниц. */
export function groupSources(ins: Insight): { groups: SourceGroup[]; index: SourceIndex } {
  const cited = new Set<string>([`news:${ins.news_id}`]);
  const claims = [...ins.what_happened.facts, ...ins.what_happened.assumptions, ...ins.why_important, ...ins.risks,
    ...ins.opportunities, ...ins.actions, ...ins.bank_view.theses];
  claims.forEach((c) => c.source_ids.forEach((id) => cited.add(id)));
  const groups: SourceGroup[] = [];
  const byKey = new Map<string, SourceGroup>();
  for (const s of ins.sources) {
    if (!cited.has(s.source_id) || s.kind === "bank_product") continue;
    const key = s.kind === "bank_analytics" && s.doc_id ? `doc:${s.doc_id}` : s.source_id;
    let g = byKey.get(key);
    if (!g) {
      g = { key, kind: s.kind, title: s.title, date: s.date, url: sourceLink(s), items: [] };
      byKey.set(key, g);
      groups.push(g);
    }
    g.items.push(s);
  }
  groups.forEach((g) => g.items.sort((a, b) => (a.page ?? 0) - (b.page ?? 0)));
  const index: SourceIndex = new Map();
  groups.forEach((g, i) => g.items.forEach((s) => index.set(s.source_id, i + 1)));
  return { groups, index };
}

// Причина отбора — короткая метка и суть, без повторов.
const REASON_LABEL: Record<string, string> = {
  role: "Ваша роль", sector_mention: "Ваша отрасль в новости", group: "Группа компаний", country: "Страны ВЭД",
  region: "Ваш регион", magnitude: "Масштаб события", feedback: "Ваши оценки", supply_chain: "Контрагенты",
};
const FEATURE_LABEL: Record<string, string> = {
  sector: "Ваша отрасль", fts_countries: "ВЭД", "suppliers.by_sector": "Поставщики", "customers.by_sector": "Покупатели",
  "suppliers.top1_share": "Поставщики", group: "Группа компаний", workers_fns: "Персонал", revenue: "Масштаб компании",
  market: "Место в отрасли",
};

export function reasonLines(reasons: Insight["relevance"]["reasons"]): { label: string; text: string }[] {
  const out: { label: string; text: string }[] = [];
  const seen = new Set<string>();
  for (const r of reasons) {
    const label = r.kind === "exposure"
      ? FEATURE_LABEL[r.feature] ?? (r.feature.startsWith("products.") ? "Ваши продукты банка"
        : r.feature.startsWith("extra.") ? "Сведения компании" : "Профиль компании")
      : REASON_LABEL[r.kind] ?? "Причина";
    if (seen.has(label)) continue;
    seen.add(label);
    // «Есть лизинг: платежи…» -> «есть лизинг, платежи…»; у роли и упоминания отрасли текст и так короткий.
    let text = r.text.replace(/^Отрасль «[^»]+»:\s*/, "").replace(": ", " — ");
    if (r.kind === "role") text = text.replace(/^Важная тема для /, "тема важна для ");
    out.push({ label, text: text.charAt(0).toLowerCase() + text.slice(1) });
    if (out.length >= 4) break;
  }
  return out;
}
