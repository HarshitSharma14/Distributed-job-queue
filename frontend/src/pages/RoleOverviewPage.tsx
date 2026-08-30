import { useQuery } from "@tanstack/react-query";
import { Activity, CheckCircle2, Clock3, Layers3 } from "lucide-react";

import type { Analytics, JobList } from "../api/types";
import { PageHeading, StatCard } from "../components/DashboardPrimitives";
import { PageError } from "../components/Feedback";
import { JobTable } from "../components/JobTable";
import { api } from "../lib/api";
import { compactNumber, duration, percent } from "../lib/format";

export function RoleOverviewPage({ role }: { role: "publisher" | "producer" }) {
  const title = role === "publisher" ? "Job Type performance" : "Your submitted work";
  const description = role === "publisher"
    ? "Every job created from handlers you publish, across producers and versions."
    : "Lifecycle, outcomes, and recent activity for jobs submitted by you.";
  const analytics = useQuery({ queryKey: [role, "analytics"], queryFn: () => api<Analytics>(`/${role}/analytics`), refetchInterval: 30_000 });
  const jobs = useQuery({ queryKey: [role, "jobs"], queryFn: () => api<JobList>(`/${role}/jobs?limit=8`), refetchInterval: 15_000 });
  if (analytics.isPending || jobs.isPending) return <div className="h-96 animate-pulse rounded-2xl bg-white" />;
  if (analytics.isError || jobs.isError) return <PageError message={(analytics.error ?? jobs.error)?.message} />;
  const data = analytics.data;
  return (
    <div className="space-y-8">
      <PageHeading eyebrow={`${role} workspace`} title={title} description={description} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Visible jobs" value={compactNumber(data.total_jobs)} note={role === "publisher" ? `${data.job_types.length} released versions` : "Ownership scoped"} icon={Layers3} />
        <StatCard label="Success rate" value={percent(data.terminal_success_rate)} note={`${data.terminal_jobs} terminal jobs`} icon={CheckCircle2} tone="emerald" />
        <StatCard label="Completion time" value={duration(data.average_completion_latency_ms)} note="Average end-to-end" icon={Clock3} tone="amber" />
        <StatCard label="Attempts" value={compactNumber(data.total_attempts)} note={`${data.average_attempts?.toFixed(2) ?? "—"} per job`} icon={Activity} tone="slate" />
      </div>
      <JobTable jobs={jobs.data.items} />
    </div>
  );
}
