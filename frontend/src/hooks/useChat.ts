import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, streamChat } from "../lib/api";
import { loadConversations, newId, saveConversations } from "../lib/storage";
import type { ChatMessage, Conversation, Feedback } from "../lib/types";

export const MAX_MESSAGE = 1000;

export function useChat() {
  const [convs, setConvs] = useState<Conversation[]>(loadConversations);
  const [activeId, setActiveId] = useState<string>(() => newId());
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Persist (debounced) so a refresh keeps history without writing on every streamed token.
  useEffect(() => {
    const t = setTimeout(() => saveConversations(convs), 300);
    return () => clearTimeout(t);
  }, [convs]);

  // Flush immediately if the tab is closed or reloaded inside the debounce window.
  const latest = useRef(convs);
  latest.current = convs;
  useEffect(() => {
    const flush = () => saveConversations(latest.current);
    window.addEventListener("pagehide", flush);
    return () => window.removeEventListener("pagehide", flush);
  }, []);

  const active: Conversation = useMemo(
    () => convs.find((c) => c.id === activeId) ?? { id: activeId, title: "", updatedAt: Date.now(), messages: [] },
    [convs, activeId],
  );

  const patchMessage = useCallback((convId: string, msgId: string, patch: Partial<ChatMessage> | ((m: ChatMessage) => Partial<ChatMessage>)) => {
    setConvs((all) => all.map((c) => c.id !== convId ? c : {
      ...c, updatedAt: Date.now(),
      messages: c.messages.map((m) => m.id !== msgId ? m : { ...m, ...(typeof patch === "function" ? patch(m) : patch) }),
    }));
  }, []);

  const send = useCallback(async (raw: string) => {
    const text = raw.trim();
    if (!text || busy || text.length > MAX_MESSAGE) return;
    const convId = activeId;
    const now = Date.now();
    const userMsg: ChatMessage = { id: newId(), role: "user", text, createdAt: now };
    const botId = newId();
    const bot: ChatMessage = { id: botId, role: "assistant", text: "", createdAt: now, streaming: true, citations: [], related: [] };

    setConvs((all) => {
      const existing = all.find((c) => c.id === convId);
      if (existing) return all.map((c) => c.id === convId ? { ...c, updatedAt: now, messages: [...c.messages, userMsg, bot] } : c);
      const title = text.length > 48 ? text.slice(0, 47) + "…" : text;
      return [{ id: convId, title, updatedAt: now, messages: [userMsg, bot] }, ...all];
    });

    const ctl = new AbortController();
    abortRef.current = ctl;
    setBusy(true);
    try {
      await streamChat({ session_id: convId, message: text }, {
        onMeta: (d) => patchMessage(convId, botId, { messageId: d.message_id, language: d.language, route: d.route }),
        onToken: (t) => patchMessage(convId, botId, (m) => ({ text: m.text + t })),
        onReplace: (t) => patchMessage(convId, botId, { text: t }),
        onCitations: (c) => patchMessage(convId, botId, { citations: c }),
        onAbstain: (r) => patchMessage(convId, botId, { abstainReason: r }),
        onEmergency: (n) => patchMessage(convId, botId, { emergencyNumbers: n }),
        onRelated: (p) => patchMessage(convId, botId, { related: p }),
        onHandoff: (o) => patchMessage(convId, botId, { handoff: o }),
        onDone: (d) => patchMessage(convId, botId, (m) => ({
          streaming: false, outcome: d.outcome, generator: d.generator, timingsMs: d.timings_ms, text: m.text.trim(),
        })),
      }, ctl.signal);
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        patchMessage(convId, botId, { streaming: false, error: "stopped" });
      } else {
        const msg = e instanceof ApiError ? e.message : "Something went wrong. Please try again.";
        patchMessage(convId, botId, { streaming: false, error: msg });
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }, [activeId, busy, patchMessage]);

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const newChat = useCallback(() => { if (!busy) setActiveId(newId()); }, [busy]);
  const select = useCallback((id: string) => { if (!busy) setActiveId(id); }, [busy]);

  const remove = useCallback((id: string) => {
    if (busy && id === activeId) return;
    setConvs((all) => all.filter((c) => c.id !== id));
    if (id === activeId) setActiveId(newId());
  }, [activeId, busy]);

  const clearAll = useCallback(() => {
    if (busy) return;
    setConvs([]);
    setActiveId(newId());
  }, [busy]);

  const rate = useCallback(async (msgId: string, backendId: string, value: Feedback): Promise<boolean> => {
    try {
      await api.feedback(backendId, value);
      patchMessage(activeId, msgId, { feedback: value });
      return true;
    } catch { return false; }
  }, [activeId, patchMessage]);

  const retryLast = useCallback(() => {
    const msgs = active.messages;
    const lastUser = [...msgs].reverse().find((m) => m.role === "user");
    if (!lastUser || busy) return;
    // Drop the failed assistant turn (and its user message) so the retry replaces it instead of duplicating.
    setConvs((all) => all.map((c) => c.id !== activeId ? c : { ...c, messages: c.messages.slice(0, c.messages.lastIndexOf(lastUser)) }));
    setTimeout(() => void send(lastUser.text), 0);
  }, [active.messages, activeId, busy, send]);

  return { conversations: convs, active, busy, send, stop, newChat, select, remove, clearAll, rate, retryLast };
}
