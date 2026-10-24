"use client";

// Слой данных (SPR3-07): кэш ответов по ключу на время жизни вкладки.
// - Одинаковые запросы в полете объединяются: несколько частей экрана получают один ответ.
// - Свежий ответ (моложе staleMs) отдается без запроса: переход лента → разбор → назад не грузит ленту заново.
// - Устаревший ответ показывается сразу и тихо обновляется в фоне (stale-while-revalidate).
// - invalidate(prefix) — сброс после изменений (новая новость, «Повторить»).
// Отмена одного потребителя не отменяет общий запрос: его ответ пригодится остальным.

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { AbortedError, ApiError } from "./api";

type Entry = { data?: unknown; at: number; promise?: Promise<unknown>; error?: ApiError };

export const DEFAULT_STALE_MS = 60_000;

const entries = new Map<string, Entry>();
const listeners = new Set<() => void>();
let version = 0;

function notify() {
  version += 1;
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function asApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError("Непредвиденная ошибка", "CLIENT", true);
}

/** Сохраненный ответ по ключу (без запроса). */
export function peek<T>(key: string): { data: T; at: number } | undefined {
  const entry = entries.get(key);
  return entry && "data" in entry ? { data: entry.data as T, at: entry.at } : undefined;
}

/** Ответ по ключу: свежий из кэша, общий запрос в полете или новый запрос (fresh — всегда новый). */
export function query<T>(key: string, fetcher: () => Promise<T>, opts: { staleMs?: number; fresh?: boolean } = {}): Promise<T> {
  const staleMs = opts.staleMs ?? DEFAULT_STALE_MS;
  const entry = entries.get(key) ?? { at: 0 };
  if (!opts.fresh && "data" in entry && Date.now() - entry.at < staleMs) return Promise.resolve(entry.data as T);
  if (!opts.fresh && entry.promise) return entry.promise as Promise<T>;
  const promise = fetcher().then(
    (data) => {
      if (entries.get(key)?.promise === promise) entries.set(key, { data, at: Date.now() });
      notify();
      return data;
    },
    (e) => {
      const current = entries.get(key);
      if (current?.promise === promise) entries.set(key, { ...current, promise: undefined, error: asApiError(e) });
      notify();
      throw e;
    },
  );
  entries.set(key, { ...entry, promise, error: undefined });
  return promise;
}

/** Ожидание общего запроса с собственной отменой: отменяется только ожидание этого потребителя. */
export function withSignal<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(new AbortedError());
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(new AbortedError());
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
}

/** Сброс кэша по префиксу ключа (или целиком): следующий запрос пойдет на сервер. */
export function invalidate(prefix = ""): void {
  for (const key of [...entries.keys()]) if (key.startsWith(prefix)) entries.delete(key);
  notify();
}

export type QueryState<T> = { data: T | null; error: ApiError | null; loading: boolean; reload: () => void };

/** Данные по ключу для компонента: сразу из кэша, при устаревании — обновление в фоне; null — не загружать. */
export function useQuery<T>(key: string | null, fetcher: () => Promise<T>, opts: { staleMs?: number } = {}): QueryState<T> {
  useSyncExternalStore(subscribe, () => version, () => version);
  const [failed, setFailed] = useState<{ key: string; error: ApiError } | null>(null);

  useEffect(() => {
    if (key === null) return;
    query(key, fetcher, opts).catch((e) => {
      if (!(e instanceof AbortedError)) setFailed({ key, error: asApiError(e) });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fetcher и opts — новые на каждой отрисовке, зависимость — ключ
  }, [key]);

  const reload = useCallback(() => {
    if (key === null) return;
    setFailed(null);
    query(key, fetcher, { ...opts, fresh: true }).catch((e) => {
      if (!(e instanceof AbortedError)) setFailed({ key, error: asApiError(e) });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const cached = key === null ? undefined : peek<T>(key);
  const error = failed?.key === key && !cached ? failed.error : null;
  return { data: cached?.data ?? null, error, loading: key !== null && !cached && !error, reload };
}
