import { describe, expect, it } from "vitest";
import { impactOf, targetOf } from "@/lib/impact";
import type { Insight } from "@/lib/types";

const reason = (kind: string, feature: string, text: string) => ({ kind, feature, text, origin: "client_data", weight: 1, topic: null });
const claim = (text: string, source_ids: string[]) => ({ text, origin: "client_data", source_ids, features: [] });

function insight(over: Partial<Insight> = {}): Insight {
  return {
    title: "ЦБ повысил ключевую ставку до 15%", effect: "neg", risks: [], opportunities: [],
    relevance: { score: 80, reasons: [] }, ...over,
  } as unknown as Insight;
}

describe("impactOf", () => {
  it("каналы из причин отбора: без роли и повторов, с понятными названиями; не больше четырех", () => {
    const ins = insight({ relevance: { score: 80, reasons: [
      reason("exposure", "products.loans", "Есть кредиты: стоимость новых займов зависит от ставки"),
      reason("exposure", "products.loans", "Есть кредиты: условия кредитования влияют на финансирование"),
      reason("role", "role", "Важная тема для финансового директора"),
      reason("supply_chain", "customers.by_sector", "Через ваших покупателей: отрасль «Энергетика и ЖКХ», 99% поступлений"),
      reason("region", "region", "Касается вашего региона — Москва"),
      reason("exposure", "extra.notes", "Компания сообщила: импорт из Китая"),
      reason("counterparty", "counterparty_graph", "Поставщик ООО «Ромашка» назван в новости"),
    ] } as Insight["relevance"] });
    const m = impactOf(ins);
    expect(m.channels.map((c) => c.title)).toEqual(["Кредиты", "Покупатели: Энергетика и ЖКХ", "Регион", "Сведения компании"]);
    expect(m.channels[0].detail).toBe("стоимость новых займов зависит от ставки");
    expect(m.channels.every((c) => c.tone === "neg")).toBe(true);
  });

  it("сумма — из расчета «что если» со ссылкой на формулу; без расчета — нет суммы", () => {
    const withAmount = insight({ risks: [claim("Чувствительность к ставке: каждый +1 п.п. — это ≈ 145 млн ₽ процентных расходов в год",
      ["news:n1", "client:scenario:key_rate"])] as Insight["risks"] });
    expect(impactOf(withAmount)).toMatchObject({ amount: "145 млн ₽", amountSign: "neg" });
    const gain = insight({ effect: "pos", opportunities: [claim("Экономия ≈ 1,2 млрд ₽ в год", ["client:scenario:key_rate"])] as Insight["opportunities"] });
    expect(impactOf(gain)).toMatchObject({ amount: "1,2 млрд ₽", amountSign: "pos" });
    expect(impactOf(insight({ risks: [claim("≈ 5 млн ₽", ["news:n1"])] as Insight["risks"] })).amount).toBeNull();
  });

  it("покупатели из признаков компании — тоже с отраслью", () => {
    const m = impactOf(insight({ relevance: { score: 1, reasons: [reason("exposure", "customers.by_sector",
      "99% известной части поступлений от покупателей — отрасль «Энергетика и ЖКХ»: инвестпрограммы финансируются долгом")] } as Insight["relevance"] }));
    expect(m.channels[0].title).toBe("Покупатели: Энергетика и ЖКХ");
  });

  it("длинный заголовок сокращается; неизвестный признак — «Профиль компании»; без эффекта — unclear", () => {
    const m = impactOf(insight({ title: "Ч".repeat(120), effect: null as unknown as Insight["effect"],
      relevance: { score: 1, reasons: [reason("exposure", "workers_x", "Персонал: много сотрудников"), reason("mention", "mention", "Компания названа")] } as Insight["relevance"] }));
    expect(m.event.length).toBe(89);
    expect(m.channels.map((c) => [c.title, c.tone])).toEqual([["Профиль компании", "neutral"], ["Компания в новости", "neutral"]]);
    expect(m.effect).toBe("unclear");
  });

  it("ветка ведет к первому выводу со своим признаком; без совпадения — к «Почему это важно»", () => {
    const withClaims = insight({
      why_important: [{ ...claim("Отрасль", ["x"]), features: ["sector"] }],
      risks: [{ ...claim("Кредиты дорожают", ["x"]), features: [] }, { ...claim("Долг", ["x"]), features: ["products.loans"] }],
    } as unknown as Partial<Insight>);
    expect(targetOf(withClaims, "products.loans")).toBe("risk-1");
    expect(targetOf(withClaims, "sector")).toBe("why-0");
    expect(targetOf(withClaims, "region")).toBe("why-0");
  });
});
