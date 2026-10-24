"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useLoad } from "@/lib/hooks";
import type { AISettings } from "@/lib/types";
import { ErrorState, Icon, Skeleton } from "./ui";
import styles from "@/components/AISettingsCard.module.scss";
import common from "@/styles/common.module.scss";

const MIN = 40, MAX = 95, STEP = 5;

function hint(threshold: number): string {
  if (threshold >= 85) return "только самые важные события — меньше расход AI";
  if (threshold >= 70) return "важные события — баланс скорости и расхода";
  return "большинство событий ленты — больше разборов готово сразу";
}

/** «AI-разборы заранее»: конвейер готовит AI-версию разбора для новостей не ниже порога — разбор открывается сразу.
 *  Меняет администратор компании, остальные видят текущую настройку. */
export default function AISettingsCard({ companyId, companyName, isAdmin }: { companyId: string; companyName: string; isAdmin: boolean }) {
  const { data, error, reload } = useLoad((s) => api.aiSettings(companyId, s), [companyId]);
  const [draft, setDraft] = useState<{ for: AISettings; threshold: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const current = data && draft?.for === data ? draft.threshold : data?.threshold ?? 85;

  const save = async (enabled: boolean, threshold: number) => {
    setSaving(true);
    setSaveError(null);
    try {
      await api.saveAISettings(companyId, { enabled, threshold });
      reload();
    } catch (e) {
      setSaveError(e instanceof ApiError ? e.message : "Не удалось сохранить настройку");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className={common.card} aria-labelledby="ai-settings-title">
      <div className={common.cardHead}>
        <h2 id="ai-settings-title"><Icon name="spark" /> AI-разборы заранее</h2>
        <span className={`${common.muted} ${common.small}`}>{companyName}</span>
      </div>
      <p className={`${common.muted} ${common.small}`}>
        Важные новости разбираются AI-моделью сразу после появления — разбор открывается мгновенно, без ожидания.
      </p>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && !error && <Skeleton lines={2} />}
      {data && (
        <div className={styles.body}>
          <label className={styles.switchRow}>
            <span>
              <strong>Готовить заранее</strong>
              <small className={common.muted}>{data.enabled ? "Включено" : "Выключено — AI-разбор строится при открытии"}</small>
            </span>
            <input type="checkbox" role="switch" className={styles.switch} checked={data.enabled}
              disabled={!isAdmin || saving} onChange={(e) => save(e.target.checked, current)} />
          </label>
          <div className={`${styles.threshold} ${data.enabled ? "" : styles.dim}`}>
            <label htmlFor={`ai-threshold-${companyId}`}>
              <span>С какой важности</span>
              <strong>{current} из 100</strong>
            </label>
            <input id={`ai-threshold-${companyId}`} type="range" className={styles.range} min={MIN} max={MAX} step={STEP}
              value={current} disabled={!isAdmin || saving || !data.enabled}
              style={{ "--fill": `${((current - MIN) / (MAX - MIN)) * 100}%` } as React.CSSProperties}
              onChange={(e) => setDraft({ for: data, threshold: Number(e.target.value) })}
              onPointerUp={() => current !== data.threshold && save(true, current)}
              onKeyUp={() => current !== data.threshold && save(true, current)} />
            <div className={styles.scale}><span>{MIN}</span><span className={common.small}>{hint(current)}</span><span>{MAX}</span></div>
          </div>
          {!isAdmin && <p className={`${common.muted} ${common.small}`}>Изменить может администратор компании.</p>}
          {saveError && <p className={styles.error} role="alert">{saveError}</p>}
        </div>
      )}
    </section>
  );
}
