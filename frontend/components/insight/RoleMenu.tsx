"use client";

import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { ROLE_NAMES } from "@/lib/session";
import type { Role } from "@/lib/types";
import { Icon } from "../ui";
import styles from "@/components/InsightView.module.scss";

/** Выбор роли для «другого разреза»: таблетка в стиле кнопок шапки и аккуратное меню. */
export default function RoleMenu({ value, own, disabled, onChange }: { value: Role; own?: Role; disabled?: boolean; onChange: (r: Role) => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const roles = Object.keys(ROLE_NAMES) as Role[];

  useEffect(() => {
    if (!open) return;
    box.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
    const close = (e: PointerEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  const move = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const items = Array.from(box.current?.querySelectorAll<HTMLButtonElement>("[role=menuitemradio]") ?? []);
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
  };

  return (
    <div className={styles.roleMenu} ref={box}>
      <button type="button" className={styles.perspective} disabled={disabled} aria-haspopup="menu" aria-expanded={open}
        title="Тот же разбор с точки зрения другой роли в компании" onClick={() => setOpen((o) => !o)}>
        <Icon name="eye" size={16} />
        <span>{ROLE_NAMES[value]}</span>
        <Icon name="chevron" size={16} />
      </button>
      {open && (
        <div className={styles.roleMenuPop} role="menu" aria-label="Глазами роли" onKeyDown={move}>
          <div className={styles.roleMenuHead}>Посмотреть глазами</div>
          {roles.map((r) => (
            <button key={r} type="button" role="menuitemradio" aria-checked={r === value}
              className={`${styles.roleMenuItem} ${r === value ? styles.roleMenuOn : ""}`}
              onClick={() => { setOpen(false); if (r !== value) onChange(r); }}>
              <span>{ROLE_NAMES[r]}</span>
              {r === own && <span className={styles.roleMenuYou}>вы</span>}
              {r === value && <Icon name="check" size={16} />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
