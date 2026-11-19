import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { MAX_MESSAGE } from "../hooks/useChat";
import type { Strings } from "../lib/i18n";
import { IconSend, IconStop } from "./Icons";

interface Props { t: Strings; busy: boolean; disabled?: boolean; onSend: (text: string) => void; onStop: () => void; focusKey: string }

export function Composer({ t, busy, disabled, onSend, onStop, focusKey }: Props) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { ref.current?.focus(); }, [focusKey]);
  useEffect(() => { // auto-grow up to ~6 lines
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [text]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const v = text.trim();
    if (!v || busy || disabled || v.length > MAX_MESSAGE) return;
    onSend(v);
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Don't send while an IME (Hindi keyboards) is composing a word.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
  };
  const left = MAX_MESSAGE - text.length;

  return (
    <form onSubmit={submit} className="border-t border-navy-100 bg-white/95 px-3 pt-3 pb-safe backdrop-blur sm:px-6">
      <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-navy-200 bg-white p-2 shadow-card focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-200">
        <label htmlFor="composer" className="sr-only">{t.placeholder}</label>
        <textarea id="composer" ref={ref} rows={1} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
          placeholder={t.placeholder} maxLength={MAX_MESSAGE + 200} lang="en"
          className="max-h-40 min-h-[2.5rem] flex-1 resize-none bg-transparent px-2 py-2 text-[16px] leading-snug text-navy-900 placeholder:text-navy-400 focus:outline-none focus-visible:ring-0 focus-visible:ring-offset-0" />
        {busy ? (
          <button type="button" onClick={onStop} aria-label={t.stop} className="grid h-10 shrink-0 place-items-center rounded-xl bg-navy-800 px-3 text-white hover:bg-navy-900"><IconStop width={18} height={18} /></button>
        ) : (
          <button type="submit" aria-label={t.send} disabled={!text.trim() || !!disabled || left < 0} className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-700 text-white hover:bg-brand-800 disabled:bg-navy-200 disabled:text-navy-500"><IconSend /></button>
        )}
      </div>
      <div className="mx-auto mt-1.5 flex max-w-3xl items-center justify-between px-1 text-xs text-navy-500">
        <span>{t.privacyNote}</span>
        {left < 150 && <span className={left < 0 ? "font-semibold text-alert-700" : ""} aria-live="polite">{left}</span>}
      </div>
    </form>
  );
}
