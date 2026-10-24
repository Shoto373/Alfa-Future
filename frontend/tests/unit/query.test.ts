import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { AbortedError, ApiError } from "@/lib/api";
import { invalidate, peek, query, useQuery, withSignal } from "@/lib/query";

afterEach(() => {
  invalidate();
  vi.useRealTimers();
});

describe("query", () => {
  it("объединяет одинаковые запросы в полете", async () => {
    const fetcher = vi.fn(() => Promise.resolve(42));
    const [a, b] = await Promise.all([query("k", fetcher), query("k", fetcher)]);
    expect([a, b]).toEqual([42, 42]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("свежий ответ отдает без запроса, устаревший — запрашивает заново", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockResolvedValueOnce("first").mockResolvedValueOnce("second");
    expect(await query("k", fetcher, { staleMs: 1000 })).toBe("first");
    expect(await query("k", fetcher, { staleMs: 1000 })).toBe("first");
    expect(fetcher).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1500);
    expect(await query("k", fetcher, { staleMs: 1000 })).toBe("second");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("fresh всегда идет на сервер, invalidate сбрасывает по префиксу", async () => {
    const fetcher = vi.fn().mockResolvedValue("x");
    await query("feed:a", fetcher);
    await query("feed:a", fetcher, { fresh: true });
    expect(fetcher).toHaveBeenCalledTimes(2);
    await query("company:a", fetcher);
    invalidate("feed:");
    expect(peek("feed:a")).toBeUndefined();
    expect(peek("company:a")?.data).toBe("x");
  });

  it("ошибка не остается в кэше: следующий запрос повторяет попытку", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new ApiError("нет связи", "NETWORK_ERROR", true)).mockResolvedValueOnce("ok");
    await expect(query("k", fetcher)).rejects.toBeInstanceOf(ApiError);
    expect(await query("k", fetcher)).toBe("ok");
  });

  it("withSignal отменяет только ожидание этого потребителя", async () => {
    let resolve!: (v: string) => void;
    const shared = new Promise<string>((r) => { resolve = r; });
    const controller = new AbortController();
    const mine = withSignal(shared, controller.signal);
    const other = withSignal(shared);
    controller.abort();
    await expect(mine).rejects.toBeInstanceOf(AbortedError);
    resolve("done");
    expect(await other).toBe("done");
    const aborted = new AbortController();
    aborted.abort();
    await expect(withSignal(shared, aborted.signal)).rejects.toBeInstanceOf(AbortedError);
  });
});

describe("useQuery", () => {
  it("второй компонент с тем же ключом получает данные из кэша без запроса", async () => {
    const fetcher = vi.fn().mockResolvedValue({ items: [1, 2] });
    const first = renderHook(() => useQuery("feed:c", fetcher));
    expect(first.result.current.loading).toBe(true);
    await waitFor(() => expect(first.result.current.data).toEqual({ items: [1, 2] }));
    const second = renderHook(() => useQuery("feed:c", fetcher));
    expect(second.result.current.loading).toBe(false);
    expect(second.result.current.data).toEqual({ items: [1, 2] });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("ошибка видна, «Повторить» запрашивает заново", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new ApiError("сбой", "INTERNAL_ERROR", false)).mockResolvedValueOnce("ok");
    const hook = renderHook(() => useQuery("k2", fetcher));
    await waitFor(() => expect(hook.result.current.error?.code).toBe("INTERNAL_ERROR"));
    act(() => hook.result.current.reload());
    await waitFor(() => expect(hook.result.current.data).toBe("ok"));
    expect(hook.result.current.error).toBeNull();
  });

  it("ключ null — не загружать", () => {
    const fetcher = vi.fn();
    const hook = renderHook(() => useQuery(null, fetcher));
    expect(hook.result.current.loading).toBe(false);
    hook.result.current.reload();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
