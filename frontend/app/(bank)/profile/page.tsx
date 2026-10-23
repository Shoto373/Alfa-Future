"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { CompanyTile, ErrorBox, Icon, Loading } from "@/components/ui";
import { AbortedError, api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { ROLE_NAMES, useSession } from "@/lib/session";
import type { Member, Membership, Role } from "@/lib/types";
import styles from "@/app/(bank)/profile/page.module.scss";
import common from "@/styles/common.module.scss";
import ui from "@/components/ui.module.scss";
import forms from "@/styles/forms.module.scss";

const ROLES = Object.keys(ROLE_NAMES) as Role[];
const SELF_HINT = "Свою роль может изменить только другой администратор";
type RoleChange = { member: Member; role: Role };

/** Ненавязчивое меню компании: участник видит только «Выйти», основатель — только «Расформировать». */
function CompanyMenu({ m, selfId, onChanged }: { m: Membership; selfId: string; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const disband = m.is_founder;

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

function MemberMenu({ member, busy, onToggleAdmin, onRemove }: {
  member: Member;
  busy: boolean;
  onToggleAdmin: () => void;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const name = member.name ?? member.email;

  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const close = (event: PointerEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const navigate = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Tab") {
      setOpen(false);
      trigger.current?.focus();
      return;
    }
    const buttons = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>("button") ?? []);
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === "ArrowDown" ? (index + 1) % buttons.length
      : event.key === "ArrowUp" ? (index - 1 + buttons.length) % buttons.length
      : event.key === "Home" ? 0
      : event.key === "End" ? buttons.length - 1 : null;
    if (next !== null) {
      event.preventDefault();
      buttons[next]?.focus();
    }
  };

  const run = (action: () => void) => {
    setOpen(false);
    trigger.current?.focus();
    action();
  };

  return (
    <div className={styles.memberActions} ref={box}>
      <button ref={trigger} type="button" className={styles.iconBtn} disabled={busy}
        aria-label={`Действия с участником: ${name}`} aria-haspopup="menu" aria-expanded={open}
        aria-controls={open ? menuId : undefined} onClick={() => setOpen((value) => !value)}>
        <Icon name="more" size={20} />
      </button>
      {open && (
        <div ref={menu} id={menuId} className={`${styles.companyMenuPop} ${styles.memberMenuPop}`}
          role="menu" aria-label={`Действия с участником: ${name}`} onKeyDown={navigate}>
          <button type="button" role="menuitem" className={styles.menuItem} onClick={() => run(onToggleAdmin)}>
            {member.is_admin ? "Снять админа" : "Сделать админом"}
          </button>
          <button type="button" role="menuitem" className={`${styles.menuItem} ${styles.dangerItem}`} onClick={() => run(onRemove)}>
            Удалить
          </button>
        </div>
      )}
    </div>
  );
}

function RoleChangeDialog({ change, focusTarget, onConfirm, onCancel }: {
  change: RoleChange;
  focusTarget: HTMLSelectElement | null;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const element = dialog.current!;
    const previousOverflow = document.body.style.overflow;
    element.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      element.close();
      document.body.style.overflow = previousOverflow;
      focusTarget?.focus({ preventScroll: true });
    };
  }, [focusTarget]);

  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <dialog ref={dialog} className={styles.roleDialog} aria-labelledby={titleId} aria-describedby={descriptionId}
      aria-modal="true" aria-busy={busy}
      onCancel={(event) => { event.preventDefault(); if (!busy) onCancel(); }}
      onClick={(event) => {
        if (event.target !== event.currentTarget || busy) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onCancel();
      }}>
      <div className={styles.roleDialogContent}>
        <h2 id={titleId}>Изменить роль участника?</h2>
        <p id={descriptionId} className={styles.roleDialogDescription}>
          Вы уверены, что хотите изменить роль пользователя <strong>{change.member.name ?? change.member.email}</strong> на «{ROLE_NAMES[change.role]}»?
        </p>
        <dl className={styles.roleChangeSummary}>
          <div><dt>Текущая роль</dt><dd>{ROLE_NAMES[change.member.role]}</dd></div>
          <div><dt>Новая роль</dt><dd>{ROLE_NAMES[change.role]}</dd></div>
        </dl>
        {error && <p className={ui.errorText} role="alert">{error}</p>}
        <div className={styles.roleDialogActions}>
          <button type="button" className={`${common.btn} ${common.btnSecondary}`} autoFocus disabled={busy} onClick={onCancel}>Отмена</button>
          <button type="button" className={`${common.btn} ${common.btnPrimary}`} disabled={busy} onClick={confirm}>
            {busy ? "Сохраняем…" : "Изменить роль"}
          </button>
        </div>
      </div>
    </dialog>
  );
}

