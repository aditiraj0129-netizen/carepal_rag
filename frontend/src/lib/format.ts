export const pct = (v: number | null | undefined): string => (v == null ? "n/a" : `${Math.round(v * 100)}%`);
export const ms = (v: number | null | undefined): string => (v == null ? "n/a" : `${Math.round(v)} ms`);

export function pageLabel(url: string): string {
  try {
    const p = new URL(url).pathname.replace(/\/$/, "");
    return p === "" ? "/" : p;
  } catch { return url; }
}

export function timeAgo(ts: number, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - ts) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export const humanize = (s: string): string => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
