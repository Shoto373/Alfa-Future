// Типы публичного контракта 1.0.0: схемы с сервера генерируются в api-types.ts (npm run gen:api
// из contracts/openapi.json) — здесь только имена для кода. Ниже — типы адресов, у которых на сервере
// пока нет схемы ответа (лента, профиль компании, аналитика), их описание ручное.
import type { components } from "./api-types";

type Schemas = components["schemas"];
export type Membership = Schemas["Membership"];
export type User = Schemas["User"];
export type Member = Schemas["Member"];
export type Role = Membership["role"];
export type Claim = Schemas["Claim"];
export type Origin = Claim["origin"];
export type Source = Schemas["Source"];
export type RelevanceReason = Schemas["RelevanceReason"];
export type Relevance = Schemas["Relevance"];
export type TraceStep = Schemas["TraceStep"];
export type Insight = Schemas["Insight"];
export type Effect = NonNullable<Insight["effect"]>;
export type Answer = Schemas["Answer"];

export interface LLMSwitch {
  paused: boolean;
  connected: boolean;
  by?: string;
  at?: string;
}

export interface LookupCompany {
  company_id: string;
  display_name: string;
  sector_name: string;
  region: string | null;
  claimed: boolean;
}

/** Ответ /feed: total и topic_counts — по всей ленте компании, items — с учетом фильтра. */
export interface FeedPage {
  items: FeedItem[];
  total: number;
  topic_counts: TopicCount[];
  stories: StoryChip[];
}

/** Мониторинг качества: показатели за период, накопленные метрики и выводы. */
export interface QualityOverview {
  period: {
    hours: number;
    insights: number;
    llm_attempted: number;
    llm_share: number | null;
    first_pass: number | null;
    grounded: number | null;
    bank_coverage: number | null;
    latency_p50: number | null;
    latency_p90: number | null;
    feedback: { up: number; down: number; useful_rate: number | null };
    feed_views: number;
    insight_opens: number;
    questions: number;
    pipeline: {
      started_at?: string | null;
      rss?: { added: number; duplicates: number; skipped: number; failed: string[] } | null;
      rules_built?: number | null;
      llm_built?: number | null;
    } | null;
  };
  totals: {
    content: { insights: number; first_pass_rate: number; claims_with_sources: number; checks_pass_rate: Record<string, number> };
    personalization: { by_section: Record<string, { up: number; down: number }> };
    ai: { llm_connected: boolean; llm_usage?: { tokens: number; limit: number | null; cost: number; cost_limit: number } };
  };
  findings: { level: "ok" | "warn" | "info"; text: string }[];
  check_labels: Record<string, string>;
}

export type ExtraShareKey = "floating_debt_share" | "fx_revenue_share" | "import_share";

/** Сведения, которые компания сообщила о себе: доли в процентах и свободный текст. */
/** Готовить AI-разборы важных новостей заранее: включено и с какой оценки важности. */
export interface AISettings {
  company_id: string;
  enabled: boolean;
  threshold: number;
  updated_at: string | null;
}

export interface CompanyExtra {
  company_id: string;
  shares: Partial<Record<ExtraShareKey, number>>;
  notes: string;
  updated_at: string | null;
  fields: { key: ExtraShareKey; label: string }[];
  files: CompanyFile[];
}

/** Приложенный файл: текст из него — часть сведений компании для агента. */
export interface CompanyFile {
  file_id: string;
  name: string;
  kind: "csv" | "pdf";
  size: number;
  chars: number;
  uploaded_at: string;
  preview: string;
}

export interface CompanySummary {
  company_id: string;
  display_name: string;
  sector: string;
  sector_name: string;
  okved_code: string | null;
  okved_name: string | null;
  region: string | null;
  revenue: number | null;
  client_type: string | null;
  fts_countries: string[];
}

export interface Counterparties {
  total_amount: number;
  counterparties: number;
  top1_share: number | null;
  intra_group_share: number | null;
  by_sector: { sector: string; share: number }[];
}

