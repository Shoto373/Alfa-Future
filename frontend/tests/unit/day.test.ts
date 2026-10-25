import { describe, expect, it } from "vitest";
import { importantWord, inDays, nextDigest, taxDeadline } from "@/lib/day";

describe("Ваш день", () => {
  it("налоговый платеж — 28-е, с выходного переносится на понедельник, после срока — следующий месяц", () => {
    expect(taxDeadline(new Date(2026, 9, 25)).date.getDate()).toBe(28);            // 28.10.2026 — среда
    expect(taxDeadline(new Date(2026, 9, 25)).days).toBe(3);
    const nov = taxDeadline(new Date(2026, 9, 29));                                // после срока — 28 ноября (сб) → 30 ноября (пн)
    expect([nov.date.getMonth(), nov.date.getDate()]).toEqual([10, 30]);
    const feb = taxDeadline(new Date(2027, 1, 1));                                 // 28.02.2027 — воскресенье → 1 марта
    expect([feb.date.getMonth(), feb.date.getDate()]).toEqual([2, 1]);
    expect(taxDeadline(new Date(2026, 9, 28, 18)).days).toBe(0);                   // в день срока — «сегодня»
  });

  it("сводка — сегодня до своего времени, иначе завтра; выключена — нет", () => {
    const s = { digest: true, digest_time: "08:30" };
    expect(nextDigest(new Date(2026, 9, 25, 7, 0), s)).toEqual({ today: true, time: "08:30" });
    expect(nextDigest(new Date(2026, 9, 25, 9, 0), s)).toEqual({ today: false, time: "08:30" });
    expect(nextDigest(new Date(), { digest: false, digest_time: "08:30" })).toBeNull();
    expect(nextDigest(new Date(), null)).toBeNull();
  });

  it("сроки словами", () => {
    expect([inDays(0), inDays(1), inDays(2), inDays(5), inDays(11), inDays(21), inDays(22)])
      .toEqual(["сегодня", "завтра", "через 2 дня", "через 5 дней", "через 11 дней", "через 21 день", "через 22 дня"]);
  });

  it("склонение «важных событий»", () => {
    expect([1, 3, 5, 11, 21, 22].map(importantWord))
      .toEqual(["важное событие", "важных события", "важных событий", "важных событий", "важное событие", "важных события"]);
  });
});
