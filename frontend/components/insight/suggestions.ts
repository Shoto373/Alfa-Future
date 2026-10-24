import type { Insight } from "@/lib/types";

const MAX = 4;

/** Подсказки для чата под эту новость и этот разбор. Формулировки совпадают с намерениями помощника
 *  (риски, позиция банка, контрагенты, возможности, действия, источники), поэтому ответ есть и без модели. */
export function chatSuggestions(ins: Insight): string[] {
  const out: string[] = [];
  const features = new Set(ins.features_used.map((f) => f.name));

  if (ins.risks.length) out.push("Какие риски это несет для компании?");
  if (ins.bank_view.available) out.push("Что думает Альфа-Банк об этом событии?");
  if (features.has("suppliers.by_sector") || features.has("customers.by_sector") || features.has("suppliers.top1_share")) {
    out.push("Как это затронет наших поставщиков и покупателей?");
  }
  if (ins.opportunities.length) out.push("Какие возможности это открывает?");
  out.push("Что делать в ближайшее время?");
  if (features.has("market")) out.push("Как мы выглядим на фоне отрасли?");
  out.push("На чем основан этот вывод?");
  return [...new Set(out)].slice(0, MAX);
}
