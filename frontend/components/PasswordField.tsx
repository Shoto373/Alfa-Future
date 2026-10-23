"use client";

import { useState } from "react";
import forms from "@/styles/forms.module.scss";
import styles from "@/components/PasswordField.module.scss";
import common from "@/styles/common.module.scss";

export default function PasswordField({
  id, label, value, onChange, error, autoComplete, hint,
}: { id: string; label: string; value: string; onChange: (v: string) => void; error?: string; autoComplete: string; hint?: string }) {
  const [shown, setShown] = useState(false);
  return (
    <div className={forms.field}>
      <label htmlFor={id}>{label}</label>
      <div className={styles.pwWrap}>
        <input className={forms.input}
          id={id} type={shown ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-err` : undefined}
        />
        <button type="button" className={`${styles.btn} ${common.btnLink} ${common.btnSm}`} onClick={() => setShown((v) => !v)} aria-pressed={shown}>
          {shown ? "Скрыть" : "Показать"}
        </button>
      </div>
      {hint && !error && <small className={common.muted}>{hint}</small>}
      {error && <small id={`${id}-err`} className={forms.fieldError}>{error}</small>}
    </div>
  );
}
