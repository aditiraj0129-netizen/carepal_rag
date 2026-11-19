import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type EvalResult } from "../lib/api";
import { humanize, ms, pageLabel, pct } from "../lib/format";
import type { Overview, SupportRequestRow, UnansweredCluster } from "../lib/types";
import { BarList, EmptyState, Kpi, Section, StackedBar } from "./admin/widgets";
import { IconChart, IconChat, IconLock, IconRefresh } from "./Icons";
import { Wordmark } from "./Logo";

const KEY = "carepal-assist:admin-key";
const getKey = () => { try { return sessionStorage.getItem(KEY) ?? ""; } catch { return ""; } };
const LANG_NAME: Record<string, string> = { en: "English", hi: "Hindi", hinglish: "Hinglish" };

function maskPhone(p: unknown): string {
  const s = String(p ?? "");
  return s.length > 4 ? "•".repeat(Math.max(0, s.length - 4)) + s.slice(-4) : s;
}

export function AdminPage() {
  const [key, setKey] = useState(getKey);
  const [draft, setDraft] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const [overview, setOverview] = useState<Overview | null>(null);
  const [clusters, setClusters] = useState<UnansweredCluster[]>([]);
  const [requests, setRequests] = useState<SupportRequestRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reveal, setReveal] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const signOut = useCallback(() => { try { sessionStorage.removeItem(KEY); } catch { /* ignore */ } setKey(""); setOverview(null); }, []);

  const load = useCallback(async (k: string) => {
    setLoading(true); setError(null);
    try {
      const [o, u, r] = await Promise.all([api.overview(k), api.unanswered(k), api.supportRequests(k)]);
      setOverview(o); setClusters(u.clusters); setRequests(r.requests); setUpdatedAt(new Date());
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) { signOut(); setLoginError(e.message); }
      else setError(e instanceof ApiError ? e.message : "Could not load the dashboard.");
    } finally { setLoading(false); }
  }, [signOut]);

  useEffect(() => { if (key) void load(key); }, [key, load]);

  async function login(ev: FormEvent) {
    ev.preventDefault();
    const k = draft.trim();
    if (!k) return;
    setChecking(true); setLoginError(null);
    try {
      await api.overview(k); // verifies the key against the backend
      try { sessionStorage.setItem(KEY, k); } catch { /* ignore */ }
      setDraft(""); setKey(k);
    } catch (e) {
      setLoginError(e instanceof ApiError ? (e.status === 503 ? e.message : e.status === 401 ? "That admin key was not accepted." : e.message) : "Could not sign in.");
    } finally { setChecking(false); }
  }

  if (!key) {
    return (
      <div className="grid min-h-[100dvh] place-items-center bg-gradient-to-b from-white to-navy-50 px-4">
        <form onSubmit={login} className="card w-full max-w-sm space-y-4 p-6">
          <Wordmark />
          <div>
            <h1 className="flex items-center gap-2 font-display text-xl font-bold text-navy-900"><IconLock width={20} height={20} className="text-brand-700" />Admin sign-in</h1>
            <p className="mt-1 text-sm text-navy-500">Enter the admin key configured on the server (<code className="rounded bg-navy-100 px-1">ADMIN_API_KEY</code>). It is kept only for this browser tab.</p>
          </div>
          <div>
            <label htmlFor="admin-key" className="mb-1 block text-sm font-semibold text-navy-800">Admin key</label>
            <input id="admin-key" type="password" autoFocus autoComplete="off" className="input" value={draft} onChange={(e) => setDraft(e.target.value)} aria-invalid={!!loginError} />
            {loginError && <p role="alert" className="mt-1.5 text-sm text-alert-700">{loginError}</p>}
          </div>
          <button type="submit" className="btn-primary w-full" disabled={checking || !draft.trim()}>{checking ? "Checking…" : "Sign in"}</button>
          <a href="#/" className="block text-center text-sm font-medium text-navy-600 hover:underline">← Back to chat</a>
        </form>
      </div>
    );
  }

  return (
    <div className="min-h-[100dvh] bg-navy-50">
      <header className="sticky top-0 z-20 border-b border-navy-100 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
          <Wordmark />
          <span className="rounded-full bg-sky-100 px-2.5 py-1 text-xs font-semibold text-sky-700">Admin</span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {updatedAt && <span className="hidden text-xs text-navy-500 sm:inline">Updated {updatedAt.toLocaleTimeString()}</span>}
            <button type="button" className="btn-secondary !px-3" onClick={() => void load(key)} disabled={loading}><IconRefresh width={16} height={16} className={loading ? "animate-spin" : ""} />Refresh</button>
            <a href="#/" className="btn-secondary !px-3"><IconChat width={16} height={16} />Chat</a>
            <button type="button" className="btn-ghost !px-3" onClick={signOut}>Sign out</button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-5 px-4 py-6 sm:px-6">
        <div>
          <h1 className="flex items-center gap-2 font-display text-2xl font-extrabold tracking-tight text-navy-900"><IconChart className="text-brand-700" />Operations dashboard</h1>
          <p className="mt-1 text-sm text-navy-500">{overview?.note ?? "Computed from this prototype's own chat logs. Not TheCarePal business statistics."}</p>
        </div>

        {error && <div role="alert" className="rounded-xl bg-alert-50 px-4 py-3 text-sm text-alert-700">{error} <button className="font-semibold underline" onClick={() => void load(key)}>Retry</button></div>}
        {!overview && loading && <div className="card p-10 text-center text-navy-500" role="status">Loading dashboard…</div>}

        {overview && <Dashboard o={overview} clusters={clusters} requests={requests} reveal={reveal} onReveal={() => setReveal((v) => !v)} adminKey={key} onChanged={() => void load(key)} />}
      </main>
    </div>
  );
}

