import { useEffect, useState } from "react";

// Ход работы модели (SSE-событие progress, SPR4-03): положение индикатора выводится только из пришедших событий.
// Вес этапа — его типичная доля времени; пока этап идет, полоса стоит на месте, а не «ползет» по таймеру.

export type PhaseId = "collect" | "draft" | "check" | "review" | "finalize";

export const PHASES: { id: PhaseId; label: string; weight: number }[] = [
  { id: "collect", label: "Собираем данные компании и аналитику банка", weight: 15 },
  { id: "draft", label: "Составляем черновик", weight: 40 },
  { id: "check", label: "Проверяем факты и источники", weight: 15 },
  { id: "review", label: "Проверяем выводы AI по смыслу", weight: 20 },
  { id: "finalize", label: "Оформляем карточку", weight: 10 },
];
export const FIX_LABEL = "Исправляем и дополняем";

export type ProgressEvent = { stage: string; index: number; total: number; state: "start" | "done"; label?: string; step?: string };
export type ProgressState = { started: number; done: number; fixing: boolean };

export const emptyProgress: ProgressState = { started: 0, done: 0, fixing: false };

const indexOf = (stage: string) => PHASES.findIndex((p) => p.id === stage) + 1;

/** Новое состояние по событию. Этап считается завершенным по событию «done» или когда начался следующий. */
export function reduceProgress(s: ProgressState, ev: ProgressEvent): ProgressState {
  const i = indexOf(ev.stage);
  if (i === 0) return s;  // неизвестный этап (более новый сервер) — игнорируем
  if (ev.state === "done") return { started: Math.max(s.started, i), done: Math.max(s.done, i), fixing: ev.stage === "check" ? false : s.fixing };
  return {
    started: Math.max(s.started, i), done: Math.max(s.done, i - 1),
    fixing: ev.stage === "check" && ev.step === "fix" ? true : s.fixing && s.started === i,
  };
}

/** Доля готовности, %: только завершенные этапы. */
export function percent(s: ProgressState): number {
  return PHASES.slice(0, s.done).reduce((sum, p) => sum + p.weight, 0);
}

/** Этап, который идет сейчас (начат, но не завершен); undefined — между этапами или событий еще не было. */
export function activeIndex(s: ProgressState): number | undefined {
  return s.started > s.done ? s.started : undefined;
}

export const hasProgress = (s: ProgressState) => s.started > 0;

// Уход плашки после успешного завершения: live → done (показ «готово») → exiting (схлопывание) → gone.
// Сбой, «Пересчитать» и поток без событий хода плашку не показывают дольше — сразу gone.
export type ExitPhase = "live" | "done" | "exiting" | "gone";
export const EXIT_HOLD_MS = 650;
export const EXIT_MS = 650;

/** Следующая фаза: live — идет ход модели с полосой; success — поток закончился штатно и разбор обновлен. */
export function nextExit(phase: ExitPhase, live: boolean, success: boolean, abort = false): ExitPhase {
  if (live) return "live";  // новый запуск во время ухода отменяет уход
  if (abort) return "gone";  // «Пересчитать» и т.п.: плашка исчезает сразу, без «готово»
  return phase === "live" ? (success ? "done" : "gone") : phase;
}

/** Фаза плашки с таймерами ухода; состояние выводится при отрисовке, в эффектах — только таймеры. */
export function useUpgradeExit(live: boolean, success: boolean, abort = false): ExitPhase {
  const [phase, setPhase] = useState<ExitPhase>("gone");
  const next = nextExit(phase, live, success, abort);
  if (next !== phase) setPhase(next);
  useEffect(() => {
    if (phase !== "done" && phase !== "exiting") return;
    const t = setTimeout(() => setPhase(phase === "done" ? "exiting" : "gone"), phase === "done" ? EXIT_HOLD_MS : EXIT_MS);
    return () => clearTimeout(t);
  }, [phase]);
  return next;
}
