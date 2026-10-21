"use client";

import { useEffect, useRef, useState } from "react";
import { AbortedError, api } from "@/lib/api";
import { money } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { CompanySummary } from "@/lib/types";
import { Icon } from "./ui";

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
  return (
    <div className="switcher" ref={box}>
      <button className="switcher-btn" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="switcher-label">Организация</span>
        <span className="switcher-name">{session.companyName}</span>
        <Icon name="chevron" />
      </button>
      {open && (
        <div className="switcher-pop" role="dialog" aria-label="Выбор организации">
          <input autoFocus placeholder="ID, ОКВЭД, отрасль или регион" value={q} onChange={(e) => setQ(e.target.value)} />
          {error && <p className="error-text">{error}</p>}
          <p className="muted small">Найдено: {total}. Крупный бизнес из данных кейса (выручка от 15 млрд ₽).</p>
          <ul>
            {items.map((c) => (
              <li key={c.company_id}>
                <button
                  className={c.company_id === session.companyId ? "current" : ""}
                  onClick={() => { update({ companyId: c.company_id, companyName: c.display_name }); setOpen(false); }}
                >
                  <strong>{c.display_name}</strong>
                  <span>{c.sector_name} · {c.region ?? "регион н/д"} · {money(c.revenue)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
