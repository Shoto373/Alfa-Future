"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AbortedError, api } from "@/lib/api";
import { money } from "@/lib/format";
import { shortName, useSession } from "@/lib/session";
import type { CompanySummary } from "@/lib/types";
import { CompanyTile, Icon } from "./ui";

export default function CompanySwitcher() {
  const { session, update } = useSession();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [items, setItems] = useState<CompanySummary[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const t = setTimeout(() => {
      api.companies(q, 30, controller.signal)
        .then((r) => { setItems(r.items); setTotal(r.total); setError(null); })
        .catch((e) => { if (!(e instanceof AbortedError)) setError(e.message); });
    }, 200);
    return () => { clearTimeout(t); controller.abort(); };
  }, [q, open]);

  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  if (!session) return null;
  const mine = session.companies ?? [{ id: session.companyId, name: session.companyName }];
  const choose = (id: string, name: string) => {
    // Компания из общей выборки добавляется в «Мои компании» — так демо ведет себя как доступ к нескольким организациям.
    const companies = mine.some((c) => c.id === id) ? mine : [...mine, { id, name }];
    update({ companyId: id, companyName: name, companies });
    setOpen(false);
  };
  const others = items.filter((c) => !mine.some((m) => m.id === c.company_id));

  return (
    <div className="switcher" ref={box}>
      <div className="switcher-chip">
        <Link href="/company" className="switcher-link" title="Профиль компании">
          <CompanyTile id={session.companyId} name={session.companyName} size={36} />
          <span className="switcher-text">
            <span className="switcher-name">{session.companyName}</span>
            <span className="switcher-label">{shortName(session.userName)}{mine.length > 1 ? ` · ещё ${mine.length - 1} в «Моих компаниях»` : ""}</span>
          </span>
        </Link>
        <button className="switcher-btn icon-btn" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-label="Сменить организацию" title="Сменить организацию">
          <Icon name="chevron" size={16} />
        </button>
      </div>
      {open && (
        <div className="switcher-pop" role="dialog" aria-label="Выбор организации">
          <p className="pop-title">Мои компании</p>
          <ul>
            {mine.map((c) => (
              <li key={c.id}>
                <button className={c.id === session.companyId ? "current" : ""} onClick={() => choose(c.id, c.name)}>
                  <CompanyTile id={c.id} name={c.name} size={32} />
                  <span><strong>{c.name}</strong>{c.id === session.companyId && <small>Текущая организация</small>}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="pop-title">Все компании выборки</p>
          <input autoFocus placeholder="ID, ОКВЭД, отрасль или регион" value={q} onChange={(e) => setQ(e.target.value)} />
          {error && <p className="error-text">{error}</p>}
          <p className="muted small">Найдено: {total}. Крупный бизнес из данных кейса (выручка от 15 млрд ₽).</p>
          <ul className="pop-scroll">
            {others.map((c) => (
              <li key={c.company_id}>
                <button onClick={() => choose(c.company_id, c.display_name)}>
                  <CompanyTile id={c.company_id} name={c.display_name} size={32} />
                  <span><strong>{c.display_name}</strong><small>{c.sector_name} · {c.region ?? "регион н/д"} · {money(c.revenue)}</small></span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
