"use client";

import { useEffect, useState } from "react";
import { Card, ErrorState, Icon, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { date } from "@/lib/format";
import { useLoad } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { ConfigDoc, ConfigIssue, ConfigPreview, ConfigTexts, LookupCompany, Role } from "@/lib/types";
import styles from "@/app/(bank)/admin/config/page.module.scss";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";

const DOCS: { key: ConfigDoc; label: string; hint: string }[] = [
  { key: "topics", label: "Темы", hint: "словари, знак направления, формулировки эффекта, действия по ролям" },
  { key: "sectors", label: "Отрасли", hint: "ОКВЭД, слова в новостях, чувствительность к темам, эталоны знака" },
  { key: "language", label: "Слова-маркеры", hint: "страны, направления, курс, санкции, участники событий" },
];
const ROLES: { role: Role; name: string }[] = [
  { role: "cfo", name: "Финансовый директор" }, { role: "ceo", name: "Генеральный директор" }, { role: "owner", name: "Собственник" },
];
const POLL_MS = 2000;

/** Отрасли, темы и действия как данные (SPR4-00): правка YAML, проверка, превью ленты, публикация и откат. */
export default function ConfigPage() {
  const { session } = useSession();
  const operator = !!session!.user.is_operator;
  const load = useLoad((signal) => operator ? api.config(signal) : Promise.resolve(null), [operator]);
  const [texts, setTexts] = useState<ConfigTexts | null>(null);
  const [tab, setTab] = useState<ConfigDoc>("topics");
  const [issues, setIssues] = useState<ConfigIssue[] | null>(null);
  const [note, setNote] = useState("");
  const [state, setState] = useState<{ busy: boolean; message?: string; error?: string }>({ busy: false });

  if (!operator) return <div className={common.page}><h1>Отрасли и темы</h1><Card><p>Раздел доступен аналитикам банка.</p></Card></div>;
  if (load.error) return <ErrorState error={load.error} onRetry={load.reload} />;
  if (!load.data) return <Skeleton lines={8} />;
  const current = texts ?? load.data.texts;
  const shown = issues ?? load.data.issues;
  const errors = shown.filter((i) => i.level === "error");
  const changed = texts !== null && DOCS.some((d) => texts[d.key] !== load.data!.texts[d.key]);

  const act = async (fn: () => Promise<string | void>) => {
    setState({ busy: true });
    try {
      setState({ busy: false, message: (await fn()) || undefined });
    } catch (e) {
      setState({ busy: false, error: errorText(e) });
    }
  };
  const check = () => act(async () => {
    const r = await api.configValidate(current);
    setIssues(r.issues);
    return r.ok ? "Ошибок нет — можно публиковать" : undefined;
  });
  const publish = () => act(async () => {
    const r = await api.configPublish(current, note);
    setTexts(null);
    setIssues(null);
    load.reload();
    return `Опубликована версия ${r.id}. Новости переклассифицируются в фоне — лента обновится через минуту.`;
  });

  return (
    <div className={common.page}>
      <div className={common.pageHead}>
        <div>
          <span className={common.eyebrow}><Icon name="settings" /> Доменная конфигурация</span>
          <h1>Отрасли и темы</h1>
          <p className={common.muted}>Словари тем, чувствительность отраслей и действия по ролям — данные, а не код. Версия публикуется
            без деплоя; валидатор не пропустит перевернутый знак. Сейчас действует {load.data.version ? `версия ${load.data.version}` : "конфигурация из репозитория"}.</p>
        </div>
      </div>
      <Card>
        <div className={styles.tabs} role="tablist">
          {DOCS.map((d) => {
            const n = shown.filter((i) => i.doc === d.key && i.level === "error").length;
            return (
              <button key={d.key} role="tab" type="button" aria-selected={tab === d.key} className={tab === d.key ? styles.on : undefined}
                onClick={() => setTab(d.key)}>
                {d.label}{n > 0 && <span className={styles.badge}>{n}</span>}
              </button>
            );
          })}
        </div>
        <p className={common.muted}>{DOCS.find((d) => d.key === tab)!.hint}</p>
        <textarea className={`${forms.textarea} ${styles.yaml}`} spellCheck={false} aria-label={`YAML: ${tab}`} value={current[tab]}
          onChange={(e) => { setTexts({ ...current, [tab]: e.target.value }); setIssues(null); }} />
        <Issues issues={shown} onPick={setTab} />
        <div className={styles.actions}>
          <button type="button" className={`${common.btn} ${common.btnSecondary}`} disabled={state.busy} onClick={check}>Проверить</button>
          <input className={`${forms.input} ${styles.note}`} placeholder="Что изменено (для истории версий)" value={note}
            onChange={(e) => setNote(e.target.value)} maxLength={300} />
          <button type="button" className={`${common.btn} ${common.btnPrimary}`} disabled={state.busy || !changed || errors.length > 0 || issues === null}
            title={issues === null ? "Сначала проверьте конфигурацию" : undefined} onClick={publish}>Опубликовать</button>
        </div>
        {state.message && <p className={common.muted} role="status">{state.message}</p>}
        {state.error && <ErrorState error={state.error} />}
      </Card>
      <PreviewCard texts={current} disabled={errors.length > 0} />
      <Versions versions={load.data.versions} onRollback={(id) => act(async () => {
        await api.configRollback(id);
        setTexts(null);
        setIssues(null);
        load.reload();
        return `Версия ${id} снова действует`;
      })} />
    </div>
  );
}

function Issues({ issues, onPick }: { issues: ConfigIssue[]; onPick: (doc: ConfigDoc) => void }) {
  if (!issues.length) return <p className={styles.ok}>✓ Ошибок и предупреждений нет</p>;
  return (
    <ul className={styles.issues} aria-label="Результат проверки">
      {issues.map((i, n) => (
        <li key={n} className={i.level === "error" ? styles.error : styles.warning}>
          <button type="button" onClick={() => onPick(i.doc)}>{i.level === "error" ? "Ошибка" : "Предупреждение"} · {i.doc}</button>
          <code>{i.path}</code> {i.message}
        </li>
      ))}
    </ul>
  );
}

function PreviewCard({ texts, disabled }: { texts: ConfigTexts; disabled: boolean }) {
  const [companies, setCompanies] = useState<LookupCompany[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [role, setRole] = useState<Role>("cfo");
  const [preview, setPreview] = useState<{ id: string; result?: ConfigPreview } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.lookupCompanies("", 50, 0).then((r) => { setCompanies(r.items); setCompanyId((id) => id || r.items[0]?.company_id || ""); })
      .catch((e) => setError(errorText(e)));
  }, []);
  // Превью считает воркер: опрашиваем результат, пока он не готов.
  useEffect(() => {
    if (!preview || preview.result?.status === "ready" || preview.result?.status === "invalid") return;
    const t = setTimeout(() => api.configPreviewResult(preview.id).then((result) => setPreview({ ...preview, result }))
      .catch((e) => setError(errorText(e))), POLL_MS);
    return () => clearTimeout(t);
  }, [preview]);

  const run = async () => {
    setError(null);
    try {
      setPreview({ id: (await api.configPreview(texts, companyId, role)).id });
    } catch (e) {
      setError(errorText(e));
    }
  };
  const r = preview?.result;
  return (
    <Card title="Как изменится лента компании">
      <div className={styles.actions}>
        <select className={forms.select} aria-label="Компания" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
          {companies.map((c) => <option key={c.company_id} value={c.company_id}>{c.display_name} · {c.sector_name}</option>)}
        </select>
        <select className={forms.select} aria-label="Роль" value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {ROLES.map((x) => <option key={x.role} value={x.role}>{x.name}</option>)}
        </select>
        <button type="button" className={`${common.btn} ${common.btnSecondary}`} disabled={disabled || !companyId} onClick={run}>Показать превью</button>
      </div>
      {preview && !r?.after && r?.status !== "invalid" && <p className={common.muted} role="status">Считаем ленту с новой конфигурацией…</p>}
      {r?.status === "invalid" && <p className={styles.error}>Конфигурация с ошибками — превью не построено</p>}
      {r?.after && (
        <div className={styles.compare} data-testid="config-preview">
          <div>
            <h3>Сейчас</h3>
            <ol>{r.before!.map((x) => <li key={x.news_id}><b>{x.score}</b> {x.title}</li>)}</ol>
          </div>
          <div>
            <h3>С новой конфигурацией</h3>
            <ol>
            {r.after.map((x) => (
              <li key={x.news_id} className={x.rank_before === null || x.rank_before === undefined ? styles.added : undefined}>
                <b>{x.score}</b> {x.title}
                {x.rank_before === null || x.rank_before === undefined ? <em>новая в топе</em>
                  : x.rank_before !== x.rank ? <em>{x.rank_before > x.rank! ? "▲" : "▼"} {Math.abs(x.rank_before - x.rank!)}</em> : null}
              </li>
            ))}
            </ol>
          </div>
        </div>
      )}
      {error && <ErrorState error={error} />}
    </Card>
  );
}

function Versions({ versions, onRollback }: { versions: { id: number; status: string; created_by: string; note: string; created_at: string }[];
  onRollback: (id: number) => void }) {
  return (
    <Card title="Версии">
      {!versions.length ? <p className={common.muted}>Опубликованных версий нет — действует конфигурация из репозитория.</p> : (
        <ul className={styles.versions}>
          {versions.map((v) => (
            <li key={v.id}>
              <span><b>Версия {v.id}</b> · {date(v.created_at)} · {v.created_by}{v.note ? ` · ${v.note}` : ""}</span>
              {v.status === "published" ? <span className={styles.current}>действует</span>
                : <button type="button" className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} onClick={() => onRollback(v.id)}>Вернуть</button>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
