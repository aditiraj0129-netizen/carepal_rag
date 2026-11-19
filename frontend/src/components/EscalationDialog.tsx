import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { normalizeIndianMobile, validateName } from "../lib/phone";
import type { Strings } from "../lib/i18n";
import type { EscalateResponse, Lang } from "../lib/types";
import { IconCheck, IconClose, IconCopy, IconExternal, IconShield } from "./Icons";

const WHATSAPP = "https://wa.me/917855816586";

interface Props { t: Strings; sessionId: string; reason: string; question?: string; language: Lang; onClose: () => void }

export function EscalationDialog({ t, sessionId, reason, question, language, onClose }: Props) {
  const e = t.escalation;
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [consent, setConsent] = useState(false);
  const [touched, setTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [done, setDone] = useState<EscalateResponse | null>(null);
  const [copied, setCopied] = useState(false);
  const firstRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    firstRef.current?.focus();
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape" && !submitting) onClose();
      if (ev.key === "Tab" && dialogRef.current) { // keep focus inside the dialog
        const f = dialogRef.current.querySelectorAll<HTMLElement>("button, a[href], input, textarea");
        const list = [...f].filter((x) => !x.hasAttribute("disabled"));
        if (!list.length) return;
        const first = list[0], last = list[list.length - 1];
        if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
        else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, submitting]);

  const cleanName = validateName(name);
  const cleanPhone = normalizeIndianMobile(phone);
  const nameErr = touched && !cleanName ? e.nameError : null;
  const phoneErr = touched && !cleanPhone ? e.phoneError : null;
  const consentErr = touched && !consent ? e.consentError : null;

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    setTouched(true);
    setServerError(null);
    if (!cleanName || !cleanPhone || !consent) return;
    setSubmitting(true);
    try {
      const res = await api.escalate({ session_id: sessionId, name: cleanName, phone: cleanPhone, consent, reason, question, language });
      setDone(res);
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally { setSubmitting(false); }
  }

  const copyId = async () => {
    if (!done) return;
    try { await navigator.clipboard.writeText(done.request_id); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* blocked */ }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-navy-900/50 sm:items-center sm:p-4" onMouseDown={(ev) => { if (ev.target === ev.currentTarget && !submitting) onClose(); }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="esc-title" className="flex max-h-[94vh] w-full max-w-lg animate-rise flex-col rounded-t-3xl bg-white shadow-pop sm:rounded-3xl">
        <div className="flex items-start justify-between gap-3 border-b border-navy-100 px-5 py-4">
          <h2 id="esc-title" className="font-display text-xl font-bold text-navy-900">{done ? e.doneTitle : e.title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-navy-600 hover:bg-navy-100"><IconClose /></button>
        </div>

        {done ? (
          <div className="space-y-4 overflow-y-auto px-5 py-5">
            <div className="flex items-center gap-2 text-brand-700"><span className="grid h-9 w-9 place-items-center rounded-full bg-brand-100"><IconCheck /></span><span className="font-semibold">{e.doneTitle}</span></div>
            <div className="rounded-2xl border border-brand-200 bg-brand-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-brand-800">{e.requestId}</div>
              <div className="mt-1 flex items-center justify-between gap-3">
                <code className="font-mono text-xl font-bold tracking-wide text-navy-900" data-testid="request-id">{done.request_id}</code>
                <button type="button" onClick={copyId} className="btn-secondary !px-3 !py-1.5 text-xs">{copied ? <IconCheck width={15} height={15} /> : <IconCopy width={15} height={15} />}{copied ? t.copied : t.copy}</button>
              </div>
            </div>
            {/* Confirmation text comes verbatim from the server so the UI never claims more than the backend did. */}
            <div>
              <div className="text-sm font-semibold text-navy-800">{e.whatNext}</div>
              <p className="mt-1 text-[15px] leading-relaxed text-navy-700">{done.message}</p>
              {done.duplicate && <p className="mt-2 text-sm text-warm-700">{e.duplicate}</p>}
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <a className="btn-secondary flex-1" href={WHATSAPP} target="_blank" rel="noopener noreferrer">{e.whatsapp}<IconExternal width={15} height={15} /></a>
              <button type="button" className="btn-primary flex-1" onClick={onClose}>{e.close}</button>
            </div>
          </div>
        ) : (
          <form onSubmit={submit} noValidate className="space-y-4 overflow-y-auto px-5 py-5">
            <div className="rounded-2xl bg-navy-50 p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-navy-800"><IconShield width={18} height={18} className="text-brand-700" />{e.whyTitle}</div>
              <p className="mt-1.5 text-sm leading-relaxed text-navy-700">{e.why}</p>
              <p className="mt-2 rounded-lg bg-warm-50 px-2.5 py-1.5 text-xs font-medium text-warm-700">{e.honest}</p>
            </div>

            <div>
              <label htmlFor="esc-name" className="mb-1 block text-sm font-semibold text-navy-800">{e.name}</label>
              <input id="esc-name" ref={firstRef} className={`input ${nameErr ? "!border-alert-600" : ""}`} value={name} onChange={(x) => setName(x.target.value)} autoComplete="name" maxLength={80} aria-invalid={!!nameErr} aria-describedby={nameErr ? "esc-name-err" : undefined} />
              {nameErr && <p id="esc-name-err" role="alert" className="mt-1 text-sm text-alert-700">{nameErr}</p>}
            </div>

            <div>
              <label htmlFor="esc-phone" className="mb-1 block text-sm font-semibold text-navy-800">{e.phone}</label>
              <input id="esc-phone" type="tel" inputMode="tel" className={`input ${phoneErr ? "!border-alert-600" : ""}`} value={phone} onChange={(x) => setPhone(x.target.value)} autoComplete="tel" maxLength={20} placeholder="98765 43210" aria-invalid={!!phoneErr} aria-describedby="esc-phone-hint" />
              <p id="esc-phone-hint" className={`mt-1 text-sm ${phoneErr ? "text-alert-700" : "text-navy-500"}`} role={phoneErr ? "alert" : undefined}>{phoneErr ?? e.phoneHint}</p>
            </div>

            <div>
              <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-navy-200 p-3 hover:bg-navy-50">
                <input type="checkbox" className="mt-0.5 h-5 w-5 shrink-0 accent-brand-700" checked={consent} onChange={(x) => setConsent(x.target.checked)} aria-invalid={!!consentErr} />
                <span className="text-sm leading-relaxed text-navy-800">{e.consent}</span>
              </label>
              {consentErr && <p role="alert" className="mt-1 text-sm text-alert-700">{consentErr}</p>}
            </div>

            {serverError && <div role="alert" className="rounded-xl bg-alert-50 px-3 py-2 text-sm text-alert-700">{serverError}</div>}

            <div className="flex flex-col-reverse gap-2 pb-safe sm:flex-row sm:justify-end">
              <button type="button" className="btn-ghost" onClick={onClose} disabled={submitting}>{e.cancel}</button>
              <button type="submit" className="btn-primary" disabled={submitting}>{submitting ? e.submitting : e.submit}</button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
