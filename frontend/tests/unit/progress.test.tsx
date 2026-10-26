import { describe, expect, it, vi } from "vitest";
import { act, render, renderHook, screen } from "@testing-library/react";
import UpgradeProgress from "@/components/insight/UpgradeProgress";
import { activeIndex, emptyProgress, EXIT_HOLD_MS, EXIT_MS, nextExit, percent, reduceProgress, useUpgradeExit, type ProgressEvent, type ProgressState } from "@/components/insight/progress";

const ev = (stage: string, state: "start" | "done", step?: string): ProgressEvent =>
  ({ stage, index: ["collect", "draft", "check", "review", "finalize"].indexOf(stage) + 1, total: 5, state, step });
const play = (...events: ProgressEvent[]): ProgressState => events.reduce(reduceProgress, emptyProgress);

describe("ход модели: состояние выводится только из событий", () => {
  it("без событий полоса на нуле", () => {
    expect(percent(emptyProgress)).toBe(0);
    expect(activeIndex(emptyProgress)).toBeUndefined();
  });

  it("начало этапа не двигает полосу, завершение двигает на вес этапа", () => {
    const s1 = play(ev("collect", "start"));
    expect(percent(s1)).toBe(0);
    expect(activeIndex(s1)).toBe(1);
    const s2 = reduceProgress(s1, ev("collect", "done"));
    expect(percent(s2)).toBe(15);
    expect(activeIndex(s2)).toBeUndefined();
    expect(percent(reduceProgress(s2, ev("draft", "start")))).toBe(15);
  });

  it("пропущенный этап (нет смысловой проверки) закрывается началом следующего", () => {
    const s = play(ev("collect", "start"), ev("collect", "done"), ev("draft", "start"), ev("draft", "done"),
      ev("check", "start"), ev("check", "done"), ev("finalize", "start"));
    expect(s.done).toBe(4);
    expect(percent(s)).toBe(90);
    expect(percent(reduceProgress(s, ev("finalize", "done")))).toBe(100);
  });

  it("исправление — признак внутри этапа проверки, полоса не меняется; события не откатывают прогресс назад", () => {
    const before = play(ev("collect", "done"), ev("draft", "done"), ev("check", "start"));
    const fix = reduceProgress(before, ev("check", "start", "fix"));
    expect(fix.fixing).toBe(true);
    expect(percent(fix)).toBe(percent(before));
    expect(reduceProgress(fix, ev("check", "done")).fixing).toBe(false);
    expect(reduceProgress(fix, ev("collect", "start")).done).toBe(fix.done);
  });

  it("неизвестный этап игнорируется", () => {
    expect(reduceProgress(emptyProgress, { stage: "future", index: 9, total: 9, state: "start" })).toBe(emptyProgress);
  });
});

describe("UpgradeProgress", () => {
  it("progressbar с числом, подписью этапа и списком: готово, идет, ожидает", () => {
    render(<UpgradeProgress state={play(ev("collect", "done"), ev("draft", "start"))} />);
    const bar = screen.getByRole("progressbar", { name: "Ход подготовки AI-разбора" });
    expect(bar.getAttribute("aria-valuenow")).toBe("15");
    expect(bar.getAttribute("aria-valuemin")).toBe("0");
    expect(bar.getAttribute("aria-valuemax")).toBe("100");
    expect(bar.getAttribute("aria-valuetext")).toContain("Этап 2 из 5: Составляем черновик");
    expect(screen.getByText("Этап 2 из 5: Составляем черновик")).toBeTruthy();
    expect(screen.getByText(/Собираем данные компании и аналитику банка/).textContent).toContain("готово");
    expect(document.querySelector("[aria-current='step']")?.textContent).toContain("выполняется");
    expect(screen.getByText(/Оформляем карточку/).textContent).toContain("ожидает");
  });

  it("во время исправления этап проверки называется «Исправляем и дополняем»", () => {
    render(<UpgradeProgress state={play(ev("collect", "done"), ev("draft", "done"), ev("check", "start"), ev("check", "start", "fix"))} />);
    expect(screen.getByText("Этап 3 из 5: Исправляем и дополняем")).toBeTruthy();
  });
});

describe("уход плашки хода модели", () => {
  it("nextExit: успех → done, сбой → сразу gone, новый запуск во время ухода → live", () => {
    expect(nextExit("gone", true, false)).toBe("live");
    expect(nextExit("live", false, true)).toBe("done");
    expect(nextExit("live", false, false)).toBe("gone");
    expect(nextExit("done", false, true)).toBe("done");
    expect(nextExit("exiting", true, false)).toBe("live");
    expect(nextExit("gone", false, true)).toBe("gone");
    expect(nextExit("done", false, true, true)).toBe("gone");  // «Пересчитать» во время показа «готово»
  });

  it("хук: успех — удержание, схлопывание, исчезновение по таймерам", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ live, ok }) => useUpgradeExit(live, ok), { initialProps: { live: true, ok: false } });
    expect(result.current).toBe("live");
    rerender({ live: false, ok: true });
    expect(result.current).toBe("done");
    act(() => { vi.advanceTimersByTime(EXIT_HOLD_MS + 10); });
    expect(result.current).toBe("exiting");
    act(() => { vi.advanceTimersByTime(EXIT_MS + 10); });
    expect(result.current).toBe("gone");
    vi.useRealTimers();
  });

  it("хук: сбой или «Пересчитать» — без показа «готово»; перезапуск во время ухода отменяет уход", () => {
    vi.useFakeTimers();
    const fail = renderHook(({ live, ok }) => useUpgradeExit(live, ok), { initialProps: { live: true, ok: false } });
    fail.rerender({ live: false, ok: false });
    expect(fail.result.current).toBe("gone");
    const ok = renderHook(({ live, ok }) => useUpgradeExit(live, ok), { initialProps: { live: true, ok: false } });
    ok.rerender({ live: false, ok: true });
    act(() => { vi.advanceTimersByTime(EXIT_HOLD_MS + 10); });
    expect(ok.result.current).toBe("exiting");
    ok.rerender({ live: true, ok: false });
    expect(ok.result.current).toBe("live");
    act(() => { vi.advanceTimersByTime(5000); });
    expect(ok.result.current).toBe("live");
    vi.useRealTimers();
  });
});
