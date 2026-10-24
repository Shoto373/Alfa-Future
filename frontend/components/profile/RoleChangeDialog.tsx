"use client";

import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { errorText } from "@/lib/errors";
import { ROLE_NAMES } from "@/lib/session";
import type { Member, Role } from "@/lib/types";
import styles from "@/app/(bank)/profile/page.module.scss";
import common from "@/styles/common.module.scss";
import ui from "@/components/ui.module.scss";

export type RoleChange = { member: Member; role: Role };

/** Подтверждение смены роли; фокус возвращается на выпадающий список, из которого диалог открыли. */
export default function RoleChangeDialog({ change, focusTarget, onConfirm, onCancel }: {
  change: RoleChange;
  focusTarget: RefObject<HTMLSelectElement | null>;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const element = dialog.current!;
    const returnFocus = focusTarget.current;
    const previousOverflow = document.body.style.overflow;
    element.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      element.close();
      document.body.style.overflow = previousOverflow;
      returnFocus?.focus({ preventScroll: true });
    };
  }, [focusTarget]);

  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <dialog ref={dialog} className={styles.roleDialog} aria-labelledby={titleId} aria-describedby={descriptionId}
      aria-modal="true" aria-busy={busy}
      onCancel={(event) => { event.preventDefault(); if (!busy) onCancel(); }}
      onClick={(event) => {
        if (event.target !== event.currentTarget || busy) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onCancel();
      }}>
      <div className={styles.roleDialogContent}>
        <h2 id={titleId}>Изменить роль участника?</h2>
        <p id={descriptionId} className={styles.roleDialogDescription}>
          Вы уверены, что хотите изменить роль пользователя <strong>{change.member.name ?? change.member.email}</strong> на «{ROLE_NAMES[change.role]}»?
        </p>
        <dl className={styles.roleChangeSummary}>
          <div><dt>Текущая роль</dt><dd>{ROLE_NAMES[change.member.role]}</dd></div>
          <div><dt>Новая роль</dt><dd>{ROLE_NAMES[change.role]}</dd></div>
        </dl>
        {error && <p className={ui.errorText} role="alert">{error}</p>}
        <div className={styles.roleDialogActions}>
          <button type="button" className={`${common.btn} ${common.btnSecondary}`} autoFocus disabled={busy} onClick={onCancel}>Отмена</button>
          <button type="button" className={`${common.btn} ${common.btnPrimary}`} disabled={busy} onClick={confirm}>
            {busy ? "Сохраняем…" : "Изменить роль"}
          </button>
        </div>
      </div>
    </dialog>
  );
}
