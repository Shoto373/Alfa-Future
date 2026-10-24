"use client";

import { useCallback, useEffect, useState } from "react";
import { AbortedError, ApiError, api } from "./api";
import type { CompanyProfile, Exposure, FeedItem, FeedPage } from "./types";

export type Load<T> = { data: T | null; error: ApiError | null; loading: boolean; reload: () => void };
type Result<T> = { key: string; data: T | null; error: ApiError | null };

/** Загрузка по ключу из deps: результат другого ключа не показывается — при смене компании или роли
 *  старые данные исчезают сразу, а ответ на устаревший запрос отбрасывается. */
export function useLoad<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[]): Load<T> {
  const [result, setResult] = useState<Result<T> | null>(null);
  const [tick, setTick] = useState(0);
  const key = JSON.stringify([...deps, tick]);

  useEffect(() => {
    const controller = new AbortController();
    fn(controller.signal)
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

export function useFeed(companyId: string, topic?: string): Load<FeedItem[]> {
  return useLoad((s) => api.feed(companyId, topic, s).then((r) => r.items), [companyId, topic]);
}

/** Лента вместе со счетчиками тем по всей ленте компании (для фильтра тем). */
export function useFeedWithTopics(companyId: string, topic?: string, story?: string): Load<FeedPage> {
  return useLoad((s) => api.feed(companyId, topic, s, story), [companyId, topic, story]);
}

export function useCompany(companyId: string): Load<{ profile: CompanyProfile; exposures: Exposure[] }> {
  return useLoad((s) => api.company(companyId, s), [companyId]);
}
