"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import AuthLayout from "@/components/AuthLayout";
import PasswordField from "@/components/PasswordField";
import { errorText } from "@/lib/errors";
import { useSession } from "@/lib/session";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";
import ui from "@/components/ui.module.scss";

export default function LoginPage() {
  const { login } = useSession();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError("Введите email и пароль.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const user = await login(email.trim(), password);
      router.replace(user.memberships.length ? "/" : "/company/register");
    } catch (err) {
      setError(errorText(err, "Не удалось войти. Повторите попытку."));
      setBusy(false);
    }
  };

  return (
    <AuthLayout>
      <h2>Вход</h2>
      <p className={common.muted}>Войдите в свой аккаунт, чтобы увидеть ленту Альфа.Пульса для ваших компаний.</p>
      <form className={forms.form} onSubmit={submit} noValidate>
        {error && <div className={ui.errorBox} role="alert"><span>{error}</span></div>}
        <div className={forms.field}>
          <label htmlFor="email">Email</label>
          <input className={forms.input} id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={Boolean(error)} />
        </div>
        <PasswordField id="password" label="Пароль" value={password} onChange={setPassword} autoComplete="current-password" />
        <button type="submit" className={`${common.btn} ${common.btnPrimary}`} disabled={busy}>{busy ? "Входим…" : "Войти"}</button>
      </form>
      <p className={`${common.muted} ${common.small}`}>Нет аккаунта? <Link href="/register">Регистрация</Link></p>
    </AuthLayout>
  );
}