function Dashboard({ o, clusters, requests, reveal, onReveal, adminKey, onChanged }: {
  o: Overview; clusters: UnansweredCluster[]; requests: SupportRequestRow[]; reveal: boolean; onReveal: () => void; adminKey: string; onChanged: () => void;
}) {
  const noData = { title: "No conversations yet", body: "This fills in as people use the chat. Nothing here is sample data." };
  const answeredSub = o.questions_total ? `${pct(o.answered_rate)} of questions` : "no questions yet";
  const unansweredSub = o.questions_total ? `${pct(o.questions_total ? o.unanswered / o.questions_total : null)} of questions` : "no questions yet";
  const fb = o.feedback;

  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-6">
        <Kpi label="Conversations" value={o.conversations} sub={`${o.questions_total} questions`} />
        <Kpi label="Answered" value={o.answered} sub={answeredSub} tone="blue" />
        <Kpi label="Unanswered" value={o.unanswered} sub={unansweredSub} tone="warm" />
        <Kpi label="Escalations" value={o.support_requests.total} sub={Object.keys(o.support_requests.by_status).length ? Object.entries(o.support_requests.by_status).map(([k, v]) => `${v} ${k}`).join(", ") : "none yet"} tone="alert" />
        <Kpi label="Safety replies" value={o.templated} sub="templated (emergency etc.)" />
        <Kpi label="Feedback" value={`${fb.up ?? 0} 👍 / ${fb.down ?? 0} 👎`} sub="from users" tone="blue" />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Section title="Common topics" hint="Pages cited in answers, counted per question.">
          <BarList rows={o.common_topics.map((t) => ({ label: t.topic, value: t.questions }))} unit="questions" empty={noData} />
        </Section>
        <Section title="Language distribution" hint="Detected language of each question.">
          <StackedBar parts={Object.entries(o.language_split).map(([k, v]) => ({ label: LANG_NAME[k] ?? k, value: v }))} empty={noData} />
          <div className="mt-5 grid grid-cols-3 gap-3 text-center">
            {[["Retrieval p50", ms(o.latency_ms.retrieval_p50)], ["Total p50", ms(o.latency_ms.total_p50)], ["Total p95", ms(o.latency_ms.total_p95)]].map(([l, v]) => (
              <div key={l} className="rounded-xl bg-navy-50 py-2"><div className="text-[11px] font-semibold uppercase tracking-wide text-navy-500">{l}</div><div className="font-display text-lg font-bold text-navy-900">{v}</div></div>
            ))}
          </div>
        </Section>
      </div>

      <Section title="Knowledge gaps" hint="Questions the assistant could not answer from published pages, grouped by shared terms. These are candidates for new FAQ content.">
        {clusters.length === 0 ? (
          <EmptyState title="No knowledge gaps recorded" body="When the assistant abstains or answers with low confidence, the question is grouped here." />
        ) : (
          <ul className="divide-y divide-navy-100">
            {clusters.map((c) => (
              <li key={c.cluster_id} className="grid gap-2 py-3 sm:grid-cols-[1fr_auto] sm:items-start">
                <div className="min-w-0">
                  <div className="font-semibold text-navy-900">{c.label}</div>
                  <div className="mt-1 flex flex-wrap gap-1.5 text-xs">
                    {Object.entries(c.reasons).map(([r, n]) => <span key={r} className="rounded-full bg-warm-100 px-2 py-0.5 font-semibold text-warm-700">{humanize(r)} ×{n}</span>)}
                    {Object.keys(c.languages).map((l) => <span key={l} className="rounded-full bg-navy-100 px-2 py-0.5 font-medium text-navy-700">{LANG_NAME[l] ?? l}</span>)}
                    {c.terms.slice(0, 4).map((t) => <span key={t} className="rounded-full bg-brand-50 px-2 py-0.5 text-brand-800">{t}</span>)}
                  </div>
                  {c.examples.length > 1 && <p className="mt-1.5 text-sm text-navy-500">e.g. “{c.examples[1]}”</p>}
                </div>
                <div className="text-left sm:text-right"><span className="font-display text-2xl font-extrabold text-navy-900">{c.count}</span><span className="ml-1 text-sm text-navy-500">asked</span><div className="text-xs text-navy-500">last {new Date(c.last_seen).toLocaleDateString()}</div></div>
              </li>
            ))}
          </ul>
        )}
        {Object.keys(o.gap_reasons).length > 0 && (
          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-navy-100 pt-3 text-sm">
            <span className="font-semibold text-navy-700">Why answers were withheld:</span>
            {Object.entries(o.gap_reasons).map(([k, v]) => <span key={k} className="rounded-full bg-navy-100 px-2.5 py-0.5 text-navy-700">{humanize(k)}: {v}</span>)}
          </div>
        )}
      </Section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Section title="Frequently retrieved documents" hint="Pages whose text was used as evidence for an answer.">
          <BarList rows={o.top_retrieved_pages.map((p) => ({ label: p.title || pageLabel(p.url), value: p.questions, href: p.url, sub: pageLabel(p.url) }))} unit="questions" empty={noData} />
          {o.never_cited_pages.length > 0 && (
            <details className="mt-4 rounded-xl bg-navy-50 px-3 py-2 text-sm">
              <summary className="cursor-pointer font-semibold text-navy-700">{o.never_cited_pages.length} indexed pages never cited</summary>
              <ul className="mt-2 space-y-1 text-navy-600">{o.never_cited_pages.map((u) => <li key={u}>{pageLabel(u)}</li>)}</ul>
            </details>
          )}
        </Section>

        <Section title="Escalation requests" hint="Saved locally. Nobody is notified automatically."
          action={requests.length > 0 ? <button type="button" onClick={onReveal} className="btn-secondary !px-3 !py-1.5 text-xs">{reveal ? "Hide numbers" : "Show numbers"}</button> : undefined}>
          {requests.length === 0 ? (
            <EmptyState title="No escalation requests" body="Requests appear here when someone asks to talk to a person and gives consent." />
          ) : (
            <div className="-mx-1 overflow-x-auto">
              <table className="w-full min-w-[30rem] text-left text-sm">
                <thead className="text-xs uppercase tracking-wide text-navy-500"><tr><th className="px-1 py-2">Request</th><th className="px-1 py-2">Name / phone</th><th className="px-1 py-2">Reason</th><th className="px-1 py-2">Priority</th></tr></thead>
                <tbody className="divide-y divide-navy-100">
                  {requests.map((r) => (
                    <tr key={String(r.request_id)} className="align-top">
                      <td className="px-1 py-2"><code className="text-xs font-bold text-navy-900">{String(r.request_id)}</code><div className="text-xs text-navy-500">{r.created_at ? new Date(String(r.created_at)).toLocaleString() : ""}</div></td>
                      <td className="px-1 py-2"><div className="font-medium text-navy-800">{String(r.name)}</div><div className="font-mono text-xs text-navy-600">{reveal ? String(r.phone) : maskPhone(r.phone)}</div></td>
                      <td className="px-1 py-2"><div>{humanize(String(r.reason))}</div><div className="text-xs text-navy-500">{LANG_NAME[String(r.language)] ?? String(r.language)}</div></td>
                      <td className="px-1 py-2"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${r.priority === "urgent" || r.priority === "high" ? "bg-alert-100 text-alert-700" : "bg-navy-100 text-navy-700"}`}>{String(r.priority)}</span><div className="mt-0.5 text-xs text-navy-500">{String(r.status)} · {String(r.delivery)}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      </div>

      <KnowledgeBase o={o} adminKey={adminKey} onChanged={onChanged} />
    </>
  );
}

function KnowledgeBase({ o, adminKey, onChanged }: { o: Overview; adminKey: string; onChanged: () => void }) {
  const [busy, setBusy] = useState<"ingest" | "eval" | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [evalRes, setEvalRes] = useState<EvalResult | null>(null);
  const [source, setSource] = useState<"snapshots" | "crawl">("snapshots");

  async function ingest(force: boolean) {
    setBusy("ingest"); setMsg(null);
    try {
      const r = await api.ingest(adminKey, source, force);
      setMsg({ ok: true, text: `Ingestion ${String(r.status)}: ${String(r.chunks_total)} chunks (${String(r.chunks_new)} new, ${String(r.chunks_removed)} removed, ${String(r.embeddings_computed)} embedded).` });
      onChanged();
    } catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : "Ingestion failed." }); }
    finally { setBusy(null); }
  }
  async function evaluate() {
    setBusy("eval"); setMsg(null);
    try { setEvalRes(await api.evaluate(adminKey, "dev")); }
    catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : "Evaluation failed." }); }
    finally { setBusy(null); }
  }

  const modes = evalRes ? Object.entries(evalRes.retrieval.modes) : [];
  return (
    <Section title="Knowledge base and retrieval quality" hint={o.index ? `${o.index.chunks} chunks · ${o.index.embedding_model} · updated ${new Date(o.index.updated_at).toLocaleString()}` : "No index loaded."}>
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="ingest-source">Ingestion source</label>
        <select id="ingest-source" className="input !w-auto" value={source} onChange={(e) => setSource(e.target.value as "snapshots" | "crawl")}>
          <option value="snapshots">Seed snapshots</option>
          <option value="crawl">Crawl thecarepal.com</option>
        </select>
        <button type="button" className="btn-secondary" onClick={() => void ingest(false)} disabled={busy !== null}>{busy === "ingest" ? "Indexing…" : "Run incremental ingest"}</button>
        <button type="button" className="btn-primary" onClick={() => void evaluate()} disabled={busy !== null}>{busy === "eval" ? "Evaluating…" : "Run evaluation (dev split)"}</button>
      </div>
      {Object.keys(o.chunk_provenance).length > 0 && (
        <p className="mt-3 text-sm text-navy-500">Content provenance: {Object.entries(o.chunk_provenance).map(([k, v]) => `${humanize(k)} (${v})`).join(", ")}</p>
      )}
      {msg && <div role={msg.ok ? "status" : "alert"} className={`mt-3 rounded-xl px-3 py-2 text-sm ${msg.ok ? "bg-brand-50 text-brand-800" : "bg-alert-50 text-alert-700"}`}>{msg.text}</div>}
      {evalRes && (
        <div className="mt-4">
          <div className="-mx-1 overflow-x-auto">
            <table className="w-full min-w-[28rem] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-navy-500"><tr><th className="px-1 py-2">Retriever</th>{["recall@1", "recall@5", "precision@3", "mrr", "ndcg@5"].map((h) => <th key={h} className="px-1 py-2">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-navy-100">
                {modes.map(([m, v]) => (
                  <tr key={m}><td className="px-1 py-2 font-semibold capitalize text-navy-800">{m === "bm25" ? "BM25" : m}</td>{["recall@1", "recall@5", "precision@3", "mrr", "ndcg@5"].map((k) => <td key={k} className="px-1 py-2 tabular-nums">{v.overall[k]?.toFixed(2)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-navy-500">{evalRes.retrieval.n_answerable} answerable questions · embedder: {evalRes.embedding_model}{evalRes.embedding_semantic ? "" : " (non-semantic fallback)"}</p>
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-navy-500">{evalRes.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
        </div>
      )}
    </Section>
  );
}
