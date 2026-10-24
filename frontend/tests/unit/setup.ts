// Без globals Testing Library не убирает отрисованное между тестами — убираем сами.
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => cleanup());
