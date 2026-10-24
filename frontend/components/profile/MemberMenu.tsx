"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import type { Member } from "@/lib/types";
import { Icon } from "../ui";
import styles from "@/app/(bank)/profile/page.module.scss";

/** Меню действий с участником: стрелки, Home/End и Esc — как у системного меню. */
export default function MemberMenu({ member, busy, onToggleAdmin, onRemove }: {
  member: Member;
  busy: boolean;
  onToggleAdmin: () => void;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const name = member.name ?? member.email;

  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const close = (event: PointerEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const navigate = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Tab") {
      setOpen(false);
      trigger.current?.focus();
      return;
    }
    const buttons = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>("button") ?? []);
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === "ArrowDown" ? (index + 1) % buttons.length
      : event.key === "ArrowUp" ? (index - 1 + buttons.length) % buttons.length
      : event.key === "Home" ? 0
      : event.key === "End" ? buttons.length - 1 : null;
    if (next !== null) {
      event.preventDefault();
      buttons[next]?.focus();
    }
  };

  const run = (action: () => void) => {
    setOpen(false);
    trigger.current?.focus();
    action();
  };

  return (
    <div className={styles.memberActions} ref={box}>
      <button ref={trigger} type="button" className={styles.iconBtn} disabled={busy}
        aria-label={`Действия с участником: ${name}`} aria-haspopup="menu" aria-expanded={open}
        aria-controls={open ? menuId : undefined} onClick={() => setOpen((value) => !value)}>
        <Icon name="more" size={20} />
      </button>
      {open && (
        <div ref={menu} id={menuId} className={`${styles.companyMenuPop} ${styles.memberMenuPop}`}
          role="menu" aria-label={`Действия с участником: ${name}`} onKeyDown={navigate}>
          <button type="button" role="menuitem" className={styles.menuItem} onClick={() => run(onToggleAdmin)}>
            {member.is_admin ? "Снять админа" : "Сделать админом"}
          </button>
          <button type="button" role="menuitem" className={`${styles.menuItem} ${styles.dangerItem}`} onClick={() => run(onRemove)}>
            Удалить
          </button>
        </div>
      )}
    </div>
  );
}
