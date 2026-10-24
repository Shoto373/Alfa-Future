"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import AccessDenied from "@/components/AccessDenied";
import FeedRail from "@/components/FeedRail";
import InsightView from "@/components/InsightView";
import { ErrorState, Icon, Skeleton } from "@/components/ui";
import { AbortedError, ApiError, api } from "@/lib/api";
import { markRead } from "@/lib/notifications";
import { useSession } from "@/lib/session";
import type { Insight, Role } from "@/lib/types";
import common from "@/styles/common.module.scss";
import styles from "@/app/(bank)/pulse/n/[newsId]/page.module.scss";

const STEPS = ["Определяем контекст компании", "Ищем аналитику Альфа-Банка", "Сопоставляем риски и возможности", "Проверяем выводы и источники"];

export default function InsightPage() {
  const { newsId } = useParams<{ newsId: string }>();
  const { session } = useSession();
  // Смена компании или новости — разбор с чистого листа; ответ на старый запрос игнорируется.
  return (
    <div className={styles.split}>
      <FeedRail activeId={decodeURIComponent(newsId)} />
      <NewsInsight key={`${session!.companyId}:${session!.role}:${newsId}`} newsId={newsId} />
    </div>
  );
}

function NewsInsight({ newsId }: { newsId: string }) {
  const { session } = useSession();
  const companyId = session!.companyId;
  const [insight, setInsight] = useState<Insight | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [step, setStep] = useState(0);
  const [upgrading, setUpgrading] = useState(false);
  const [upgradeFailed, setUpgradeFailed] = useState(false);
  // Другой разрез: тот же разбор глазами другой роли компании; по умолчанию — своя роль.
  const [perspective, setPerspective] = useState<Role>(session!.role);
  const seq = useRef(0);

  // Открыли разбор — уведомление по этой новости прочитано.
  useEffect(() => {
    if (session && newsId) markRead(session.user.user_id, session.companyId, [newsId]);
  }, [session, newsId]);
  const controller = useRef<AbortController | null>(null);

  // Запрос разбора; состояние меняется только по ответам — сброс перед повтором делает load.
  const run = useCallback((force: boolean) => {
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    const mine = ++seq.current;
    const id = decodeURIComponent(newsId);
    // 1) Сразу — готовая карточка или разбор на правилах (доли секунды).
    const view = perspective === session!.role ? undefined : perspective;
    api.insight(companyId, id, { force, fast: true, perspective: view }, c.signal)
      .then((ins) => {
        if (mine !== seq.current) return;
        setInsight(ins);
        setLoading(false);
        if (ins.mode !== "rules") return;
        // 2) Следом — версия модели: она заменит карточку на правилах, когда будет готова.
        setUpgrading(true);
        return api.insight(companyId, id, { perspective: view }, c.signal)
          .then((full) => {
            if (mine !== seq.current) return;
            setInsight(full);
            if (full.mode === "rules") setUpgradeFailed(true);  // модель не ответила или ее выводы не прошли проверку
          })
          .catch((e) => {
            if (mine === seq.current && !(e instanceof AbortedError)) setUpgradeFailed(true);
          })
          .finally(() => { if (mine === seq.current) setUpgrading(false); });
      })
      .catch((e) => {
        if (mine !== seq.current || e instanceof AbortedError) return;
        setError(e instanceof ApiError ? e : new ApiError("Непредвиденная ошибка", "CLIENT", true));
        setLoading(false);
      });
  }, [companyId, newsId, perspective, session]);

  // «Пересчитать» и «Повторить»: сброс состояния и новый запрос.
  const load = (force = false) => {
    setLoading(true);
    setError(null);
    setUpgrading(false);
    setUpgradeFailed(false);
    setStep(0);
    if (!force) setInsight(null);
    run(force);
  };

  useEffect(() => {
    run(false);
    return () => controller.current?.abort();
  }, [run]);

  useEffect(() => {
    if (!loading) return;
    const t = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 700);
    return () => clearInterval(t);
  }, [loading]);

  return (
    <div className={common.page}>
      <nav className={styles.crumbs}><Link href="/pulse"><Icon name="chevron" size={14} /> Лента Альфа.Пульс</Link></nav>
      {loading && !insight && (
        <div className={`${common.card} ${styles.agentProgress}`} role="status">
          <h2>Агент готовит разбор для {session!.companyName}</h2>
          <ol>{STEPS.map((s, i) => <li key={s} className={i < step ? styles.done : i === step ? styles.now : ""}>{s}</li>)}</ol>
          <Skeleton lines={4} />
        </div>
      )}
      {error && (error.code === "FORBIDDEN" ? <AccessDenied /> : <ErrorState error={error} onRetry={() => load()} />)}
      {insight && <InsightView insight={insight} onRefresh={() => load(true)} refreshing={loading}
        upgrading={upgrading} upgradeFailed={upgradeFailed}
        perspective={perspective} ownRole={session!.role} onPerspective={setPerspective} />}
    </div>
  );
}
