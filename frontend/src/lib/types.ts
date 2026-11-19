export type Lang = "en" | "hi" | "hinglish";

export interface Citation {
  alias: string;
  chunk_id: string;
  title: string;
  url: string;
  section: string;
  snippet: string;
  /** scraped_html = text crawled from the site; research_summary = paraphrased snapshot */
  provenance: string;
}

export interface RelatedPage { title: string; url: string; provenance?: string }

export interface HandoffOffer {
  reason: string;
  priority: string;
  ask: string[];
  whatsapp_url: string;
  notifies_team_automatically: boolean;
}

export type Feedback = 1 | -1;

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  createdAt: number;
  // assistant-only
  messageId?: string; // backend message id (used for feedback)
  language?: Lang;
  route?: string;
  outcome?: string;
  citations?: Citation[];
  related?: RelatedPage[];
  handoff?: HandoffOffer | null;
  abstainReason?: string | null;
  emergencyNumbers?: string[] | null;
  feedback?: Feedback | null;
  streaming?: boolean;
  error?: string | null;
  timingsMs?: Record<string, number>;
  generator?: string;
}

export interface Conversation {
  id: string; // also used as the backend session_id
  title: string;
  updatedAt: number;
  messages: ChatMessage[];
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  index_ready: boolean;
  index_error: string | null;
  chunks: number;
  embedding_model: string | null;
  embedding_semantic: boolean | null;
  embedding_multilingual: boolean | null;
  generator: string;
  retrieval_mode: string;
  rrf_k: number;
  tracing_enabled: boolean;
}

export interface EscalateResponse {
  request_id: string;
  status: string;
  delivery: string;
  notified_team: boolean;
  duplicate: boolean;
  message: string;
}

export interface Overview {
  note: string;
  questions_total: number;
  conversations: number;
  outcomes: Record<string, number>;
  answered: number;
  unanswered: number;
  templated: number;
  answered_rate: number | null;
  abstain_rate: number | null;
  language_split: Record<string, number>;
  routes: Record<string, number>;
  gap_reasons: Record<string, number>;
  after_hours_share_ist: number | null;
  latency_ms: Record<string, number | null>;
  common_topics: { topic: string; questions: number }[];
  top_retrieved_pages: { url: string; title: string; questions: number }[];
  top_cited_pages: { url: string; citations: number }[];
  never_cited_pages: string[];
  support_requests: { total: number; by_reason: Record<string, number>; by_priority: Record<string, number>; by_status: Record<string, number> };
  pipeline_events: { stage: string; error_type: string; count: number }[];
  feedback: { up?: number; down?: number };
  index: { embedding_model: string; chunks: number; updated_at: string } | null;
  chunk_provenance: Record<string, number>;
}

export interface UnansweredCluster {
  cluster_id: number;
  label: string;
  count: number;
  terms: string[];
  languages: Record<string, number>;
  reasons: Record<string, number>;
  statuses: Record<string, number>;
  examples: string[];
  first_seen: string;
  last_seen: string;
}

export interface SupportRequestRow {
  [key: string]: unknown;
  request_id?: string;
  id?: string;
}
