import type { JobSummary } from "../api/types";
import { EmptyRows, Panel, StatusBadge, TimeCell } from "./DashboardPrimitives";

export function JobTable({ jobs, title = "Recent jobs" }: { jobs: JobSummary[]; title?: string }) {
  return (
    <Panel title={title} description="Newest durable jobs visible to this role">
      {jobs.length === 0 ? <EmptyRows label="jobs" /> : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50/70 text-[11px] uppercase tracking-wider text-slate-400"><tr><th className="px-5 py-3 font-semibold">Job</th><th className="px-5 py-3 font-semibold">Queue</th><th className="px-5 py-3 font-semibold">Status</th><th className="px-5 py-3 font-semibold">Attempts</th><th className="px-5 py-3 font-semibold">Created</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {jobs.map((job) => <tr key={job.job_id} className="hover:bg-slate-50/60"><td className="px-5 py-4"><p className="font-medium text-slate-900">{job.type}</p><p className="mt-0.5 max-w-36 truncate font-mono text-[10px] text-slate-400">{job.job_id}</p></td><td className="px-5 py-4 text-slate-600">{job.queue}</td><td className="px-5 py-4"><StatusBadge status={job.status} /></td><td className="px-5 py-4 tabular-nums text-slate-600">{job.attempt_count}/{job.max_attempts}</td><td className="px-5 py-4 text-slate-500"><TimeCell value={job.created_at} /></td></tr>)}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
