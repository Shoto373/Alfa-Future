import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ApiError } from "@/lib/api";
import type { Claim } from "@/lib/types";
import ClaimList, { OpenSource, RulesMode } from "@/components/insight/ClaimList";
import { ErrorState } from "@/components/ui";

describe("ErrorState", () => {
  it("повторяемая ошибка — понятный текст и кнопка «Повторить»", () => {
    const onRetry = vi.fn();
    render(<ErrorState error={new ApiError("x", "TOO_MANY_REQUESTS", true, 429)} onRetry={onRetry} />);
    expect(screen.getByRole("alert").textContent).toMatch(/Подождите минуту/);
    fireEvent.click(screen.getByText("Повторить"));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("«нет прав» — без кнопки: повтор не поможет", () => {
    render(<ErrorState error={new ApiError("Недостаточно прав", "FORBIDDEN", false, 403)} onRetry={() => {}} />);
    expect(screen.getByRole("alert").textContent).toBe("Недостаточно прав для этого действия.");
    expect(screen.queryByText("Повторить")).toBeNull();
  });
});

const claims: Claim[] = [
  { text: "Ставка выросла до 18%", origin: "fact", source_ids: ["news:1"] },
  { text: "Расходы на обслуживание долга вырастут", origin: "ai", source_ids: ["bank:t1", "bank:t2", "unknown"] },
  { text: "Стоит зафиксировать ставку", origin: "ai", source_ids: [] },
] as Claim[];

describe("ClaimList", () => {
  it("метки происхождения, одна метка на группу, сноски без повторов", () => {
    const open = vi.fn();
    render(
      <OpenSource.Provider value={open}>
        <ClaimList items={claims} index={new Map([["news:1", 1], ["bank:t1", 2], ["bank:t2", 2]])} />
      </OpenSource.Provider>,
    );
    expect(screen.getByText("Факт из новости")).toBeTruthy();
    const ai = screen.getAllByText("Вывод AI");
    expect(ai).toHaveLength(2);
    expect(ai[1].parentElement?.getAttribute("aria-hidden")).toBe("true");
    expect(screen.getAllByRole("link").map((a) => a.textContent)).toEqual(["1", "2"]);
    fireEvent.click(screen.getByLabelText("Источник 2"));
    expect(open).toHaveBeenCalledWith(2);
  });

  it("карточка на правилах подписана «Быстрый разбор»; пустой список — текст-заглушка", () => {
    const { unmount } = render(<RulesMode.Provider value><ClaimList items={claims.slice(1, 2)} index={new Map()} /></RulesMode.Provider>);
    expect(screen.getByText("Быстрый разбор")).toBeTruthy();
    unmount();
    render(<ClaimList items={[]} index={new Map()} empty="Нет рисков" />);
    expect(screen.getByText("Нет рисков")).toBeTruthy();
  });
});
