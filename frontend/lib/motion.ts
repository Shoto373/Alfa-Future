"use client";

import { useEffect, useRef, useState } from "react";

/** Пользователь попросил систему уменьшить движение — цифры меняются сразу, без анимации. */
function reducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Число плавно «досчитывается» до нового значения (ease-out), например сумма в «что если» при движении ползунка.
 * Без start первое значение показывается сразу (анимируется только изменение); со start — подъем от него
 * при появлении (стрелка шкалы поднимается от нуля).
 */
export function useAnimatedNumber(target: number, durationMs = 450, start?: number): number {
  const [shown, setShown] = useState(start ?? target);
  const from = useRef(start ?? target);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    const start = from.current;
    if (start === target || reducedMotion()) {
      from.current = target;
      setShown(target);
      return;
    }
    const began = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - began) / durationMs);
      const value = start + (target - start) * (1 - (1 - t) ** 3);
      from.current = value;
      setShown(value);
      if (t < 1) frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => { if (frame.current !== null) cancelAnimationFrame(frame.current); };
  }, [target, durationMs]);

  return shown;
}
