import { useQuery } from "@tanstack/react-query";
import { Activity, Gauge, Server, ShieldCheck } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { AdminOverview } from "../api/types";
import { PageError } from "../components/Feedback";
import { PageHeading, Panel, StatCard } from "../components/DashboardPrimitives";
import { api } from "../lib/api";
import { compactNumber, duration, percent } from "../lib/format";

export function AdminOverviewPage() {
  const overview = useQuery({
    queryKey: ["admin-overview", "24h"],
    queryFn: () => api<AdminOverview>("/admin/overview?window=24h"),
    refetchInterval: 30_000,
  });
  if (overview.isPending) return <AdminSkeleton />;
  if (overview.isError) return <PageError message={overview.error.message} />;
  const { exact, operational } = overview.data;
  const submission = operational.series.find((item) => item.metric === "job_submission_rate");
  const chartData = submission?.points.map((point) => ({
    time: new Date(point.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    value: point.value,
  })) ?? [];

  return (
    <div className="space-y-8">
      <PageHeading eyebrow="Platform control" title="System overview" description="Durable truth from PostgreSQL, live operating signals from Prometheus." action={<span className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${operational.available ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}><span className={`h-2 w-2 rounded-full ${operational.available ? "bg-emerald-500" : "bg-amber-500"}`} />{operational.available ? "Signals live" : "Exact data only"}</span>} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total jobs" value={compactNumber(exact.total_jobs)} note="All durable jobs" icon={Server} />
        <StatCard label="Terminal success" value={percent(exact.terminal_success_rate)} note={`${exact.terminal_jobs} terminal jobs`} icon={ShieldCheck} tone="emerald" />
        <StatCard label="Average completion" value={duration(exact.average_completion_latency_ms)} note="Created to completed" icon={Gauge} tone="amber" />
        <StatCard label="Total attempts" value={compactNumber(exact.total_attempts)} note={`${exact.average_attempts?.toFixed(2) ?? "—"} per job`} icon={Activity} tone="slate" />
      </div>
      <div className="grid gap-5 xl:grid-cols-[1.55fr_0.8fr]">
        <Panel title="Submission signal" description={`${submission?.labels.queue ?? "All queues"} · last 24 hours`}>
          <div className="h-72 p-4">
            {chartData.length ? <ResponsiveContainer width="100%" height="100%"><LineChart data={chartData}><CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} /><XAxis dataKey="time" tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} minTickGap={30} /><YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} width={35} /><Tooltip contentStyle={{ borderRadius: 12, borderColor: "#e2e8f0", fontSize: 12 }} /><Line type="monotone" dataKey="value" stroke="#4f46e5" strokeWidth={2.5} dot={false} /></LineChart></ResponsiveContainer> : <div className="grid h-full place-items-center text-sm text-slate-400">{operational.available ? "Waiting for submission samples" : "Prometheus trends unavailable"}</div>}
          </div>
        </Panel>
        <Panel title="Lifecycle mix" description="Current PostgreSQL state">
          <div className="space-y-4 p-5">
            {Object.entries(exact.status_counts).filter(([, count]) => count > 0).map(([status, count]) => { const share = exact.total_jobs ? count / exact.total_jobs * 100 : 0; return <div key={status}><div className="flex justify-between text-xs"><span className="font-medium text-slate-600">{status.replaceAll("_", " ")}</span><span className="tabular-nums text-slate-400">{count}</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-indigo-500" style={{ width: `${share}%` }} /></div></div>; })}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function AdminSkeleton() {
  return <div className="space-y-8 animate-pulse"><div className="h-24 rounded-2xl bg-slate-200/70" /><div className="grid gap-4 sm:grid-cols-4">{[1,2,3,4].map((item) => <div key={item} className="h-44 rounded-2xl bg-white" />)}</div><div className="h-80 rounded-2xl bg-white" /></div>;
}