export interface CompanyProfile extends CompanySummary {
  ownership: string | null;
  age_years: string | null;
  stage: string | null;
  workers_fns: string | null;
  products: Record<string, boolean | null>;
  fts_flag: boolean | null;
  market: { okved_peers: number | null; okved_rank: number | null; okved_share: number | null; sector_share: number | null; note: string };
  group: { group_id: string | null; members: number | null; revenue: number | null; reliable: boolean | null; top_sectors?: string[];
    sector_shares?: { sector: string; share: number }[]; focus_sectors?: string[]; usable?: boolean };
  suppliers: Counterparties;
  customers: Counterparties;
  linked_persons: number;
  affiliated_companies: number;
  data_quality: string[];
}

export interface Exposure {
  topic: string;
  weight: number;
  sign: number;
  feature: string;
  why: string;
  origin: string;
}

export interface NewsBrief {
  news_id: string;
  title: string;
  lead: string;
  source: string;
  url: string | null;
  kind: "seed" | "rss" | "user" | "external";
  published_at: string;
  topics: { topic: string; name: string }[];
  sectors: string[];
  countries: string[];
  direction: string | null;
  duplicates: number;
  /** Организации в новости и их отношение к компании (лента); есть ли среди них она сама или ее контрагент. */
  mentions?: Mention[];
  mentions_company?: boolean;
}

/** Организация в тексте новости: своя компания, поставщик, покупатель или сторонняя (SPR3-02). */
export interface Mention {
  name: string;
  company_id: string | null;
  method: "dictionary" | "legal_form" | "inn" | "ogrn";
  relation: "self" | "supplier" | "customer" | "other";
}

export interface TopicCount {
  topic: string;
  name: string;
  count: number;
}

// Динамическая тема: сюжет из нескольких сообщений разных СМИ (название дает модель).
export interface StoryChip {
  story_id: string;
  label: string;
  size: number;
}

// Общий знак события для компании: скорее риск, скорее возможность, и то и другое, зависит от операций, нет влияния.
export interface FeedItem {
  news: NewsBrief;
  relevance: Relevance;
  cached_insight_id: string | null;
  cached_effect?: Effect | null;
}

export interface Meta {
  data: { profiles: number; total_companies: number; selection_rule: string; source_dir: string };
  knowledge: { documents: number; theses: number };
  news: number;
  llm: { connected: boolean; allowed_models: string[] };
  roles: { role: Role; name: string }[];
  topics: { topic: string; name: string }[];
  sectors: { sector: string; name: string }[];
}

export interface BankDocument {
  doc_id: string;
  title: string;
  date: string;
  author: string;
  stale?: boolean;
  pdf_available: boolean;
  theses: { id: string; page: number; text: string; topics: string[]; stance?: string; stale?: boolean }[];
}

/** Расход дневного бюджета LLM (/metrics → ai.llm_usage), для блока «Сервис банка». */
export interface LLMBudget {
  cost: number;
  cost_limit: number;
  reserved_cost: number;
  rejected_by_budget: number;
}

// Проверка аналитиком тезисов из распознанных PDF (SPR3-03).
export interface KbCheck {
  name: "numbers" | "quote" | "document_date" | "topic" | "duplicate";
  ok: boolean;
  detail: string;
  missing?: string[];
  duplicate_of?: string | null;
}

export interface KbDraft {
  draft_id: string;
  doc_id: string;
  page: number;
  status: "draft" | "approved" | "rejected";
  topic?: string;
  sectors?: string[];
  metric?: string;
  value?: string;
  horizon?: string;
  quote?: string;
  text?: string;
  stance?: "forecast";
  forecast_values?: Record<string, number>;
  checks: KbCheck[];
  edited?: boolean;
  thesis_id: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  reject_reason?: string;
  supersedes?: string | null;
  supersedes_candidate: string | null;
}

export interface KbUploadItem {
  doc_id: string;
  filename: string;
  status: "queued" | "processing" | "ready" | "failed";
  created_at: string;
  title: string | null;
  date: string | null;
  pages: number | null;
  error: string | null;
  model: string | null;
  drafts: { draft: number; approved: number; rejected: number };
}

