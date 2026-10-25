"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ROLE_NAMES, useSession } from "@/lib/session";
import { CompanyTile, Icon } from "./ui";
import styles from "@/components/CompanySwitcher.module.scss";
import common from "@/styles/common.module.scss";

/** Переключает активную компанию среди тех, где у пользователя есть членство. Роль берется из членства и только отображается. */
export default function CompanySwitcher() {
  const { session, setActiveCompany } = useSession();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, []);

  if (!session || !session.companyId) return null;
  const many = session.memberships.length > 1;

  const label = (
    <>
      <CompanyTile id={session.companyId} name={session.companyName} size={36} />
      <span className={styles.switcherText}>
        <span className={styles.switcherName} data-testid="company-name">{session.companyName}</span>
        <span className={styles.switcherLabel} data-testid="company-role">{ROLE_NAMES[session.role]}</span>
      </span>
    </>
  );

  return (
    <div className={styles.switcher} ref={box}>
      <div className={styles.switcherChip}>
        <Link href="/company" className={styles.switcherLink} title="Профиль компании">{label}</Link>
        {many && (
          <button type="button" className={`${styles.switcherBtn} ${common.iconBtn}`} onClick={() => setOpen((v) => !v)} aria-expanded={open}
            aria-label="Сменить организацию" title="Сменить организацию">
            <span className={styles.switcherBtnText}>Сменить</span>
            <Icon name="chevron" size={16} />
          </button>
        )}
      </div>
      {open && many && (
        <div className={styles.switcherPop} role="dialog" aria-label="Выбор организации">
          <p className={common.popTitle}>Мои компании</p>
          <ul>
            {session.memberships.map((m) => (
              <li key={m.company_id}>
                <button type="button" className={m.company_id === session.companyId ? styles.current : ""}
                  onClick={() => { setActiveCompany(m.company_id); setOpen(false); }}>
                  <CompanyTile id={m.company_id} name={m.company_name} size={32} />
                  <span><strong>{m.company_name}</strong><small>{ROLE_NAMES[m.role]}</small></span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
