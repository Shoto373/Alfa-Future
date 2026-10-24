"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { useLoad } from "@/lib/hooks";
import type { BankOffer } from "@/lib/types";
import styles from "@/components/InsightView.module.scss";
import common from "@/styles/common.module.scss";
import forms from "@/styles/forms.module.scss";

const STATUS: Record<string, string> = { new: "отправлена", in_progress: "менеджер работает", done: "обсуждено", declined: "закрыта" };

/** Предложение банка (SPR4-06): только при выявленной потребности, с пометкой «Реклама банка» — отдельно от выводов
 *  AI и позиции банка. «Обсудить с менеджером» отправляет заявку только после явного согласия. */
export default function BankOffers({ insightId }: { insightId: string }) {
  const { data, reload } = useLoad((s) => api.insightOffers(insightId, s), [insightId]);
  const [asking, setAsking] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const [comment, setComment] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!data || data.offers.length === 0) return null;
  const sent = new Map(data.leads.map((l) => [l.offer_id, l.status]));

  const send = async (offer: BankOffer) => {
    setBusy(true);
    setStatus(null);
    try {
      const r = await api.createLead({ insight_id: insightId, offer_id: offer.offer_id, consent: true, comment: comment.trim() || null });
      setStatus(r.managers ? "Заявка отправлена — менеджер свяжется с вами." : "Заявка сохранена — ее увидит закрепленный за компанией менеджер.");
      setAsking(null);
      reload();
    } catch (e) {
      setStatus(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.offers} data-testid="bank-offers">
      <span className={styles.offerLabel}>Реклама банка</span>
      {data.offers.map((o) => (
        <div className={styles.offer} key={o.offer_id}>
          <strong>{o.title}</strong>
          <span>{o.text}</span>
          <small className={common.muted}>Почему показано: {o.need.charAt(0).toLowerCase() + o.need.slice(1)} — {o.reason}.</small>
          {sent.has(o.offer_id) ? <small className={common.muted}>Заявка {STATUS[sent.get(o.offer_id)!] ?? sent.get(o.offer_id)}.</small>
            : asking === o.offer_id ? (
              <div className={styles.consent}>
                <label className={forms.check}><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                  {data.consent_text}</label>
                <input className={forms.input} placeholder="Комментарий для менеджера (необязательно)" maxLength={500}
                  value={comment} onChange={(e) => setComment(e.target.value)} />
                <div className={styles.consentActions}>
                  <button type="button" className={`${common.btn} ${common.btnPrimary} ${common.btnSm}`} disabled={!consent || busy}
                    onClick={() => send(o)}>Отправить менеджеру</button>
                  <button type="button" className={`${common.btn} ${common.btnSecondary} ${common.btnSm}`} onClick={() => setAsking(null)}>Отмена</button>
                </div>
              </div>
            ) : (
              <button type="button" className={`${common.btn} ${common.btnSecondary} ${common.btnSm} ${styles.offerAsk}`}
                onClick={() => { setAsking(o.offer_id); setConsent(false); setComment(""); }}>Обсудить с менеджером</button>
            )}
        </div>
      ))}
      {status && <p role="status" className={common.small}>{status}</p>}
    </div>
  );
}
