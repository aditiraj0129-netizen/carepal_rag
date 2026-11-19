import type { ReactNode } from "react";

export function Section({ title, hint, children, action }: { title: string; hint?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="card min-w-0 p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="font-display text-base font-bold text-navy-900">{title}</h2>
          {hint && <p className="mt-0.5 text-sm text-navy-500">{hint}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Kpi({ label, value, sub, tone = "brand" }: { label: string; value: string | number; sub?: string; tone?: "brand" | "blue" | "warm" | "alert" }) {
  const bar = { brand: "bg-brand-500", blue: "bg-sky-600", warm: "bg-warm-700", alert: "bg-alert-600" }[tone];
  return (
    <div className="card relative min-w-0 overflow-hidden p-4">
      <span className={`absolute inset-y-0 left-0 w-1 ${bar}`} aria-hidden />
      <div className="text-xs font-semibold uppercase tracking-wide text-navy-500">{label}</div>
      <div className="mt-1 font-display text-3xl font-extrabold tracking-tight text-navy-900" data-testid={`kpi-${label}`}>{value}</div>
      {sub && <div className="mt-0.5 text-sm text-navy-500">{sub}</div>}
    </div>
  );
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl border border-dashed border-navy-200 bg-navy-50/50 px-4 py-8 text-center">
      <div className="font-display text-sm font-bold text-navy-700">{title}</div>
      <p className="mx-auto mt-1 max-w-sm text-sm text-navy-500">{body}</p>
    </div>
  );
}

export interface BarRow { label: string; value: number; href?: string; sub?: string }

export function BarList({ rows, unit, empty }: { rows: BarRow[]; unit: string; empty: { title: string; body: string } }) {
  if (!rows.length) return <EmptyState {...empty} />;
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <ul className="space-y-3">
      {rows.map((r) => (
        <li key={r.label}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            {r.href ? <a href={r.href} target="_blank" rel="noopener noreferrer" className="min-w-0 truncate font-medium text-sky-700 hover:underline">{r.label}</a>
              : <span className="min-w-0 truncate font-medium text-navy-800">{r.label}</span>}
            <span className="shrink-0 tabular-nums text-navy-600">{r.value} {r.value === 1 ? unit.replace(/s$/, "") : unit}</span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-navy-100" role="img" aria-label={`${r.label}: ${r.value} ${unit}`}>
            <div className="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-700" style={{ width: `${Math.max(4, (r.value / max) * 100)}%` }} />
          </div>
          {r.sub && <div className="mt-0.5 text-xs text-navy-500">{r.sub}</div>}
        </li>
      ))}
    </ul>
  );
}

const SEG_COLORS = ["bg-brand-600", "bg-sky-600", "bg-warm-700", "bg-navy-500"];

export function StackedBar({ parts, empty }: { parts: { label: string; value: number }[]; empty: { title: string; body: string } }) {
  const total = parts.reduce((a, p) => a + p.value, 0);
  if (!total) return <EmptyState {...empty} />;
  return (
    <div>
      <div className="flex h-4 overflow-hidden rounded-full bg-navy-100" role="img" aria-label={parts.map((p) => `${p.label} ${p.value}`).join(", ")}>
        {parts.filter((p) => p.value > 0).map((p, i) => <div key={p.label} className={SEG_COLORS[i % SEG_COLORS.length]} style={{ width: `${(p.value / total) * 100}%` }} />)}
      </div>
      <ul className="mt-3 grid gap-2 sm:grid-cols-3">
        {parts.map((p, i) => (
          <li key={p.label} className="flex items-center gap-2 text-sm">
            <span className={`h-3 w-3 rounded-sm ${SEG_COLORS[i % SEG_COLORS.length]}`} aria-hidden />
            <span className="font-medium text-navy-800">{p.label}</span>
            <span className="ml-auto tabular-nums text-navy-600">{p.value} · {Math.round((p.value / total) * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
