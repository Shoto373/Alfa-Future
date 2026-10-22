"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useSession } from "@/lib/session";
import CompanySwitcher from "./CompanySwitcher";
import Notifications from "./Notifications";
import { AlfaMark, Icon } from "./ui";

type NavItem = { href: string; label: string; icon: string; badge?: string; accent?: boolean; disabled?: boolean };

// Разделы Альфа-Бизнеса с экранов банка; рабочие — только разделы Альфа.Пульса.
const NAV: (NavItem | "divider")[] = [
  { href: "#services", label: "Все сервисы", icon: "grid", disabled: true },
  "divider",
  { href: "/", label: "Главная", icon: "home" },
  { href: "/pulse", label: "Альфа.Пульс", icon: "pulse", badge: "НОВОЕ", accent: true },
  { href: "/pulse/analytics", label: "Аналитика банка", icon: "doc" },
];

export default function Shell({ children }: { children: ReactNode }) {
  const { session, ready, logout } = useSession();
  const router = useRouter();
  const path = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  // Без компаний доступны только регистрация компании и профиль.
  const noCompanyOk = path === "/company/register" || path === "/profile";
  const needCompany = Boolean(session) && session!.memberships.length === 0 && !noCompanyOk;

  useEffect(() => {
    if (!ready) return;
    if (!session) router.replace("/login");
    else if (needCompany) router.replace("/company/register");
  }, [ready, session, needCompany, router]);

  useEffect(() => setMenuOpen(false), [path]);

  if (!ready || !session || needCompany) {
    return <div className="boot"><span className="spinner" aria-label="Загрузка" /></div>;
  }

  const active = (href: string) => (href === "/" ? path === "/" : path === href || (href === "/pulse" && path.startsWith("/pulse/n")));

  return (
    <div className="app">
      <aside className={`sidebar ${menuOpen ? "open" : ""}`}>
        <Link href="/" className="brand" aria-label="Альфа-Бизнес, главная">
          <AlfaMark size={34} />
          <span className="brand-text">Альфа-Бизнес</span>
        </Link>
        <nav className="nav">
          {NAV.map((item, i) => {
            if (item === "divider") return <hr key={`d${i}`} className="nav-divider" />;
            const inner = (
              <>
                <Icon name={item.icon} size={20} /> <span className="nav-label">{item.label}</span>
                {item.badge && <span className="nav-badge">{item.badge}</span>}
              </>
            );
            return item.disabled ? (
              <span key={item.href} className="nav-item disabled" title="Раздел интернет-банка, не входит в прототип">{inner}</span>
            ) : (
              <Link key={item.href} href={item.href} className={`nav-item ${active(item.href) ? "active" : ""} ${item.accent ? "accent" : ""}`}>{inner}</Link>
            );
          })}
        </nav>
      </aside>
      {menuOpen && <div className="scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" />}

      <div className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setMenuOpen((v) => !v)} aria-label="Меню">
            <Icon name="menu" />
          </button>
          <div className="topbar-right">
            {session.memberships.length > 0 && <Notifications />}
            <CompanySwitcher />
            <Link href="/profile" className="user-pill" aria-label={`Профиль: ${session.userName}`}>
              <span className="avatar">{session.userName.slice(0, 1)}</span>
              <span className="user-name">{session.userName}</span>
            </Link>
            <button className="icon-btn" onClick={async () => { await logout(); router.replace("/login"); }} aria-label="Выйти" title="Выйти">
              <Icon name="logout" size={20} />
            </button>
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
