"use client";

import { useEffect, useState } from "react";
import AddNews from "@/components/AddNews";
import CompanyPanel from "@/components/CompanyPanel";
import NewsCard from "@/components/NewsCard";
import { Card, ErrorBox, Icon, Loading, Skeleton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useCompany, useFeed } from "@/lib/hooks";
import { ROLE_NAMES, useSession } from "@/lib/session";
import type { Meta } from "@/lib/types";

export default function PulsePage() {
  const { session } = useSession();
  const [topic, setTopic] = useState<string | undefined>();
  const [meta, setMeta] = useState<Meta | null>(null);
  const feed = useFeed(session!.companyId, session!.role, topic);
  const company = useCompany(session!.companyId);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

  useEffect(() => { api.meta().then(setMeta).catch(() => setMeta(null)); }, []);
  useEffect(() => setTopic(undefined), [session!.companyId]);
  // Переход с главной по теме: /pulse?topic=key_rate.
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("topic");
    if (t) setTopic(t);
  }, []);

  const sectors = Object.fromEntries((meta?.sectors ?? []).map((s) => [s.sector, s.name]));

  const refresh = async () => {
    setRefreshing(true);
    setRefreshNote(null);
    try {
      const r = await api.refreshNews();
      const failed = r.sources.filter((s) => s.error).map((s) => s.name);
      setRefreshNote(`Новых: ${r.added}, дубликатов: ${r.duplicates}${failed.length ? `. Недоступны: ${failed.join(", ")}` : ""}`);
      feed.reload();
    } catch (e) {
      setRefreshNote(e instanceof ApiError ? e.message : "Не удалось обновить ленту");
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="eyebrow"><Icon name="spark" /> Альфа.Пульс</span>
          <h1>Лента {session!.companyName}</h1>
          <p className="muted">Ранжировано под профиль компании и роль «{ROLE_NAMES[session!.role]}». Смените роль в шапке — лента перестроится.</p>
        </div>
        <button className="btn btn-secondary" onClick={refresh} disabled={refreshing}>
          <Icon name="refresh" /> {refreshing ? "Собираем новости…" : "Обновить из RSS"}
        </button>
      </div>
      {refreshNote && <p className="muted small">{refreshNote}</p>}

      <div className="chips" role="toolbar" aria-label="Фильтр по темам">
        <button className={!topic ? "chip on" : "chip"} onClick={() => setTopic(undefined)}>Все темы</button>
        {meta?.topics.map((t) => (
          <button key={t.topic} className={topic === t.topic ? "chip on" : "chip"} onClick={() => setTopic(t.topic)}>{t.name}</button>
        ))}
      </div>

      <div className="layout-2">
        <div className="feed">
          {feed.loading && <Loading text="Подбираем новости под компанию…" />}
          {feed.error && <ErrorBox message={feed.error.message} onRetry={feed.reload} />}
          {feed.data?.length === 0 && <Card><p>По этой теме новостей нет. Выберите другую тему или добавьте новость.</p></Card>}
          {feed.data?.map((item) => <NewsCard key={item.news.news_id} item={item} />)}
        </div>
        <aside className="side">
          {company.loading && <Card title="Контекст компании"><Skeleton lines={6} /></Card>}
          {company.error && <ErrorBox message={company.error.message} onRetry={company.reload} />}
          {company.data && <CompanyPanel profile={company.data.profile} exposures={company.data.exposures} sectors={sectors} />}
          <AddNews onAdded={feed.reload} />
        </aside>
      </div>
    </div>
  );
}
