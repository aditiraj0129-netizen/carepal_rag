import { useCallback, useEffect, useRef, useState } from "react";
import { useChat } from "../hooks/useChat";
import { api } from "../lib/api";
import { STRINGS } from "../lib/i18n";
import type { Citation, Health, Lang } from "../lib/types";
import { Composer } from "./Composer";
import { EscalationDialog } from "./EscalationDialog";
import { Header } from "./Header";
import { MessageBubble } from "./MessageBubble";
import { Sidebar } from "./Sidebar";
import { SourcePanel } from "./SourcePanel";
import { Welcome } from "./Welcome";

function loadLang(): Lang {
  try { const v = localStorage.getItem("carepal-assist:ui-lang"); if (v === "en" || v === "hi" || v === "hinglish") return v; } catch { /* ignore */ }
  return "en";
}

export function ChatPage() {
  const chat = useChat();
  const [lang, setLangState] = useState<Lang>(loadLang);
  const t = STRINGS[lang];
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [source, setSource] = useState<Citation | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [escalation, setEscalation] = useState<{ reason: string; question?: string } | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const setLang = (l: Lang) => { setLangState(l); try { localStorage.setItem("carepal-assist:ui-lang", l); } catch { /* ignore */ } document.documentElement.lang = l === "hi" ? "hi" : "en"; };

  useEffect(() => {
    let alive = true;
    api.health().then((h) => { if (alive) { setHealth(h); setHealthError(false); } }).catch(() => alive && setHealthError(true));
    return () => { alive = false; };
  }, []);

  // Keep the newest content in view while streaming.
  const last = chat.active.messages[chat.active.messages.length - 1];
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [chat.active.messages.length, last?.text, last?.streaming]);
  useEffect(() => { setSource(null); }, [chat.active.id]);

  const ask = useCallback((q: string) => void chat.send(q), [chat]);
  const lastBotLang = [...chat.active.messages].reverse().find((m) => m.role === "assistant" && m.language)?.language;
  const escLang: Lang = lastBotLang ?? lang;
  const disabled = healthError || (health !== null && !health.index_ready);
  const empty = chat.active.messages.length === 0;

  return (
    <div className="flex h-[100dvh] flex-col">
      <Header t={t} lang={lang} onLang={setLang} health={health} healthError={healthError} busy={chat.busy}
        onHistory={() => setHistoryOpen(true)} onNew={chat.newChat} onHuman={() => setEscalation({ reason: "wants_human" })} />

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-72 shrink-0 border-r border-navy-100 lg:block">
          <Sidebar t={t} conversations={chat.conversations} activeId={chat.active.id} disabled={chat.busy}
            onSelect={chat.select} onNew={chat.newChat} onDelete={chat.remove} onClear={chat.clearAll} onClose={() => undefined} />
        </aside>

        {historyOpen && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <div className="absolute inset-0 animate-fade bg-navy-900/40" onClick={() => setHistoryOpen(false)} aria-hidden />
            <div className="absolute inset-y-0 left-0 w-[85%] max-w-xs animate-rise shadow-pop">
              <Sidebar t={t} conversations={chat.conversations} activeId={chat.active.id} disabled={chat.busy}
                onSelect={(id) => { chat.select(id); setHistoryOpen(false); }} onNew={() => { chat.newChat(); setHistoryOpen(false); }}
                onDelete={chat.remove} onClear={chat.clearAll} onClose={() => setHistoryOpen(false)} />
            </div>
          </div>
        )}

        <main className="flex min-w-0 flex-1 flex-col bg-gradient-to-b from-white to-navy-50">
          {(healthError || (health && !health.index_ready)) && (
            <div role="alert" className="border-b border-warm-100 bg-warm-50 px-4 py-2.5 text-center text-sm font-medium text-warm-700">
              {healthError ? `${t.serverDown}. ` : `${t.indexNotReady} `}
              <button type="button" className="font-semibold underline" onClick={() => { setHealthError(false); api.health().then(setHealth).catch(() => setHealthError(true)); }}>{t.retry}</button>
            </div>
          )}
          <div className="flex-1 overflow-y-auto" aria-live="off">
            {empty ? (
              <Welcome t={t} onAsk={ask} disabled={chat.busy || disabled} />
            ) : (
              <div className="mx-auto w-full max-w-3xl space-y-5 px-3 py-6 sm:px-6" role="log" aria-label="Conversation">
                {chat.active.messages.map((m, i, arr) => (
                  <MessageBubble key={m.id} msg={m} t={t} isLast={i === arr.length - 1 && !chat.busy}
                    precedingQuestion={arr[i - 1]?.role === "user" ? arr[i - 1].text : undefined}
                    onOpenSource={setSource} onEscalate={(reason, question) => setEscalation({ reason, question })}
                    onRate={(msg, v) => (msg.messageId ? chat.rate(msg.id, msg.messageId, v) : Promise.resolve(false))} onRetry={chat.retryLast} />
                ))}
                <div ref={endRef} />
              </div>
            )}
          </div>
          <Composer t={t} busy={chat.busy} disabled={disabled} onSend={ask} onStop={chat.stop} focusKey={chat.active.id} />
        </main>

        {source && <SourcePanel source={source} t={t} onClose={() => setSource(null)} />}
      </div>

      {escalation && (
        <EscalationDialog t={t} sessionId={chat.active.id} reason={escalation.reason} question={escalation.question} language={escLang} onClose={() => setEscalation(null)} />
      )}
    </div>
  );
}
