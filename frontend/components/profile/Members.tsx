"use client";

import { useEffect, useRef, useState } from "react";
import { AbortedError, api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { ROLE_NAMES } from "@/lib/session";
import type { Member, Membership, Role } from "@/lib/types";
import { ErrorState, Loading } from "../ui";
import InviteForm from "./InviteForm";
import MemberMenu from "./MemberMenu";
import RoleChangeDialog, { type RoleChange } from "./RoleChangeDialog";
import styles from "@/app/(bank)/profile/page.module.scss";
import common from "@/styles/common.module.scss";

const ROLES = Object.keys(ROLE_NAMES) as Role[];
const SELF_HINT = "Свою роль может изменить только другой администратор";

/** Участники компании: роли, статусы, права администратора и приглашения. */
export default function Members({ m, selfId, onChanged }: { m: Membership; selfId: string; onChanged: () => void }) {
  const [members, setMembers] = useState<Member[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [roleChange, setRoleChange] = useState<RoleChange | null>(null);
  const roleTrigger = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    const c = new AbortController();
    api.members(m.company_id, c.signal)
      .then((r) => { setMembers(r.members); setError(null); })
      .catch((e) => { if (!(e instanceof AbortedError)) setError(errorText(e)); });
    return () => c.abort();
  }, [m.company_id, attempt]);

  const reload = () => setAttempt((a) => a + 1);

  const confirmRoleChange = async () => {
    if (!roleChange) return;
    const { member, role: nextRole } = roleChange;
    await api.updateMember(m.company_id, member.member_id, { role: nextRole });
    setMembers((current) => current?.map((item) => item.member_id === member.member_id ? { ...item, role: nextRole } : item) ?? null);
    setRoleChange(null);
    reload();
    onChanged();
  };

  const act = async (id: string, fn: () => Promise<unknown>) => {
    setBusy(id);
    setActionError(null);
    try {
      await fn();
      reload();
      onChanged();
    } catch (e) {
      setActionError(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={styles.members}>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!members && !error && <Loading text="Загружаем участников…" />}
      {actionError && <ErrorState error={actionError} />}
      {members && (
        <ul className={styles.memberList}>
          {members.map((mem) => {
            const self = mem.user_id === selfId;
            const off = busy === mem.member_id;
            return (
              <li key={mem.member_id} className={styles.memberRow}>
                <div className={styles.memberWho}>
                  <strong>{mem.name ?? mem.email}{self && " (вы)"}</strong>
                  {mem.name && <small className={common.muted}>{mem.email}</small>}
                </div>
                <div className={styles.memberMeta}>
                  {m.is_admin && !self ? (
                    <>
                      <label className={common.srOnly} htmlFor={`r-${mem.member_id}`}>Роль: {mem.name ?? mem.email}</label>
                      <select className={`${styles.roleControl} ${styles.roleSelect}`} id={`r-${mem.member_id}`} value={mem.role} disabled={off}
                        onChange={(event) => {
                          const nextRole = event.target.value as Role;
                          if (nextRole !== mem.role) {
                            roleTrigger.current = event.currentTarget;
                            setRoleChange({ member: mem, role: nextRole });
                          }
                        }}>
                        {ROLES.map((r) => <option key={r} value={r}>{ROLE_NAMES[r]}</option>)}
                      </select>
                    </>
                  ) : (
                    <span className={styles.roleControl} title={self ? SELF_HINT : undefined}>{ROLE_NAMES[mem.role]}</span>
                  )}
                  <span className={`${common.tag} ${mem.status === "active" ? common.tagOn : common.tagWarn}`}>{mem.status === "active" ? "Активен" : "Приглашён"}</span>
                  {mem.is_admin && <span className={`${common.tag} ${common.tagAdmin}`}>Администратор</span>}
                </div>
                {m.is_admin && !self && (
                  <MemberMenu member={mem} busy={off}
                    onToggleAdmin={() => act(mem.member_id, () => api.updateMember(m.company_id, mem.member_id, { is_admin: !mem.is_admin }))}
                    onRemove={() => act(mem.member_id, () => api.removeMember(m.company_id, mem.member_id))} />
                )}
              </li>
            );
          })}
        </ul>
      )}

      {roleChange && <RoleChangeDialog change={roleChange} focusTarget={roleTrigger}
        onConfirm={confirmRoleChange} onCancel={() => setRoleChange(null)} />}

      {m.is_admin && <InviteForm companyId={m.company_id} onInvited={reload} onError={setActionError} />}
    </div>
  );
}
