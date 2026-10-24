"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import AuthLayout from "@/components/AuthLayout";
import PasswordField from "@/components/PasswordField";
import { ErrorState } from "@/components/ui";
import { errorText } from "@/lib/errors";
import { useSession } from "@/lib/session";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";

type Errors = Partial<Record<"name" | "email" | "password" | "confirm", string>>;

export default function RegisterPage() {
  const { register } = useSession();
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const validate = (): Errors => {
    const e: Errors = {};
    if (name.trim().length < 2) e.name = "Укажите имя и фамилию.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) e.email = "Введите корректный email.";
    if (password.length < 8) e.password = "Пароль — не короче 8 символов.";
    else if (password.length > 128) e.password = "Пароль — не длиннее 128 символов.";
    if (confirm !== password) e.confirm = "Пароли не совпадают.";
    return e;
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    const e = validate();
    setErrors(e);
    setError(null);
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      const user = await register(name.trim(), email.trim(), password);
      router.replace(user.memberships.length ? "/" : "/company/register");
    } catch (err) {
      setError(errorText(err, "Не удалось зарегистрироваться. Повторите попытку."));
      setBusy(false);
    }
  };

  return (
    <AuthLayout>
      <h2>Регистрация</h2>
      <p className={common.muted}>Создайте аккаунт. Компанию вы добавите на следующем шаге.</p>
      <form className={forms.form} onSubmit={submit} noValidate>
        {error && <ErrorState error={error} />}
        <div className={forms.field}>
          <label htmlFor="name">Имя и фамилия</label>
          <input className={forms.input} id="name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)}
            aria-invalid={Boolean(errors.name)} aria-describedby={errors.name ? "name-err" : undefined} />
          {errors.name && <small id="name-err" className={forms.fieldError}>{errors.name}</small>}
        </div>
        <div className={forms.field}>
          <label htmlFor="email">Email</label>
          <input className={forms.input} id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)}
            aria-invalid={Boolean(errors.email)} aria-describedby={errors.email ? "email-err" : undefined} />
          {errors.email && <small id="email-err" className={forms.fieldError}>{errors.email}</small>}
        </div>
        <PasswordField id="password" label="Пароль" value={password} onChange={setPassword} autoComplete="new-password"
          error={errors.password} hint="От 8 до 128 символов." />
        <PasswordField id="confirm" label="Повторите пароль" value={confirm} onChange={setConfirm} autoComplete="new-password" error={errors.confirm} />
        <button type="submit" className={`${common.btn} ${common.btnPrimary}`} disabled={busy}>{busy ? "Создаём…" : "Зарегистрироваться"}</button>
      </form>
      <p className={`${common.muted} ${common.small}`}>Уже есть аккаунт? <Link href="/login">Войти</Link></p>
    </AuthLayout>
  );
}
