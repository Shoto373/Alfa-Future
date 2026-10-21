import { mockMode, mockRequest } from "./mock";
import type { CompanyProfile, ErrorResponse, Insight, InsightRequest } from "./types";

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export const BROWSER_TIMEOUT_MS = 10_000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly retryable: boolean,
    readonly status?: number,
    readonly requestId?: string,
  ) {
    super(message);
  }
}

/** Ошибка, вызванная отменой запроса пользователем (смена выбора). Не показывается. */
export class AbortedError extends Error {}

function isErrorResponse(value: unknown): value is ErrorResponse {
  const error = (value as ErrorResponse | null)?.error;
  return typeof error?.code === "string" && typeof error?.message === "string";
}

async function request<T>(path: string, init: RequestInit, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, BROWSER_TIMEOUT_MS);
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort);

  try {
    if (mockMode) {
      return (await mockRequest(path, init, controller.signal)) as T;
    }

    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}${path}`, { ...init, signal: controller.signal });
    } catch {
      if (timedOut) {
        throw new ApiError("Сервер не ответил за 10 секунд", "BROWSER_TIMEOUT", true);
      }
      if (signal?.aborted) {
        throw new AbortedError();
      }
      throw new ApiError("Нет связи с сервером. Проверьте, что backend запущен.", "NETWORK_ERROR", true);
    }

    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      if (isErrorResponse(body)) {
        const { code, message, retryable, request_id } = body.error;
        throw new ApiError(message, code, retryable, response.status, request_id);
      }
      throw new ApiError(`Ошибка сервера (HTTP ${response.status})`, "HTTP_ERROR", response.status >= 500, response.status);
    }
    if (body === null) {
      throw new ApiError("Сервер вернул некорректный ответ", "INVALID_RESPONSE", true, response.status);
    }
    return body as T;
  } catch (error) {
    if (signal?.aborted && !timedOut) {
      throw new AbortedError();
    }
    if (timedOut && !(error instanceof ApiError)) {
      throw new ApiError("Сервер не ответил за 10 секунд", "BROWSER_TIMEOUT", true);
    }
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

export async function fetchCompanies(signal?: AbortSignal): Promise<CompanyProfile[]> {
  const body = await request<{ items: CompanyProfile[] }>("/api/v1/companies", { method: "GET" }, signal);
  if (!Array.isArray(body.items)) {
    throw new ApiError("Сервер вернул некорректный список компаний", "INVALID_RESPONSE", true);
  }
  return body.items;
}

export async function createInsight(payload: InsightRequest, signal?: AbortSignal): Promise<Insight> {
  return request<Insight>(
    "/api/v1/insights",
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    signal,
  );
}
