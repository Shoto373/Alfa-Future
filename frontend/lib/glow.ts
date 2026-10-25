import type { PointerEvent } from "react";

/**
 * Красное пятно темных блоков ползет за курсором: позиция мыши — в CSS-переменные --cx/--cy (в процентах
 * от блока), стили (styles/_glow.scss) плавно смешивают ее с собственным плаванием пятна. Только мышь:
 * касание на телефоне фон не двигает. Когда курсор уходит, позиция не сбрасывается — пятно плавно
 * перетекает от последней точки обратно в свое плавание.
 */
export const glow = {
  onPointerMove(e: PointerEvent<HTMLElement>) {
    if (e.pointerType !== "mouse") return;
    const el = e.currentTarget;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    el.style.setProperty("--cx", `${(((e.clientX - r.left) / r.width) * 100).toFixed(1)}%`);
    el.style.setProperty("--cy", `${(((e.clientY - r.top) / r.height) * 100).toFixed(1)}%`);
  },
};
