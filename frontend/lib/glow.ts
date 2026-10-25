import type { PointerEvent } from "react";

/**
 * Свечение за курсором на темных карточках главной: позиция мыши — в CSS-переменные --gx/--gy (в процентах
 * от карточки), по ним стили двигают красное пятно. Только мышь: на телефоне касание не должно дергать фон.
 * Без курсора переменные снимаются — пятно возвращается к своему медленному «дыханию».
 */
export const glow = {
  onPointerMove(e: PointerEvent<HTMLElement>) {
    if (e.pointerType !== "mouse") return;
    const el = e.currentTarget;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    el.style.setProperty("--gx", `${(((e.clientX - r.left) / r.width) * 100).toFixed(1)}%`);
    el.style.setProperty("--gy", `${(((e.clientY - r.top) / r.height) * 100).toFixed(1)}%`);
  },
  onPointerLeave(e: PointerEvent<HTMLElement>) {
    e.currentTarget.style.removeProperty("--gx");
    e.currentTarget.style.removeProperty("--gy");
  },
};
