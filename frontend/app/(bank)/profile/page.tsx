"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { CompanyTile, ErrorBox, Icon, Loading } from "@/components/ui";
import { AbortedError, api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { ROLE_NAMES, useSession } from "@/lib/session";
import type { Member, Membership, Role } from "@/lib/types";

const ROLES = Object.keys(ROLE_NAMES) as Role[];
const SELF_HINT = "Свою роль может изменить только другой администратор";

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
    <div className="company-menu" ref={box}>
      <button type="button" className="icon-btn" aria-label="Действия с компанией" aria-expanded={open}
        onClick={() => { setOpen((v) => !v); setConfirm(false); setError(null); }}>
        <Icon name="more" size={20} />
      </button>
      {open && (
        <div className="company-menu-pop" role="menu">
          {!confirm ? (
            <button type="button" role="menuitem" className="menu-item" onClick={() => setConfirm(true)}>
              {disband ? "Расформировать компанию" : "Выйти из компании"}
            </button>
          ) : (
            <div className="menu-confirm">
              <p>{disband
                ? "Все участники потеряют доступ, компания освободится. Это нельзя отменить."
                : "Вы потеряете доступ. Вернуться можно только по новому приглашению."}</p>
              {error && <p className="error-text">{error}</p>}
              <div>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setConfirm(false)} disabled={busy}>Отмена</button>
                <button type="button" className="btn btn-primary btn-sm" onClick={run} disabled={busy}>{busy ? "…" : disband ? "Расформировать" : "Выйти"}</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
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

  useEffect(() => {
    const c = new AbortController();
    api.members(m.company_id, c.signal)
      .then((r) => { setMembers(r.members); setError(null); })
      .catch((e) => { if (!(e instanceof AbortedError)) setError(errorText(e)); });
    return () => c.abort();
  }, [m.company_id, attempt]);

  const reload = () => setAttempt((a) => a + 1);

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
    <div className="members">
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!members && !error && <Loading text="Загружаем участников…" />}
      {actionError && <div className="error-box" role="alert"><span>{actionError}</span></div>}
      {members && (
        <ul className="member-list">
          {members.map((mem) => {
            const self = mem.user_id === selfId;
            const off = busy === mem.member_id;
            return (
              <li key={mem.member_id} className="member-row">
                <div className="member-who">
                  <strong>{mem.name ?? mem.email}{self && " (вы)"}</strong>
                  {mem.name && <small className="muted">{mem.email}</small>}
                </div>
                <div className="member-meta">
                  {m.is_admin ? (
                    <>
                      <label className="sr-only" htmlFor={`r-${mem.member_id}`}>Роль: {mem.name ?? mem.email}</label>
                      <select id={`r-${mem.member_id}`} value={mem.role} disabled={self || off} title={self ? SELF_HINT : undefined}
                        onChange={(e) => act(mem.member_id, () => api.updateMember(m.company_id, mem.member_id, { role: e.target.value as Role }))}>
                        {ROLES.map((r) => <option key={r} value={r}>{ROLE_NAMES[r]}</option>)}
                      </select>
                    </>
                  ) : (
                    <span>{ROLE_NAMES[mem.role]}</span>
                  )}
                  <span className={`tag ${mem.status === "active" ? "tag-on" : "tag-warn"}`}>{mem.status === "active" ? "Активен" : "Приглашён"}</span>
                  {mem.is_admin && <span className="tag tag-admin">Администратор</span>}
                </div>
                {m.is_admin && (
                  <div className="member-actions">
                    <button type="button" className="btn btn-secondary btn-sm" disabled={self || off} title={self ? SELF_HINT : undefined}
                      onClick={() => act(mem.member_id, () => api.updateMember(m.company_id, mem.member_id, { is_admin: !mem.is_admin }))}>
                      {mem.is_admin ? "Снять админа" : "Сделать админом"}
                    </button>
                    <button type="button" className="btn btn-secondary btn-sm" disabled={self || off} title={self ? SELF_HINT : undefined}
                      onClick={() => act(mem.member_id, () => api.removeMember(m.company_id, mem.member_id))}>
                      Удалить
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {m.is_admin && (
        <form className="invite-form" onSubmit={invite} noValidate>
          <h3>Пригласить участника</h3>
          <div className="invite-fields">
            <div className="field">
              <label htmlFor={`inv-email-${m.company_id}`}>Email</label>
              <input id={`inv-email-${m.company_id}`} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor={`inv-role-${m.company_id}`}>Роль</label>
              <select id={`inv-role-${m.company_id}`} value={role} onChange={(e) => setRole(e.target.value as Role)}>
                {ROLES.map((r) => <option key={r} value={r}>{ROLE_NAMES[r]}</option>)}
              </select>
            </div>
          </div>
          <label className="check"><input type="checkbox" checked={admin} onChange={(e) => setAdmin(e.target.checked)} /> Администратор компании</label>
          <button type="submit" className="btn btn-primary btn-sm" disabled={inviting}>{inviting ? "Отправляем…" : "Пригласить"}</button>
        </form>
      )}
    </div>
  );
}

export default function ProfilePage() {
  const { session, logout, refresh } = useSession();
  const router = useRouter();
  const user = session!.user;
  const onChanged = useCallback(() => { void refresh(); }, [refresh]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Профиль</h1>
          <p className="muted">Доступ к данным определяется вашим членством в компаниях.</p>
        </div>
        <button type="button" className="btn btn-secondary" onClick={async () => { await logout(); router.replace("/login"); }}>Выйти</button>
      </div>

      <div className="card profile-head">
        <span className="avatar profile-avatar">{user.name.slice(0, 1)}</span>
        <div>
          <h2>{user.name}</h2>
          <p className="muted">{user.email}</p>
        </div>
      </div>

      <div className="page-head">
        <h2>Мои компании</h2>
        <Link href="/company/register" className="btn btn-primary btn-sm">Зарегистрировать компанию</Link>
      </div>

      {user.memberships.length === 0 && (
        <div className="card"><p className="muted">У вас пока нет компаний. Зарегистрируйте компанию или попросите администратора пригласить вас.</p></div>
      )}

      {user.memberships.map((m) => (
        <section key={m.company_id} className="card" aria-label={m.company_name}>
          <div className="card-head">
            <h2><CompanyTile id={m.company_id} name={m.company_name} size={32} /> {m.company_name}</h2>
            <div className="tags">
              <span className="tag">{ROLE_NAMES[m.role]}</span>
              {m.is_admin && <span className="tag tag-admin">Администратор</span>}
              <CompanyMenu m={m} selfId={user.user_id} onChanged={onChanged} />
            </div>
          </div>
          <h3>Участники</h3>
          <Members m={m} selfId={user.user_id} onChanged={onChanged} />
        </section>
      ))}
    </div>
  );
}
