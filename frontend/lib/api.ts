import type {
  AISettings, Answer, BankDocument, CompanyExtra, CompanyProfile, Exposure, FeedPage, Insight, LLMBudget, LLMSwitch, ConfigPreview, ConfigState, ConfigTexts, ConfigIssue, BankOffer, CounterpartiesView, DialogTurn, FlagSetting, ProductReport, Lead, ManagerClient, Inbox, NotificationSettings, ScenarioKind, ScenarioResponse, KbDocument, KbDraft, KbUploadItem, LabelingState, LookupCompany, Member, Membership, Mention, Meta, NewsBrief, QualityOverview, Role, User, } from "./types";

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
export const FEED_LIMIT = 500;


export const api = {
  me: (signal?: AbortSignal) => request<User>("/api/v1/auth/me", {}, { signal }),
  // Способы входа: по паролю (демо) и через корпоративный IdP (Альфа-ID, OIDC).
  authMethods: () => request<{ password: boolean; oidc: boolean }>("/api/v1/auth/methods"),
  oidcLoginUrl: (next = "/") => `${API_BASE_URL}/api/v1/auth/oidc/login?next=${encodeURIComponent(next)}`,
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
  aiSettings: (id: string, signal?: AbortSignal) =>
    request<AISettings>(`/api/v1/companies/${cid(id)}/ai-settings`, {}, { signal }),
  saveAISettings: (id: string, data: { enabled: boolean; threshold: number }) =>
    request<AISettings>(`/api/v1/companies/${cid(id)}/ai-settings`, json("PUT", data)),
  companyExtra: (id: string, signal?: AbortSignal) =>
    request<CompanyExtra>(`/api/v1/companies/${cid(id)}/extra`, {}, { signal }),
  saveCompanyExtra: (id: string, data: { shares: CompanyExtra["shares"]; notes: string }) =>
    request<CompanyExtra>(`/api/v1/companies/${cid(id)}/extra`, json("PUT", data)),
  // Файл — телом запроса (без multipart): сервер сам извлекает из него текст.
  uploadCompanyFile: (id: string, file: File) =>
    request<CompanyExtra>(`/api/v1/companies/${cid(id)}/extra/files?name=${encodeURIComponent(file.name)}`,
      { method: "POST", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file }, { timeoutMs: 120_000 }),
  deleteCompanyFile: (id: string, fileId: string) =>
    request<CompanyExtra>(`/api/v1/companies/${cid(id)}/extra/files/${cid(fileId)}`, { method: "DELETE" }),
  // Всегда вся лента компании (FEED_LIMIT): главная, лента и уведомления считают по одному списку.
  // Общий ответ и кэш — lib/hooks.loadFeed (lib/query): один запрос на все части экрана.
  feed: (companyId: string, topic?: string, story?: string) =>
    request<FeedPage>(`/api/v1/feed?company_id=${encodeURIComponent(companyId)}&limit=${FEED_LIMIT}` +
      `${topic ? `&topic=${encodeURIComponent(topic)}` : ""}${story ? `&story=${encodeURIComponent(story)}` : ""}`),
  // fast: готовая карточка или разбор на правилах без LLM за доли секунды; без fast — версия модели.
  // perspective — другой разрез: тот же разбор глазами другой роли (по умолчанию — своя роль).
  // Новость с организациями в тексте и их отношением к компании (SPR3-02).
  newsMentions: (newsId: string, companyId: string, signal?: AbortSignal) =>
    request<{ entities: Omit<Mention, "relation">[]; mentions: Mention[]; mentions_company: boolean }>(
      `/api/v1/news/${cid(newsId)}?company_id=${cid(companyId)}`, {}, { signal }),
  insight: (companyId: string, newsId: string, opts: { force?: boolean; fast?: boolean; perspective?: Role } = {}, signal?: AbortSignal) =>
    request<Insight>("/api/v1/insights", json("POST", {
      company_id: companyId, news_id: newsId, force_refresh: !!opts.force, fast: !!opts.fast,
      ...(opts.perspective ? { perspective: opts.perspective } : {}),
    }), { signal, timeoutMs: opts.fast ? 30_000 : 180_000 }),
  // Потоковый разбор (SSE, SPR4-03): проверенный разбор правил сразу, затем ход модели и итог. Возвращает «закрыть поток».
  insightStream: (companyId: string, newsId: string, perspective: Role | undefined, on: {
    insight: (ins: Insight) => void; stage: (stage: string) => void; done: (ins: Insight) => void; failed: () => void;
  }) => {
    const q = new URLSearchParams({ company_id: companyId, news_id: newsId, ...(perspective ? { perspective } : {}) });
    const source = new EventSource(`${API_BASE_URL}/api/v1/insights/stream?${q}`, { withCredentials: true });
    let finished = false;
    const parse = (e: Event) => JSON.parse((e as MessageEvent).data);
    source.addEventListener("insight", (e) => on.insight(parse(e)));
    source.addEventListener("stage", (e) => on.stage(parse(e).stage));
    source.addEventListener("done", (e) => { finished = true; source.close(); on.done(parse(e)); });
    // Обрыв до итога (прокси без SSE, сеть): закрываем — интерфейс перейдет на обычный запрос.
    source.onerror = () => { if (!finished) { source.close(); on.failed(); } };
    return () => { finished = true; source.close(); };
  },
  ask: (insightId: string, question: string) =>
    request<Answer>(`/api/v1/insights/${insightId}/questions`, json("POST", { question }), { timeoutMs: 90_000 }),
  // Диалог по разбору (SPR4-05): история реплик пользователя и оценка ответа.
  dialog: (insightId: string) => request<DialogTurn[]>(`/api/v1/insights/${cid(insightId)}/questions`),
  rateAnswer: (insightId: string, turnId: number, rating: 1 | -1) =>
    request<{ ok: boolean }>(`/api/v1/insights/${cid(insightId)}/questions/${turnId}/rating`, json("POST", { rating })),
  feedback: (insightId: string, rating: 1 | -1, section: string, comment?: string) =>
    request<{ status: string }>("/api/v1/feedback", json("POST", { insight_id: insightId, rating, section, comment: comment || null })),
  addNews: (payload: { title?: string; text?: string; url?: string }) =>
    request<{ created: boolean; duplicate_of: string | null; news: NewsBrief }>("/api/v1/news", json("POST", payload), { timeoutMs: 30_000 }),
  analytics: () => request<{ documents: BankDocument[] }>("/api/v1/analytics"),
  // Сводка для сотрудника банка; интерфейсу нужен только расход бюджета, остальное — для API-клиентов.
  metrics: () => request<{ ai?: { llm_usage?: LLMBudget } } & Record<string, unknown>>("/api/v1/metrics"),
  audit: () => request<{ items: Record<string, unknown>[] }>("/api/v1/audit?limit=60"),
  // Сотрудник банка: выключатель AI без удаления ключа с сервера.
  llmSwitch: () => request<LLMSwitch>("/api/v1/ops/llm"),
  setLLMPaused: (paused: boolean) => request<LLMSwitch>("/api/v1/ops/llm", json("POST", { paused })),
  qualityOverview: (hours: number, signal?: AbortSignal) =>
    request<QualityOverview>(`/api/v1/metrics/overview?hours=${hours}`, {}, { signal }),
  // Экран аналитика банка (SPR3-03): PDF на распознавание, черновики тезисов, публикация.
  kbDocuments: (signal?: AbortSignal) => request<{ items: KbUploadItem[] }>("/api/v1/admin/kb/documents", {}, { signal }),
  kbUpload: (file: File, meta: { title?: string; date?: string }) => {
    const q = new URLSearchParams({ name: file.name, ...(meta.title ? { title: meta.title } : {}), ...(meta.date ? { date: meta.date } : {}) });
    return request<{ doc_id: string; status: string; created: boolean }>(`/api/v1/admin/kb/documents?${q}`,
      { method: "POST", headers: { "Content-Type": "application/pdf" }, body: file }, { timeoutMs: 120_000 });
  },
  kbUploadDemo: () => request<{ doc_id: string; status: string; created: boolean }>("/api/v1/admin/kb/demo", { method: "POST" }),
  kbDocument: (docId: string, signal?: AbortSignal) => request<KbDocument>(`/api/v1/admin/kb/documents/${cid(docId)}`, {}, { signal }),
  kbDocumentMeta: (docId: string, meta: { title?: string; date?: string }) =>
    request<KbDocument>(`/api/v1/admin/kb/documents/${cid(docId)}`, json("PATCH", meta)),
  kbPageImageUrl: (docId: string, page: number) => `${API_BASE_URL}/api/v1/admin/kb/documents/${cid(docId)}/pages/${page}/image`,
  kbPdfUrl: (docId: string, page?: number) => `${API_BASE_URL}/api/v1/admin/kb/documents/${cid(docId)}/pdf${page ? `#page=${page}` : ""}`,
  kbEditDraft: (draftId: string, patch: Partial<KbDraft>) => request<KbDraft>(`/api/v1/admin/kb/drafts/${cid(draftId)}`, json("PATCH", patch)),
  kbApprove: (draftId: string, supersedes?: string | null) =>
    request<{ thesis: { id: string } }>(`/api/v1/admin/kb/drafts/${cid(draftId)}/approve`, json("POST", { supersedes: supersedes ?? null })),
  kbReject: (draftId: string, reason: string) => request<KbDraft>(`/api/v1/admin/kb/drafts/${cid(draftId)}/reject`, json("POST", { reason })),
  labelingNext: (signal?: AbortSignal) => request<LabelingState>("/api/v1/admin/labeling/next", {}, { signal }),
  labelingSave: (label: { news_id: string; company_id: string; role: Role; grade: number; reason: string }) =>
    request<LabelingState>("/api/v1/admin/labeling/labels", json("POST", label)),
  // Доменная конфигурация (SPR4-00): проверка, превью ленты, публикация и откат версии.
  config: (signal?: AbortSignal) => request<ConfigState>("/api/v1/admin/config", {}, { signal }),
  configValidate: (texts: ConfigTexts) =>
    request<{ ok: boolean; issues: ConfigIssue[] }>("/api/v1/admin/config/validate", json("POST", texts)),
  configPreview: (texts: ConfigTexts, companyId: string, role: Role) =>
    request<{ id: string }>("/api/v1/admin/config/preview", json("POST", { ...texts, company_id: companyId, role })),
  configPreviewResult: (id: string) => request<ConfigPreview>(`/api/v1/admin/config/preview/${cid(id)}`),
  configPublish: (texts: ConfigTexts, note: string) =>
    request<{ id: number; warnings: ConfigIssue[] }>("/api/v1/admin/config/publish", json("POST", { ...texts, note })),
  configRollback: (id: number) => request<{ id: number }>(`/api/v1/admin/config/versions/${id}/rollback`, { method: "POST" }),
  counterparties: (companyId: string, signal?: AbortSignal) =>
    request<CounterpartiesView>(`/api/v1/companies/${cid(companyId)}/counterparties`, {}, { signal }),
  scenario: (body: { company_id: string; scenario: ScenarioKind; shock: number; debt?: number; floating_share?: number;
    fx_revenue_share?: number; import_share?: number; exposure?: number }) =>
    request<ScenarioResponse>("/api/v1/scenarios", json("POST", body)),
  // Продуктовая аналитика (SPR4-07): флаги пользователя, отчет пилота и настройка флагов (оператор).
  flags: (companyId: string | null) =>
    request<{ flags: Record<string, { enabled: boolean; variant: string | null }> }>(`/api/v1/flags${companyId ? `?company_id=${cid(companyId)}` : ""}`),
  productReport: (days: number, signal?: AbortSignal) => request<ProductReport>(`/api/v1/admin/product?days=${days}`, {}, { signal }),
  flagSettings: (signal?: AbortSignal) => request<{ flags: Record<string, FlagSetting> }>("/api/v1/admin/flags", {}, { signal }),
  saveFlag: (key: string, body: { percent?: number; companies?: string[] }) =>
    request<FlagSetting>(`/api/v1/admin/flags/${cid(key)}`, json("PUT", body)),
  // Связь с банком (SPR4-06): предложения по потребности, заявка с согласия, кабинет менеджера.
  insightOffers: (insightId: string, signal?: AbortSignal) =>
    request<{ offers: BankOffer[]; leads: Lead[]; consent_text: string }>(`/api/v1/insights/${cid(insightId)}/offers`, {}, { signal }),
  createLead: (body: { insight_id: string; offer_id: string; consent: true; comment: string | null }) =>
    request<Lead & { created: boolean; managers: number }>("/api/v1/leads", json("POST", body)),
  managerClients: (hours: number, signal?: AbortSignal) =>
    request<{ hours: number; priority_formula: string; clients: ManagerClient[] }>(`/api/v1/manager/clients?hours=${hours}`, {}, { signal }),
  managerLeads: (signal?: AbortSignal) => request<{ items: Lead[] }>("/api/v1/manager/leads", {}, { signal }),
  managerLeadStatus: (id: number, status: Lead["status"]) => request<Lead>(`/api/v1/manager/leads/${id}`, json("PATCH", { status })),
  managerLeadsCsv: () => `${API_BASE_URL}/api/v1/manager/leads.csv`,
  // Сводки и алерты (SPR4-04).
  notificationSettings: (companyId: string, signal?: AbortSignal) =>
    request<NotificationSettings>(`/api/v1/notifications/settings?company_id=${cid(companyId)}`, {}, { signal }),
  saveNotificationSettings: (companyId: string, changes: Partial<Omit<NotificationSettings, "company_id">>) =>
    request<NotificationSettings>(`/api/v1/notifications/settings?company_id=${cid(companyId)}`, json("PUT", changes)),
  inbox: (companyId: string, signal?: AbortSignal) =>
    request<Inbox>(`/api/v1/notifications?company_id=${cid(companyId)}`, {}, { signal }),
  inboxRead: (companyId: string, ids?: number[]) =>
    request<{ updated: number }>("/api/v1/notifications/read", json("POST", { company_id: companyId, ids: ids ?? null })),
  notificationOpened: (id: number) => request<{ ok: boolean }>(`/api/v1/notifications/${id}/opened`, { method: "POST" }),
  testDigest: (companyId: string) =>
    request<{ created: number; channels: string[] }>(`/api/v1/notifications/test-digest?company_id=${cid(companyId)}`, { method: "POST" }),
  pdfUrl: (docId: string, page?: number | null) => `${API_BASE_URL}/api/v1/analytics/${docId}/pdf${page ? `#page=${page}` : ""}`,
};
