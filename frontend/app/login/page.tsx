"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AlfaMark, CompanyTile, ErrorBox, Loading } from "@/components/ui";
import { AbortedError, api } from "@/lib/api";
import { ROLE_NAMES, useSession } from "@/lib/session";
import type { CompanySummary, Role } from "@/lib/types";

// Демо-пользователи. Авторизация в Альфа-Бизнесе привязана к человеку: у одного пользователя может быть
// доступ к нескольким компаниям, а у одной компании — несколько пользователей с разными ролями.
const PEOPLE: { name: string; role: Role; companies: number[]; note?: string }[] = [
  { name: "Анна Морозова", role: "cfo", companies: [0, 1, 2] },
  { name: "Игорь Белов", role: "ceo", companies: [0, 3] },
  { name: "Олег Сафонов", role: "owner", companies: [0, 1, 2, 3, 4], note: "собственник группы" },
  { name: "Мария Ким", role: "treasurer", companies: [1] },
  { name: "Елена Петрова", role: "accountant", companies: [2] },
  { name: "Дмитрий Орлов", role: "clevel", companies: [3, 4], note: "директор по закупкам" },
];

export default function LoginPage() {
  const { login } = useSession();
  const router = useRouter();
  const [companies, setCompanies] = useState<CompanySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    api.companies("", 6, controller.signal)
      .then((r) => setCompanies(r.items))
      .catch((e) => { if (!(e instanceof AbortedError)) setError(e.message); });
    return () => controller.abort();
  }, [attempt]);

  const accessible = (idx: number[]) => idx.map((i) => companies?.[i]).filter((c): c is CompanySummary => Boolean(c));

  const enter = (person: (typeof PEOPLE)[number]) => {
    const list = accessible(person.companies);
    if (!list.length) return;
    login({
      userName: person.name, role: person.role, companyId: list[0].company_id, companyName: list[0].display_name,
      companies: list.map((c) => ({ id: c.company_id, name: c.display_name })),
    });
    router.replace("/");
  };

  return (
    <div className="login">
      <section className="login-hero">
        <div className="brand">
          <AlfaMark size={40} />
          <span className="brand-text">Альфа-Бизнес</span>
        </div>
        <div className="login-hero-text">
          <h1>Альфа.Пульс</h1>
          <p>Новости и аналитика Альфа-Банка, разобранные под вашу компанию и роль: что произошло, почему это важно, риски, возможности и что делать.</p>
        </div>
        <p className="login-hero-foot">Демо-стенд хакатона. Данные компаний обезличены.</p>
      </section>

      <section className="login-panel">
        <h2>Вход для проверки</h2>
        <p className="muted">
          Тестовые учетные записи без пароля: считаем, что пользователь уже прошел авторизацию в интернет-банке.
          Каждый видит свои компании и свою ленту.
        </p>
        {error && <ErrorBox message={error} onRetry={() => setAttempt((a) => a + 1)} />}
        {!companies && !error && <Loading text="Загружаем организации…" />}
        {companies && companies.length === 0 && <p>Нет данных о компаниях. Проверьте DATA_DIR на backend.</p>}
        {companies && companies.length > 0 && (
          <div className="login-list">
            {PEOPLE.map((p) => {
              const list = accessible(p.companies);
              if (!list.length) return null;
              return (
                <button key={p.name} className="login-user" onClick={() => enter(p)}>
                  <span className="avatar">{p.name[0]}</span>
                  <span className="login-user-text">
                    <strong>{p.name}</strong>
                    <small>{ROLE_NAMES[p.role]}{p.note ? ` · ${p.note}` : ""}</small>
                  </span>
                  <span className="login-companies" title={list.map((c) => c.display_name).join(", ")}>
                    {list.slice(0, 3).map((c) => <CompanyTile key={c.company_id} id={c.company_id} name={c.display_name} size={26} />)}
                    <small>{list.length === 1 ? list[0].display_name : `${list.length} ${list.length < 5 ? "компании" : "компаний"}`}</small>
                  </span>
                </button>
              );
            })}
          </div>
        )}
        <p className="muted small">Роль и компанию можно сменить после входа в шапке интернет-банка.</p>
      </section>
    </div>
  );
}
