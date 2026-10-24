"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { ROLE_NAMES } from "@/lib/session";
import type { Role } from "@/lib/types";
import styles from "@/app/(bank)/profile/page.module.scss";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";

const ROLES = Object.keys(ROLE_NAMES) as Role[];

/** Приглашение участника по email (видит администратор компании); ошибка уходит в общий блок ошибок участников. */
export default function InviteForm({ companyId, onInvited, onError }: {
  companyId: string; onInvited: () => void; onError: (message: string | null) => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("cfo");
  const [admin, setAdmin] = useState(false);
  const [inviting, setInviting] = useState(false);

  const invite = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      onError("Введите корректный email.");
      return;
    }
    setInviting(true);
    onError(null);
    try {
      await api.inviteMember(companyId, email.trim(), role, admin);
      setEmail("");
      setAdmin(false);
      onInvited();
    } catch (e) {
      onError(errorText(e));
    } finally {
      setInviting(false);
    }
  };

  return (
    <form className={styles.inviteForm} onSubmit={invite} noValidate>
      <h3>Пригласить участника</h3>
      <div className={styles.inviteFields}>
        <div className={forms.field}>
          <label htmlFor={`inv-email-${companyId}`}>Email</label>
          <input className={forms.input} id={`inv-email-${companyId}`} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className={forms.field}>
          <label htmlFor={`inv-role-${companyId}`}>Роль</label>
          <select className={`${styles.roleControl} ${styles.roleSelect} ${styles.inviteRole}`} id={`inv-role-${companyId}`} value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_NAMES[r]}</option>)}
          </select>
        </div>
      </div>
      <label className={forms.check}><input className={forms.input} type="checkbox" checked={admin} onChange={(e) => setAdmin(e.target.checked)} /> Администратор компании</label>
      <button type="submit" className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`} disabled={inviting}>{inviting ? "Отправляем…" : "Пригласить"}</button>
    </form>
  );
}
