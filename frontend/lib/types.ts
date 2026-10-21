// Типы публичного контракта 0.1.0 (contracts/schemas/common.json).

export type Role = "ceo" | "cfo";

export interface CompanyProfile {
  company_id: string;
  display_name: string;
  industry_name: string;
  region: string | null;
  has_credit: boolean | null;
  has_deposit: boolean | null;
  is_synthetic: true;
}

export interface Source {
  source_id: string;
  kind: "synthetic_fixture";
  title: string;
}

export interface Insight {
  schema_version: "0.1.0";
  request_id: string;
  company_id: string;
  event_id: string;
  role: Role;
  status: "completed";
  is_mock: true;
  title: string;
  facts: string[];
  company_relevance: string;
  risks: string[];
  opportunities: string[];
  actions: string[];
  bank_position: null;
  model_conclusion: string;
  sources: Source[];
  uncertainty: string[];
}

export interface InsightRequest {
  company_id: string;
  role: Role;
  event_id: string;
}

export interface ErrorResponse {
  error: {
    code: string;
    message: string;
    request_id: string;
    retryable: boolean;
  };
}
