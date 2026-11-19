import { timeAgo } from "../lib/format";
import type { Strings } from "../lib/i18n";
import type { Conversation } from "../lib/types";
import { IconChat, IconClose, IconHistory, IconPlus, IconTrash } from "./Icons";

interface Props {
  t: Strings; conversations: Conversation[]; activeId: string; disabled: boolean;
  onSelect: (id: string) => void; onNew: () => void; onDelete: (id: string) => void; onClear: () => void; onClose: () => void;
}

export function Sidebar({ t, conversations, activeId, disabled, onSelect, onNew, onDelete, onClear, onClose }: Props) {
  return (
    <div className="flex h-full flex-col bg-white">
      <div className="flex items-center justify-between gap-2 border-b border-navy-100 px-4 py-3">
        <div className="flex items-center gap-2 font-display text-sm font-bold text-navy-900"><IconHistory width={18} height={18} className="text-brand-700" />{t.history}</div>
        <button type="button" onClick={onClose} aria-label="Close history" className="grid h-9 w-9 place-items-center rounded-lg text-navy-600 hover:bg-navy-100 lg:hidden"><IconClose /></button>
      </div>
      <div className="p-3">
        <button type="button" className="btn-primary w-full" onClick={onNew} disabled={disabled}><IconPlus width={18} height={18} />{t.newChat}</button>
      </div>
      <nav aria-label={t.history} className="flex-1 overflow-y-auto px-2 pb-2">
        {conversations.length === 0 ? (
          <div className="mx-2 mt-6 rounded-2xl border border-dashed border-navy-200 p-5 text-center">
            <span className="mx-auto grid h-11 w-11 place-items-center rounded-full bg-brand-50 text-brand-700"><IconChat /></span>
            <div className="mt-3 font-display text-sm font-bold text-navy-800">{t.noHistoryTitle}</div>
            <p className="mt-1 text-sm leading-relaxed text-navy-500">{t.noHistoryBody}</p>
          </div>
        ) : (
          <ul className="space-y-1">
            {[...conversations].sort((a, b) => b.updatedAt - a.updatedAt).map((c) => (
              <li key={c.id} className={`group flex items-center rounded-xl ${c.id === activeId ? "bg-brand-50 ring-1 ring-brand-200" : "hover:bg-navy-50"}`}>
                <button type="button" onClick={() => onSelect(c.id)} disabled={disabled && c.id !== activeId} aria-current={c.id === activeId ? "true" : undefined} className="min-w-0 flex-1 px-3 py-2.5 text-left">
                  <span className="block truncate text-sm font-semibold text-navy-900">{c.title || t.newChat}</span>
                  <span className="block text-xs text-navy-500">{timeAgo(c.updatedAt)} · {c.messages.filter((m) => m.role === "user").length}</span>
                </button>
                <button type="button" onClick={() => onDelete(c.id)} aria-label={`${t.deleteChat}: ${c.title}`} disabled={disabled && c.id === activeId} className="mr-1 grid h-9 w-9 shrink-0 place-items-center rounded-lg text-navy-400 hover:bg-alert-100 hover:text-alert-700 focus-visible:text-alert-700 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100">
                  <IconTrash width={17} height={17} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </nav>
      {conversations.length > 0 && (
        <div className="border-t border-navy-100 p-3 pb-safe">
          <button type="button" className="btn-ghost w-full !text-alert-700 hover:!bg-alert-50" onClick={() => { if (window.confirm(t.clearHistory + "?")) onClear(); }} disabled={disabled}><IconTrash width={16} height={16} />{t.clearHistory}</button>
        </div>
      )}
    </div>
  );
}
