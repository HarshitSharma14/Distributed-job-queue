import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import type { WorkerAssignment, WorkerAttempt } from "../api/types";
import {
  PageHeading,
  Panel,
  StatCard,
} from "../components/DashboardPrimitives";
import { PageError, TableSkeleton } from "../components/Feedback";
import { AssignmentTable, AttemptTable } from "../components/WorkerTables";
import { api } from "../lib/api";
import { duration } from "../lib/format";
interface AssignmentList {
  items: WorkerAssignment[];
  next_cursor: string | null;
}
interface AttemptList {
  items: WorkerAttempt[];
  next_cursor: string | null;
}
export function WorkerOverviewPage() {
  const assignments = useQuery({
    queryKey: ["worker", "assignments"],
    queryFn: () =>
      api<AssignmentList>("/worker-management/assignments?limit=20"),
    refetchInterval: 10_000,
  });
  const attempts = useQuery({
    queryKey: ["worker", "attempts"],
    queryFn: () => api<AttemptList>("/worker-management/attempts?limit=10"),
    refetchInterval: 30_000,
  });
  const records = attempts.data?.items;
  const timed = records?.filter((item) => item.duration_ms !== null);
  const average = timed?.length
    ? timed.reduce((sum, item) => sum + item.duration_ms!, 0) / timed.length
    : null;
  return (
    <div className="space-y-6">
      <PageHeading
        title="Worker overview"
        description="Current work and recent execution outcomes for your agents."
        action={
          <Link className="button button-primary" to="/worker/agents">
            Enroll an agent
          </Link>
        }
      />
      <div className="stats-grid">
        <StatCard
          label="Visible assignments"
          value={
            assignments.data
              ? `${assignments.data.items.length}${assignments.data.next_cursor ? "+" : ""}`
              : "—"
          }
          note="Up to 20 · refreshes every 10s"
        />
        <StatCard
          label="Recent completions"
          value={
            records
              ? String(
                  records.filter((a) => a.attempt_status === "COMPLETED")
                    .length,
                )
              : "—"
          }
          note="Within the 10 latest attempts"
        />
        <StatCard
          label="Average runtime"
          value={duration(average)}
          note="Timed attempts in this page"
        />
        <StatCard
          label="Recent attempt records"
          value={records ? String(records.length) : "—"}
          note="Up to 10 · refreshes every 30s"
        />
      </div>
      <Panel
        title="Active assignments"
        action={
          <Link className="text-link" to="/worker/assignments">
            View all assignments →
          </Link>
        }
      >
        {assignments.isPending ? (
          <TableSkeleton />
        ) : assignments.isError ? (
          <PageError
            message={assignments.error.message}
            retry={assignments.refetch}
          />
        ) : (
          <AssignmentTable items={assignments.data.items} />
        )}
      </Panel>
      <Panel
        title="Recent attempts"
        action={
          <Link className="text-link" to="/worker/attempts">
            View attempt history →
          </Link>
        }
      >
        {attempts.isPending ? (
          <TableSkeleton />
        ) : attempts.isError ? (
          <PageError
            message={attempts.error.message}
            retry={attempts.refetch}
          />
        ) : (
          <AttemptTable items={attempts.data.items} />
        )}
      </Panel>
    </div>
  );
}
