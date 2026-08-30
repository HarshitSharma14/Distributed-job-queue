import { useQuery } from "@tanstack/react-query";
import { Activity, Cpu, History, TimerReset } from "lucide-react";

import type { WorkerAssignment, WorkerAttempt } from "../api/types";
import { EmptyRows, PageHeading, Panel, StatCard, StatusBadge, TimeCell } from "../components/DashboardPrimitives";
import { PageError } from "../components/Feedback";
import { api } from "../lib/api";
import { compactNumber, duration } from "../lib/format";

interface AssignmentList { items: WorkerAssignment[]; next_cursor: string | null }
interface AttemptList { items: WorkerAttempt[]; next_cursor: string | null }

export function WorkerOverviewPage() {
  const assignments = useQuery({ queryKey: ["worker", "assignments"], queryFn: () => api<AssignmentList>("/worker-management/assignments?limit=20"), refetchInterval: 10_000 });
  const attempts = useQuery({ queryKey: ["worker", "attempts"], queryFn: () => api<AttemptList>("/worker-management/attempts?limit=10"), refetchInterval: 30_000 });
  if (assignments.isPending || attempts.isPending) return <div className="h-96 animate-pulse rounded-2xl bg-white" />;
  if (assignments.isError || attempts.isError) return <PageError message={(assignments.error ?? attempts.error)?.message} />;
  const completed = attempts.data.items.filter((attempt) => attempt.attempt_status === "COMPLETED").length;
  const averageDuration = attempts.data.items.reduce((sum, item) => sum + (item.duration_ms ?? 0), 0) / (attempts.data.items.filter((item) => item.duration_ms !== null).length || 1);
  return (
    <div className="space-y-8">
      <PageHeading eyebrow="Worker workspace" title="Execution history" description="Current assignments and the safe execution record for Worker Agents you own." />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Active assignments" value={compactNumber(assignments.data.items.length)} note="Across owned agents" icon={Cpu} />
        <StatCard label="Recent completions" value={compactNumber(completed)} note="In visible attempt history" icon={Activity} tone="emerald" />
        <StatCard label="Average runtime" value={duration(averageDuration)} note="Finished attempts" icon={TimerReset} tone="amber" />
        <StatCard label="Attempt records" value={compactNumber(attempts.data.items.length)} note="Most recent page" icon={History} tone="slate" />
      </div>
      <Panel title="Active assignments" description="Payload and lease secrets stay inside the assigned Worker Agent">
        {assignments.data.items.length === 0 ? <EmptyRows label="active assignments" /> : <div className="divide-y divide-slate-100">{assignments.data.items.map((item) => <div key={item.job_id} className="grid gap-3 px-5 py-4 md:grid-cols-[1.4fr_1fr_auto_auto] md:items-center"><div><p className="font-medium">{item.type}</p><p className="mt-0.5 font-mono text-[10px] text-slate-400">{item.worker_id}</p></div><p className="text-sm text-slate-500">{item.queue}</p><StatusBadge status={item.status} /><p className="text-xs text-slate-400"><TimeCell value={item.assigned_at} /></p></div>)}</div>}
      </Panel>
      <Panel title="Recent attempts" description="Outcomes and duration, without credentials or historical payload access">
        {attempts.data.items.length === 0 ? <EmptyRows label="attempts" /> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-[11px] uppercase tracking-wider text-slate-400"><tr><th className="px-5 py-3">Job</th><th className="px-5 py-3">Agent</th><th className="px-5 py-3">Outcome</th><th className="px-5 py-3">Runtime</th></tr></thead><tbody className="divide-y divide-slate-100">{attempts.data.items.map((item) => <tr key={item.attempt_id}><td className="px-5 py-4 font-medium">{item.type}</td><td className="px-5 py-4 font-mono text-[10px] text-slate-500">{item.worker_id}</td><td className="px-5 py-4"><StatusBadge status={item.attempt_status} /></td><td className="px-5 py-4 text-slate-500">{duration(item.duration_ms)}</td></tr>)}</tbody></table></div>}
      </Panel>
    </div>
  );
}
