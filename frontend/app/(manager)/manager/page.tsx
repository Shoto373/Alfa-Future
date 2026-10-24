"use client";

import { useState } from "react";
import { Card, EmptyState, ErrorState, Icon, Score, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { date, money } from "@/lib/format";
import { useLoad } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Lead } from "@/lib/types";
import styles from "@/app/(manager)/manager/page.module.scss";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";

const STATUSES: { value: Lead["status"]; label: string }[] = [
  { value: "new", label: "Новая" }, { value: "in_progress", label: "В работе" },
  { value: "done", label: "Обсуждено" }, { value: "declined", label: "Закрыта" },
];
const WINDOWS = [{ hours: 24, label: "Сегодня" }, { hours: 24 * 7, label: "Неделя" }, { hours: 24 * 30, label: "Месяц" }];

/** Кабинет менеджера (SPR4-06): свои клиенты, затронутые событиями, по приоритету и заявки «обсудить с менеджером». */
export default function ManagerPage() {
  const { session } = useSession();
  const [hours, setHours] = useState(24);
  const clients = useLoad((s) => api.managerClients(hours, s), [hours]);
  const leads = useLoad((s) => api.managerLeads(s), []);
  const [error, setError] = useState<string | null>(null);

  if (!session!.user.is_manager) {
    return <div className={common.page}><EmptyState>Кабинет доступен менеджерам банка, за которыми закреплены клиенты.</EmptyState></div>;
  }
  const setStatus = async (id: number, status: Lead["status"]) => {
    setError(null);
    try {
      await api.managerLeadStatus(id, status);
      leads.reload();
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <div className={common.page}>
      <div className={common.pageHead}>
        <div>
          <span className={common.eyebrow}><Icon name="users" /> Кабинет менеджера</span>
          <h1>Клиенты и заявки</h1>
          <p className={common.muted}>Только ваши закрепленные клиенты. Заявки клиенты отправляют сами, с явным согласием на передачу
            новости, вывода разбора и предложения.</p>
        </div>
      </div>

      <Card title="Клиенты, затронутые событиями" actions={
        <div className={styles.windows} role="tablist" aria-label="Период">
          {WINDOWS.map((w) => <button key={w.hours} type="button" role="tab" aria-selected={hours === w.hours}
            className={hours === w.hours ? styles.on : undefined} onClick={() => setHours(w.hours)}>{w.label}</button>)}
        </div>}>
        {clients.error && <ErrorState error={clients.error} onRetry={clients.reload} />}
        {!clients.data && !clients.error && <Skeleton lines={4} />}
        {clients.data && (
          <>
            <p className={`${common.muted} ${common.small}`}>Приоритет: {clients.data.priority_formula}.</p>
            <ul className={styles.clients} data-testid="manager-clients">
              {clients.data.clients.map((c) => (
                <li key={c.company_id}>
                  <div className={styles.clientHead}>
                    <strong>{c.name}</strong>
                    <span className={common.muted}>{c.sector}{c.revenue ? ` · выручка ${money(c.revenue)}` : ""}</span>
                    <span className={styles.priority} title="Приоритет">{c.priority.toString().replace(".", ",")}</span>
                    {c.new_leads > 0 && <span className={styles.badge}>новых заявок: {c.new_leads}</span>}
                  </div>
                  {c.events.length === 0 ? <small className={common.muted}>Событий за период нет.</small> : (
                    <ul className={styles.events}>
                      {c.events.slice(0, 3).map((e) => (
                        <li key={e.news_id}><Score value={e.score} /> <span>{e.title}</span> <small className={common.muted}>{date(e.published_at)}</small></li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>

      <Card title="Заявки «обсудить с менеджером»" actions={
        <a className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} href={api.managerLeadsCsv()}>Выгрузить CSV</a>}>
        {leads.error && <ErrorState error={leads.error} onRetry={leads.reload} />}
        {!leads.data && !leads.error && <Skeleton lines={3} />}
        {leads.data && (leads.data.items.length === 0 ? <EmptyState>Заявок пока нет.</EmptyState> : (
          <ul className={styles.leads} data-testid="manager-leads">
            {leads.data.items.map((l) => (
              <li key={l.id}>
                <div className={styles.clientHead}>
                  <strong>{l.offer_title}</strong>
                  <span className={common.muted}>{l.company_name} · {l.contact_name}{l.contact_email ? `, ${l.contact_email}` : ""} · {date(l.created_at)}</span>
                  <select className={forms.select} value={l.status} aria-label={`Статус заявки ${l.id}`}
                    onChange={(e) => setStatus(l.id, e.target.value as Lead["status"])}>
                    {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                  </select>
                </div>
                <p><b>Повод:</b> {l.news_title}</p>
                <p><b>Вывод разбора:</b> {l.headline}</p>
                <p><b>Потребность:</b> {l.need}{l.reason ? ` — ${l.reason}` : ""}</p>
                {l.comment && <p><b>Комментарий клиента:</b> {l.comment}</p>}
              </li>
            ))}
          </ul>
        ))}
        {error && <p role="alert" className={common.small}>{error}</p>}
      </Card>
    </div>
  );
}