export interface KbDocument extends Omit<KbUploadItem, "drafts" | "created_at"> {
  page_texts: Record<string, string>;
  topics: Record<string, string>;
  drafts: KbDraft[];
}

// Разметка релевантности (SPR3-06): пара без оценки системы и прогресс.
export interface LabelPair {
  news_id: string;
  company_id: string;
  role: Role;
  role_name: string;
  overlap: boolean;
  news: { title: string | null; lead: string | null; source: string | null; published_at: string | null; topics: string[] };
  company: { name: string | null; sector: string | null; region: string | null; revenue: number | null;
             countries: string[]; suppliers: string[]; customers: string[] };
}

export interface LabelingState {
  pair: LabelPair | null;
  stats: { planned: number; labeled_pairs: number; labels: number; overlap_planned: number; overlap_done: number;
           kappa: number | null; annotators: Record<string, number> };
}

// Доменная конфигурация (SPR4-00): темы, отрасли и слова-маркеры в YAML.
export type ConfigDoc = "topics" | "sectors" | "language";
export type ConfigTexts = Record<ConfigDoc, string>;

export interface ConfigIssue {
  level: "error" | "warning";
  doc: ConfigDoc;
  path: string;
  message: string;
}

export interface ConfigVersion {
  id: number;
  status: "published" | "archived";
  created_by: string;
  note: string;
  signature: string;
  created_at: string;
}

export interface ConfigState {
  version: number | null;
  signature: string;
  texts: ConfigTexts;
  issues: ConfigIssue[];
  versions: ConfigVersion[];
}

export interface ConfigPreviewRow {
  news_id: string;
  title: string;
  score: number;
  topics: string[];
  rank?: number;
  rank_before?: number | null;
}

export interface ConfigPreview {
  status: "queued" | "ready" | "invalid";
  before?: ConfigPreviewRow[];
  after?: ConfigPreviewRow[];
  gone?: ConfigPreviewRow[];
  issues?: ConfigIssue[];
}

// Граф контрагентов (SPR4-01).
export interface Counterparty {
  company_id: string;
  name: string;
  sector: string | null;
  relation: "supplier" | "customer" | "person";
  level: 1 | 2;
  weight: number;
  amount?: number;
  count?: number;
  text: string;
}

export interface CounterpartyEvent {
  news_id: string;
  counterparty_id: string;
  counterparty_name: string;
  level: number;
  relation: string;
  chain: string;
  title: string;
  published_at: string;
  strength: number;
  created_at: string;
}

export interface CounterpartiesView {
  company_id: string;
  top: Counterparty[];
  second_level: Counterparty[];
  possible_links: Counterparty[];
  events: CounterpartyEvent[];
}

// Сводки и алерты (SPR4-04).
export interface NotificationSettings {
  company_id: string;
  digest: boolean;
  digest_time: string;
  timezone: string;
  threshold: number;
  topics: string[];
  counterparties: boolean;
  quiet_from: string;
  quiet_to: string;
  alerts_per_day: number;
  channels: { inapp: boolean; email: boolean; telegram: boolean };
}

export interface InboxMessage {
  id: number;
  kind: "digest" | "alert";
  title: string;
  created_at: string;
  read: boolean;
  items: { news_id: string; headline: string; score: number; href: string }[];
}

export interface Inbox {
  items: InboxMessage[];
  unread: number;
}

// Сценарии «что если» (SPR4-02).
export type ScenarioKind = "key_rate" | "fx" | "commodity";

export interface ScenarioResult {
  scenario: ScenarioKind;
  shock: number;
  shock_unit: string;
  effect_rub: number;
  text: string;
  formula: string;
  inputs: { name: string; label: string; value: number; unit: string; origin: string; source: string }[];
  caveats: string[];
}

export interface ScenarioResponse {
  ok: boolean;
  result: ScenarioResult | null;
  refusal: { message: string; missing: string[] } | null;
  corridor: { label: string; horizon: string; unit: string; low: number; high: number; sources: string[] } | null;
}
