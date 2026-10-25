import { describe, expect, it } from "vitest";
import type { PointerEvent } from "react";
import { glow } from "@/lib/glow";

function event(el: HTMLElement, pointerType: string, x: number, y: number) {
  return { currentTarget: el, pointerType, clientX: x, clientY: y } as unknown as PointerEvent<HTMLElement>;
}

describe("glow", () => {
  it("мышь двигает свечение в процентах от блока", () => {
    const el = document.createElement("div");
    el.getBoundingClientRect = () => ({ left: 100, top: 50, width: 200, height: 100 }) as DOMRect;
    glow.onPointerMove(event(el, "mouse", 150, 75));
    expect([el.style.getPropertyValue("--mx"), el.style.getPropertyValue("--my")]).toEqual(["25.0%", "25.0%"]);
  });

  it("касание на телефоне и блок без размера свечение не двигают", () => {
    const el = document.createElement("div");
    el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 100 }) as DOMRect;
    glow.onPointerMove(event(el, "touch", 50, 50));
    expect(el.style.getPropertyValue("--mx")).toBe("");
    el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 0, height: 0 }) as DOMRect;
    glow.onPointerMove(event(el, "mouse", 50, 50));
    expect(el.style.getPropertyValue("--mx")).toBe("");
  });
});
