/** «Ваш день» в шапке: даты, которые важны руководителю сегодня (часы с датой открывают эту сводку). */

const DAY = 86_400_000;

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

export function daysBetween(from: Date, to: Date): number {
  return Math.round((startOfDay(to).getTime() - startOfDay(from).getTime()) / DAY);
}

/**
 * Срок единого налогового платежа: 28-е число месяца; если оно выпадает на субботу или воскресенье —
 * следующий понедельник (праздничные переносы не учитываются). После срока — 28-е следующего месяца.
 */
export function taxDeadline(now: Date): { date: Date; days: number } {
  for (let shift = 0; shift < 2; shift++) {
    const d = new Date(now.getFullYear(), now.getMonth() + shift, 28);
    const wd = d.getDay();
    if (wd === 6) d.setDate(d.getDate() + 2);
    if (wd === 0) d.setDate(d.getDate() + 1);
    const days = daysBetween(now, d);
    if (days >= 0) return { date: d, days };
  }
  /* c8 ignore next */
  throw new Error("unreachable");
}

/** Когда придет следующая утренняя сводка: сегодня (если ее время еще не наступило) или завтра. */
export function nextDigest(now: Date, settings: { digest: boolean; digest_time: string } | null): { today: boolean; time: string } | null {
  if (!settings?.digest) return null;
  const [h, m] = settings.digest_time.split(":").map(Number);
  const today = now.getHours() * 60 + now.getMinutes() < h * 60 + m;
  return { today, time: settings.digest_time };
}

export function inDays(n: number): string {
  if (n === 0) return "сегодня";
  if (n === 1) return "завтра";
  const m10 = n % 10, m100 = n % 100;
  const word = m10 === 1 && m100 !== 11 ? "день" : m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? "дня" : "дней";
  return `через ${n} ${word}`;
}

/** «1 важное событие», «3 важных события», «7 важных событий». */
export function importantWord(n: number): string {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return "важное событие";
  return m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? "важных события" : "важных событий";
}
