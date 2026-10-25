import type { PointerEvent } from "react";

/**
 * Свечение под курсором на темных блоках: позиция мыши — в CSS-переменные --mx/--my (в процентах от блока),
 * по ним слой свечения (styles/_glow.scss) плавно следует за курсором. Только мышь: касание на телефоне
 * не должно дергать фон. Когда курсор уходит, позиция не сбрасывается — свечение гаснет там, где было,
 * а не уезжает в угол.
 */
export const glow = {
  onPointerMove(e: PointerEvent<HTMLElement>) {
    if (e.pointerType !== "mouse") return;
    const el = e.currentTarget;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    el.style.setProperty("--mx", `${(((e.clientX - r.left) / r.width) * 100).toFixed(1)}%`);
    el.style.setProperty("--my", `${(((e.clientY - r.top) / r.height) * 100).toFixed(1)}%`);
  },
};
