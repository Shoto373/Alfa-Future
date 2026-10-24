import { afterEach, describe, expect, it, vi } from "vitest";
import { API_BASE_URL, AbortedError, ApiError, api } from "@/lib/api";

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(new Response(body === undefined ? null : JSON.stringify(body), { status }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("api", () => {
  it("успешный ответ — JSON; запрос с cookie и телом JSON", async () => {
    const fetch = respond(200, { user_id: "u1" });
    vi.stubGlobal("fetch", fetch);
    expect(await api.login("a@b.ru", "x")).toEqual({ user_id: "u1" });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe(`${API_BASE_URL}/api/v1/auth/login`);
    expect(init.credentials).toBe("include");
    expect(JSON.parse(init.body)).toEqual({ email: "a@b.ru", password: "x" });
  });

  it("ошибка контракта — ApiError с кодом, retryable и request_id", async () => {
    vi.stubGlobal("fetch", respond(403, { error: { code: "FORBIDDEN", message: "Недостаточно прав", retryable: false, request_id: "req_1" } }));
    const err = await api.me().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect([err.code, err.retryable, err.status, err.requestId]).toEqual(["FORBIDDEN", false, 403, "req_1"]);
  });

  it("ответ без тела контракта: 5xx — повторяемая ошибка, 4xx — нет", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("oops", { status: 502 })));
    expect(await api.me().catch((e) => [e.code, e.retryable])).toEqual(["HTTP_ERROR", true]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nope", { status: 404 })));
    expect(await api.me().catch((e) => [e.code, e.retryable])).toEqual(["HTTP_ERROR", false]);
  });

  it("нет связи — NETWORK_ERROR, 204 — пустой ответ", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    expect(await api.me().catch((e) => e.code)).toBe("NETWORK_ERROR");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    expect(await api.logout()).toBeUndefined();
  });

  it("отмена потребителем — AbortedError, тайм-аут — BROWSER_TIMEOUT", async () => {
    vi.stubGlobal("fetch", vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })));
    const controller = new AbortController();
    const pending = api.me(controller.signal);
    controller.abort();
    await expect(pending).rejects.toBeInstanceOf(AbortedError);

    vi.useFakeTimers();
    const slow = api.me().catch((e) => e.code);
    await vi.advanceTimersByTimeAsync(16_000);
    expect(await slow).toBe("BROWSER_TIMEOUT");
  });

  it("адреса: PDF с номером страницы, вход через Альфа-ID с возвратом", () => {
    expect(api.pdfUrl("doc-1", 3)).toBe(`${API_BASE_URL}/api/v1/analytics/doc-1/pdf#page=3`);
    expect(api.oidcLoginUrl("/pulse?topic=fx")).toBe(`${API_BASE_URL}/api/v1/auth/oidc/login?next=%2Fpulse%3Ftopic%3Dfx`);
  });

  it("лента — вся лента компании с фильтром темы", async () => {
    const fetch = respond(200, { items: [], topic_counts: [], stories: [] });
    vi.stubGlobal("fetch", fetch);
    await api.feed("U 1", "fx");
    expect(fetch.mock.calls[0][0]).toBe(`${API_BASE_URL}/api/v1/feed?company_id=U%201&limit=500&topic=fx`);
  });
});

describe("api — маршруты и методы", () => {
  it("каждый метод клиента идет по своему адресу контракта", async () => {
    const fetch = respond(200, {});
    vi.stubGlobal("fetch", fetch);
    const file = new File(["x"], "отчет.pdf", { type: "application/pdf" });
    const calls: [Promise<unknown>, string, string][] = [
      [api.authMethods(), "GET", "/api/v1/auth/methods"],
      [api.register("И", "i@b.ru", "x"), "POST", "/api/v1/auth/register"],
      [api.lookupCompanies("ал фа", 20, 40), "GET", "/api/v1/companies/lookup?q=%D0%B0%D0%BB%20%D1%84%D0%B0&limit=20&offset=40"],
      [api.claimCompany("A", "cfo"), "POST", "/api/v1/companies/A/claim"],
      [api.members("A"), "GET", "/api/v1/companies/A/members"],
      [api.inviteMember("A", "e@b.ru", "ceo", false), "POST", "/api/v1/companies/A/members"],
      [api.updateMember("A", "m1", { is_admin: true }), "PATCH", "/api/v1/companies/A/members/m1"],
      [api.removeMember("A", "m1"), "DELETE", "/api/v1/companies/A/members/m1"],
      [api.disbandCompany("A"), "DELETE", "/api/v1/companies/A"],
      [api.meta(), "GET", "/api/v1/meta"],
      [api.company("A"), "GET", "/api/v1/companies/A"],
      [api.aiSettings("A"), "GET", "/api/v1/companies/A/ai-settings"],
      [api.saveAISettings("A", { enabled: true, threshold: 85 }), "PUT", "/api/v1/companies/A/ai-settings"],
      [api.companyExtra("A"), "GET", "/api/v1/companies/A/extra"],
      [api.saveCompanyExtra("A", { shares: {}, notes: "" }), "PUT", "/api/v1/companies/A/extra"],
      [api.uploadCompanyFile("A", file), "POST", "/api/v1/companies/A/extra/files?name=%D0%BE%D1%82%D1%87%D0%B5%D1%82.pdf"],
      [api.deleteCompanyFile("A", "f1"), "DELETE", "/api/v1/companies/A/extra/files/f1"],
      [api.feed("A", undefined, "s1"), "GET", "/api/v1/feed?company_id=A&limit=500&story=s1"],
      [api.insight("A", "n1", { fast: true, perspective: "ceo" }), "POST", "/api/v1/insights"],
      [api.ask("i1", "Что делать?"), "POST", "/api/v1/insights/i1/questions"],
      [api.feedback("i1", 1, "actions"), "POST", "/api/v1/feedback"],
      [api.addNews({ url: "https://e.ru/n" }), "POST", "/api/v1/news"],
      [api.analytics(), "GET", "/api/v1/analytics"],
      [api.metrics(), "GET", "/api/v1/metrics"],
      [api.audit(), "GET", "/api/v1/audit?limit=60"],
      [api.llmSwitch(), "GET", "/api/v1/ops/llm"],
      [api.setLLMPaused(true), "POST", "/api/v1/ops/llm"],
      [api.qualityOverview(24), "GET", "/api/v1/metrics/overview?hours=24"],
    ];
    await Promise.all(calls.map(([p]) => p));
    calls.forEach(([, method, path], i) => {
      const [url, init] = fetch.mock.calls[i];
      expect([init.method ?? "GET", url]).toEqual([method, `${API_BASE_URL}${path}`]);
    });
    const insightBody = JSON.parse(fetch.mock.calls[18][1].body);
    expect(insightBody).toEqual({ company_id: "A", news_id: "n1", force_refresh: false, fast: true, perspective: "ceo" });
    expect(api.pdfUrl("d1")).toBe(`${API_BASE_URL}/api/v1/analytics/d1/pdf`);
  });
});
