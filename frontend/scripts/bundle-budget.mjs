// Бюджет размера главной (SPR3-07): JS, который браузер загружает для «/», ≤ 200 КБ gzip.
// Запуск после `next build`: node scripts/bundle-budget.mjs [страница.html] [лимит КБ].
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

const page = process.argv[2] ?? ".next/server/app/index.html";
const limitKb = Number(process.argv[3] ?? 200);
const html = readFileSync(page, "utf8");
const scripts = [...new Set(html.match(/\/_next\/static\/[^"'\s]+\.js/g) ?? [])];
if (!scripts.length) throw new Error(`В ${page} нет скриптов /_next/static — сборка не найдена?`);

let total = 0;
for (const src of scripts) {
  const size = gzipSync(readFileSync(join(".next", src.replace("/_next/", "")))).length;
  total += size;
  console.log(`${(size / 1024).toFixed(1).padStart(7)} КБ  ${src}`);
}
const kb = total / 1024;
console.log(`Главная: ${kb.toFixed(1)} КБ gzip из ${limitKb} КБ (${scripts.length} файлов)`);
if (kb > limitKb) {
  console.error(`Бюджет превышен на ${(kb - limitKb).toFixed(1)} КБ`);
  process.exit(1);
}
