import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { relativeTime } from "../lib/format";

export function PageHeading({ eyebrow, title, description, action }: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.22em] text-indigo-600">{eyebrow}</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 md:text-4xl">{title}</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">{description}</p>
      </div>
      {action}
    </header>
  );
}

export function StatCard({ label, value, note, icon: Icon, tone = "indigo" }: {
  label: string;
  value: string;
  note: string;
  icon: LucideIcon;
  tone?: "indigo" | "emerald" | "amber" | "slate";
}) {
  const tones = {
    indigo: "bg-indigo-50 text-indigo-600",
    emerald: "bg-emerald-50 text-emerald-600",
    amber: "bg-amber-50 text-amber-600",
    slate: "bg-slate-100 text-slate-600",
  };
  return (
    <article className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className={`grid h-10 w-10 place-items-center rounded-xl ${tones[tone]}`}><Icon className="h-5 w-5" /></div>
      <p className="mt-5 text-sm font-medium text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">{value}</p>
      <p className="mt-2 text-xs text-slate-400">{note}</p>
    </article>
  );
}

export function Panel({ title, description, children, className = "" }: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-2xl border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)] ${className}`}>
      <div className="border-b border-slate-100 px-5 py-4">
        <h2 className="font-semibold text-slate-900">{title}</h2>
        {description && <p className="mt-1 text-xs text-slate-500">{description}</p>}
      </div>
      {children}
    </section>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const style = status === "COMPLETED" || status === "ONLINE"
    ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20"
    : status === "FAILED" || status === "DEAD_LETTERED" || status === "OFFLINE"
      ? "bg-rose-50 text-rose-700 ring-rose-600/20"
      : status === "RUNNING"
        ? "bg-blue-50 text-blue-700 ring-blue-600/20"
        : "bg-amber-50 text-amber-700 ring-amber-600/20";
  return <span className={`rounded-full px-2 py-1 text-[11px] font-bold ring-1 ring-inset ${style}`}>{status.replaceAll("_", " ")}</span>;
}

export function EmptyRows({ label }: { label: string }) {
  return <div className="px-5 py-12 text-center text-sm text-slate-400">No {label} yet.</div>;
}

export function TimeCell({ value }: { value: string }) {
  return <span title={new Date(value).toLocaleString()}>{relativeTime(value)}</span>;
}
