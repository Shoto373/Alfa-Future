"use client";

import Link from "next/link";
import { useSession } from "@/lib/session";
import { Card, Icon } from "./ui";
import common from "@/styles/common.module.scss";
import styles from "@/components/Shell.module.scss";

/** Компания из ссылки или ответа сервера (403) недоступна пользователю: вместо пустой страницы — что произошло и что делать. */
export default function AccessDenied({ backHref = "/pulse" }: { backHref?: string }) {
  const { session } = useSession();
  return (
    <Card className={styles.denied}>
      <div role="alert">
        <Icon name="shield" size={32} />
        <h1>Нет доступа к компании</h1>
        <p className={common.muted}>
          Ссылка ведет на компанию, к которой ваш профиль не подключен. Данные других компаний недоступны —
          попросите администратора той компании пригласить вас.
        </p>
        {session?.companyId && (
          <Link href={backHref} className={`${common.btn} ${common.btnPrimary}`}>Открыть «{session.companyName}»</Link>
        )}
      </div>
    </Card>
  );
}
