"use client";

import { useCallback, useEffect, useState } from "react";
import { AbortedError, ApiError, api } from "./api";
import { query, useQuery, withSignal, type QueryState } from "./query";
import type { CompanyProfile, Exposure, FeedItem, FeedPage } from "./types";

export type Load<T> = QueryState<T>;
type Result<T> = { key: string; data: T | null; error: ApiError | null };

/** Загрузка без кэша по ключу из deps (настройки, формы): результат другого ключа не показывается —
 *  при смене компании старые данные исчезают сразу, а ответ на устаревший запрос отбрасывается. */
export function useLoad<T>(fn: (signal: AbortSignal, reloaded: boolean) => Promise<T>, deps: unknown[]): Load<T> {
  const [result, setResult] = useState<Result<T> | null>(null);
  const [tick, setTick] = useState(0);
  const key = JSON.stringify([...deps, tick]);

  useEffect(() => {
    const controller = new AbortController();
    fn(controller.signal, tick > 0)
      .then((data) => { if (!controller.signal.aborted) setResult({ key, data, error: null }); })
      .catch((e) => {
        if (e instanceof AbortedError || controller.signal.aborted) return;
        setResult({ key, data: null, error: e instanceof ApiError ? e : new ApiError("Непредвиденная ошибка", "CLIENT", true) });
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fn меняется на каждой отрисовке, зависимости — в key
  }, [key]);

  const current = result?.key === key ? result : null;
  return { data: current?.data ?? null, error: current?.error ?? null, loading: current === null,
           reload: useCallback(() => setTick((t) => t + 1), []) };
}

/** Ключ ленты в кэше: все ленты компании начинаются с feed:<companyId>. */
export const feedKey = (companyId: string, topic?: string, story?: string) =>
  `feed:${companyId}:${topic ?? ""}:${story ?? ""}`;

/** Лента из общего кэша: страница и уведомления в шапке получают один ответ; fresh — новый запрос. */
export function loadFeed(companyId: string, opts: { topic?: string; story?: string; fresh?: boolean; signal?: AbortSignal } = {}) {
  const promise = query(feedKey(companyId, opts.topic, opts.story), () => api.feed(companyId, opts.topic, opts.story),
                        { fresh: opts.fresh });
  return withSignal(promise, opts.signal);
}

export function useFeed(companyId: string, topic?: string): Load<FeedItem[]> {
  const page = useFeedWithTopics(companyId, topic);
  return { ...page, data: page.data?.items ?? null };
}

/** Лента вместе со счетчиками тем по всей ленте компании (для фильтра тем). */
export function useFeedWithTopics(companyId: string, topic?: string, story?: string): Load<FeedPage> {
  return useQuery(feedKey(companyId, topic, story), () => api.feed(companyId, topic, story));
}

export function useCompany(companyId: string): Load<{ profile: CompanyProfile; exposures: Exposure[] }> {
  return useQuery(`company:${companyId}`, () => api.company(companyId), { staleMs: 5 * 60_000 });
}
