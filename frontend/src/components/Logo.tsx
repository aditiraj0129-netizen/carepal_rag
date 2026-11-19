import { IconHeart } from "./Icons";

export function LogoMark({ size = 36 }: { size?: number }) {
  return (
    <span className="grid shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-sm" style={{ width: size, height: size }} aria-hidden>
      <IconHeart width={size * 0.55} height={size * 0.55} fill="currentColor" strokeWidth={1.2} />
    </span>
  );
}

export function Wordmark({ tagline }: { tagline?: string }) {
  return (
    <div className="flex items-center gap-2.5 min-w-0">
      <LogoMark />
      <div className="min-w-0 leading-tight">
        <div className="font-display text-[17px] font-extrabold tracking-tight text-navy-900">
          CarePal <span className="text-brand-700">Assist</span>
        </div>
        {tagline && <div className="hidden truncate text-xs text-navy-500 sm:block">{tagline}</div>}
      </div>
    </div>
  );
}
