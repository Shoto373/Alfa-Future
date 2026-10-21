"use client";

import Link from "next/link";
import NewsCard from "@/components/NewsCard";
import { Card, ErrorBox, Icon, Skeleton } from "@/components/ui";
import { money, PRODUCT_NAMES } from "@/lib/format";
import { useCompany, useFeed } from "@/lib/hooks";
import { ROLE_NAMES, useSession } from "@/lib/session";

export default function HomePage() {
  const { session } = useSession();
  const feed = useFeed(session!.companyId, session!.role);
  const company = useCompany(session!.companyId);
  const p = company.data?.profile;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Добрый день, {session!.userName.split(" ")[0]}</h1>
          <p className="muted">{ROLE_NAMES[session!.role]} · {session!.companyName}</p>
        </div>
      </div>

      <section className="pulse-hero">
        <div className="pulse-hero-text">
          <span className="eyebrow"><Icon name="spark" /> Альфа.Пульс</span>
          <h2>Что важно для вашего бизнеса сегодня</h2>
          <p>
            Новости и аналитика Альфа-Банка, отобранные под профиль компании и вашу роль. По каждой новости — что произошло,
            почему это касается именно вас, риски, возможности и что можно сделать.
          </p>
          <Link href="/pulse" className="btn btn-white">Открыть ленту</Link>
        </div>
        <div className="pulse-hero-list">
          {feed.loading && <Skeleton lines={4} />}
          {feed.error && <ErrorBox message={feed.error.message} onRetry={feed.reload} />}
          {feed.data?.length === 0 && <p>Пока нет новостей. Добавьте новость в ленте.</p>}
          {feed.data?.slice(0, 3).map((item) => <NewsCard key={item.news.news_id} item={item} compact />)}
        </div>
      </section>

      <div className="grid-3">
        <Card title="Счета">
          <p className="big-number">•••• ₽</p>
          <p className="muted small">Балансы в прототипе не отображаются.</p>
        </Card>
        <Card title="Профиль компании">
          {company.loading && <Skeleton />}
          {company.error && <ErrorBox message={company.error.message} onRetry={company.reload} />}
          {p && (
            <ul className="kv">
              <li><span>Отрасль</span><strong>{p.sector_name}</strong></li>
              <li><span>Выручка</span><strong>{money(p.revenue)}</strong></li>
              <li><span>Регион</span><strong>{p.region ?? "нет данных"}</strong></li>
            </ul>
          )}
        </Card>
        <Card title="Продукты банка">
          {p && (
            <div className="tags">
              {Object.entries(p.products).filter(([, v]) => v).map(([k]) => <span key={k} className="tag tag-on">{PRODUCT_NAMES[k] ?? k}</span>)}
              {Object.values(p.products).every((v) => !v) && <span className="muted">Нет подключенных продуктов</span>}
            </div>
          )}
          {company.loading && <Skeleton lines={2} />}
        </Card>
      </div>
    </div>
  );
}
