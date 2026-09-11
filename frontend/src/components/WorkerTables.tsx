import {
  DataTable,
  EmptyRows,
  IdCell,
  StatusBadge,
  TimeCell,
} from "./DashboardPrimitives";
import type { WorkerAssignment, WorkerAttempt } from "../api/types";
import { duration } from "../lib/format";
export function AssignmentTable({ items }: { items: WorkerAssignment[] }) {
  return items.length === 0 ? (
    <EmptyRows
      label="active assignments"
      description="Start an enrolled agent to claim queued jobs. Its current work will appear here."
    />
  ) : (
    <DataTable label="Active assignments">
      <thead>
        <tr>
          <th>Job</th>
          <th>Agent</th>
          <th>Queue</th>
          <th>Status</th>
          <th className="numeric">Assigned</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.job_id}>
            <td>
              <p className="row-title">{item.type}</p>
              <IdCell value={item.job_id} />
            </td>
            <td>
              <code>{item.worker_id}</code>
            </td>
            <td>
              <code>{item.queue}</code>
            </td>
            <td>
              <StatusBadge status={item.status} />
            </td>
            <td className="numeric">
              <TimeCell value={item.assigned_at} />
            </td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}
export function AttemptTable({ items }: { items: WorkerAttempt[] }) {
  return items.length === 0 ? (
    <EmptyRows
      label="attempts yet"
      description="Each worker execution will add an outcome and runtime here."
    />
  ) : (
    <DataTable label="Recent attempts">
      <thead>
        <tr>
          <th>Job</th>
          <th>Agent</th>
          <th>Outcome</th>
          <th className="numeric">Started</th>
          <th className="numeric">Runtime</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.attempt_id}>
            <td>
              <p className="row-title">{item.type}</p>
              <IdCell value={item.job_id} />
            </td>
            <td>
              <code>{item.worker_id}</code>
            </td>
            <td>
              <StatusBadge status={item.attempt_status} />
            </td>
            <td className="numeric">
              <TimeCell value={item.started_at} />
            </td>
            <td className="numeric">{duration(item.duration_ms)}</td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}
