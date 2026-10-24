"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useSession } from "@/lib/session";
import CompanySwitcher from "./CompanySwitcher";
import Notifications from "./Notifications";
import { AlfaMark, Icon } from "./ui";
import styles from "@/components/Shell.module.scss";
import ui from "@/components/ui.module.scss";
import common from "@/styles/common.module.scss";

type NavItem = { href: string; label: string; icon: string; badge?: string; accent?: boolean; disabled?: boolean; operatorOnly?: boolean };

// Разделы Альфа-Бизнеса с экранов банка; рабочие — только разделы Альфа.Пульса.
const NAV: (NavItem | "divider")[] = [
  { href: "#services", label: "Все сервисы", icon: "grid", disabled: true },
  "divider",
  { href: "/", label: "Главная", icon: "home" },
  { href: "/pulse", label: "Альфа.Пульс", icon: "pulse", accent: true },
  { href: "/pulse/analytics", label: "Аналитика банка", icon: "doc" },
  { href: "/quality", label: "Качество", icon: "shield", operatorOnly: true },
];

export default function Shell({ children }: { children: ReactNode }) {
  const { session, ready, logout } = useSession();
  const router = useRouter();
  const path = usePathname();
  // Меню открыто для страницы, где его открыли: переход на другую страницу его закрывает.
  const [menuPath, setMenuPath] = useState<string | null>(null);
  const menuOpen = menuPath === path;
  const setMenuOpen = (open: boolean) => setMenuPath(open ? path : null);

  // Без компаний доступны только регистрация компании и профиль.
  const noCompanyOk = path === "/company/register" || path === "/profile";
  const needCompany = Boolean(session) && session!.memberships.length === 0 && !noCompanyOk;

  useEffect(() => {
    if (!ready) return;
    if (!session) router.replace("/login");
    else if (needCompany) router.replace("/company/register");
  }, [ready, session, needCompany, router]);

  if (!ready || !session || needCompany) {
    return <div className={styles.boot}><span className={ui.spinner} aria-label="Загрузка" /></div>;
  }

  const active = (href: string) => path === href || (href === "/pulse" && path.startsWith("/pulse/n/"));

  return (
    <div className={styles.app}>
      <aside className={`${styles.sidebar} ${menuOpen ? styles.open : ""}`}>
        <Link href="/" className={common.brand} aria-label="Альфа-Бизнес, главная">
          <AlfaMark size={34} />
          <span className={common.brandText}>Альфа-Бизнес</span>
        </Link>
        <nav className={styles.nav}>
          {NAV.map((item, i) => {
            if (item === "divider") return <hr key={`d${i}`} className={styles.navDivider} />;
            if (item.operatorOnly && !session.user.is_operator) return null;  // мониторинг — только сотрудникам банка
            const inner = (
              <>
                <Icon name={item.icon} size={20} /> <span className={styles.navLabel}>{item.label}</span>
                {item.badge && <span className={styles.navBadge}>{item.badge}</span>}
              </>
            );
            return item.disabled ? (
              <span key={item.href} className={`${styles.navItem} ${styles.disabled}`} title="Раздел интернет-банка, не входит в прототип">{inner}</span>
            ) : (
              <Link key={item.href} href={item.href} className={`${styles.navItem} ${active(item.href) ? styles.active : ""} ${item.accent ? styles.accent : ""}`}>{inner}</Link>
            );
          })}
        </nav>
        <div className={styles.sidebarFoot}>
          <Link href="/help" className={`${styles.footLink} ${path === "/help" ? styles.active : ""}`}>Вопросы и ответы</Link>
          <Link href="/legal" className={`${styles.footLink} ${path === "/legal" ? styles.active : ""}`}>Правовая информация</Link>
        </div>
      </aside>
      {menuOpen && <div className={styles.scrim} onClick={() => setMenuOpen(false)} aria-hidden="true" />}

      <div className={styles.main}>
        <header className={styles.topbar}>
          <button className={`${common.iconBtn} ${styles.menuBtn}`} onClick={() => setMenuOpen(!menuOpen)} aria-label="Меню">
            <Icon name="menu" />
          </button>
          <div className={styles.topbarRight}>
            {session.memberships.length > 0 && <Notifications />}
            <CompanySwitcher />
            <Link href="/profile" className={styles.userPill} aria-label={`Профиль: ${session.userName}`}>
              <span className={styles.avatar}>{session.userName.slice(0, 1)}</span>
              <span className={styles.userName}>{session.userName}</span>
            </Link>
            <button className={common.iconBtn} onClick={async () => { await logout(); router.replace("/login"); }} aria-label="Выйти" title="Выйти">
              <Icon name="logout" size={20} />
            </button>
          </div>
        </header>
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  );
}
