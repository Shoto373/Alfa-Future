import type { ReactNode } from "react";
import { AlfaMark } from "./ui";
import styles from "@/components/AuthLayout.module.scss";
import common from "@/styles/common.module.scss";

/** Общая рамка входа и регистрации: бренд-панель слева, форма справа. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className={styles.login}>
      <section className={styles.loginHero}>
        {/* Плавающее красное свечение: два размытых круга с разными траекториями. */}
        <span className={styles.orb} aria-hidden="true" />
        <span className={styles.orbSmall} aria-hidden="true" />
        <div className={common.brand}>
          <AlfaMark size={40} />
          <span className={common.brandText}>Альфа-Бизнес</span>
        </div>
        <div className={styles.loginHeroText}>
          <h1>Альфа.Пульс</h1>
          <p>Новости и аналитика Альфа-Банка, разобранные под вашу компанию и роль: что произошло, почему это важно, риски, возможности и что делать.</p>
        </div>
        <p className={styles.loginHeroFoot}>Прототип. Данные компаний обезличены.</p>
      </section>
      <section className={styles.loginPanel}>{children}</section>
    </div>
  );
}
