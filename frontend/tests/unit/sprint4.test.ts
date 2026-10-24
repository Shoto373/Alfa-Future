import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { API_BASE_URL, api } from "@/lib/api";
import { openSource, setTrackCompany, setTrackPath, track, useFlags } from "@/lib/track";

function respond(body: unknown = {}) {
  return vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(body), { status: 200 })));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const texts = { topics: "t", sectors: "s", language: "l" };

describe("api — адреса спринтов 3–4", () => {
  it("каждый метод клиента идет по своему адресу контракта", async () => {
    const fetch = respond();
    vi.stubGlobal("fetch", fetch);
    const pdf = new File(["%PDF"], "обзор.pdf", { type: "application/pdf" });
    const calls: [Promise<unknown>, string, string][] = [
      // Аналитика банка и разметка (SPR3-03, SPR3-06).
      [api.kbDocuments(), "GET", "/api/v1/admin/kb/documents"],
      [api.kbUpload(pdf, { title: "Обзор", date: "2026-10-01" }), "POST",
        "/api/v1/admin/kb/documents?name=%D0%BE%D0%B1%D0%B7%D0%BE%D1%80.pdf&title=%D0%9E%D0%B1%D0%B7%D0%BE%D1%80&date=2026-10-01"],
      [api.kbUploadDemo(), "POST", "/api/v1/admin/kb/demo"],
      [api.kbDocument("d 1"), "GET", "/api/v1/admin/kb/documents/d%201"],
      [api.kbDocumentMeta("d1", { title: "Новое" }), "PATCH", "/api/v1/admin/kb/documents/d1"],
      [api.kbEditDraft("t1", { text: "Тезис" }), "PATCH", "/api/v1/admin/kb/drafts/t1"],
      [api.kbApprove("t1"), "POST", "/api/v1/admin/kb/drafts/t1/approve"],
      [api.kbReject("t1", "дубль"), "POST", "/api/v1/admin/kb/drafts/t1/reject"],
      [api.labelingNext(), "GET", "/api/v1/admin/labeling/next"],
      [api.labelingSave({ news_id: "n", company_id: "A", role: "cfo", grade: 2, reason: "" }), "POST", "/api/v1/admin/labeling/labels"],
      // Доменная конфигурация (SPR4-00).
      [api.config(), "GET", "/api/v1/admin/config"],
      [api.configValidate(texts), "POST", "/api/v1/admin/config/validate"],
      [api.configPreview(texts, "A", "cfo"), "POST", "/api/v1/admin/config/preview"],
      [api.configPreviewResult("p1"), "GET", "/api/v1/admin/config/preview/p1"],
      [api.configPublish(texts, "знак"), "POST", "/api/v1/admin/config/publish"],
      [api.configRollback(3), "POST", "/api/v1/admin/config/versions/3/rollback"],
      // Контрагенты и «что если» (SPR4-01, SPR4-02).
      [api.counterparties("A"), "GET", "/api/v1/companies/A/counterparties"],
      [api.scenario({ company_id: "A", scenario: "fx", shock: 10 }), "POST", "/api/v1/scenarios"],
      // Диалог (SPR4-05).
      [api.dialog("i 1"), "GET", "/api/v1/insights/i%201/questions"],
      [api.rateAnswer("i1", 7, -1), "POST", "/api/v1/insights/i1/questions/7/rating"],
      // Связь с банком (SPR4-06).
      [api.insightOffers("i1"), "GET", "/api/v1/insights/i1/offers"],
      [api.createLead({ insight_id: "i1", offer_id: "factoring", consent: true, comment: null }), "POST", "/api/v1/leads"],
      [api.managerClients(24), "GET", "/api/v1/manager/clients?hours=24"],
      [api.managerLeads(), "GET", "/api/v1/manager/leads"],
      [api.managerLeadStatus(5, "done"), "PATCH", "/api/v1/manager/leads/5"],
      // Уведомления (SPR4-04).
      [api.notificationSettings("A"), "GET", "/api/v1/notifications/settings?company_id=A"],
      [api.saveNotificationSettings("A", { threshold: 90 }), "PUT", "/api/v1/notifications/settings?company_id=A"],
      [api.inbox("A"), "GET", "/api/v1/notifications?company_id=A"],
      [api.inboxRead("A"), "POST", "/api/v1/notifications/read"],
      [api.notificationOpened(9), "POST", "/api/v1/notifications/9/opened"],
      [api.testDigest("A"), "POST", "/api/v1/notifications/test-digest?company_id=A"],
      // Продуктовая аналитика (SPR4-07).
      [api.flags("A"), "GET", "/api/v1/flags?company_id=A"],
      [api.flags(null), "GET", "/api/v1/flags"],
      [api.productReport(28), "GET", "/api/v1/admin/product?days=28"],
      [api.flagSettings(), "GET", "/api/v1/admin/flags"],
      [api.saveFlag("dialog", { percent: 50 }), "PUT", "/api/v1/admin/flags/dialog"],
    ];
    await Promise.all(calls.map(([p]) => p));
    calls.forEach(([, method, path], i) => {
      const [url, init] = fetch.mock.calls[i];
      expect([init.method ?? "GET", url]).toEqual([method, `${API_BASE_URL}${path}`]);
    });
    const body = (path: string) => JSON.parse(fetch.mock.calls.find(([url]) => url === `${API_BASE_URL}${path}`)![1].body);
    expect(body("/api/v1/leads").consent).toBe(true);
    expect(body("/api/v1/notifications/read")).toEqual({ company_id: "A", ids: null });
    expect(body("/api/v1/admin/kb/drafts/t1/approve")).toEqual({ supersedes: null });
    expect(body("/api/v1/admin/config/preview")).toEqual({ ...texts, company_id: "A", role: "cfo" });
  });

  it("адреса файлов: страница и PDF обзора, выгрузка заявок", () => {
    expect(api.kbPageImageUrl("d1", 2)).toBe(`${API_BASE_URL}/api/v1/admin/kb/documents/d1/pages/2/image`);
    expect(api.kbPdfUrl("d1", 4)).toBe(`${API_BASE_URL}/api/v1/admin/kb/documents/d1/pdf#page=4`);
    expect(api.kbPdfUrl("d1")).toBe(`${API_BASE_URL}/api/v1/admin/kb/documents/d1/pdf`);
    expect(api.managerLeadsCsv()).toBe(`${API_BASE_URL}/api/v1/manager/leads.csv`);
  });
});

