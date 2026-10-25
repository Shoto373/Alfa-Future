import type { Counterparty } from "@/lib/types";
import { anonId } from "@/components/counterparties/Chain";

/** Новости ищутся только по компаниям с названием: у безымянных (в данных лишь идентификатор) совпасть нечему. */
export const isKnown = (c: Counterparty) => !anonId(c.name, c.company_id);

export const pct = (w: number) => (w > 0 && w < 0.01 ? "<1%" : `${Math.round(w * 100)}%`);

export const plural = (n: number, one: string, few: string, many: string) => {
  const m = n % 100, d = n % 10;
  return m > 10 && m < 15 ? many : d === 1 ? one : d >= 2 && d <= 4 ? few : many;
};

/** Название в кавычках; в «АО «Ромашка»» кавычки уже есть. */
export const quote = (name: string) => (name.includes("«") ? name : `«${name}»`);

export const label = (c: Counterparty) => (isKnown(c) ? quote(c.name) : `без названия (${c.company_id})`);

export type RiskLevel = "high" | "medium" | "low";

export const RISK_TEXT: Record<RiskLevel, string> = { high: "Высокий риск", medium: "Средний риск", low: "Низкий риск" };
export const RISK_RANK: Record<RiskLevel, number> = { high: 2, medium: 1, low: 0 };

/** Порог зависимости: от 40% платежей — высокая, от 25% — средняя. */
export const shareLevel = (w: number): RiskLevel => (w >= 0.4 ? "high" : w >= 0.25 ? "medium" : "low");

/** Светофор по контрагенту: доля платежей; прямое упоминание контрагента в свежей новости поднимает уровень на ступень. */
export function riskOf(c: Counterparty, directNews: boolean): RiskLevel {
  const base = shareLevel(c.weight);
  if (!directNews) return base;
  return base === "low" ? "medium" : "high";
}
