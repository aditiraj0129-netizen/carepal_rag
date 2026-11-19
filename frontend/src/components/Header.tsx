import { LANG_LABEL } from "../lib/i18n";
import type { Strings } from "../lib/i18n";
import type { Health, Lang } from "../lib/types";
import { IconChart, IconHistory, IconPlus, IconUser } from "./Icons";
import { Wordmark } from "./Logo";

interface Props {
  t: Strings; lang: Lang; onLang: (l: Lang) => void; health: Health | null; healthError: boolean;
  onHistory: () => void; onNew: () => void; onHuman: () => void; busy: boolean;
}

export function Header({ t, lang, onLang, health, healthError, onHistory, onNew, onHuman, busy }: Props) {
  const status = healthError ? { text: t.serverDown, cls: "bg-alert-50 text-alert-700" }
    : health === null ? { text: "…", cls: "bg-navy-100 text-navy-600" }
    : health.index_ready ? { text: `${health.chunks} chunks`, cls: "bg-brand-50 text-brand-800" }
    : { text: "Index not ready", cls: "bg-warm-50 text-warm-700" };

  return (
    <header className="sticky top-0 z-20 border-b border-navy-100 bg-white/95 backdrop-blur">
      <div className="flex items-center gap-2 px-3 py-2.5 sm:gap-3 sm:px-5">
        <button type="button" onClick={onHistory} aria-label={t.history} className="grid h-10 w-10 shrink-0 place-items-center rounded-xl text-navy-700 hover:bg-navy-100 lg:hidden"><IconHistory /></button>
        <Wordmark tagline={t.tagline} />
        <span className={`ml-1 hidden rounded-full px-2.5 py-1 text-xs font-semibold md:inline ${status.cls}`} title={health ? `${health.embedding_model} · ${health.generator}` : undefined}>{status.text}</span>
        <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
          <div role="group" aria-label="Interface language" className="flex rounded-xl bg-navy-100 p-0.5">
            {(Object.keys(LANG_LABEL) as Lang[]).map((l) => (
              <button key={l} type="button" onClick={() => onLang(l)} aria-pressed={lang === l}
                className={`rounded-[10px] px-2 py-1.5 text-xs font-semibold sm:px-3 sm:text-[13px] ${lang === l ? "bg-white text-brand-800 shadow-sm" : "text-navy-600 hover:text-navy-900"}`}>{LANG_LABEL[l]}</button>
            ))}
          </div>
          <button type="button" onClick={onHuman} className="btn-secondary hidden !px-3 md:inline-flex"><IconUser width={17} height={17} />{t.talkToHuman}</button>
          <button type="button" onClick={onHuman} aria-label={t.talkToHuman} className="grid h-10 w-10 place-items-center rounded-xl border border-navy-200 text-navy-700 hover:bg-navy-50 md:hidden"><IconUser /></button>
          <button type="button" onClick={onNew} disabled={busy} aria-label={t.newChat} className="grid h-10 w-10 place-items-center rounded-xl border border-navy-200 text-navy-700 hover:bg-navy-50 disabled:opacity-50 lg:hidden"><IconPlus /></button>
          <a href="#/admin" aria-label="Admin dashboard" title="Admin dashboard" className="hidden h-10 w-10 place-items-center rounded-xl text-navy-500 hover:bg-navy-100 sm:grid"><IconChart /></a>
        </div>
      </div>
    </header>
  );
}
