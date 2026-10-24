import type { KbUploadItem } from "@/lib/types";

/** Статус распознавания документа для аналитика. */
export const STATUS: Record<KbUploadItem["status"], string> = {
  queued: "В очереди", processing: "Распознается", ready: "Готов к проверке", failed: "Ошибка",
};
