"use client";

import { useCallback, useEffect, useState } from "react";
import { AbortedError, ApiError, api } from "./api";
import type { CompanyProfile, Exposure, FeedItem, TopicCount, StoryChip } from "./types";

type Load<T> = { data: T | null; error: ApiError | null; loading: boolean; reload: () => void };

function useLoad<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[]): Load<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setData(null); // смена компании/роли — старые данные не показываем
    fn(controller.signal)
      .then((d) => { if (!controller.signal.aborted) setData(d); })
      .catch((e) => {
        if (e instanceof AbortedError || controller.signal.aborted) return;
        setError(e instanceof ApiError ? e : new ApiError("Непредвиденная ошибка", "CLIENT", true));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data, error, loading, reload: useCallback(() => setTick((t) => t + 1), []) };
}

export function useFeed(companyId: string, topic?: string): Load<FeedItem[]> {
  return useLoad((s) => api.feed(companyId, topic, s).then((r) => r.items), [companyId, topic]);
}

/** Лента вместе со счетчиками тем по всей ленте компании (для фильтра тем). */
export function useFeedWithTopics(companyId: string, topic?: string, story?: string): Load<{ items: FeedItem[]; topic_counts: TopicCount[]; stories: StoryChip[] }> {
  return useLoad((s) => api.feed(companyId, topic, s, story), [companyId, topic, story]);
}

export function useCompany(companyId: string): Load<{ profile: CompanyProfile; exposures: Exposure[] }> {
  return useLoad((s) => api.company(companyId, s), [companyId]);
}
