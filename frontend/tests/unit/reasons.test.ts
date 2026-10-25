import { describe, expect, it } from "vitest";
import { cardReasons } from "@/lib/reasons";
import type { RelevanceReason } from "@/lib/types";

const r = (kind: string, feature: string, text: string): RelevanceReason =>
  ({ kind, feature, text, origin: "client_data", weight: 1, topic: null }) as unknown as RelevanceReason;

describe("cardReasons", () => {
  it("один признак компании — одна причина; общая фраза роли убирается", () => {
    const out = cardReasons([
      r("exposure", "products.loans", "Есть кредиты: стоимость новых займов зависит от ставки"),
      r("exposure", "products.loans", "Есть кредиты: условия кредитования влияют на финансирование"),
      r("supply_chain", "customers.by_sector", "Через ваших покупателей: отрасль «Энергетика»"),
      r("role", "role", "Важная тема для финансового директора"),
      r("exposure", "products.leasing", "Есть лизинг: платежи по новым сделкам зависят от ставки"),
    ]);
    expect(out.map((x) => x.text)).toEqual([
      "Есть кредиты: стоимость новых займов зависит от ставки",
      "Через ваших покупателей: отрасль «Энергетика»",
      "Есть лизинг: платежи по новым сделкам зависят от ставки",
    ]);
  });

  it("роль остается, если других причин нет; одинаковый текст — один раз; лимит", () => {
    expect(cardReasons([r("role", "role", "Важная тема для финансового директора")]).length).toBe(1);
    expect(cardReasons([r("region", "region", "Касается вашего региона"), r("region", "region", "Касается вашего региона ")]).length).toBe(1);
    const many = ["a", "b", "c", "d", "e"].map((x) => r("exposure", x, x));
    expect(cardReasons(many, 2).map((x) => x.text)).toEqual(["a", "b"]);
  });
});
