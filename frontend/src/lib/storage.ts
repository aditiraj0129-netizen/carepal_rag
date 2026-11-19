import type { Conversation } from "./types";

const KEY = "carepal-assist:conversations:v1";
const MAX = 30;

export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const list = JSON.parse(raw) as Conversation[];
    // A reload mid-stream leaves a half-written message; mark it instead of showing a spinner forever.
    return list.map((c) => ({
      ...c,
      messages: c.messages.map((m) => (m.streaming ? { ...m, streaming: false, error: m.error ?? "interrupted" } : m)),
    }));
  } catch { return []; }
}

export function saveConversations(list: Conversation[]): void {
  try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX))); } catch { /* storage full or blocked */ }
}

export function clearConversations(): void {
  try { localStorage.removeItem(KEY); } catch { /* ignore */ }
}

export function newId(): string {
  const r = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now();
  return "s-" + r.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 40);
}
