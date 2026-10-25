"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import type { Membership } from "@/lib/types";
import { Icon } from "../ui";
import styles from "@/app/(bank)/profile/page.module.scss";
import common from "@/styles/common.module.scss";
import ui from "@/components/ui.module.scss";

/** Ненавязчивое меню компании: участник видит только «Выйти», собственник — только «Расформировать». */
export default function CompanyMenu({ m, selfId, onChanged }: { m: Membership; selfId: string; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const disband = m.role === "owner";

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) { setOpen(false); setConfirm(false); } };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); setConfirm(false); } };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      if (disband) {
        await api.disbandCompany(m.company_id);
      } else {
        const { members } = await api.members(m.company_id);
        const self = members.find((x) => x.user_id === selfId);
        if (self) await api.removeMember(m.company_id, self.member_id);
      }
      setOpen(false);
      onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  if (m.is_founder && !disband) return null; // основатель с другой ролью не уходит и не расформировывает

  return (
    <div className={styles.companyMenu} ref={box}>
      <button type="button" className={styles.iconBtn} aria-label="Действия с компанией" aria-expanded={open}
        onClick={() => { setOpen((v) => !v); setConfirm(false); setError(null); }}>
        <Icon name="more" size={20} />
      </button>
      {open && (
        <div className={styles.companyMenuPop} role="menu">
          {!confirm ? (
            <button type="button" role="menuitem" className={styles.menuItem} onClick={() => setConfirm(true)}>
              {disband ? "Расформировать компанию" : "Выйти из компании"}
            </button>
          ) : (
            <div className={styles.menuConfirm}>
              <p>{disband
                ? "Все участники потеряют доступ, компания освободится. Это нельзя отменить."
                : "Вы потеряете доступ. Вернуться можно только по новому приглашению."}</p>
              {error && <p className={ui.errorText}>{error}</p>}
              <div>
                <button type="button" className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} onClick={() => setConfirm(false)} disabled={busy}>Отмена</button>
                <button type="button" className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`} onClick={run} disabled={busy}>{busy ? "…" : disband ? "Расформировать" : "Выйти"}</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
