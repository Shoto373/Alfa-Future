import Link from "next/link";
import NewsAnalytics from "@/components/NewsAnalytics";

export const metadata = { title: "Новостная аналитика — демо" };

export default function AnalyticsPage() {
  return (
    <main className="page">
      <nav className="breadcrumbs">
        <Link href="/">← Главная</Link>
      </nav>
      <NewsAnalytics />
    </main>
  );
}
