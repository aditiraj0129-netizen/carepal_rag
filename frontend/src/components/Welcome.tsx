import type { Strings } from "../lib/i18n";
import { IconBook, IconHeart, IconShield, IconUser } from "./Icons";

export function Welcome({ t, onAsk, disabled }: { t: Strings; onAsk: (q: string) => void; disabled: boolean }) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-4 py-8 sm:py-12">
      <div className="animate-rise text-center">
        <span className="mx-auto grid h-16 w-16 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-card">
          <IconHeart width={32} height={32} fill="currentColor" strokeWidth={1.2} />
        </span>
        <h1 className="mt-5 font-display text-3xl font-extrabold leading-tight tracking-tight text-navy-900 sm:text-4xl">{t.welcomeTitle}</h1>
        <p className="mx-auto mt-3 max-w-xl text-base leading-relaxed text-navy-600">{t.welcomeBody}</p>
      </div>

      <div className="mt-8">
        <h2 className="mb-3 text-center text-xs font-semibold uppercase tracking-wider text-navy-500">{t.suggestedTitle}</h2>
        <ul className="grid gap-2.5 sm:grid-cols-2">
          {t.suggested.map((q, i) => (
            <li key={q} className={`animate-rise ${i === t.suggested.length - 1 && t.suggested.length % 2 === 1 ? "sm:col-span-2" : ""}`} style={{ animationDelay: `${i * 50}ms` }}>
              <button type="button" disabled={disabled} onClick={() => onAsk(q)}
                className="card flex h-full w-full items-center justify-between gap-3 px-4 py-3.5 text-left text-[15px] font-medium text-navy-800 transition hover:-translate-y-0.5 hover:border-brand-400 hover:bg-brand-50 disabled:opacity-50">
                <span>{q}</span>
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-brand-100 text-brand-800" aria-hidden>→</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <ul className="mt-8 grid gap-3 text-sm text-navy-600 sm:grid-cols-3">
        {[IconBook, IconShield, IconUser].map((Icon, i) => (
          <li key={i} className="flex items-center gap-2.5 rounded-xl bg-white/70 px-3 py-2.5"><Icon width={18} height={18} className="shrink-0 text-brand-700" />{t.trust[i]}</li>
        ))}
      </ul>
    </div>
  );
}
