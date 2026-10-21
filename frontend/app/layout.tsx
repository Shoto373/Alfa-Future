import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { SessionProvider } from "@/lib/session";
import "./globals.css";

export const metadata: Metadata = {
  title: "Альфа.Пульс — новостная аналитика для бизнеса",
  description: "Прототип хакатона: персонализированные бизнес-инсайты из новостей и аналитики Альфа-Банка",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#EF3124" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
