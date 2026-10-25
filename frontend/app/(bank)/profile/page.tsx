"use client";

import Link from "next/link";
import { useCallback } from "react";
import { CompanyTile, EmptyState } from "@/components/ui";
import AISettingsCard from "@/components/AISettingsCard";
import NotificationSettings from "@/components/NotificationSettings";
import OperatorPanel from "@/components/OperatorPanel";
import CompanyMenu from "@/components/profile/CompanyMenu";
import Members from "@/components/profile/Members";
import { ROLE_NAMES, useSession } from "@/lib/session";
import styles from "@/app/(bank)/profile/page.module.scss";
import common from "@/styles/common.module.scss";

export default function ProfilePage() {
  const { session, refresh, setActiveCompany } = useSession();
  const user = session!.user;
  const onChanged = useCallback(() => { void refresh(); }, [refresh]);

  return (
    <div className={common.page}>
      <header className={styles.head}>
        <h1>Профиль</h1>
      </header>

      <div className={styles.layout}>
        <aside className={styles.side}>
          <div className={`${common.card} ${styles.profileHead}`}>
            <span className={`${common.avatar} ${styles.profileAvatar}`}>{user.name.slice(0, 1)}</span>
            <h2>{user.name}</h2>
            <p className={common.muted}>{user.email}</p>
            {user.is_operator && <span className={`${common.tag} ${common.tagAdmin}`}>Сотрудник банка</span>}
            <dl className={styles.facts}>
              <div><dt>Компаний</dt><dd>{user.memberships.length}</dd></div>
              {session!.companyId && <div><dt>Активная</dt><dd>{session!.companyName}</dd></div>}
              {session!.companyId && <div><dt>Роль</dt><dd>{ROLE_NAMES[session!.role]}</dd></div>}
            </dl>
            <Link href="/company/register" className={`${common.btn} ${common.btnSecondary} ${common.btnSm} ${styles.addCompany}`}>+ Зарегистрировать компанию</Link>
          </div>
          <nav className={`${common.card} ${styles.nav}`} aria-label="Разделы профиля">
            <a href="#companies">Мои компании</a>
            {session!.companyId && <a href="#notifications">Уведомления</a>}
            {session!.companyId && <a href="#ai">ИИ-настройки</a>}
            {user.is_operator && <a href="#operator">Панель оператора</a>}
          </nav>
        </aside>

        <div className={styles.main}>
          <section id="companies" className={styles.block} aria-label="Мои компании">
            <div className={styles.blockHead}>
              <h2>Мои компании</h2>
            </div>

            {user.memberships.length === 0 && (
              <div className={common.card}><EmptyState>У вас пока нет компаний. Зарегистрируйте компанию или попросите администратора пригласить вас.</EmptyState></div>
            )}

            {user.memberships.map((m) => (
              <section key={m.company_id} className={common.card} aria-label={m.company_name}>
                <div className={common.cardHead}>
                  <h2><CompanyTile id={m.company_id} name={m.company_name} size={32} /> {m.company_name}</h2>
                  <div className={styles.companyActions}>
                    {m.company_id === session!.companyId ? (
                      <span className={`${common.tag} ${common.tagOn}`}>Активная</span>
                    ) : (
                      <button type="button" className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`}
                        onClick={() => setActiveCompany(m.company_id)}>Сделать активной</button>
                    )}
                    <CompanyMenu m={m} selfId={user.user_id} onChanged={onChanged} />
                  </div>
                </div>
                <h3>Участники</h3>
                <Members m={m} selfId={user.user_id} onChanged={onChanged} />
              </section>
            ))}
          </section>

          {session!.companyId && <NotificationSettings />}

          {session!.companyId && (
            <div id="ai" className={styles.anchor}>
              <AISettingsCard companyId={session!.companyId} companyName={session!.companyName} isAdmin={session!.isAdmin} />
            </div>
          )}

          {user.is_operator && <div id="operator" className={styles.anchor}><OperatorPanel /></div>}
        </div>
      </div>
    </div>
  );
}
