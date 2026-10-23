// Типы публичного контракта 1.0.0 (contracts/schemas/common.json).

export type Role = "owner" | "ceo" | "cfo" | "accountant" | "treasurer" | "clevel";
export interface Membership {
  company_id: string;
  company_name: string;
  role: Role;
  is_admin: boolean;
  is_founder: boolean;
}

export interface User {
  user_id: string;
  name: string;
  email: string;
  memberships: Membership[];
  is_operator?: boolean;  // сотрудник банка: блок «Сервис банка» в профиле
}

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

export interface Member {
  member_id: string;
  user_id: string | null;
  name: string | null;
  email: string;
  role: Role;
  is_admin: boolean;
  is_founder: boolean;
  status: "active" | "invited";
}

export type Origin = "fact" | "client_data" | "bank" | "ai";

export interface Claim {
  text: string;
  origin: Origin;
  source_ids: string[];
  features: string[];
}

export interface Source {
  source_id: string;
  kind: "news" | "bank_analytics" | "client_data" | "bank_product";
  title: string;
  url: string | null;
  doc_id: string | null;
  page: number | null;
  date: string | null;
  excerpt: string | null;
}

export interface RelevanceReason {
  kind: string;
  feature: string;
  origin: string;
  weight: number;
  text: string;
  topic?: string | null;
}

export interface Relevance {
  score: number;
  reasons: RelevanceReason[];
}

export interface TraceStep {
  step: number;
  stage: "plan" | "tool" | "compose" | "check" | "adapt" | "finalize";
  name: string;
  detail: string;
  status: "ok" | "warning" | "error" | "skipped";
  duration_ms: number;
}

export interface Insight {
  schema_version: "1.0.0";
  insight_id: string;
  request_id: string;
  company_id: string;
  role: Role;
  news_id: string;
  created_at: string;
  mode: "llm" | "rules";
  model: string | null;
  fallback_reason?: "paused" | "disabled" | "budget" | "unavailable" | "checks" | null;
  title: string;
  headline: string;
  effect?: Effect | null;
  what_happened: { summary: string; facts: Claim[]; actors: string[]; dates: string[]; assumptions: Claim[] };
  why_important: Claim[];
  risks: Claim[];
  opportunities: Claim[];
  actions: Claim[];
  questions: string[];
  bank_view: { available: boolean; summary: string | null; theses: Claim[]; conflicts: string[] };
  products: { product_id: string; title: string; text: string; reason: string }[];
  features_used: { name: string; label: string; value: string }[];
  relevance: Relevance;
  sources: Source[];
  quality: { passed: boolean; attempts: number; checks: { name: string; passed: boolean; detail: string }[] };
  trace: TraceStep[];
  disclaimer: string;
}

export interface Answer {
  insight_id: string;
  question: string;
  answer: string;
  claims: Claim[];
  sources: Source[];
  mode: "llm" | "rules";
  refused: boolean;
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
  group: { group_id: string | null; members: number | null; revenue: number | null; reliable: boolean | null };
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
export type Effect = "neg" | "pos" | "mixed" | "unclear" | "none";

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
