"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AbortedError, ApiError, createInsight, fetchCompanies } from "@/lib/api";
import { mockMode } from "@/lib/mock";
import type { CompanyProfile, Insight, Role } from "@/lib/types";
import InsightCard from "./InsightCard";

const EVENT_ID = "demo_event_001";

const ROLES: { value: Role; label: string }[] = [
  { value: "ceo", label: "CEO — генеральный директор" },
  { value: "cfo", label: "CFO — финансовый директор" },
];

type CompaniesState =
  | { status: "loading" }
  | { status: "error"; error: ApiError }
  | { status: "ready"; items: CompanyProfile[] };

type AnalysisState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: ApiError }
  | { status: "success"; insight: Insight };

function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError("Непредвиденная ошибка интерфейса", "CLIENT_ERROR", true);
}

export default function NewsAnalytics() {
  const [companies, setCompanies] = useState<CompaniesState>({ status: "loading" });
  const [companyId, setCompanyId] = useState("");
  const [role, setRole] = useState<Role>("cfo");
  const [analysis, setAnalysis] = useState<AnalysisState>({ status: "idle" });

  // Номер актуального запроса анализа: ответы на устаревшие запросы игнорируются.
  const seq = useRef(0);
  const inflight = useRef<AbortController | null>(null);

  const loadCompanies = useCallback((signal?: AbortSignal) => {
    setCompanies({ status: "loading" });
    fetchCompanies(signal)
      .then((items) => {
        setCompanies({ status: "ready", items });
        setCompanyId((current) => (items.some((c) => c.company_id === current) ? current : items[0]?.company_id ?? ""));
      })
      .catch((error: unknown) => {
        if (error instanceof AbortedError) return;
        setCompanies({ status: "error", error: toApiError(error) });
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadCompanies(controller.signal);
    return () => controller.abort();
  }, [loadCompanies]);

  useEffect(() => () => inflight.current?.abort(), []);

  const resetAnalysis = () => {
    seq.current += 1;
    inflight.current?.abort();
    inflight.current = null;
    setAnalysis({ status: "idle" });
  };

  const runAnalysis = async () => {
    if (!companyId || analysis.status === "loading") return;
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    const mySeq = ++seq.current;
    setAnalysis({ status: "loading" });

    try {
      const insight = await createInsight({ company_id: companyId, role, event_id: EVENT_ID }, controller.signal);
      if (mySeq !== seq.current) return;
      if (insight.company_id !== companyId || insight.role !== role) {
        throw new ApiError("Ответ не соответствует выбранной компании или роли", "CONTEXT_MISMATCH", true);
      }
      setAnalysis({ status: "success", insight });
    } catch (error) {
      if (mySeq !== seq.current || error instanceof AbortedError) return;
      setAnalysis({ status: "error", error: toApiError(error) });
    } finally {
      if (inflight.current === controller) inflight.current = null;
    }
  };

  const selected = companies.status === "ready" ? companies.items.find((c) => c.company_id === companyId) : undefined;
  const busy = analysis.status === "loading";

  return (
    <section className="analytics">
      <header className="analytics-header">
        <h1>Новостная аналитика</h1>
        <div className="badges">
          <span className="badge badge-test">Тестовые данные</span>
          <span className="badge badge-nollm">Анализ без LLM</span>
          {mockMode && <span className="badge badge-mock">Локальный mock API: {mockMode}</span>}
        </div>
      </header>

      <div className="panel">
        <h2 className="panel-title">Параметры анализа</h2>

        {companies.status === "loading" && <p className="state" role="status">Загружаем список компаний…</p>}

        {companies.status === "error" && (
          <div className="state state-error" role="alert">
            <p>Не удалось загрузить компании: {companies.error.message}</p>
            <button className="button" onClick={() => loadCompanies()}>
              Повторить
            </button>
          </div>
        )}

        {companies.status === "ready" && companies.items.length === 0 && (
          <div className="state" role="status">
            <p>Список компаний пуст. Анализ недоступен.</p>
            <button className="button" onClick={() => loadCompanies()}>
              Обновить
            </button>
          </div>
        )}

        {companies.status === "ready" && companies.items.length > 0 && (
          <form
            className="form"
            onSubmit={(e) => {
              e.preventDefault();
              void runAnalysis();
            }}
          >
            <label className="field">
              <span>Компания</span>
              <select
                value={companyId}
                onChange={(e) => {
                  setCompanyId(e.target.value);
                  resetAnalysis();
                }}
              >
                {companies.items.map((c) => (
                  <option key={c.company_id} value={c.company_id}>
                    {c.display_name}
                  </option>
                ))}
              </select>
            </label>

            {selected && (
              <dl className="profile">
                <div><dt>Отрасль</dt><dd>{selected.industry_name}</dd></div>
                <div><dt>Регион</dt><dd>{selected.region ?? "неизвестно"}</dd></div>
                <div><dt>Кредит</dt><dd>{flag(selected.has_credit)}</dd></div>
                <div><dt>Депозит</dt><dd>{flag(selected.has_deposit)}</dd></div>
              </dl>
            )}

            <fieldset className="field roles">
              <legend>Роль</legend>
              {ROLES.map((r) => (
                <label key={r.value} className="radio">
                  <input
                    type="radio"
                    name="role"
                    value={r.value}
                    checked={role === r.value}
                    onChange={() => {
                      setRole(r.value);
                      resetAnalysis();
                    }}
                  />
                  {r.label}
                </label>
              ))}
            </fieldset>

            <p className="muted">Событие: учебное событие {EVENT_ID}</p>

            <button className="button button-primary" type="submit" disabled={busy || !companyId}>
              {busy ? "Анализируем…" : "Запустить анализ"}
            </button>
          </form>
        )}
      </div>

      {analysis.status === "loading" && (
        <div className="panel state" role="status">
          Формируем тестовую карточку…
        </div>
      )}

      {analysis.status === "error" && (
        <div className="panel state state-error" role="alert">
          <p>
            {analysis.error.message}
            {analysis.error.requestId && <span className="muted"> (request_id: {analysis.error.requestId})</span>}
          </p>
          <button className="button" onClick={() => void runAnalysis()}>
            Повторить
          </button>
        </div>
      )}

      {analysis.status === "success" && <InsightCard insight={analysis.insight} />}
    </section>
  );
}

function flag(value: boolean | null): string {
  if (value === null) return "неизвестно";
  return value ? "есть" : "нет";
}
