"use client";

import { useEffect, useState } from "react";
import { Card, ErrorState, Icon, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { date, money } from "@/lib/format";
import { useLoad } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { LabelingState } from "@/lib/types";
import styles from "@/app/(bank)/admin/labeling/page.module.scss";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";

const GRADES = [
  { grade: 0, label: "Не про компанию" }, { grade: 1, label: "Слабо связана" },
  { grade: 2, label: "Важна" }, { grade: 3, label: "Важна, нужна реакция" },
];

/** Разметка релевантности (SPR3-06): аналитик оценивает пару «новость × компания × роль» без подсказок системы. */
export default function LabelingPage() {
  const { session } = useSession();
  const operator = !!session!.user.is_operator;
  const load = useLoad((signal) => operator ? api.labelingNext(signal) : Promise.resolve(null), [operator]);
  const [state, setState] = useState<LabelingState | null>(null);
  const current = state ?? load.data;
  const [grade, setGrade] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pair = current?.pair ?? null;

  const save = async () => {
    if (!pair || grade === null) return;
    setBusy(true);
    setError(null);
    try {
      setState(await api.labelingSave({ news_id: pair.news_id, company_id: pair.company_id, role: pair.role, grade, reason }));
      setGrade(null);
      setReason("");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  // Клавиши 0–3 — оценка (кроме поля причины): разметчик не тянется к мыши на каждой паре.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "TEXTAREA") return;
      if (/^[0-3]$/.test(e.key)) setGrade(Number(e.key));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!operator) return <div className={common.page}><h1>Разметка ленты</h1><Card><p>Раздел доступен аналитикам банка.</p></Card></div>;
  if (load.error) return <ErrorState error={load.error} onRetry={load.reload} />;
  if (!current) return <Skeleton lines={6} />;
  const s = current.stats;

  return (
    <div className={common.page}>
      <div className={common.pageHead}>
        <div>
          <span className={common.eyebrow}><Icon name="list" /> Качество ленты</span>
          <h1>Разметка ленты</h1>
          <p className={common.muted}>Насколько новость важна этой компании и роли. Оценка системы не показывается,
            чтобы разметка была независимой. По разметке считается nDCG@10 и калибруются веса ранжирования.</p>
        </div>
      </div>
      <Card>
        <div className={styles.progress} aria-label="Прогресс разметки">
          <div><b>{s.labeled_pairs}</b> из {s.planned} пар</div>
          <div><b>{s.overlap_done}</b> из {s.overlap_planned} пар со вторым мнением</div>
          <div>Согласованность κ: <b>{s.kappa ?? "—"}</b> <small className={common.muted}>(цель ≥ 0,6)</small></div>
          <progress max={s.planned} value={s.labeled_pairs} />
        </div>
      </Card>
      {!pair ? <Card><p>Все пары размечены. Спасибо!</p></Card> : (
        <div className={styles.pair} data-testid="label-pair">
          <Card title={pair.company.name ?? pair.company_id}>
            <p className={styles.role}>Роль: <b>{pair.role_name}</b></p>
            <ul className={styles.facts}>
              <li><span>Отрасль</span>{pair.company.sector}</li>
              {pair.company.region && <li><span>Регион</span>{pair.company.region}</li>}
              {pair.company.revenue !== null && <li><span>Выручка</span>{money(pair.company.revenue)}</li>}
              {pair.company.suppliers.length > 0 && <li><span>Поставщики</span>{pair.company.suppliers.join(", ")}</li>}
              {pair.company.customers.length > 0 && <li><span>Покупатели</span>{pair.company.customers.join(", ")}</li>}
              {pair.company.countries.length > 0 && <li><span>Страны ВЭД</span>{pair.company.countries.join(", ")}</li>}
            </ul>
          </Card>
          <Card title={pair.news.title ?? pair.news_id}>
            <p className={common.muted}>{pair.news.source} · {date(pair.news.published_at)}</p>
            <p>{pair.news.lead}</p>
            <div className={common.tags}>{pair.news.topics.map((t) => <span key={t} className={common.tag}>{t}</span>)}</div>
          </Card>
          <Card title="Оценка">
            <div className={styles.grades} role="radiogroup" aria-label="Оценка релевантности">
              {GRADES.map((g) => (
                <button key={g.grade} type="button" role="radio" aria-checked={grade === g.grade}
                  className={grade === g.grade ? styles.on : undefined} onClick={() => setGrade(g.grade)}>
                  <b>{g.grade}</b> {g.label}
                </button>
              ))}
            </div>
            <label className={forms.field}>Причина (коротко)
              <textarea className={forms.textarea} rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)}
                placeholder="Например: долг компании в рублях с плавающей ставкой" />
            </label>
            <button type="button" className={`${common.btn} ${common.btnPrimary}`} disabled={grade === null || busy} onClick={save}>
              Сохранить и дальше
            </button>
            {error && <ErrorState error={error} />}
          </Card>
        </div>
      )}
    </div>
  );
}
