import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Альфа.Пульс — демо",
  description: "Демонстрационный макет новостной аналитики на синтетических данных",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <div className="demo-banner" role="note">
          Демонстрационный макет хакатона. Не является действующим сервисом банка. Все данные искусственные.
        </div>
        {children}
      </body>
    </html>
  );
}
