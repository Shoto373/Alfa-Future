// Unit-тесты интерфейса (SPR3-07): слой данных, клиент API, сессия и ключевые компоненты разбора.
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: { jsx: "automatic" },
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: {
    environment: "jsdom",
    setupFiles: ["tests/unit/setup.ts"],
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    css: { modules: { classNameStrategy: "non-scoped" } },
    coverage: {
      provider: "v8",
      include: ["lib/**/*.{ts,tsx}"],
      exclude: ["lib/api-types.ts", "lib/types.ts"],  // только типы
      reporter: ["text", "json-summary"],
      thresholds: { lines: 70, statements: 70, functions: 70, branches: 60 },
    },
  },
});
