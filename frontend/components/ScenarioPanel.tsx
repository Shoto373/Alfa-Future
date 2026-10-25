"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { useAnimatedNumber } from "@/lib/motion";
import type { ScenarioKind, ScenarioResponse } from "@/lib/types";
import { Card } from "./ui";
import styles from "@/components/ScenarioPanel.module.scss";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";

const KINDS: { kind: ScenarioKind; label: string; unit: string; min: number; max: number; step: number; start: number; hint: string }[] = [
  { kind: "key_rate", label: "Ставка", unit: "п.п.", min: -3, max: 3, step: 0.25, start: 1, hint: "изменение ключевой ставки" },
  { kind: "fx", label: "Курс", unit: "%", min: -30, max: 30, step: 1, start: 10, hint: "плюс — рубль слабее" },
  { kind: "commodity", label: "Цена сырья", unit: "%", min: -40, max: 40, step: 1, start: -10, hint: "изменение цены сырья отрасли" },
];
const ORIGIN: Record<string, string> = {
  client_data: "Данные кейса", company_reported: "Сообщила компания", estimate: "Оценка по отрасли", user: "Вы указали", bank: "Прогноз банка",
};
const MISSING: Record<string, string> = {
  debt: "долг компании", fx_revenue_share: "доля валютной выручки", import_share: "доля импорта в закупках",
  exposure: "доля выручки, зависящая от цены сырья", revenue: "выручка", purchases: "платежи поставщикам",
};
const FIELDS: Record<ScenarioKind, { key: "debt" | "floating_share" | "fx_revenue_share" | "import_share" | "exposure"; label: string; percent: boolean }[]> = {
  key_rate: [{ key: "debt", label: "Долг, млн ₽", percent: false }, { key: "floating_share", label: "С плавающей ставкой, %", percent: true }],
  fx: [{ key: "fx_revenue_share", label: "Валютная выручка, %", percent: true }, { key: "import_share", label: "Импорт в закупках, %", percent: true }],
  commodity: [{ key: "exposure", label: "Выручка от цены сырья, %", percent: true }],
};

function money(rub: number): string {
  const m = Math.abs(rub) / 1e6;
  return `${(m < 10 ? m.toFixed(1) : Math.round(m).toString()).replace(".", ",")} млн ₽`;
}

/** «Что если» (SPR4-02): чувствительность к ставке, курсу и цене сырья — по формулам, без модели. */
export default function ScenarioPanel({ companyId, initial = "key_rate" }: { companyId: string; initial?: ScenarioKind }) {
  const [kind, setKind] = useState<ScenarioKind>(initial);
  const spec = KINDS.find((k) => k.kind === kind)!;
  const [shock, setShock] = useState(spec.start);
  const [own, setOwn] = useState<Record<string, string>>({});
  const [data, setData] = useState<ScenarioResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const overrides = Object.fromEntries(FIELDS[kind].filter((f) => own[f.key]?.trim()).map((f) => {
      const v = Number(own[f.key].replace(",", "."));
      return [f.key, f.percent ? v / 100 : v * 1e6];
    }));
    // Небольшая задержка: слайдер дергает расчет на каждое движение.
    const t = setTimeout(() => {
      api.scenario({ company_id: companyId, scenario: kind, shock, ...overrides })
        .then((r) => { setData(r); setError(null); }).catch((e) => setError(errorText(e)));
    }, 250);
    return () => clearTimeout(t);
  }, [companyId, kind, shock, own]);

  const pick = (k: ScenarioKind) => { setKind(k); setShock(KINDS.find((x) => x.kind === k)!.start); setOwn({}); };
  const r = data?.result;
  const effect = useAnimatedNumber(r?.effect_rub ?? 0);
  return (
    <Card title="Что если: во что это обойдется" className={styles.panel}>
      <div className={styles.tabs} role="tablist" aria-label="Сценарий">
        {KINDS.map((k) => <button key={k.kind} type="button" role="tab" aria-selected={kind === k.kind}
          className={kind === k.kind ? styles.on : undefined} onClick={() => pick(k.kind)}>{k.label}</button>)}
      </div>
      <label className={styles.slider}>
        <span>{spec.hint}: <b>{shock > 0 ? "+" : ""}{String(shock).replace(".", ",")} {spec.unit}</b></span>
        <input type="range" min={spec.min} max={spec.max} step={spec.step} value={shock} aria-label={spec.hint}
          onChange={(e) => setShock(Number(e.target.value))} />
      </label>
      {data?.corridor && (
        <p className={styles.corridor}>Коридор банка: {data.corridor.label.charAt(0).toLowerCase() + data.corridor.label.slice(1)} — {String(data.corridor.low).replace(".", ",")}
          {data.corridor.high !== data.corridor.low && `–${String(data.corridor.high).replace(".", ",")}`} {data.corridor.unit}</p>
      )}
      {r && (
        <div className={styles.result} data-testid="scenario-result">
          <strong className={r.effect_rub < 0 ? styles.loss : r.effect_rub > 0 ? styles.gain : undefined}>
            {Math.round(effect) === 0 ? "0 ₽" : `${effect < 0 ? "−" : "+"}${money(effect)}`} в год
          </strong>
          <p>{r.text}</p>
          <p className={styles.formula}>Формула: {r.formula}</p>
          <ul className={styles.inputs}>
            {r.inputs.map((i) => (
              <li key={i.name}><span>{i.label}</span>
                <b>{i.unit === "₽" ? money(i.value) : i.unit === "доля" ? `${Math.round(i.value * 100)}%` : String(i.value).replace(".", ",")}</b>
                <em>{ORIGIN[i.origin] ?? i.origin}</em></li>
            ))}
          </ul>
          {r.caveats.map((c) => <p key={c} className={common.muted}>{c}</p>)}
        </div>
      )}
      {data && !data.ok && data.refusal && (
        <div className={styles.refusal} role="status">
          <p>{data.refusal.message}.</p>
          <p className={common.muted}>Не хватает: {data.refusal.missing.map((m) => MISSING[m] ?? m).join(", ")}. Укажите значения ниже
            или в <Link href="/company">сведениях о компании</Link>.</p>
        </div>
      )}
      <div className={styles.own}>
        {FIELDS[kind].map((f) => (
          <label key={f.key} className={forms.field}>{f.label}
            <input className={forms.input} inputMode="decimal" placeholder="по данным" value={own[f.key] ?? ""}
              onChange={(e) => setOwn({ ...own, [f.key]: e.target.value })} />
          </label>
        ))}
      </div>
      <p className={common.muted}>Оценка чувствительности по прозрачной формуле, а не инвестиционная рекомендация.</p>
      {error && <p className={styles.loss}>{error}</p>}
    </Card>
  );
}
