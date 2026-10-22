/** Порог релевантности, с которого новость считается важной для компании и роли (главная, колокольчик). */
export const IMPORTANT_SCORE = 50;

export function money(value: number | null | undefined): string {
  if (!value) return "нет данных";
  if (value >= 1e9) return `${(value / 1e9).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млрд ₽`;
  if (value >= 1e6) return `${(value / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млн ₽`;
  return `${value.toLocaleString("ru-RU")} ₽`;
}

export function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toLocaleString("ru-RU", { maximumFractionDigits: digits })}%`;
}

export function date(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

export const PRODUCT_NAMES: Record<string, string> = {
  rko: "РКО",
  loans: "Кредиты",
  leasing: "Лизинг",
  deposits: "Депозиты",
  guarantees: "Гарантии",
  payroll: "Зарплатный проект",
  factoring: "Факторинг",
};

export const ORIGIN_LABEL: Record<string, string> = {
  fact: "Факт из новости",
  client_data: "Данные компании",
  bank: "Альфа-Банк",
  ai: "Вывод AI",
};
