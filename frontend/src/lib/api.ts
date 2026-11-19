import type { Citation, EscalateResponse, Feedback, Health, HandoffOffer, Lang, Overview, RelatedPage, SupportRequestRow, UnansweredCluster } from "./types";

const BASE = "/api";

export class ApiError extends Error {
  constructor(public status: number, message: string, public requestId?: string | null) {
    super(message);
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let message = `Request failed (${res.status})`;
  let rid: string | null = res.headers.get("x-request-id");
  try {
    const j = await res.json();
    if (j?.error?.message) { message = j.error.message; rid = j.error.request_id ?? rid; }
    else if (Array.isArray(j?.detail)) message = j.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ") || message;
    else if (typeof j?.detail === "string") message = j.detail;
  } catch { /* non-JSON body */ }
  return new ApiError(res.status, message, rid);
}

async function request<T>(path: string, init: RequestInit = {}, adminKey?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (adminKey) headers.set("Authorization", `Bearer ${adminKey}`);
  let res: Response;
  try {
    res = await fetch(BASE + path, { ...init, headers });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "Can't reach the CarePal Assist server. Check your connection and try again.");
  }
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),
  feedback: (message_id: string, value: Feedback) =>
    request<{ status: string }>("/feedback", { method: "POST", body: JSON.stringify({ message_id, value }) }),
  escalate: (body: { session_id: string; name: string; phone: string; consent: boolean; reason: string; question?: string; language: Lang }) =>
    request<EscalateResponse>("/support/escalate", { method: "POST", body: JSON.stringify({ ...body, website: "" }) }),
  overview: (key: string) => request<Overview>("/admin/analytics", {}, key),
  unanswered: (key: string) => request<{ clusters: UnansweredCluster[] }>("/admin/unanswered?limit=50", {}, key),
  supportRequests: (key: string) => request<{ requests: SupportRequestRow[] }>("/admin/support-requests?limit=100", {}, key),
  ingest: (key: string, source: "snapshots" | "crawl", force: boolean) =>
    request<Record<string, unknown>>("/admin/ingest", { method: "POST", body: JSON.stringify({ source, force }) }, key),
  evaluate: (key: string, split: "dev" | "test" | "all") =>
    request<EvalResult>("/evaluation/run", { method: "POST", body: JSON.stringify({ split, modes: ["dense", "bm25", "hybrid"] }) }, key),
};

export interface EvalResult {
  split: string;
  n_questions: number;
  embedding_model: string;
  embedding_semantic: boolean;
  generator: string;
  retrieval: { n_answerable: number; modes: Record<string, { overall: Record<string, number> }> };
  answers: Record<string, unknown>;
  caveats: string[];
}

// ---------------------------------------------------------------- streaming chat (SSE over fetch)
export interface StreamHandlers {
  onMeta?: (d: { message_id: string; language: Lang; route: string }) => void;
  onToken?: (text: string) => void;
  onReplace?: (text: string) => void;
  onCitations?: (c: Citation[]) => void;
  onAbstain?: (reason: string) => void;
  onEmergency?: (numbers: string[]) => void;
  onRelated?: (pages: RelatedPage[]) => void;
  onHandoff?: (o: HandoffOffer) => void;
  onDone?: (d: { outcome: string; generator: string; timings_ms?: Record<string, number> }) => void;
}

/** Parse a block of SSE text ("event: x\ndata: {...}") into events. Exported for unit tests. */
export function parseSseBlock(block: string): { event: string; data: unknown } | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (!data.length) return null;
  try { return { event, data: JSON.parse(data.join("\n")) }; } catch { return null; }
}

export async function streamChat(
  body: { session_id: string; message: string },
  h: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(BASE + "/chat/stream", {
      method: "POST", signal, headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "Can't reach the CarePal Assist server. Check your connection and try again.");
  }
  if (!res.ok) throw await parseError(res);
  if (!res.body) throw new ApiError(0, "The server sent an empty response.");

  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let sawDone = false;
  const dispatch = (ev: { event: string; data: any }) => { // eslint-disable-line @typescript-eslint/no-explicit-any
    const d = ev.data;
    switch (ev.event) {
      case "meta": h.onMeta?.(d); break;
      case "token": h.onToken?.(d.text); break;
      case "replace": h.onReplace?.(d.text); break;
      case "citations": h.onCitations?.(d.citations); break;
      case "abstain": h.onAbstain?.(d.reason); break;
      case "emergency": h.onEmergency?.(d.numbers); break;
      case "related": h.onRelated?.(d.pages); break;
      case "handoff_offer": h.onHandoff?.(d); break;
      case "done": sawDone = true; h.onDone?.(d); break;
      case "error": throw new ApiError(500, "Something went wrong while answering. Please try again.", d?.request_id);
    }
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const ev = parseSseBlock(buf.slice(0, idx));
      buf = buf.slice(idx + 2);
      if (ev) dispatch(ev as { event: string; data: unknown });
    }
  }
  if (!sawDone) throw new ApiError(0, "The connection ended before the answer finished. Please try again.");
}
