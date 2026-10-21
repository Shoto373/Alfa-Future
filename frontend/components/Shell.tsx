"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ROLE_NAMES, useSession } from "@/lib/session";
import type { Role } from "@/lib/types";
import CompanySwitcher from "./CompanySwitcher";
import { Icon } from "./ui";

const NAV = [
  { href: "/", label: "Главная", icon: "home" },
  { href: "/pulse", label: "Альфа.Пульс", icon: "pulse", accent: true },
  { href: "/pulse/analytics", label: "Аналитика банка", icon: "doc" },
  { href: "/pulse/quality", label: "Качество и аудит", icon: "check" },
  { href: "#accounts", label: "Счета и выписки", icon: "wallet", disabled: true },
  { href: "#payments", label: "Платежи", icon: "send", disabled: true },
  { href: "#credit", label: "Кредиты и гарантии", icon: "credit", disabled: true },
  { href: "#fx", label: "ВЭД и валюта", icon: "globe", disabled: true },
] as const;

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
          <span className="brand-mark">А</span>
          <span className="brand-text">Альфа-Бизнес<small>демо-стенд хакатона</small></span>
        </Link>
        <nav className="nav">
          {NAV.map((item) =>
            "disabled" in item && item.disabled ? (
              <span key={item.href} className="nav-item disabled" title="Не входит в прототип">
                <Icon name={item.icon} /> {item.label}
              </span>
            ) : (
              <Link key={item.href} href={item.href} className={`nav-item ${active(item.href) ? "active" : ""} ${"accent" in item ? "accent" : ""}`}>
                <Icon name={item.icon} /> {item.label}
                {"accent" in item && <span className="nav-badge">AI</span>}
              </Link>
            ),
          )}
        </nav>
        <div className="sidebar-note">Прототип. Данные компаний обезличены, это не действующий интернет-банк.</div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setMenuOpen((v) => !v)} aria-label="Меню">
            <Icon name="menu" />
          </button>
          <CompanySwitcher />
          <div className="topbar-right">
            <label className="role-select">
              <span className="sr-only">Роль</span>
              <select value={session.role} onChange={(e) => update({ role: e.target.value as Role })}>
                {(Object.keys(ROLE_NAMES) as Role[]).map((r) => (
                  <option key={r} value={r}>{ROLE_NAMES[r]}</option>
                ))}
              </select>
            </label>
            <div className="user">
              <span className="avatar">{session.userName.slice(0, 1)}</span>
              <span className="user-name">{session.userName}</span>
            </div>
            <button className="icon-btn" onClick={() => { logout(); router.replace("/login"); }} aria-label="Выйти" title="Выйти">
              <Icon name="logout" />
            </button>
          </div>
        </header>
        <main className="content">{children}</main>
      </div>

      <Link href="/pulse" className={`fab ${path.startsWith("/pulse") ? "hidden" : ""}`} aria-label="Открыть Альфа.Пульс">
        <Icon name="pulse" /> Альфа.Пульс
      </Link>
    </div>
  );
}
