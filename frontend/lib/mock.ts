// Локальный test double API — только для разработки и ручных UI-проверок.
// Включается NEXT_PUBLIC_API_MOCK=ok|empty|error|slow; при приемке переменная не задается.

import type { CompanyProfile, Insight, InsightRequest } from "./types";

type MockMode = "ok" | "empty" | "error" | "slow";

const raw = process.env.NEXT_PUBLIC_API_MOCK;
export const mockMode: MockMode | null =
  raw === "ok" || raw === "empty" || raw === "error" || raw === "slow" ? raw : null;

const MOCK_COMPANY: CompanyProfile = {
  company_id: "mock_company_001",
  display_name: "Демо Mock-компания",
  industry_name: "Тестовая отрасль",
  region: null,
  has_credit: null,
  has_deposit: null,
  is_synthetic: true,
};

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("aborted", "AbortError"));
    });
  });
}

export async function mockRequest(path: string, init: RequestInit, signal: AbortSignal): Promise<unknown> {
  await delay(mockMode === "slow" ? 15_000 : 400, signal);
  if (mockMode === "error") {
    throw new TypeError("mock network error");
  }
  if (path === "/api/v1/companies") {
    return { items: mockMode === "empty" ? [] : [MOCK_COMPANY] };
  }
  const req = JSON.parse(String(init.body)) as InsightRequest;
  const insight: Insight = {
    schema_version: "0.1.0",
    request_id: "mock_request",
    company_id: req.company_id,
    event_id: req.event_id,
    role: req.role,
    status: "completed",
    is_mock: true,
    title: "Mock-карточка локальной разработки",
    facts: [],
    company_relevance: "Mock-ответ без backend.",
    risks: [],
    opportunities: [],
    actions: [],
    bank_position: null,
    model_conclusion: "Mock без вызова backend и LLM.",
    sources: [],
    uncertainty: ["Все признаки компании неизвестны (mock)."],
  };
  return insight;
}
