import type { RelevanceReason } from "./types";

/**
 * Причины отбора для карточки новости — без повторов и общих слов.
 * Один признак компании дает одну причину: «Есть кредиты» от двух тем новости (ставка и кредитование) —
 * это один и тот же факт, второй пункт ничего не добавляет. «Важная тема для роли» — общая фраза:
 * показывается, только если других причин нет. Порядок (самые весомые первыми) сохраняется.
 */
export function cardReasons(reasons: RelevanceReason[], limit = 4): RelevanceReason[] {
  const specific = reasons.filter((r) => r.kind !== "role");
  const pool = specific.length ? specific : reasons;
  const seen = new Set<string>();
  const out: RelevanceReason[] = [];
  for (const r of pool) {
    const key = r.kind === "exposure" ? `feature:${r.feature}` : `text:${r.text.trim().toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(r);
    if (out.length >= limit) break;
  }
  return out;
}
