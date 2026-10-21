"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ErrorBox, Loading } from "@/components/ui";
import { AbortedError, api } from "@/lib/api";
import { money } from "@/lib/format";
import { ROLE_NAMES, useSession } from "@/lib/session";
import type { CompanySummary, Role } from "@/lib/types";

// Демо-пользователи: одна компания — несколько людей с разными ролями (условие кейса).
const PEOPLE: { name: string; role: Role }[] = [
  { name: "Анна Морозова", role: "cfo" },
  { name: "Игорь Белов", role: "ceo" },
  { name: "Мария Ким", role: "treasurer" },
  { name: "Олег Сафонов", role: "owner" },
  { name: "Елена Петрова", role: "accountant" },
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

  const enter = (person: { name: string; role: Role }, c: CompanySummary) => {
    login({ userName: person.name, role: person.role, companyId: c.company_id, companyName: c.display_name });
    router.replace("/");
  };

  return (
    <div className="login">
      <div className="login-panel">
        <div className="brand brand-lg">
          <span className="brand-mark">А</span>
          <span className="brand-text">Альфа-Бизнес<small>демо-стенд хакатона «Альфа.Пульс»</small></span>
        </div>
        <h1>Вход для проверки</h1>
        <p className="muted">
          Тестовые учетные записи без пароля. Сервис создается для людей: у одной компании несколько пользователей с разными ролями,
          и каждый видит свою ленту.
        </p>
        {error && <ErrorBox message={error} onRetry={() => setAttempt((a) => a + 1)} />}
        {!companies && !error && <Loading text="Загружаем организации…" />}
        {companies && companies.length === 0 && <p>Нет данных о компаниях. Проверьте DATA_DIR на backend.</p>}
        <div className="login-grid">
          {companies?.slice(0, 3).map((c, ci) => (
            <div className="login-company" key={c.company_id}>
              <div className="login-company-head">
                <strong>{c.display_name}</strong>
                <span>{c.sector_name} · {c.region ?? "регион н/д"} · {money(c.revenue)}</span>
              </div>
              {PEOPLE.slice(ci, ci + 3).map((p) => (
                <button key={p.name} className="login-user" onClick={() => enter(p, c)}>
                  <span className="avatar">{p.name[0]}</span>
                  <span><strong>{p.name}</strong><small>{ROLE_NAMES[p.role]}</small></span>
                </button>
              ))}
            </div>
          ))}
        </div>
        <p className="muted small">Компанию и роль можно сменить после входа в шапке интернет-банка.</p>
      </div>
    </div>
  );
}
