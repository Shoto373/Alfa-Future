"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ROLE_NAMES, useSession } from "@/lib/session";
import type { Role } from "@/lib/types";
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
  { href: "/pulse/quality", label: "Качество и аудит", icon: "shield" },
  "divider",
  { href: "#payment", label: "Новый платёж", icon: "plus", disabled: true },
  { href: "#operations", label: "Лента операций", icon: "mail", disabled: true },
  { href: "#statement", label: "Выписка", icon: "file", disabled: true },
  { href: "#accounts", label: "Счета", icon: "list", disabled: true },
  { href: "#counterparties", label: "Контрагенты", icon: "users", disabled: true },
  { href: "#cards", label: "Карты", icon: "card", disabled: true },
];

export default function Shell({ children }: { children: ReactNode }) {
  const { session, ready, logout, update } = useSession();
  const router = useRouter();
  const path = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (ready && !session) router.replace("/login");
  }, [ready, session, router]);

  useEffect(() => setMenuOpen(false), [path]);

  if (!ready || !session) {
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
        <div className="sidebar-foot">
          <span className="nav-item disabled"><Icon name="settings" size={20} /> Настроить меню</span>
          <p className="sidebar-note">Прототип хакатона. Данные компаний обезличены, это не действующий интернет-банк.</p>
        </div>
      </aside>
      {menuOpen && <div className="scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" />}

      <div className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setMenuOpen((v) => !v)} aria-label="Меню">
            <Icon name="menu" />
          </button>
          <div className="topbar-right">
            <label className="role-select" title="Роль определяет, какие новости и действия в приоритете">
              <span className="sr-only">Роль</span>
              <select value={session.role} onChange={(e) => update({ role: e.target.value as Role })}>
                {(Object.keys(ROLE_NAMES) as Role[]).map((r) => (
                  <option key={r} value={r}>{ROLE_NAMES[r]}</option>
                ))}
              </select>
            </label>
            <span className="icon-btn hide-sm" title="Письма банка — не входит в прототип" aria-hidden="true"><Icon name="mail" size={20} /></span>
            <Notifications />
            <CompanySwitcher />
            <div className="user-pill">
              <span className="avatar">{session.userName.slice(0, 1)}</span>
              <span className="user-name">{session.userName}</span>
            </div>
            <button className="icon-btn" onClick={() => { logout(); router.replace("/login"); }} aria-label="Выйти" title="Выйти">
              <Icon name="logout" size={20} />
            </button>
          </div>
        </header>
        <main className="content">{children}</main>
      </div>

      <Link href="/pulse" className={`fab ${path.startsWith("/pulse") ? "hidden" : ""}`} aria-label="Открыть Альфа.Пульс" title="Альфа.Пульс">
        <Icon name="pulse" size={24} />
      </Link>
    </div>
  );
}
