"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CompanyTile, ErrorBox, Loading } from "@/components/ui";
import { AbortedError, ApiError, api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { ROLE_NAMES, useSession } from "@/lib/session";
import type { LookupCompany, Role } from "@/lib/types";

const PAGE = 20;
const LIMIT = 5;

export default function CompanyRegisterPage() {
  const { session, refresh, setActiveCompany } = useSession();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<LookupCompany[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [picking, setPicking] = useState<string | null>(null);
  const [role, setRole] = useState<Role>("cfo");
  const [busy, setBusy] = useState(false);
  const [claimError, setClaimError] = useState<string | null>(null);

  const count = session?.memberships.length ?? 0;

  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    setError(null);
    const t = setTimeout(() => {
      api.lookupCompanies(q.trim(), PAGE, 0, c.signal)
        .then((r) => { setItems(r.items); setTotal(r.total); setLoading(false); })
        .catch((e) => { if (e instanceof AbortedError) return; setError(errorText(e)); setLoading(false); });
    }, 250);
    return () => { clearTimeout(t); c.abort(); };
  }, [q, attempt]);

  const loadMore = () => {
    setMore(true);
    api.lookupCompanies(q.trim(), PAGE, items.length)
      .then((r) => { setItems((prev) => [...prev, ...r.items]); setTotal(r.total); })
      .catch((e) => setError(errorText(e)))
      .finally(() => setMore(false));
  };

  const claim = async (c: LookupCompany) => {
    setBusy(true);
    setClaimError(null);
    try {
      const m = await api.claimCompany(c.company_id, role);
      setActiveCompany(m.company_id);
      await refresh();
      router.replace("/");
    } catch (e) {
      setClaimError(errorText(e));
      setBusy(false);
      // Могли опередить: обновим статус «claimed» в списке.
      if (e instanceof ApiError && e.code === "COMPANY_CLAIMED") setAttempt((a) => a + 1);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Регистрация компании</h1>
          <p className="muted">Найдите свою организацию и подтвердите свою роль в ней. Первый зарегистрировавший становится администратором компании.</p>
        </div>
        {count > 0 && <Link href="/profile" className="btn btn-secondary btn-sm">К профилю</Link>}
      </div>

      {count === 0 && (
        <div className="card empty-state">
          <h2>Нет доступа к компаниям</h2>
          <p className="muted">Данные Альфа.Пульса показываются только по компаниям, к которым у вас есть доступ. Зарегистрируйте свою компанию ниже или попросите администратора вашей компании пригласить вас по email.</p>
        </div>
      )}

      <div className="card">
        <div className="field">
          <label htmlFor="company-q">Поиск компании</label>
          <input id="company-q" type="search" placeholder="Название, ИНН, отрасль или регион" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {claimError && <div className="error-box" role="alert"><span>{claimError}</span></div>}
        {error && <ErrorBox message={error} onRetry={() => setAttempt((a) => a + 1)} />}
        {loading && <Loading text="Ищем компании…" />}
        {!loading && !error && items.length === 0 && <p className="muted">Ничего не найдено. Измените запрос.</p>}
        {!loading && items.length > 0 && (
          <>
            <ul className="lookup-list">
              {items.map((c) => (
                <li key={c.company_id} className="lookup-item">
                  <CompanyTile id={c.company_id} name={c.display_name} size={40} />
                  <div className="lookup-main">
                    <strong>{c.display_name}</strong>
                    <small className="muted">{c.sector_name} · {c.region ?? "регион н/д"}</small>
                  </div>
                  <div className="lookup-action">
                    {c.claimed ? (
                      <>
                        <span className="tag">Уже зарегистрирована</span>
                        <small className="muted">Попросите администратора компании пригласить вас</small>
                      </>
                    ) : picking === c.company_id ? (
                      <div className="inline-form">
                        <label className="sr-only" htmlFor={`role-${c.company_id}`}>Ваша роль в компании</label>
                        <select id={`role-${c.company_id}`} value={role} onChange={(e) => setRole(e.target.value as Role)}>
                          {(Object.keys(ROLE_NAMES) as Role[]).map((r) => <option key={r} value={r}>{ROLE_NAMES[r]}</option>)}
                        </select>
                        <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => claim(c)}>{busy ? "Сохраняем…" : "Подтвердить"}</button>
                        <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setPicking(null)}>Отмена</button>
                      </div>
                    ) : (
                      <button type="button" className="btn btn-primary btn-sm" disabled={count >= LIMIT}
                        title={count >= LIMIT ? `Можно зарегистрировать не больше ${LIMIT} компаний` : undefined}
                        onClick={() => { setPicking(c.company_id); setClaimError(null); }}>
                        Зарегистрировать компанию
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
            {items.length < total && (
              <button type="button" className="btn btn-secondary" onClick={loadMore} disabled={more}>
                {more ? "Загружаем…" : `Показать ещё (${total - items.length})`}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