describe("track — события воронки", () => {
  it("событие уходит на свой сервер с компанией, с cookie и keepalive", () => {
    const fetch = respond();
    vi.stubGlobal("fetch", fetch);
    setTrackCompany("U_1");
    track("feedback", { rating: 1, section: "risks" });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe(`${API_BASE_URL}/api/v1/events`);
    expect([init.method, init.credentials, init.keepalive]).toEqual(["POST", "include", true]);
    expect(JSON.parse(init.body)).toEqual({ kind: "feedback", company_id: "U_1", props: { rating: 1, section: "risks" } });
    setTrackCompany(null);
    track("feed_view");
    expect(JSON.parse(fetch.mock.calls[1][1].body).company_id).toBeNull();
  });

  it("сбой отправки не мешает работе", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    expect(() => track("feed_view")).not.toThrow();
    vi.stubGlobal("fetch", undefined);
    expect(() => track("feed_view")).not.toThrow();
  });

  it("источник открытия разбора: метка ссылки или предыдущая страница приложения", () => {
    expect(openSource("digest")).toBe("digest");
    expect(openSource("alert")).toBe("alert");
    for (const [prev, source] of [["/pulse", "feed"], ["/pulse/n/x", "rail"], ["/pulse/counterparties", "counterparties"],
      ["/", "home"], ["/profile", "direct"]]) {
      setTrackPath(prev);
      setTrackPath("/pulse/n/opened");
      expect(openSource(null)).toBe(source);
      setTrackPath("/reset");
    }
    setTrackPath("/same");
    setTrackPath("/same");  // повторная отрисовка той же страницы не меняет предыдущую
    setTrackPath("/pulse/n/y");
    expect(openSource(null)).toBe("direct");
  });

  it("флаги пользователя загружаются один раз на компанию; ошибка — пустой набор", async () => {
    const fetch = respond({ flags: { dialog: { enabled: true, variant: null } } });
    vi.stubGlobal("fetch", fetch);
    const first = renderHook(() => useFlags("F1"));
    expect(first.result.current).toBeNull();
    await waitFor(() => expect(first.result.current?.dialog.enabled).toBe(true));
    const second = renderHook(() => useFlags("F1"));
    await waitFor(() => expect(second.result.current?.dialog.enabled).toBe(true));
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    const failed = renderHook(() => useFlags("F2"));
    await waitFor(() => expect(failed.result.current).toEqual({}));
    failed.unmount();
  });
});