function Members({ m, selfId, onChanged }: { m: Membership; selfId: string; onChanged: () => void }) {
  const [members, setMembers] = useState<Member[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("cfo");
  const [admin, setAdmin] = useState(false);
  const [inviting, setInviting] = useState(false);
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

  const invite = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setActionError("Введите корректный email.");
      return;
    }
    setInviting(true);
    setActionError(null);
    try {
      await api.inviteMember(m.company_id, email.trim(), role, admin);
      setEmail("");
      setAdmin(false);
      reload();
    } catch (e) {
      setActionError(errorText(e));
    } finally {
      setInviting(false);
    }
  };

  return (
    <div className={styles.members}>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!members && !error && <Loading text="Загружаем участников…" />}
      {actionError && <div className={ui.errorBox} role="alert"><span>{actionError}</span></div>}
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

      {roleChange && <RoleChangeDialog change={roleChange} focusTarget={roleTrigger.current}
        onConfirm={confirmRoleChange} onCancel={() => setRoleChange(null)} />}

      {m.is_admin && (
        <form className={styles.inviteForm} onSubmit={invite} noValidate>
          <h3>Пригласить участника</h3>
          <div className={styles.inviteFields}>
            <div className={forms.field}>
              <label htmlFor={`inv-email-${m.company_id}`}>Email</label>
              <input className={forms.input} id={`inv-email-${m.company_id}`} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className={forms.field}>
              <label htmlFor={`inv-role-${m.company_id}`}>Роль</label>
              <select className={`${styles.roleControl} ${styles.roleSelect} ${styles.inviteRole}`} id={`inv-role-${m.company_id}`} value={role} onChange={(e) => setRole(e.target.value as Role)}>
                {ROLES.map((r) => <option key={r} value={r}>{ROLE_NAMES[r]}</option>)}
              </select>
            </div>
          </div>
          <label className={forms.check}><input className={forms.input} type="checkbox" checked={admin} onChange={(e) => setAdmin(e.target.checked)} /> Администратор компании</label>
          <button type="submit" className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`} disabled={inviting}>{inviting ? "Отправляем…" : "Пригласить"}</button>
        </form>
      )}
    </div>
  );
}

export default function ProfilePage() {
  const { session, refresh } = useSession();
  const user = session!.user;
  const onChanged = useCallback(() => { void refresh(); }, [refresh]);

  return (
    <div className={common.page}>
      <div className={common.pageHead}>
        <div>
          <h1>Профиль</h1>
          <p className={common.muted}>Доступ к данным определяется вашим членством в компаниях.</p>
        </div>
      </div>

      <div className={`${common.card} ${styles.profileHead}`}>
        <span className={`${common.avatar} ${styles.profileAvatar}`}>{user.name.slice(0, 1)}</span>
        <div>
          <h2>{user.name}</h2>
          <p className={common.muted}>{user.email}</p>
        </div>
      </div>

      <div className={common.pageHead}>
        <h2>Мои компании</h2>
        <Link href="/company/register" className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`}>Зарегистрировать компанию</Link>
      </div>

      {user.memberships.length === 0 && (
        <div className={common.card}><p className={common.muted}>У вас пока нет компаний. Зарегистрируйте компанию или попросите администратора пригласить вас.</p></div>
      )}

      {user.memberships.map((m) => (
        <section key={m.company_id} className={common.card} aria-label={m.company_name}>
          <div className={common.cardHead}>
            <h2><CompanyTile id={m.company_id} name={m.company_name} size={32} /> {m.company_name}</h2>
            <CompanyMenu m={m} selfId={user.user_id} onChanged={onChanged} />
          </div>
          <h3>Участники</h3>
          <Members m={m} selfId={user.user_id} onChanged={onChanged} />
        </section>
      ))}
    </div>
  );
}
