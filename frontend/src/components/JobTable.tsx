import { Link, useLocation } from "react-router-dom";
import type { JobSummary } from "../api/types";
import {
  DataTable,
  EmptyRows,
  IdCell,
  Panel,
  StatusBadge,
  TimeCell,
} from "./DashboardPrimitives";
export function JobTable({
  jobs,
  title = "Recent jobs",
  bare = false,
}: {
  jobs: JobSummary[];
  title?: string;
  bare?: boolean;
}) {
  const role = useLocation().pathname.split("/")[1];
  const table =
    jobs.length === 0 ? (
      <EmptyRows
        label="jobs found"
        description="Submitted jobs will appear here. Adjust the filters to include more results."
      />
    ) : (
      <DataTable label={title}>
        <thead>
          <tr>
            <th>Job / ID</th>
            <th>Status</th>
            <th>Queue</th>
            <th className="numeric">Priority</th>
            <th className="numeric">Attempts</th>
            <th className="numeric">Created</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.job_id}>
              <td>
                <Link className="row-title" to={`/${role}/jobs/${job.job_id}`}>
                  {job.type}
                </Link>
                <div>
                  <IdCell value={job.job_id} />
                </div>
              </td>
              <td>
                <StatusBadge status={job.status} />
              </td>
              <td>
                <code>{job.queue}</code>
              </td>
              <td className="numeric">{job.priority}</td>
              <td className="numeric">
                {job.attempt_count}
                <span className="text-muted"> / {job.max_attempts}</span>
              </td>
              <td className="numeric">
                <TimeCell value={job.created_at} />
              </td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    );
  return bare ? (
    table
  ) : (
    <Panel
      title={title}
      description="Newest jobs visible to this role"
      action={
        <Link className="text-link" to={`/${role}/jobs`}>
          View all jobs →
        </Link>
      }
    >
      {table}
    </Panel>
  );
}
