"use client";

import { useCallback, useEffect, useState } from "react";

/** Прочитанные уведомления хранятся на устройстве отдельно для каждого пользователя и компании. */
const key = (userId: string, companyId: string) => `alfa-pulse-read:${userId}:${companyId}`;
const EVENT = "alfa-pulse-read-change";
const MAX_STORED = 500;

function load(userId: string, companyId: string): string[] {
  try {
    const raw = localStorage.getItem(key(userId, companyId));
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function markRead(userId: string, companyId: string, ids: string[]): void {
  const next = Array.from(new Set([...load(userId, companyId), ...ids])).slice(-MAX_STORED);
  try {
    localStorage.setItem(key(userId, companyId), JSON.stringify(next));
  } catch {
    /* хранилище недоступно — отметка живет до перезагрузки */
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: { userId, companyId, ids } }));
}

/** Набор прочитанных id и функции отметки; синхронизируется между вкладками и компонентами. */
export function useRead(userId: string, companyId: string) {
  const [read, setRead] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    const sync = () => setRead(new Set(load(userId, companyId)));
    sync();
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, [userId, companyId]);

  const mark = useCallback((ids: string[]) => markRead(userId, companyId, ids), [userId, companyId]);
  return { read, mark };
}
