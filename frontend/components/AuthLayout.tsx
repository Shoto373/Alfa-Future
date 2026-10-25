import type { ReactNode } from "react";
import { AlfaMark } from "./ui";
import styles from "@/components/AuthLayout.module.scss";
import common from "@/styles/common.module.scss";

/** Общая рамка входа и регистрации: бренд-панель слева, форма справа. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className={styles.login}>
      <section className={styles.loginHero}>
        {/* Плавающее красное свечение: три размытых круга с разными траекториями и «дыханием». */}
        <span className={styles.orb} aria-hidden="true" />
        <span className={styles.orbSmall} aria-hidden="true" />
        <span className={styles.orbThird} aria-hidden="true" />
        <div className={common.brand}>
          <AlfaMark size={40} />
          <span className={common.brandText}>Альфа-Бизнес</span>
        </div>
        <div className={styles.loginHeroText}>
          {/* Линия пульса: по ней бежит световой импульс. */}
          <svg viewBox="0 0 520 90" className={styles.pulseLine} aria-hidden="true">
            <defs>
              <filter id="login-glow" x="-10%" y="-60%" width="120%" height="220%"><feGaussianBlur stdDeviation="4" /></filter>
              <path id="login-pulse" pathLength="100"
                d="M0 58H150c6 0 8-8 12-8s6 8 12 8h10l12-48c2-6 6-6 7 0l14 76c2 6 6 6 7 0l9-38c2-5 5-5 6 0l4 10h249" />
            </defs>
            <use href="#login-pulse" className={styles.pulseBase} />
            <use href="#login-pulse" className={styles.pulseGlow} filter="url(#login-glow)" />
            <use href="#login-pulse" className={styles.pulseRun} />
          </svg>
          <h1>Альфа.Пульс</h1>
          <p>Новости и аналитика Альфа-Банка, разобранные под вашу компанию и роль: что произошло, почему это важно, риски, возможности и что делать.</p>
        </div>
        <p className={styles.loginHeroFoot}>Прототип. Данные компаний обезличены.</p>
      </section>
      <section className={styles.loginPanel}>{children}</section>
    </div>
  );
}
