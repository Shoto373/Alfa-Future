"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CompanyTile, EmptyState, ErrorState, Loading } from "@/components/ui";
import { AbortedError, ApiError, api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { ROLE_NAMES, useSession } from "@/lib/session";
import type { LookupCompany, Role } from "@/lib/types";
import common from "@/styles/common.module.scss";
import styles from "@/app/(bank)/company/register/page.module.scss";
import forms from "@/styles/forms.module.scss";

const PAGE = 20;
const LIMIT = 5;

export default function CompanyRegisterPage() {
  const { session, refresh, setActiveCompany } = useSession();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<LookupCompany[]>([]);
  const [total, setTotal] = useState(0);
  const [more, setMore] = useState(false);
  const [attempt, setAttempt] = useState(0);
  // Результат поиска относится к своему запросу: пока ответ на новый запрос не пришел — идет загрузка.
  const searchKey = JSON.stringify([q, attempt]);
  const [found, setFound] = useState<{ key: string; error: unknown } | null>(null);
  const loading = found?.key !== searchKey;
  const error = loading ? null : found.error;
  const [picking, setPicking] = useState<string | null>(null);
  const [role, setRole] = useState<Role>("cfo");
  const [busy, setBusy] = useState(false);
  const [claimError, setClaimError] = useState<string | null>(null);

  const count = session?.memberships.length ?? 0;

  useEffect(() => {
    const c = new AbortController();
    const t = setTimeout(() => {
      api.lookupCompanies(q.trim(), PAGE, 0, c.signal)
        .then((r) => { setItems(r.items); setTotal(r.total); setFound({ key: searchKey, error: null }); })
        .catch((e) => { if (!(e instanceof AbortedError)) setFound({ key: searchKey, error: e }); });
    }, 250);
    return () => { clearTimeout(t); c.abort(); };
  }, [q, searchKey]);

  const loadMore = () => {
    setMore(true);
    api.lookupCompanies(q.trim(), PAGE, items.length)
      .then((r) => { setItems((prev) => [...prev, ...r.items]); setTotal(r.total); })
      .catch((e) => setFound({ key: searchKey, error: e }))
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
    <div className={common.page}>
      <div className={common.pageHead}>
        <div>
          <h1>Регистрация компании</h1>
          <p className={styles.muted}>Найдите свою организацию и подтвердите свою роль в ней. Первый зарегистрировавший становится администратором компании.
            В пилоте доступны компании разных отраслей с самыми полными данными — на них разборы точнее всего.</p>
        </div>
        {count > 0 && <Link href="/profile" className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`}>К профилю</Link>}
      </div>

      {count === 0 && (
        <div className={`${common.card} ${styles.emptyState}`}>
          <h2>Нет доступа к компаниям</h2>
          <p className={styles.muted}>Данные Альфа.Пульса показываются только по компаниям, к которым у вас есть доступ. Зарегистрируйте свою компанию ниже или попросите администратора вашей компании пригласить вас по email.</p>
        </div>
      )}

      <div className={common.card}>
        <div className={forms.field}>
          <label htmlFor="company-q">Поиск компании</label>
          <input className={forms.input} id="company-q" type="search" placeholder="Название, ИНН, отрасль или регион" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {claimError && <ErrorState error={claimError} />}
        {error !== null && <ErrorState error={error} onRetry={() => setAttempt((a) => a + 1)} />}
        {loading && <Loading text="Ищем компании…" />}
        {!loading && error === null && items.length === 0 && <EmptyState className={styles.muted}>Ничего не найдено. Измените запрос.</EmptyState>}
        {!loading && items.length > 0 && (
          <>
            <ul className={styles.lookupList}>
              {items.map((c) => (
                <li key={c.company_id} className={styles.lookupItem}>
                  <CompanyTile id={c.company_id} name={c.display_name} size={40} />
                  <div className={styles.lookupMain}>
                    <strong>{c.display_name}</strong>
                    <small className={styles.muted}>{c.sector_name} · {c.region ?? "регион н/д"}</small>
                  </div>
                  <div className={styles.lookupAction}>
                    {c.claimed ? (
                      <>
                        <span className={common.tag}>Уже зарегистрирована</span>
                        <small className={styles.muted}>Попросите администратора компании пригласить вас</small>
                      </>
                    ) : picking === c.company_id ? (
                      <div className={styles.inlineForm}>
                        <label className={common.srOnly} htmlFor={`role-${c.company_id}`}>Ваша роль в компании</label>
                        <select className={forms.select} id={`role-${c.company_id}`} value={role} onChange={(e) => setRole(e.target.value as Role)}>
                          {(Object.keys(ROLE_NAMES) as Role[]).map((r) => <option key={r} value={r}>{ROLE_NAMES[r]}</option>)}
                        </select>
                        <button type="button" className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`} disabled={busy} onClick={() => claim(c)}>{busy ? "Сохраняем…" : "Подтвердить"}</button>
                        <button type="button" className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} disabled={busy} onClick={() => setPicking(null)}>Отмена</button>
                      </div>
                    ) : (
                      <button type="button" className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`} disabled={count >= LIMIT}
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
              <button type="button" className={`${common.btn} ${common.btnSecondary}`} onClick={loadMore} disabled={more}>
                {more ? "Загружаем…" : `Показать ещё (${total - items.length})`}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
