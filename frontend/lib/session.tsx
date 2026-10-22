"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { Role } from "./types";

export const ROLE_NAMES: Record<Role, string> = {
  owner: "Собственник",
  ceo: "Генеральный директор",
  cfo: "Финансовый директор",
  accountant: "Главный бухгалтер",
  treasurer: "Руководитель казначейства",
  clevel: "Другой C-level",
};

export interface CompanyRef {
  id: string;
  name: string;
}

export interface Session {
  userName: string;
  role: Role;
  companyId: string;
  companyName: string;
  /** Организации, к которым у пользователя есть доступ в интернет-банке (авторизация привязана к человеку). */
  companies?: CompanyRef[];
}

interface Ctx {
  session: Session | null;
  ready: boolean;
  login: (s: Session) => void;
  logout: () => void;
  update: (patch: Partial<Session>) => void;
}

const SessionContext = createContext<Ctx | null>(null);
const KEY = "alfa-pulse-session";

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) setSession(JSON.parse(raw));
    } catch {
      /* приватный режим или поврежденные данные — начинаем без сессии */
    }
    setReady(true);
  }, []);

  const persist = useCallback((s: Session | null) => {
    setSession(s);
    try {
      if (s) localStorage.setItem(KEY, JSON.stringify(s));
      else localStorage.removeItem(KEY);
    } catch {
      /* хранилище недоступно — сессия живет до перезагрузки */
    }
  }, []);

  return (
    <SessionContext.Provider
      value={{
        session,
        ready,
        login: persist,
        logout: () => persist(null),
        update: (patch) => session && persist({ ...session, ...patch }),
      }}
    >
      {children}
    </SessionContext.Provider>
  );
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
