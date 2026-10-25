"use client";

import { useState, type CSSProperties } from "react";
import { ErrorState, Skeleton } from "@/components/ui";
import TimeField from "@/components/TimeField";
import { api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { useLoad } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { NotificationSettings } from "@/lib/types";
import styles from "@/components/NotificationSettings.module.scss";
import common from "@/styles/common.module.scss";

type Draft = Omit<NotificationSettings, "company_id">;

const CHANNELS: { key: keyof Draft["channels"]; label: string; hint: string }[] = [
  { key: "inapp", label: "В приложении", hint: "колокольчик в шапке" },
  { key: "email", label: "Почта", hint: "на адрес входа; в теме письма нет данных компании" },
];

/** Уведомления (SPR4-04): утренняя сводка, мгновенные алерты, тихие часы и каналы — для каждой компании отдельно. Живут в профиле. */
export default function NotificationSettings() {
  const { session } = useSession();
  const companyId = session!.companyId;
  const settings = useLoad((s) => api.notificationSettings(companyId, s), [companyId]);
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
    <section id="notifications" className={styles.section} aria-label="Уведомления">
      <h2>Уведомления · {session!.companyName}</h2>
      <p className={styles.lead}>Утренняя сводка и алерты по важным событиям. Дубли из разных источников приходят одним сообщением.</p>
      {settings.error && <ErrorState error={settings.error} onRetry={settings.reload} />}
      {!value && !settings.error && <Skeleton lines={8} />}
      {value && (
        <form className={styles.form} onSubmit={(e) => { e.preventDefault(); save(); }}>
          <h3 className={styles.caption}>Утренняя сводка</h3>
          <div className={styles.group}>
            <label className={styles.row}>
              <span className={styles.text}><b>Присылать каждый день</b><small>3–5 главных событий компании</small></span>
              <input className={styles.switch} type="checkbox" role="switch" checked={value.digest}
                onChange={(e) => set({ digest: e.target.checked })} />
            </label>
            <div className={styles.row}>
              <label className={styles.text} htmlFor="ns-time"><b>Время</b><small>Когда прислать сводку</small></label>
              <TimeField id="ns-time" aria-label="Время сводки" value={value.digest_time} disabled={!value.digest}
                onChange={(v) => set({ digest_time: v })} />
            </div>
          </div>

          <h3 className={styles.caption}>Мгновенные алерты</h3>
          <div className={styles.group}>
            <div className={styles.row}>
              <label className={styles.text} htmlFor="ns-threshold"><b>Порог важности</b>
                <small>Днем приходит только то, что выше порога</small></label>
              <div className={styles.slider}>
                <input id="ns-threshold" className={styles.range} type="range" min={50} max={100} step={5} value={value.threshold}
                  aria-label="Порог важности" style={{ "--fill": `${(value.threshold - 50) * 2}%` } as CSSProperties}
                  onChange={(e) => set({ threshold: Number(e.target.value) })} />
                <span className={styles.pill}>{value.threshold} из 100</span>
              </div>
            </div>
            <div className={styles.row} role="group" aria-labelledby="ns-quiet">
              <span className={styles.text} id="ns-quiet"><b>Тихие часы</b><small>В это время алерты не приходят</small></span>
              <div className={styles.range2}>
                <div className={styles.inline}>с
                  <TimeField aria-label="Тихие часы с" value={value.quiet_from} onChange={(v) => set({ quiet_from: v })} />
                </div>
                <div className={styles.inline}>до
                  <TimeField aria-label="Тихие часы до" value={value.quiet_to} onChange={(v) => set({ quiet_to: v })} />
                </div>
              </div>
            </div>
          </div>

          <h3 className={styles.caption}>Каналы</h3>
          <div className={styles.group}>
            {CHANNELS.map((c) => (
              <label key={c.key} className={styles.row}>
                <span className={styles.text}><b>{c.label}</b><small>{c.hint}</small></span>
                <input className={styles.switch} type="checkbox" role="switch" checked={value.channels[c.key]}
                  onChange={(e) => set({ channels: { ...value.channels, [c.key]: e.target.checked } })} />
              </label>
            ))}
          </div>

          <div className={styles.actions}>
            <button type="submit" className={`${common.btn} ${common.btnPrimary}`} disabled={busy}>Сохранить</button>
            <button type="button" className={`${common.btn} ${common.btnSecondary}`} disabled={busy} onClick={test}>
              Отправить тестовую сводку</button>
            {status && <p role="status" className={`${common.small} ${styles.status}`}>{status}</p>}
          </div>
        </form>
      )}
    </section>
  );
}
