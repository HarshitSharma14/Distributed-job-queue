import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import type { Analytics, JobList } from "../api/types";
import { PageHeading, StatCard } from "../components/DashboardPrimitives";
import { PageError, PageSkeleton, TableSkeleton } from "../components/Feedback";
import { JobTable } from "../components/JobTable";
import { api } from "../lib/api";
import { compactNumber, duration, percent } from "../lib/format";
export function RoleOverviewPage({ role }: { role: "publisher" | "producer" }) {
  const analytics = useQuery({
    queryKey: [role, "analytics"],
    queryFn: () => api<Analytics>(`/${role}/analytics`),
    refetchInterval: 30_000,
  });
  const jobs = useQuery({
    queryKey: [role, "jobs"],
    queryFn: () => api<JobList>(`/${role}/jobs?limit=8`),
    refetchInterval: 15_000,
  });
  return (
    <div className="space-y-6">
      <PageHeading
        title={
          role === "publisher" ? "Publisher overview" : "Producer overview"
        }
        description={
          role === "publisher"
            ? "Performance of the handlers you publish, across producers and versions."
            : "Lifecycle and outcomes for the jobs you submit."
        }
        action={
          <Link
            className="button button-primary"
            to={
              role === "publisher" ? "/publisher/releases" : "/producer/submit"
            }
          >
            {role === "publisher" ? "Manage releases" : "Submit a job"}
          </Link>
        }
      />
      {analytics.isPending ? (
        <PageSkeleton />
      ) : analytics.isError ? (
        <PageError
          message={analytics.error.message}
          retry={analytics.refetch}
        />
      ) : (
        <div className="stats-grid">
          <StatCard
            label="Total jobs"
            value={compactNumber(analytics.data.total_jobs)}
            note={
              role === "publisher"
                ? `${analytics.data.job_types.length} Job Type versions with jobs`
                : "Submitted by you"
            }
          />
          <StatCard
            label="Terminal success"
            value={percent(analytics.data.terminal_success_rate)}
            note={`${analytics.data.terminal_jobs.toLocaleString()} terminal jobs`}
          />
          <StatCard
            label="Average completion"
            value={duration(analytics.data.average_completion_latency_ms)}
            note="Created to completed"
          />
          <StatCard
            label="Total attempts"
            value={compactNumber(analytics.data.total_attempts)}
            note={`${analytics.data.average_attempts?.toFixed(2) ?? "—"} per job`}
          />
        </div>
      )}
      {jobs.isPending ? (
        <TableSkeleton />
      ) : jobs.isError ? (
        <PageError message={jobs.error.message} retry={jobs.refetch} />
      ) : (
        <JobTable jobs={jobs.data.items} />
      )}
    </div>
  );
}
