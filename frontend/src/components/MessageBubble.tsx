import { Fragment, useState, type ReactNode } from "react";
import { pageLabel, humanize } from "../lib/format";
import type { Strings } from "../lib/i18n";
import type { ChatMessage, Citation, Feedback } from "../lib/types";
import { IconAlert, IconBook, IconCheck, IconCopy, IconExternal, IconHeart, IconRefresh, IconThumbDown, IconThumbUp, IconUser } from "./Icons";

interface Props {
  msg: ChatMessage;
  t: Strings;
  isLast: boolean;
  onOpenSource: (c: Citation) => void;
  onEscalate: (reason: string, question?: string) => void;
  onRate: (msg: ChatMessage, v: Feedback) => Promise<boolean>;
  onRetry: () => void;
  precedingQuestion?: string;
}

/** Turns "[S1]" markers into buttons that open the matching source; leaves unknown markers as plain text. */
function renderInline(line: string, byAlias: Map<string, Citation>, num: Map<string, number>, open: (c: Citation) => void): ReactNode[] {
  return line.split(/(\[S\d+\])/g).map((part, i) => {
    const m = /^\[(S\d+)\]$/.exec(part);
    const c = m ? byAlias.get(m[1]) : undefined;
    if (!c) return <Fragment key={i}>{part}</Fragment>;
    return (
      <button key={i} type="button" onClick={() => open(c)} aria-label={`Source ${num.get(m![1])}: ${c.title}`}
        className="mx-0.5 inline-flex h-5 min-w-[1.25rem] -translate-y-px items-center justify-center rounded-md bg-brand-100 px-1 align-middle text-[11px] font-bold text-brand-800 hover:bg-brand-200">
        {num.get(m![1])}
      </button>
    );
  });
}

/** Backend aliases (S2, S3…) can skip numbers; show readers 1, 2, 3 in citation order. */
function displayNumbers(citations: Citation[]): Map<string, number> {
  return new Map(citations.map((c, i) => [c.alias, i + 1]));
}

function AnswerText({ text, citations, open }: { text: string; citations: Citation[]; open: (c: Citation) => void }) {
  const byAlias = new Map(citations.map((c) => [c.alias, c]));
  const num = displayNumbers(citations);
  const blocks = text.split(/\n{2,}/);
  return (
    <div className="space-y-3 text-[15px] leading-relaxed">
      {blocks.map((b, i) => {
        const lines = b.split("\n");
        if (lines.every((l) => /^\s*[-•*]\s+/.test(l))) {
          return <ul key={i} className="list-disc space-y-1 pl-5">{lines.map((l, j) => <li key={j}>{renderInline(l.replace(/^\s*[-•*]\s+/, ""), byAlias, num, open)}</li>)}</ul>;
        }
        return <p key={i} className="whitespace-pre-wrap">{renderInline(b, byAlias, num, open)}</p>;
      })}
    </div>
  );
}

function ThinkingDots({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-navy-500" role="status" aria-live="polite">
      <span className="flex gap-1" aria-hidden>
        {[0, 1, 2].map((i) => <span key={i} className="h-2 w-2 animate-dots rounded-full bg-brand-500" style={{ animationDelay: `${i * 0.16}s` }} />)}
      </span>
      {label}
    </div>
  );
}

