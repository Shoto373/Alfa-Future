"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, api } from "./api";
import { invalidate } from "./query";
import type { Membership, Role, User } from "./types";

export const ROLE_NAMES: Record<Role, string> = {
  owner: "Собственник",
  ceo: "Генеральный директор",
  cfo: "Финансовый директор",
  accountant: "Главный бухгалтер",
  treasurer: "Руководитель казначейства",
  clevel: "Другой C-level",
};

export interface Session {
  user: User;
  userName: string;
  memberships: Membership[];
  /** Активная компания (UI-предпочтение, проверенное по членству); пустая строка, если компаний нет. */
  companyId: string;
  companyName: string;
  /** Роль в активной компании (приходит из членства, на клиенте только читается). */
  role: Role;
  isAdmin: boolean;
}

interface Ctx {
  session: Session | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (name: string, email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  refresh: () => Promise<User | null>;
  setActiveCompany: (id: string) => void;
}

const SessionContext = createContext<Ctx | null>(null);
const ACTIVE_KEY = "alfa-pulse-active-company";

function readActive(): string | null {
  try {
    return localStorage.getItem(ACTIVE_KEY);
  } catch {
    return null;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    // Выбранная компания из localStorage — вместе с ответом сервера: до него интерфейс ее не показывает.
    api.me()
      .then((u) => { setActiveId(readActive()); setUser(u); })
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401)) console.warn("auth/me failed", e);
        setActiveId(readActive());
        setUser(null);
      })
      .finally(() => setReady(true));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const u = await api.me();
      setUser(u);
      return u;
    } catch {
      setUser(null);
      return null;
    }
  }, []);

  // Смена пользователя сбрасывает кэш ответов: данные прежнего пользователя не показываются следующему.
  const login = useCallback(async (email: string, password: string) => {
    const u = await api.login(email, password);
    invalidate();
    setUser(u);
    return u;
  }, []);

  const register = useCallback(async (name: string, email: string, password: string) => {
    const u = await api.register(name, email, password);
    invalidate();
    setUser(u);
    return u;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* cookie истечет сама; локально выходим в любом случае */
    }
    invalidate();
    setUser(null);
  }, []);

  const setActiveCompany = useCallback((id: string) => {
    setActiveId(id);
    try {
      localStorage.setItem(ACTIVE_KEY, id);
    } catch {
      /* только UI-предпочтение */
    }
  }, []);

  const session = useMemo<Session | null>(() => {
    if (!user) return null;
    const active = user.memberships.find((m) => m.company_id === activeId) ?? user.memberships[0] ?? null;
    return {
      user,
      userName: user.name,
      memberships: user.memberships,
      companyId: active?.company_id ?? "",
      companyName: active?.company_name ?? "",
      role: active?.role ?? "clevel",
      isAdmin: active?.is_admin ?? false,
    };
  }, [user, activeId]);

  const value = useMemo(
    () => ({ session, ready, login, register, logout, refresh, setActiveCompany }),
    [session, ready, login, register, logout, refresh, setActiveCompany],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

/** Короткое имя для шапки: «Анна Морозова» → «Морозова А.». */
export function shortName(full: string): string {
  const [first, last] = full.split(" ");
  return last ? `${last} ${first[0]}.` : full;
}

export function useSession(): Ctx {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("SessionProvider missing");
  return ctx;
}
