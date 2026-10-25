import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useAnimatedNumber } from "@/lib/motion";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useAnimatedNumber", () => {
  it("первое значение сразу, изменение досчитывается до цели", async () => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance"] });
    const { result, rerender } = renderHook(({ v }) => useAnimatedNumber(v, 400), { initialProps: { v: 100 } });
    expect(result.current).toBe(100);
    rerender({ v: 200 });
    await act(async () => { vi.advanceTimersByTime(200); });
    expect(result.current).toBeGreaterThan(100);
    expect(result.current).toBeLessThan(200);
    await act(async () => { vi.advanceTimersByTime(400); });
    expect(result.current).toBe(200);
  });

  it("«уменьшить движение» в системе — новое значение сразу", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q }));
    const { result, rerender } = renderHook(({ v }) => useAnimatedNumber(v), { initialProps: { v: 1 } });
    rerender({ v: 5 });
    expect(result.current).toBe(5);
  });
});

describe("useAnimatedNumber со стартовым значением", () => {
  it("поднимается от старта к цели при появлении", async () => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance"] });
    const { result } = renderHook(() => useAnimatedNumber(72, 1000, 0));
    expect(result.current).toBe(0);
    await act(async () => { vi.advanceTimersByTime(500); });
    expect(result.current).toBeGreaterThan(0);
    expect(result.current).toBeLessThan(72);
    await act(async () => { vi.advanceTimersByTime(600); });
    expect(result.current).toBe(72);
  });
});
