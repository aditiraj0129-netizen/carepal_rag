import { useEffect, useRef } from "react";
import { pageLabel } from "../lib/format";
import type { Strings } from "../lib/i18n";
import type { Citation } from "../lib/types";
import { IconBook, IconClose, IconExternal } from "./Icons";

export function SourcePanel({ source, t, onClose }: { source: Citation; t: Strings; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, source.chunk_id]);

  const live = source.provenance === "scraped_html";
  return (
    <>
      <div className="fixed inset-0 z-30 animate-fade bg-navy-900/40 lg:hidden" onClick={onClose} aria-hidden />
      <aside role="dialog" aria-label={t.sourcePreview}
        className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md animate-slide flex-col border-l border-navy-100 bg-white shadow-pop lg:static lg:z-auto lg:w-[22rem] lg:max-w-none lg:animate-none lg:shadow-none xl:w-[24rem]">
        <div className="flex items-center justify-between border-b border-navy-100 px-4 py-3">
          <div className="flex items-center gap-2 font-display text-sm font-bold text-navy-900"><IconBook width={18} height={18} className="text-brand-700" />{t.sourcePreview}</div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close" className="grid h-9 w-9 place-items-center rounded-lg text-navy-600 hover:bg-navy-100"><IconClose /></button>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <div>
            <h2 className="mt-0 font-display text-lg font-bold leading-snug text-navy-900">{source.title}</h2>
            {source.section && <p className="mt-0.5 text-sm text-navy-500">{t.section}: {source.section}</p>}
          </div>
          <blockquote className="rounded-xl border-l-4 border-brand-500 bg-brand-50 p-3.5 text-[15px] leading-relaxed text-navy-800">{source.snippet}</blockquote>
          <div className={`rounded-xl px-3 py-2 text-xs font-medium ${live ? "bg-brand-50 text-brand-800" : "bg-warm-50 text-warm-700"}`}>
            {live ? t.fromSite : t.fromSummary}
          </div>
          <dl className="text-xs text-navy-500">
            <dt className="font-semibold uppercase tracking-wide">URL</dt>
            <dd className="mt-0.5 break-all text-navy-700">{source.url}</dd>
            <dt className="mt-2 font-semibold uppercase tracking-wide">Page</dt>
            <dd className="mt-0.5 text-navy-700">{pageLabel(source.url)}</dd>
          </dl>
        </div>
        <div className="border-t border-navy-100 p-4 pb-safe">
          <a href={source.url} target="_blank" rel="noopener noreferrer" className="btn-primary w-full">{t.openPage}<IconExternal width={16} height={16} /></a>
        </div>
      </aside>
    </>
  );
}