export function MessageBubble({ msg, t, isLast, onOpenSource, onEscalate, onRate, onRetry, precedingQuestion }: Props) {
  const [copied, setCopied] = useState(false);
  const [fbError, setFbError] = useState(false);

  if (msg.role === "user") {
    return (
      <div className="flex animate-rise justify-end gap-2.5">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-brand-700 px-4 py-2.5 text-[15px] leading-relaxed text-white shadow-sm sm:max-w-[75%]">
          <p className="whitespace-pre-wrap break-words">{msg.text}</p>
        </div>
        <span className="mt-1 hidden h-8 w-8 shrink-0 place-items-center rounded-full bg-navy-100 text-navy-600 sm:grid"><IconUser width={18} height={18} /></span>
      </div>
    );
  }

  const citations = msg.citations ?? [];
  const num = displayNumbers(citations);
  const showSources = !msg.streaming && citations.length > 0;
  const waiting = msg.streaming && !msg.text;
  const lowConfidence = msg.outcome === "answered_low_confidence";
  const abstained = !!msg.abstainReason || msg.outcome === "abstained" || msg.outcome === "fallback";
  const canRate = !msg.streaming && !msg.error && !!msg.messageId;

  const copy = async () => {
    try { await navigator.clipboard.writeText(msg.text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard blocked */ }
  };
  const rate = async (v: Feedback) => { setFbError(false); if (!(await onRate(msg, v))) setFbError(true); };

  return (
    <div className="flex animate-rise gap-2.5">
      <span className="mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand-500 to-brand-700 text-white"><IconHeart width={16} height={16} fill="currentColor" strokeWidth={1.2} /></span>
      <div className="min-w-0 max-w-[92%] flex-1 sm:max-w-[82%]">
        {msg.emergencyNumbers && msg.emergencyNumbers.length > 0 && (
          <div role="alert" className="mb-2 rounded-2xl border border-alert-600/30 bg-alert-50 p-4">
            <div className="flex items-center gap-2 font-semibold text-alert-700"><IconAlert width={20} height={20} />{t.emergencyTitle}</div>
            <p className="mt-1 text-sm text-navy-700">{t.emergencyBody}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {msg.emergencyNumbers.map((n) => (
                <a key={n} href={`tel:${n}`} className="inline-flex items-center gap-1.5 rounded-xl bg-alert-600 px-4 py-2 text-base font-bold text-white hover:bg-alert-700">
                  <IconAlert width={16} height={16} />{n}
                </a>
              ))}
            </div>
          </div>
        )}

        <div className="card rounded-tl-md px-4 py-3">
          {waiting && <ThinkingDots label={t.searching} />}
          {msg.text && <AnswerText text={msg.text} citations={citations} open={onOpenSource} />}
          {msg.streaming && msg.text && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-brand-500 align-middle" aria-hidden />}
          {msg.error && (
            <div role="alert" className={`${msg.text ? "mt-3 " : ""}flex flex-wrap items-center gap-3 rounded-xl bg-warm-50 px-3 py-2 text-sm text-warm-700`}>
              <IconAlert width={18} height={18} />
              <span className="flex-1">{msg.error === "interrupted" ? t.interrupted : msg.error === "stopped" ? t.stopped : msg.error}</span>
              {isLast && <button type="button" onClick={onRetry} className="inline-flex items-center gap-1 font-semibold underline"><IconRefresh width={14} height={14} />{t.retry}</button>}
            </div>
          )}
        </div>

        {showSources && (
          <div className="mt-2">
            <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-navy-500"><IconBook width={14} height={14} />{t.sources}</div>
            <ul className="flex flex-wrap gap-2">
              {citations.map((c) => (
                <li key={c.alias + c.chunk_id}>
                  <button type="button" onClick={() => onOpenSource(c)}
                    className="group flex max-w-[16rem] items-center gap-2 rounded-xl border border-navy-100 bg-white px-2.5 py-1.5 text-left text-xs shadow-sm hover:border-brand-400 hover:bg-brand-50">
                    <span className="grid h-5 w-5 shrink-0 place-items-center rounded-md bg-brand-100 text-[11px] font-bold text-brand-800">{num.get(c.alias)}</span>
                    <span className="min-w-0">
                      <span className="block truncate font-semibold text-navy-800">{c.title}</span>
                      <span className="block truncate text-navy-500">{c.section || pageLabel(c.url)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {!msg.streaming && abstained && (msg.related?.length ?? 0) > 0 && (
          <div className="mt-2">
            <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-navy-500">{t.closestPages}</div>
            <ul className="flex flex-wrap gap-2">
              {msg.related!.map((p) => (
                <li key={p.url}>
                  <a href={p.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-xl border border-navy-100 bg-white px-3 py-1.5 text-xs font-semibold text-navy-700 hover:border-brand-400 hover:bg-brand-50">
                    {p.title}<IconExternal width={13} height={13} />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}

        {!msg.streaming && (msg.handoff || lowConfidence) && (
          <div className="mt-3 rounded-2xl border border-brand-200 bg-brand-50 p-3.5">
            <div className="text-sm font-semibold text-brand-900">{t.humanOfferTitle}</div>
            <div className="mt-2.5 flex flex-wrap gap-2">
              <button type="button" className="btn-primary" onClick={() => onEscalate(msg.handoff?.reason ?? "low_confidence", precedingQuestion)}>
                <IconUser width={16} height={16} />{t.talkToHuman}
              </button>
              {msg.handoff?.whatsapp_url && (
                <a className="btn-secondary" href={msg.handoff.whatsapp_url} target="_blank" rel="noopener noreferrer">
                  WhatsApp<IconExternal width={14} height={14} />
                </a>
              )}
            </div>
          </div>
        )}

        {canRate && (
          <div className="mt-2 flex flex-wrap items-center gap-1 text-xs text-navy-500">
            {msg.feedback ? (
              <span className="inline-flex items-center gap-1.5 font-medium text-brand-700"><IconCheck width={15} height={15} />{t.thanks}</span>
            ) : (
              <>
                <span className="mr-1">{t.helpful}</span>
                <button type="button" aria-label="Helpful" onClick={() => rate(1)} className="grid h-8 w-8 place-items-center rounded-lg hover:bg-brand-100 hover:text-brand-800"><IconThumbUp width={17} height={17} /></button>
                <button type="button" aria-label="Not helpful" onClick={() => rate(-1)} className="grid h-8 w-8 place-items-center rounded-lg hover:bg-alert-100 hover:text-alert-700"><IconThumbDown width={17} height={17} /></button>
              </>
            )}
            <button type="button" onClick={copy} className="ml-1 inline-flex h-8 items-center gap-1 rounded-lg px-2 hover:bg-navy-100">
              {copied ? <IconCheck width={15} height={15} /> : <IconCopy width={15} height={15} />}{copied ? t.copied : t.copy}
            </button>
            {fbError && <span role="alert" className="text-alert-700">{t.feedbackFailed}</span>}
            {msg.route && msg.route !== "in_scope" && <span className="ml-auto rounded-full bg-navy-100 px-2 py-0.5 text-[11px] font-medium text-navy-600">{humanize(msg.route)}</span>}
          </div>
        )}
      </div>
    </div>
  );
}
