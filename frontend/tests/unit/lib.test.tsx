import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { ApiError, api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { date, money, pct } from "@/lib/format";
import { feedKey, loadFeed, useCompany, useFeed, useLoad } from "@/lib/hooks";
import { markRead, useRead } from "@/lib/notifications";
import { invalidate } from "@/lib/query";
import { SessionProvider, shortName, useSession } from "@/lib/session";
import type { User } from "@/lib/types";

const user: User = {
  user_id: "u1", name: "Анна Морозова", email: "a@b.ru", is_operator: false, is_manager: false,
  memberships: [
    { company_id: "A", company_name: "Альфа", role: "cfo", is_admin: true, is_founder: true },
    { company_id: "B", company_name: "Бета", role: "ceo", is_admin: false, is_founder: false },
  ],
};

afterEach(() => {
  vi.restoreAllMocks();
  invalidate();
  localStorage.clear();
});

describe("errors и format", () => {
  it("понятный текст по коду ошибки, иначе сообщение сервера или запасной текст", () => {
    expect(errorText(new ApiError("x", "TOO_MANY_REQUESTS", false))).toMatch(/Подождите минуту/);
    expect(errorText(new ApiError("Сообщение сервера", "SOMETHING", false))).toBe("Сообщение сервера");
    expect(errorText(new Error("js"), "Запасной")).toBe("Запасной");
  });

  it("деньги, проценты и даты по-русски", () => {
    expect(money(2.5e9)).toBe("2,5 млрд ₽");
    expect(money(3.2e6)).toBe("3,2 млн ₽");
    expect(money(null)).toBe("нет данных");
    expect(pct(0.256, 1)).toBe("25,6%");
    expect(pct(null)).toBe("—");
    expect(date("2026-10-24T09:00:00Z")).toMatch(/24 октября 2026/);
    expect(date("2026-10")).toMatch(/октябрь 2026/);
    expect(date("не дата")).toBe("не дата");
    expect(date(null)).toBe("");
  });
});

describe("notifications", () => {
  it("прочитанные — по пользователю и компании, синхронизируются между компонентами", async () => {
    const hook = renderHook(() => useRead("u1", "A"));
    expect(hook.result.current.read.size).toBe(0);
    act(() => hook.result.current.mark(["n1"]));
    await waitFor(() => expect(hook.result.current.read.has("n1")).toBe(true));
    markRead("u1", "B", ["n2"]);
    expect(hook.result.current.read.has("n2")).toBe(false);
    localStorage.setItem("alfa-pulse-read:u1:A", "не json");
    act(() => { window.dispatchEvent(new Event("storage")); });
    await waitFor(() => expect(hook.result.current.read.size).toBe(0));
  });
});

describe("hooks", () => {
  it("лента — один запрос на страницу и уведомления; при смене компании старые данные не видны", async () => {
    const feed = vi.spyOn(api, "feed").mockImplementation(async (companyId) => ({
      items: [{ news: { news_id: companyId } }], topic_counts: [], stories: [] }) as never);
    const hook = renderHook(({ cid }) => useFeed(cid), { initialProps: { cid: "A" } });
    await waitFor(() => expect(hook.result.current.data).toHaveLength(1));
    await loadFeed("A");
    expect(feed).toHaveBeenCalledTimes(1);
    hook.rerender({ cid: "B" });
    expect(hook.result.current.data).toBeNull();
    await waitFor(() => expect((hook.result.current.data as never as { news: { news_id: string } }[])[0].news.news_id).toBe("B"));
    expect(feedKey("A", "fx")).toBe("feed:A:fx:");
  });

  it("профиль компании кэшируется, useLoad перезагружается по reload", async () => {
    const company = vi.spyOn(api, "company").mockResolvedValue({ profile: {}, exposures: [] } as never);
    const a = renderHook(() => useCompany("A"));
    await waitFor(() => expect(a.result.current.data).not.toBeNull());
    renderHook(() => useCompany("A"));
    expect(company).toHaveBeenCalledTimes(1);

    const fn = vi.fn().mockRejectedValueOnce(new Error("js")).mockResolvedValueOnce("ok");
    const load = renderHook(() => useLoad(fn, ["x"]));
    await waitFor(() => expect(load.result.current.error?.code).toBe("CLIENT"));
    act(() => load.result.current.reload());
    await waitFor(() => expect(load.result.current.data).toBe("ok"));
  });
});

function Probe() {
  const { session, ready, setActiveCompany, logout } = useSession();
  return (
    <div>
      <span data-testid="state">{ready ? (session ? `${session.companyId}:${session.role}` : "anon") : "loading"}</span>
      <button onClick={() => setActiveCompany("B")}>B</button>
      <button onClick={() => void logout()}>out</button>
    </div>
  );
}

describe("session", () => {
  it("активная компания запоминается, выход сбрасывает пользователя и кэш", async () => {
    vi.spyOn(api, "me").mockResolvedValue(user);
    vi.spyOn(api, "logout").mockResolvedValue(undefined);
    render(<SessionProvider><Probe /></SessionProvider>);
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("A:cfo"));
    act(() => screen.getByText("B").click());
    expect(screen.getByTestId("state").textContent).toBe("B:ceo");
    expect(localStorage.getItem("alfa-pulse-active-company")).toBe("B");
    await act(async () => screen.getByText("out").click());
    expect(screen.getByTestId("state").textContent).toBe("anon");
  });

  it("без входа — аноним; useSession вне провайдера — ошибка; короткое имя", async () => {
    vi.spyOn(api, "me").mockRejectedValue(new ApiError("нет", "UNAUTHORIZED", false, 401));
    render(<SessionProvider><Probe /></SessionProvider>);
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("anon"));
    expect(() => renderHook(() => useSession())).toThrow(/SessionProvider/);
    expect(shortName("Анна Морозова")).toBe("Морозова А.");
    expect(shortName("Анна")).toBe("Анна");
  });

  it("вход и регистрация сохраняют пользователя", async () => {
    vi.spyOn(api, "me").mockRejectedValue(new ApiError("нет", "UNAUTHORIZED", false, 401));
    vi.spyOn(api, "login").mockResolvedValue(user);
    vi.spyOn(api, "register").mockResolvedValue({ ...user, memberships: [] });
    const hook = renderHook(() => useSession(), { wrapper: SessionProvider });
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    await act(async () => { await hook.result.current.login("a@b.ru", "x"); });
    expect(hook.result.current.session?.companyId).toBe("A");
    await act(async () => { await hook.result.current.register("Иван", "i@b.ru", "x"); });
    expect(hook.result.current.session?.companyId).toBe("");
    vi.spyOn(api, "me").mockResolvedValueOnce(user);
    await act(async () => { await hook.result.current.refresh(); });
    expect(hook.result.current.session?.companyId).toBe("A");
  });
});
