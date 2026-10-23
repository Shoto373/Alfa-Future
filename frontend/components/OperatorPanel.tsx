"use client";

// Блок «Сервис банка» в профиле — только для сотрудников банка (OPERATOR_EMAILS):
// выключатель AI без удаления ключа с сервера и расход общего дневного бюджета.
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { LLMSwitch } from "@/lib/types";
import { Icon } from "./ui";
import styles from "@/components/OperatorPanel.module.scss";
import common from "@/styles/common.module.scss";

interface Budget {
  cost: number;
  cost_limit: number;
  reserved_cost: number;
  rejected_by_budget: number;
}

const rub = (v: number) => `${v.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;

export default function OperatorPanel() {
  const [state, setState] = useState<LLMSwitch | null>(null);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [sw, metrics] = await Promise.all([api.llmSwitch(), api.metrics()]);
      setState(sw);
      setBudget(metrics.ai?.llm_usage ?? null);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось загрузить состояние AI");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const toggle = async (paused: boolean) => {
    setBusy(true);
    try {
      setState(await api.setLLMPaused(paused));
      setConfirming(false);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось переключить AI");
    } finally {
      setBusy(false);
    }
  };

  const status = !state ? null : state.paused
    ? { text: "AI выключен", note: state.by ? `выключил ${state.by}` : null, className: styles.off }
    : state.connected
      ? { text: "AI включен", note: null, className: styles.on }
      : { text: "AI не подключен", note: "ключ модели не задан на сервере — разборы строятся правилами", className: styles.idle };
  const share = budget && budget.cost_limit ? Math.min(100, Math.round(((budget.cost + budget.reserved_cost) / budget.cost_limit) * 100)) : 0;

  return (
    <section className={common.card} aria-labelledby="operator-panel-title">
      <div className={common.cardHead}>
        <h2 id="operator-panel-title"><Icon name="bank" /> Сервис банка</h2>
        <span className={`${common.muted} ${common.small}`}>Видно только сотрудникам банка</span>
      </div>

      {error && <p className={styles.error} role="alert">{error}</p>}

      {status && (
        <div className={styles.row}>
          <div>
            <span className={`${styles.status} ${status.className}`}>{status.text}</span>
            {status.note && <span className={`${common.muted} ${common.small}`}> {status.note}</span>}
          </div>
          {!state!.paused && !confirming && (
            <button className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} onClick={() => setConfirming(true)} disabled={busy}>
              Выключить AI
            </button>
          )}
          {state!.paused && (
            <button className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`} onClick={() => toggle(false)} disabled={busy}>
              {busy ? "Включаем…" : "Включить AI"}
            </button>
          )}
        </div>
      )}

      {confirming && (
        <div className={styles.confirm} role="alertdialog" aria-labelledby="operator-confirm">
          <p id="operator-confirm">
            Выключить AI для всех клиентов? Разборы будут строиться правилами, в карточках — «AI временно выключен банком».
            Ключ остается на сервере, включить можно в любой момент.
          </p>
          <div className={styles.actions}>
            <button className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`} onClick={() => toggle(true)} disabled={busy} autoFocus>
              {busy ? "Выключаем…" : "Да, выключить"}
            </button>
            <button className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} onClick={() => setConfirming(false)} disabled={busy}>
              Отмена
            </button>
          </div>
        </div>
      )}

      {budget && (
        <div className={styles.budget}>
          <div className={styles.budgetHead}>
            <span>Бюджет AI сегодня</span>
            <strong>{rub(budget.cost)} из {rub(budget.cost_limit)}</strong>
          </div>
          <div className={styles.bar} role="progressbar" aria-valuenow={share} aria-valuemin={0} aria-valuemax={100}
            aria-label="Доля дневного бюджета AI, включая идущие запросы">
            <span style={{ width: `${share}%` }} className={share >= 80 ? styles.barHigh : undefined} />
          </div>
          <p className={`${common.muted} ${common.small}`}>
            Сейчас зарезервировано {rub(budget.reserved_cost)} · отклонено по бюджету: {budget.rejected_by_budget}.
            Обновляется в 03:00 по Москве.
          </p>
        </div>
      )}
    </section>
  );
}
