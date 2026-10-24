"use client";

import { useEffect, useState } from "react";
import { API_BASE_URL, api } from "./api";

/**
 * Продуктовая аналитика (SPR4-07): события воронки — на свой сервер, без внешних систем.
 * Свойства — только коды-перечисления (сервер отклоняет текст), поэтому ни заголовок, ни вопрос, ни email не уходят.
 * Сбой отправки не мешает работе: событие просто теряется.
 */
export type TrackKind = "feed_view" | "insight_open" | "section_expand" | "source_click" | "question_ask" | "feedback" | "offer_click";

let company: string | null = null;
const paths = { current: "", previous: "" };

/** Страница приложения: при переходе внутри приложения document.referrer не меняется — предыдущую помним сами. */
export function setTrackPath(path: string): void {
  if (path !== paths.current) {
    paths.previous = paths.current;
    paths.current = path;
  }
}

/** Откуда открыт разбор: из сводки или алерта (метка в ссылке), из ленты, с главной, из соседней новости — или напрямую. */
export function openSource(from: string | null): string {
  if (from === "digest" || from === "alert") return from;
  const prev = paths.previous;
  if (prev.startsWith("/pulse/n/")) return "rail";
  if (prev === "/pulse/counterparties") return "counterparties";
  if (prev.startsWith("/pulse")) return "feed";
  if (prev === "/") return "home";
  return "direct";
}

/** Текущая компания сессии: события относятся к ней (роль сервер берет из членства). */
export function setTrackCompany(companyId: string | null): void {
  company = companyId || null;
}

export function track(kind: TrackKind, props: Record<string, string | number | boolean> = {}): void {
  try {
    void fetch(`${API_BASE_URL}/api/v1/events`, {
      method: "POST", credentials: "include", keepalive: true, headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, company_id: company, props }),
    }).catch(() => { /* аналитика не мешает работе */ });
  } catch {
    /* fetch недоступен (тесты) */
  }
}

export type Flags = Record<string, { enabled: boolean; variant: string | null }>;
const cache = new Map<string, Promise<Flags>>();

/** Флаги и варианты экспериментов пользователя для компании; null — еще загружаются (показываем контроль). */
export function useFlags(companyId: string | null): Flags | null {
  const [flags, setFlags] = useState<{ key: string; value: Flags } | null>(null);
  const key = companyId ?? "";
  useEffect(() => {
    if (!cache.has(key)) cache.set(key, api.flags(companyId).then((r) => r.flags).catch(() => ({})));
    let live = true;
    cache.get(key)!.then((value) => { if (live) setFlags({ key, value }); });
    return () => { live = false; };
  }, [key, companyId]);
  return flags?.key === key ? flags.value : null;
}
