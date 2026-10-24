"use client";

import Link from "next/link";
import { useCallback } from "react";
import { CompanyTile, EmptyState } from "@/components/ui";
import AISettingsCard from "@/components/AISettingsCard";
import OperatorPanel from "@/components/OperatorPanel";
import CompanyMenu from "@/components/profile/CompanyMenu";
import Members from "@/components/profile/Members";
import { useSession } from "@/lib/session";
import styles from "@/app/(bank)/profile/page.module.scss";
import common from "@/styles/common.module.scss";

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

      {session!.companyId && <AISettingsCard companyId={session!.companyId} companyName={session!.companyName} isAdmin={session!.isAdmin} />}

      {user.is_operator && <OperatorPanel />}

      <div className={common.pageHead}>
        <h2>Мои компании</h2>
        <Link href="/company/register" className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`}>Зарегистрировать компанию</Link>
      </div>

      {user.memberships.length === 0 && (
        <div className={common.card}><EmptyState>У вас пока нет компаний. Зарегистрируйте компанию или попросите администратора пригласить вас.</EmptyState></div>
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
