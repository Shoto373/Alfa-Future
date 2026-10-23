"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import InsightView from "@/components/InsightView";
import { ErrorBox, Icon, Skeleton } from "@/components/ui";
import { AbortedError, ApiError, api } from "@/lib/api";
import { markRead } from "@/lib/notifications";
import { useSession } from "@/lib/session";
import type { Insight } from "@/lib/types";

const STEPS = ["Определяем контекст компании", "Ищем аналитику Альфа-Банка", "Сопоставляем риски и возможности", "Проверяем выводы и источники"];

export default function InsightPage() {
  const { newsId } = useParams<{ newsId: string }>();
  const { session } = useSession();
  const [insight, setInsight] = useState<Insight | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [step, setStep] = useState(0);
  const seq = useRef(0);

  // Открыли разбор — уведомление по этой новости прочитано.
  useEffect(() => {
    if (session && newsId) markRead(session.user.user_id, session.companyId, [newsId]);
  }, [session, newsId]);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback((force = false) => {
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    const mine = ++seq.current;
    setLoading(true);
    setError(null);
    if (!force) setInsight(null);
    api.insight(session!.companyId, newsId, force, c.signal)
      .then((ins) => { if (mine === seq.current) setInsight(ins); })
      .catch((e) => {
        if (mine !== seq.current || e instanceof AbortedError) return;
        setError(e instanceof ApiError ? e : new ApiError("Непредвиденная ошибка", "CLIENT", true));
      })
      .finally(() => { if (mine === seq.current) setLoading(false); });
  }, [session, newsId]);

  // Смена компании или роли — новый разбор; ответ на старый запрос игнорируется.
  useEffect(() => {
    load();
    return () => controller.current?.abort();
  }, [load, session!.companyId]);

  useEffect(() => {
    if (!loading) return;
    setStep(0);
    const t = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 700);
    return () => clearInterval(t);
  }, [loading]);

  return (
    <div className="page">
      <nav className="crumbs"><Link href="/pulse"><Icon name="chevron" size={14} /> Лента Альфа.Пульс</Link></nav>
      {loading && !insight && (
        <div className="card agent-progress" role="status">
          <h2>Агент готовит разбор для {session!.companyName}</h2>
          <ol>{STEPS.map((s, i) => <li key={s} className={i < step ? "done" : i === step ? "now" : ""}>{s}</li>)}</ol>
          <Skeleton lines={4} />
        </div>
      )}
      {error && <ErrorBox message={error.message} onRetry={() => load()} />}
      {insight && <InsightView insight={insight} onRefresh={() => load(true)} refreshing={loading} />}
    </div>
  );
}
