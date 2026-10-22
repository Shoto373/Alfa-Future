import type { ReactNode } from "react";
import { AlfaMark } from "./ui";

/** Общая рамка входа и регистрации: бренд-панель слева, форма справа. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="login">
      <section className="login-hero">
        <div className="brand">
          <AlfaMark size={40} />
          <span className="brand-text">Альфа-Бизнес</span>
        </div>
        <div className="login-hero-text">
          <h1>Альфа.Пульс</h1>
          <p>Новости и аналитика Альфа-Банка, разобранные под вашу компанию и роль: что произошло, почему это важно, риски, возможности и что делать.</p>
        </div>
        <p className="login-hero-foot">Прототип. Данные компаний обезличены.</p>
      </section>
      <section className="login-panel">{children}</section>
    </div>
  );
}
