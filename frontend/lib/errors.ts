import { ApiError } from "./api";

const MESSAGES: Record<string, string> = {
  INVALID_CREDENTIALS: "Неверный email или пароль.",
  TOO_MANY_ATTEMPTS: "Слишком много попыток. Подождите немного и повторите.",
  EMAIL_TAKEN: "Пользователь с таким email уже зарегистрирован. Попробуйте войти.",
  COMPANY_CLAIMED: "Эта компания уже зарегистрирована. Попросите администратора компании пригласить вас.",
  MEMBER_EXISTS: "Этот пользователь уже есть в списке участников.",
  LAST_ADMIN: "Нельзя убрать последнего администратора компании. Сначала назначьте другого.",
  FORBIDDEN: "Недостаточно прав для этого действия.",
  UNAUTHORIZED: "Сессия истекла. Войдите снова.",
};

/** Понятное сообщение для пользователя по ошибке API. */
export function errorText(e: unknown, fallback = "Не удалось выполнить действие. Повторите попытку."): string {
  if (e instanceof ApiError) return MESSAGES[e.code] ?? (e.message || fallback);
  return fallback;
}
