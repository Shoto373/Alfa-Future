"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type ReactNode } from "react";
import { useSession } from "@/lib/session";
import { setTrackCompany, setTrackPath } from "@/lib/track";
import AccessDenied from "./AccessDenied";
import CompanySwitcher from "./CompanySwitcher";
import Clock from "./Clock";
import Notifications from "./Notifications";
import { AlfaMark, Icon } from "./ui";
import styles from "@/components/Shell.module.scss";
import ui from "@/components/ui.module.scss";
import common from "@/styles/common.module.scss";

type NavItem = { href: string; label: string; icon: string; badge?: string; accent?: boolean; disabled?: boolean; operatorOnly?: boolean; managerOnly?: boolean };

// Разделы Альфа-Бизнеса с экранов банка; рабочие — только разделы Альфа.Пульса.
const NAV: (NavItem | "divider")[] = [
  { href: "#services", label: "Все сервисы", icon: "grid", disabled: true },
  "divider",
  { href: "/", label: "Главная", icon: "home" },
  { href: "/pulse", label: "Альфа.Пульс", icon: "pulse", accent: true },
  { href: "/pulse/counterparties", label: "Контрагенты", icon: "link" },
  { href: "/pulse/analytics", label: "Аналитика банка", icon: "doc" },
  { href: "/manager", label: "Кабинет менеджера", icon: "users", managerOnly: true },
  { href: "/quality", label: "Качество", icon: "shield", operatorOnly: true },
  { href: "/quality/product", label: "Продукт и эксперименты", icon: "spark", operatorOnly: true },
  { href: "/admin/kb", label: "Тезисы аналитики", icon: "check", operatorOnly: true },
  { href: "/admin/labeling", label: "Разметка ленты", icon: "list", operatorOnly: true },
  { href: "/admin/config", label: "Отрасли и темы", icon: "settings", operatorOnly: true },
];

// Нижняя навигация на телефоне: главные разделы под большим пальцем, боковое меню — за кнопкой.
const BOTTOM_NAV: NavItem[] = [
  { href: "/", label: "Главная", icon: "home" },
  { href: "/pulse", label: "Пульс", icon: "pulse" },
  { href: "/pulse/analytics", label: "Аналитика", icon: "doc" },
  { href: "/profile", label: "Профиль", icon: "users" },
];

export default function Shell({ children }: { children: ReactNode }) {
  const { session, ready, logout } = useSession();
  const router = useRouter();
  const path = usePathname();
  // Меню открыто для страницы, где его открыли: переход на другую страницу его закрывает.
  const [menuPath, setMenuPath] = useState<string | null>(null);
  const menuOpen = menuPath === path;
  const setMenuOpen = (open: boolean) => setMenuPath(open ? path : null);

  // Без компаний доступны регистрация компании и профиль, сотруднику банка — еще его служебные разделы
  // (качество, тезисы аналитики): своей компании-клиента у него обычно нет.
  const staffPage = (Boolean(session?.user.is_operator) && (path === "/quality" || path.startsWith("/quality/") || path.startsWith("/admin/")))
    || (Boolean(session?.user.is_manager) && path === "/manager");
  const noCompanyOk = path === "/company/register" || path === "/profile" || staffPage;
  const needCompany = Boolean(session) && session!.memberships.length === 0 && !noCompanyOk;

  // События продуктовой аналитики относятся к выбранной компании (SPR4-07). Задается при отрисовке, а не в эффекте:
  // эффекты страниц выполняются раньше эффекта оболочки, и первое событие страницы осталось бы без компании.
  setTrackCompany(session?.companyId ?? null);
  setTrackPath(path);

  useEffect(() => {
    if (!ready) return;
    if (!session) router.replace("/login");
    else if (needCompany) router.replace("/company/register");
  }, [ready, session, needCompany, router]);

  if (!ready || !session || needCompany) {
    return <div className={styles.boot}><span className={ui.spinner} aria-label="Загрузка" /></div>;
  }

  const active = (href: string) => path === href || (href === "/pulse" && path.startsWith("/pulse/n/"))
    || (href === "/admin/kb" && path.startsWith("/admin/kb/"));

  return (
    <div className={styles.app}>
      <aside className={`${styles.sidebar} ${menuOpen ? styles.open : ""}`}>
        <Link href="/" className={common.brand} aria-label="Альфа-Бизнес, главная">
          <AlfaMark size={34} />
          <span className={`${common.brandText} ${styles.brandText}`}>Альфа-Бизнес</span>
        </Link>
        <nav className={styles.nav}>
          {NAV.map((item, i) => {
            if (item === "divider") return <hr key={`d${i}`} className={styles.navDivider} />;
            if (item.operatorOnly && !session.user.is_operator) return null;  // мониторинг — только сотрудникам банка
            if (item.managerOnly && !session.user.is_manager) return null;  // кабинет — менеджерам с закрепленными клиентами
            const inner = (
              <>
                <Icon name={item.icon} size={20} /> <span className={styles.navLabel}>{item.label}</span>
                {item.badge && <span className={styles.navBadge}>{item.badge}</span>}
              </>
            );
            return item.disabled ? (
              <span key={item.href} className={`${styles.navItem} ${styles.disabled}`} title={`${item.label}: раздел интернет-банка, не входит в прототип`}>{inner}</span>
            ) : (
              <Link key={item.href} href={item.href} title={item.label} className={`${styles.navItem} ${active(item.href) ? styles.active : ""} ${item.accent ? styles.accent : ""}`}>{inner}</Link>
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
            <Clock />
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
        <main className={styles.content}>
          <Suspense fallback={null}><CompanyGate>{children}</CompanyGate></Suspense>
        </main>
      </div>
      <nav className={styles.bottomNav} aria-label="Разделы">
        {BOTTOM_NAV.map((item) => (
          <Link key={item.href} href={item.href} className={active(item.href) ? styles.active : undefined}
            aria-current={active(item.href) ? "page" : undefined}>
            <Icon name={item.icon} size={22} />
            <span>{item.label}</span>
          </Link>
        ))}
      </nav>
    </div>
  );
}

// Ссылка на страницу конкретной компании (?company=…, например из письма или уведомления):
// своя компания становится активной, чужая — экран «нет доступа» вместо данных.
function CompanyGate({ children }: { children: ReactNode }) {
  const params = useSearchParams();
  const path = usePathname();
  const router = useRouter();
  const { session, setActiveCompany } = useSession();
  const wanted = params.get("company");
  const member = Boolean(wanted) && session!.memberships.some((m) => m.company_id === wanted);

  useEffect(() => {
    if (!wanted || !member) return;
    setActiveCompany(wanted);
    const rest = new URLSearchParams(params);
    rest.delete("company");
    router.replace(rest.size ? `${path}?${rest}` : path);
  }, [wanted, member, params, path, router, setActiveCompany]);

  if (wanted && !member) return <AccessDenied backHref={path} />;
  return children;
}
