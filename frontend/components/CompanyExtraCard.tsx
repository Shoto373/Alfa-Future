"use client";

import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { ErrorState, Skeleton } from "@/components/ui";
import { AbortedError, api } from "@/lib/api";
import { date } from "@/lib/format";
import { errorText } from "@/lib/errors";
import type { CompanyExtra, ExtraShareKey } from "@/lib/types";
import styles from "@/components/CompanyExtraCard.module.scss";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";
import ui from "@/components/ui.module.scss";

const NOTES_LIMIT = 15000;
const FILE_LIMIT = 5 * 1024 * 1024;  // как на сервере
const KIND_LABEL = { csv: "CSV", pdf: "PDF" } as const;
const HINTS: Record<ExtraShareKey, string> = {
  floating_debt_share: "Насколько расходы на проценты зависят от ключевой ставки",
  fx_revenue_share: "Насколько выручка зависит от курса рубля",
  import_share: "Насколько закупки зависят от курса и импортных ограничений",
};

/** Сведения, которые компания сообщает о себе сама: учитываются в ленте и разборах. */
export default function CompanyExtraCard({ companyId, isAdmin, onSaved }: { companyId: string; isAdmin: boolean; onSaved?: () => void }) {
  const [extra, setExtra] = useState<CompanyExtra | null>(null);
  const [shares, setShares] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);

  const fill = (data: CompanyExtra) => {
    setExtra(data);
    setShares(Object.fromEntries(data.fields.map((f) => [f.key, data.shares[f.key]?.toString() ?? ""])));
    setNotes(data.notes);
  };

  useEffect(() => {
    const c = new AbortController();
    api.companyExtra(companyId, c.signal)
      .then((data) => { fill(data); setError(null); })
      .catch((e) => { if (!(e instanceof AbortedError)) setError(errorText(e)); });
    return () => c.abort();
  }, [companyId, attempt]);

  // Файл уходит на сервер сразу: текст извлекается там (CSV — строки таблицы, PDF — текстовый слой).
  const upload = async (ev: ChangeEvent<HTMLInputElement>) => {
    const f = ev.target.files?.[0];
    ev.target.value = "";
    if (!f) return;
    if (!/\.(csv|pdf)$/i.test(f.name)) {
      setFileError("Поддерживаются файлы CSV и PDF.");
      return;
    }
    if (f.size > FILE_LIMIT) {
      setFileError("Файл больше 5 МБ.");
      return;
    }
    setUploading(true);
    setFileError(null);
    try {
      setExtra(await api.uploadCompanyFile(companyId, f));
      onSaved?.();
    } catch (e) {
      setFileError(errorText(e));
    } finally {
      setUploading(false);
    }
  };

  const remove = async (fileId: string) => {
    setFileError(null);
    try {
      setExtra(await api.deleteCompanyFile(companyId, fileId));
      onSaved?.();
    } catch (e) {
      setFileError(errorText(e));
    }
  };

  const save = async (ev: FormEvent) => {
    ev.preventDefault();
    const parsed: CompanyExtra["shares"] = {};
    for (const f of extra!.fields) {
      const raw = shares[f.key]?.trim().replace(",", ".");
      if (!raw) continue;
      const value = Number(raw);
      if (!Number.isFinite(value) || value < 0 || value > 100) {
        setFormError(`«${f.label}»: укажите число от 0 до 100.`);
        return;
      }
      parsed[f.key] = value;
    }
    setSaving(true);
    setFormError(null);
    try {
      fill(await api.saveCompanyExtra(companyId, { shares: parsed, notes }));
      setSaved(true);
      onSaved?.();  // признаки чувствительности в профиле пересчитаны
    } catch (e) {
      setFormError(errorText(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className={common.card} aria-labelledby="extra-title">
      <div className={common.cardHead}>
        <h2 id="extra-title">Дополнительные сведения</h2>
      </div>
      {!isAdmin && <p className={common.muted}>Изменять сведения может администратор компании.</p>}
      {error && <ErrorState error={error} onRetry={() => setAttempt((a) => a + 1)} />}
      {!extra && !error && <Skeleton lines={4} />}
      {extra && (
        <form className={styles.form} onSubmit={save} noValidate>
          <div className={styles.shares}>
            {extra.fields.map((f) => (
              <div key={f.key} className={`${forms.field} ${styles.share}`} title={HINTS[f.key]}>
                <label htmlFor={`extra-${f.key}`}>{f.label}</label>
                <span className={styles.percent}>
                  <input className={forms.input} id={`extra-${f.key}`} inputMode="decimal" placeholder="—"
                    value={shares[f.key] ?? ""} disabled={!isAdmin} aria-describedby={`extra-${f.key}-hint`}
                    onChange={(e) => { setShares((s) => ({ ...s, [f.key]: e.target.value })); setSaved(false); }} />
                  <span aria-hidden>%</span>
                </span>
                <span id={`extra-${f.key}-hint`} className={common.srOnly}>{HINTS[f.key]}</span>
              </div>
            ))}
          </div>
          <div className={forms.field}>
            <label htmlFor="extra-notes">О компании своими словами</label>
            <textarea className={forms.textarea} id="extra-notes" rows={7} maxLength={NOTES_LIMIT} disabled={!isAdmin}
              placeholder="Например: основные поставщики оборудования — в Китае, расчеты в юанях; в 2027 году планируем выпуск облигаций."
              value={notes} onChange={(e) => { setNotes(e.target.value); setSaved(false); }} />
            <small className={common.muted}>{notes.length.toLocaleString("ru-RU")} / {NOTES_LIMIT.toLocaleString("ru-RU")}</small>
          </div>
          {formError && <p className={ui.errorText} role="alert">{formError}</p>}
          {isAdmin && (
            <div className={styles.actions}>
              <button type="submit" className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`} disabled={saving}>
                {saving ? "Сохраняем…" : "Сохранить"}
              </button>
              {saved && <span className={`${common.muted} ${common.small}`} role="status">Сохранено — разборы пересчитаются с учетом сведений</span>}
            </div>
          )}
          {extra.updated_at && <p className={`${common.muted} ${common.small}`}>Обновлено {date(extra.updated_at)}</p>}
        </form>
      )}
      {extra && (
        <div className={styles.files}>
          <h3>Файлы</h3>
          {extra.files.length === 0 && <p className={common.muted}>Файлов пока нет. Можно приложить выгрузку в CSV или отчет в PDF.</p>}
          {extra.files.length > 0 && (
            <ul className={styles.fileList}>
              {extra.files.map((f) => (
                <li key={f.file_id}>
                  <span className={common.tag}>{KIND_LABEL[f.kind]}</span>
                  <span className={styles.fileMain}>
                    <strong>{f.name}</strong>
                    <small className={common.muted}>
                      {(f.size / 1024).toLocaleString("ru-RU", { maximumFractionDigits: 0 })} КБ · {f.chars.toLocaleString("ru-RU")} символов текста · {date(f.uploaded_at)}
                    </small>
                    <small className={styles.preview}>{f.preview}</small>
                  </span>
                  {isAdmin && (
                    <button type="button" className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} onClick={() => remove(f.file_id)}>Удалить</button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {fileError && <p className={ui.errorText} role="alert">{fileError}</p>}
          {isAdmin && (
            <>
              <input ref={file} type="file" accept=".csv,.pdf,text/csv,application/pdf" hidden onChange={upload} />
              <button type="button" className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} disabled={uploading}
                onClick={() => file.current?.click()}>
                {uploading ? "Загружаем…" : "Приложить файл (CSV или PDF)"}
              </button>
            </>
          )}
        </div>
      )}
    </section>
  );
}
