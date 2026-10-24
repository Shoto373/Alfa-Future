"use client";

import { useState } from "react";
import { Card, ErrorState, Icon, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { useLoad } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { NotificationSettings } from "@/lib/types";
import styles from "@/app/(bank)/settings/notifications/page.module.scss";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";

type Draft = Omit<NotificationSettings, "company_id">;

const ZONES = ["Europe/Kaliningrad", "Europe/Moscow", "Europe/Samara", "Asia/Yekaterinburg", "Asia/Omsk", "Asia/Novosibirsk",
  "Asia/Krasnoyarsk", "Asia/Irkutsk", "Asia/Yakutsk", "Asia/Vladivostok", "Asia/Magadan", "Asia/Kamchatka"];
const CHANNELS: { key: keyof Draft["channels"]; label: string; hint: string }[] = [
  { key: "inapp", label: "В приложении", hint: "колокольчик в шапке" },
  { key: "email", label: "Почта", hint: "на адрес входа; в теме письма нет данных компании" },
  { key: "telegram", label: "Telegram", hint: "скоро: бот подключается после пилота" },
];

/** Уведомления (SPR4-04): утренняя сводка, мгновенные алерты, тихие часы и каналы — для каждой компании отдельно. */
export default function NotificationSettingsPage() {
  const { session } = useSession();
  const companyId = session!.companyId;
  const settings = useLoad((s) => api.notificationSettings(companyId, s), [companyId]);
  const meta = useLoad((s) => api.meta(s), []);
  const [draft, setDraft] = useState<{ for: NotificationSettings; value: Draft } | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const data = settings.data;
  const value: Draft | null = data ? (draft?.for === data ? draft.value : data) : null;
  const set = (patch: Partial<Draft>) => data && value && setDraft({ for: data, value: { ...value, ...patch } });

  const run = async (action: () => Promise<string>) => {
    setBusy(true);
    setStatus(null);
    try {
      setStatus(await action());
    } catch (e) {
      setStatus(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const save = () => run(async () => {
    // Только поля настроек: значение из ответа сервера содержит еще company_id, а запрос принимает строгий набор полей.
    const v = value!;
    await api.saveNotificationSettings(companyId, {
      digest: v.digest, digest_time: v.digest_time, timezone: v.timezone, threshold: v.threshold, topics: v.topics,
      counterparties: v.counterparties, quiet_from: v.quiet_from, quiet_to: v.quiet_to, alerts_per_day: v.alerts_per_day,
      channels: v.channels,
    });
    settings.reload();
    return "Настройки сохранены";
  });
  const test = () => run(async () => {
    const r = await api.testDigest(companyId);
    return r.created ? `Тестовая сводка отправлена: ${r.channels.map((c) => CHANNELS.find((x) => x.key === c)?.label ?? c).join(", ")}`
      : "В ленте меньше трех событий — сводку не из чего собрать";
  });

  return (
    <div className={common.page}>
      <div className={common.pageHead}>
        <div>
          <span className={common.eyebrow}><Icon name="bell" /> Уведомления</span>
          <h1>Сводки и алерты · {session!.companyName}</h1>
          <p className={common.muted}>Утром — 3–5 главных событий для компании. Днем — только то, что выше вашего порога, не чаще лимита
            и не в тихие часы. Заметки об одном событии из разных источников приходят одним сообщением.</p>
        </div>
      </div>
      {settings.error && <ErrorState error={settings.error} onRetry={settings.reload} />}
      {!value && !settings.error && <Skeleton lines={8} />}
      {value && (
        <form className={styles.grid} onSubmit={(e) => { e.preventDefault(); save(); }}>
          <Card title="Утренняя сводка">
            <label className={forms.check}><input type="checkbox" checked={value.digest} onChange={(e) => set({ digest: e.target.checked })} />
              Присылать сводку каждый день</label>
            <div className={styles.row}>
              <label className={forms.field}>Время
                <input className={forms.input} type="time" value={value.digest_time} disabled={!value.digest}
                  onChange={(e) => set({ digest_time: e.target.value })} />
              </label>
              <label className={forms.field}>Часовой пояс
                <select className={forms.select} value={value.timezone} onChange={(e) => set({ timezone: e.target.value })}>
                  {(ZONES.includes(value.timezone) ? ZONES : [value.timezone, ...ZONES]).map((z) => <option key={z} value={z}>{z}</option>)}
                </select>
              </label>
            </div>
          </Card>
          <Card title="Мгновенные алерты">
            <label className={forms.field}>Порог важности: <b>{value.threshold} из 100</b>
              <input type="range" min={50} max={100} step={5} value={value.threshold} aria-label="Порог важности"
                onChange={(e) => set({ threshold: Number(e.target.value) })} />
            </label>
            <label className={forms.field}>Не больше алертов в сутки
              <input className={forms.input} type="number" min={0} max={10} value={value.alerts_per_day}
                onChange={(e) => set({ alerts_per_day: Math.max(0, Math.min(10, Number(e.target.value) || 0)) })} />
            </label>
            <label className={forms.check}><input type="checkbox" checked={value.counterparties}
              onChange={(e) => set({ counterparties: e.target.checked })} /> События у контрагентов (до второго уровня цепочки)</label>
            <div className={styles.row}>
              <label className={forms.field}>Тихие часы с
                <input className={forms.input} type="time" value={value.quiet_from} onChange={(e) => set({ quiet_from: e.target.value })} />
              </label>
              <label className={forms.field}>до
                <input className={forms.input} type="time" value={value.quiet_to} onChange={(e) => set({ quiet_to: e.target.value })} />
              </label>
            </div>
          </Card>
          <Card title="Темы">
            <p className={`${common.muted} ${common.small}`}>Ничего не выбрано — все темы ленты.</p>
            <div className={styles.topics}>
              {(meta.data?.topics ?? []).map((t) => (
                <label key={t.topic} className={forms.check}>
                  <input type="checkbox" checked={value.topics.includes(t.topic)} onChange={(e) => set({
                    topics: e.target.checked ? [...value.topics, t.topic] : value.topics.filter((x) => x !== t.topic) })} />
                  {t.name}
                </label>
              ))}
            </div>
          </Card>
          <Card title="Каналы">
            {CHANNELS.map((c) => (
              <label key={c.key} className={forms.check}>
                <input type="checkbox" checked={value.channels[c.key]} disabled={c.key === "telegram"}
                  onChange={(e) => set({ channels: { ...value.channels, [c.key]: e.target.checked } })} />
                {c.label} <small className={common.muted}>· {c.hint}</small>
              </label>
            ))}
          </Card>
          <div className={styles.actions}>
            <button type="submit" className={`${common.btn} ${common.btnPrimary}`} disabled={busy}>Сохранить</button>
            <button type="button" className={`${common.btn} ${common.btnSecondary}`} disabled={busy} onClick={test}>
              Отправить тестовую сводку</button>
            {status && <p role="status" className={common.small}>{status}</p>}
          </div>
        </form>
      )}
    </div>
  );
}
