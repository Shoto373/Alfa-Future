import type {
  Answer, BankDocument, CompanyProfile, CompanySummary, Exposure, FeedItem, Insight, LookupCompany, Member, Membership, Meta, NewsBrief, Role, TopicCount, User,
} from "./types";

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message: string, readonly code: string, readonly retryable: boolean, readonly status?: number, readonly requestId?: string) {
    super(message);
  }
}

/** Отмена запроса (смена компании, роли или уход со страницы) — не показывается пользователю. */
export class AbortedError extends Error {}

async function request<T>(path: string, init: RequestInit = {}, opts: { signal?: AbortSignal; timeoutMs?: number } = {}): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, opts.timeoutMs ?? 15_000);
  const onAbort = () => controller.abort();
  opts.signal?.addEventListener("abort", onAbort);
  try {
    let res: Response;
    try {
      res = await fetch(`${API_BASE_URL}${path}`, { ...init, credentials: "include", signal: controller.signal });
    } catch {
      if (timedOut) throw new ApiError("Сервер не ответил вовремя", "BROWSER_TIMEOUT", true);
      if (opts.signal?.aborted) throw new AbortedError();
      throw new ApiError("Нет связи с сервером. Проверьте подключение и повторите.", "NETWORK_ERROR", true);
    }
    if (res.status === 204) return undefined as T;
    const body: unknown = await res.json().catch(() => null);
    if (!res.ok) {
      const err = (body as { error?: { code: string; message: string; retryable: boolean; request_id: string } } | null)?.error;
      if (err) throw new ApiError(err.message, err.code, err.retryable, res.status, err.request_id);
      throw new ApiError(`Ошибка сервера (HTTP ${res.status})`, "HTTP_ERROR", res.status >= 500, res.status);
    }
    return body as T;
  } catch (e) {
    if (opts.signal?.aborted && !timedOut) throw new AbortedError();
    throw e;
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onAbort);
  }
}

const json = (method: string, data: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

const cid = encodeURIComponent;

export const api = {
  me: (signal?: AbortSignal) => request<User>("/api/v1/auth/me", {}, { signal }),
  login: (email: string, password: string) => request<User>("/api/v1/auth/login", json("POST", { email, password })),
  register: (name: string, email: string, password: string) =>
    request<User>("/api/v1/auth/register", json("POST", { name, email, password })),
  logout: () => request<void>("/api/v1/auth/logout", { method: "POST" }),
  lookupCompanies: (q: string, limit: number, offset: number, signal?: AbortSignal) =>
    request<{ total: number; items: LookupCompany[] }>(
      `/api/v1/companies/lookup?q=${cid(q)}&limit=${limit}&offset=${offset}`, {}, { signal }),
  claimCompany: (companyId: string, role: Role) =>
    request<Membership>(`/api/v1/companies/${cid(companyId)}/claim`, json("POST", { role })),
  members: (companyId: string, signal?: AbortSignal) =>
    request<{ members: Member[] }>(`/api/v1/companies/${cid(companyId)}/members`, {}, { signal }),
  inviteMember: (companyId: string, email: string, role: Role, isAdmin: boolean) =>
    request<Member>(`/api/v1/companies/${cid(companyId)}/members`, json("POST", { email, role, is_admin: isAdmin })),
  updateMember: (companyId: string, memberId: string, patch: { role?: Role; is_admin?: boolean }) =>
    request<Member>(`/api/v1/companies/${cid(companyId)}/members/${cid(memberId)}`, json("PATCH", patch)),
  removeMember: (companyId: string, memberId: string) =>
    request<void>(`/api/v1/companies/${cid(companyId)}/members/${cid(memberId)}`, { method: "DELETE" }),
  disbandCompany: (companyId: string) =>
    request<void>(`/api/v1/companies/${cid(companyId)}`, { method: "DELETE" }),
  meta: (signal?: AbortSignal) => request<Meta>("/api/v1/meta", {}, { signal }),
  company: (id: string, signal?: AbortSignal) =>
    request<{ profile: CompanyProfile; exposures: Exposure[] }>(`/api/v1/companies/${encodeURIComponent(id)}`, {}, { signal }),
  feed: (companyId: string, topic?: string, signal?: AbortSignal) =>
    request<{ items: FeedItem[]; topic_counts: TopicCount[] }>(
      `/api/v1/feed?company_id=${encodeURIComponent(companyId)}${topic ? `&topic=${encodeURIComponent(topic)}` : ""}`, {}, { signal }),
  // fast: готовая карточка или разбор на правилах без LLM за доли секунды; без fast — версия модели.
  insight: (companyId: string, newsId: string, opts: { force?: boolean; fast?: boolean } = {}, signal?: AbortSignal) =>
    request<Insight>("/api/v1/insights", json("POST", {
      company_id: companyId, news_id: newsId, force_refresh: !!opts.force, fast: !!opts.fast,
    }), { signal, timeoutMs: opts.fast ? 30_000 : 180_000 }),
  ask: (insightId: string, question: string) =>
    request<Answer>(`/api/v1/insights/${insightId}/questions`, json("POST", { question }), { timeoutMs: 90_000 }),
  feedback: (insightId: string, rating: 1 | -1, section: string, comment?: string) =>
    request<{ status: string }>("/api/v1/feedback", json("POST", { insight_id: insightId, rating, section, comment: comment || null })),
  addNews: (payload: { title?: string; text?: string; url?: string }) =>
    request<{ created: boolean; duplicate_of: string | null; news: NewsBrief }>("/api/v1/news", json("POST", payload), { timeoutMs: 30_000 }),
  refreshNews: () =>
    request<{ added: number; duplicates: number; sources: { name: string; fetched: number; error: string | null }[] }>(
      "/api/v1/news/refresh", { method: "POST" }, { timeoutMs: 90_000 }),
  analytics: () => request<{ documents: BankDocument[] }>("/api/v1/analytics"),
  metrics: () => request<Record<string, any>>("/api/v1/metrics"),
  audit: () => request<{ items: Record<string, any>[] }>("/api/v1/audit?limit=60"),
  pdfUrl: (docId: string, page?: number | null) => `${API_BASE_URL}/api/v1/analytics/${docId}/pdf${page ? `#page=${page}` : ""}`,
};
