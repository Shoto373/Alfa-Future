"use client";

import { useState } from "react";

export default function PasswordField({
  id, label, value, onChange, error, autoComplete, hint,
}: { id: string; label: string; value: string; onChange: (v: string) => void; error?: string; autoComplete: string; hint?: string }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="pw-wrap">
        <input
          id={id} type={shown ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-err` : undefined}
        />
        <button type="button" className="btn btn-link btn-sm" onClick={() => setShown((v) => !v)} aria-pressed={shown}>
          {shown ? "Скрыть" : "Показать"}
        </button>
      </div>
      {hint && !error && <small className="muted">{hint}</small>}
      {error && <small id={`${id}-err`} className="field-error">{error}</small>}
    </div>
  );
}
