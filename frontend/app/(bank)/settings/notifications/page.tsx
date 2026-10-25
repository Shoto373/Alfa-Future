import { redirect } from "next/navigation";

/** Настройки уведомлений переехали в профиль; старая ссылка из писем и закладок ведет туда же. */
export default function NotificationSettingsRedirect() {
  redirect("/profile#notifications");
}
