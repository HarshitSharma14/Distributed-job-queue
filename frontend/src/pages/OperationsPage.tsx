import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Link } from "react-router-dom";
import {
  DataTable,
  EmptyRows,
  IdCell,
  PageHeading,
  Panel,
  StatusBadge,
  TimeCell,
} from "../components/DashboardPrimitives";
import { duration } from "../lib/format";
import type { WorkerAssignment, WorkerAttempt } from "../api/types";
import type { Release } from "./ReleasesPage";
import {
  Button,
  Card,
  Field,
  inputClass,
  useAction,
  usePage,
  QueryState,
  write,
  Json,
  useLocalPage,
} from "../components/Management";

interface Agent {
  worker_id: string;
  status: string;
  capabilities: string[];
  last_heartbeat_at: string;
  owner_user_id?: string;
  active_jobs?: number;
  credential_revoked_at?: string | null;
  credential_expires_at?: string | null;
}
function AgentRows({ items, admin }: { items: Agent[]; admin: boolean }) {
  const action = useAction();
  const local = useLocalPage(items);
  return (
    <>
      {items.length === 0 ? (
        <EmptyRows
          label="agents registered"
          description="Enroll an agent and start it on a machine with Docker to see its heartbeat here."
        />
      ) : (
        <DataTable label="Worker Agents">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Health</th>
              <th>Capabilities</th>
              {admin && (
                <>
                  <th>Owner</th>
                  <th className="numeric">Active jobs</th>
                </>
              )}
              <th className="numeric">Last heartbeat</th>
              <th>Credential / action</th>
            </tr>
          </thead>
          <tbody>
            {local.items.map((a) => (
              <tr key={a.worker_id}>
                <td>
                  <code className="row-title">{a.worker_id}</code>
                </td>
                <td>
                  <StatusBadge status={a.status} />
                </td>
                <td>{a.capabilities.join(", ") || "—"}</td>
                {admin && (
                  <>
                    <td>
                      {a.owner_user_id && <IdCell value={a.owner_user_id} />}
                    </td>
                    <td className="numeric">{a.active_jobs ?? "—"}</td>
                  </>
                )}
                <td className="numeric">
                  <TimeCell value={a.last_heartbeat_at} />
                </td>
                <td>
                  {a.credential_expires_at && (
                    <p className="mb-2 text-xs text-muted">
                      Expires <TimeCell value={a.credential_expires_at} />
                    </p>
                  )}
                  {a.credential_revoked_at ? (
                    <span className="text-danger">Credential revoked</span>
                  ) : (
                    <Button
                      variant="danger"
                      disabled={action.busy}
                      onClick={async () => {
                        if (
                          await action.confirm({
                            title: "Revoke agent credential?",
                            description: `${a.worker_id} will lose access and need a fresh enrollment to reconnect.`,
                            label: "Revoke agent",
                          })
                        )
                          void action.run(
                            () =>
                              write(
                                `${admin ? "/admin/workers" : "/worker-management/agents"}/${encodeURIComponent(a.worker_id)}/credential`,
                                undefined,
                                "DELETE",
                              ),
                            "Agent credential revoked",
                          );
                      }}
                    >
                      Revoke agent
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      {local.pager}
    </>
  );
}
export function AdminWorkersPage() {
  const q = usePage<Agent>("/admin/workers");
  return (
    <div>
      <PageHeading
        title="Workers"
        description="Health, ownership, and current assignments across all agents. Updates every 15 seconds."
      />
      <Panel title="All Worker Agents">
        <QueryState query={q} />
        {q.data && <AgentRows admin items={q.data.items} />}
        {q.pager}
      </Panel>
    </div>
  );
}
const quote = (v: string) => `'${v.replaceAll("'", "'\\''")}'`;
export function AgentsPage() {
  const q = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<Agent[]>("/worker-management/agents"),
    refetchInterval: 5000,
  });
  const catalog = usePage<Release>("/catalog/job-types");
  const action = useAction();
  const [id, setId] = useState("");
  const [selectedRelease, setSelectedRelease] = useState<Release>();
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [expires, setExpires] = useState("");
  return (
    <div className="space-y-6">
      <PageHeading
        title="Worker Agents"
        description="Enroll workers and monitor the agents you own."
      />

      <Card title="Enroll an agent">
        <p className="text-sm text-muted">
          Install the Worker package and Docker on your machine. Choose the
          approved handler here, then run the generated command. A restart
          requires a fresh enrollment with the same agent name. Only public
          signing keys are provided.
        </p>
        <QueryState query={catalog} />
        {catalog.data?.items.length === 0 && (
          <p className="notice">
            No active releases available. An administrator must approve a
            handler release before you can enroll an agent.
          </p>
        )}
        <form
          className="max-w-3xl space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void action.run(async () => {
              const startup = await api<{
                trusted_public_keys: Record<string, string>;
                sandbox_image: string;
              }>("/worker-management/startup");
              const enrollment = await write<{
                token: string;
                expires_at: string;
              }>("/worker-management/enrollments", { job_type_id: id });
              setExpires(enrollment.expires_at);
              setCommand(
                `WORKER_GATEWAY_URL=${quote(window.location.origin)} WORKER_ENROLLMENT_TOKEN=${quote(enrollment.token)} HANDLER_TRUSTED_PUBLIC_KEYS=${quote(JSON.stringify(startup.trusted_public_keys))} HANDLER_SANDBOX_IMAGE=${quote(startup.sandbox_image)} job-worker --name ${quote(name)} --allow-downloaded-handler`,
              );
            }, "Enrollment created. Copy the command now; the token is shown only once.");
          }}
        >
          <Field label="Approved release">
            <select
              className={inputClass}
              required
              value={id}
              onChange={(e) => {
                setId(e.target.value);
                setSelectedRelease(
                  catalog.data?.items.find(
                    (r) => r.job_type_id === e.target.value,
                  ),
                );
              }}
            >
              <option value="">Choose a release</option>
              {selectedRelease &&
                !catalog.data?.items.some(
                  (r) => r.job_type_id === selectedRelease.job_type_id,
                ) && (
                  <option value={selectedRelease.job_type_id}>
                    {selectedRelease.name} v{selectedRelease.version} ·{" "}
                    {selectedRelease.publisher_id}
                  </option>
                )}
              {catalog.data?.items.map((r) => (
                <option key={r.job_type_id} value={r.job_type_id}>
                  {r.name} v{r.version} · {r.publisher_id}
                </option>
              ))}
            </select>
          </Field>
          <div className="catalog-pagination">
            <span>Release catalog</span>
            {catalog.pager}
          </div>
          <Field label="Agent name">
            <input
              className={inputClass}
              required
              pattern="[A-Za-z0-9_.-]+"
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Button disabled={action.busy || !id}>Create enrollment</Button>
        </form>

        {command && (
          <div className="space-y-3">
            <p className="text-sm">
              Enrollment expires: {new Date(expires).toLocaleString()}
            </p>
            <pre className="overflow-auto whitespace-pre-wrap break-all rounded-lg bg-canvas p-4 text-xs text-primary">
              {command}
            </pre>
            <Button
              variant="secondary"
              onClick={() =>
                void action.run(
                  () => navigator.clipboard.writeText(command),
                  "Command copied",
                )
              }
            >
              Copy command
            </Button>
            <Button variant="ghost" onClick={() => setCommand("")}>
              Hide token
            </Button>
          </div>
        )}
      </Card>
      <Panel
        title="Your agents"
        description="Heartbeats refresh every 5 seconds"
      >
        <QueryState query={q} />
        {q.data && <AgentRows admin={false} items={q.data} />}
      </Panel>
    </div>
  );
}
interface Queue {
  queue: string;
  durable_jobs: number;
  status_counts: Record<string, number>;
  redis_ready_jobs: number | null;
  redis_inflight_jobs: number | null;
}
export function QueuesPage() {
  const q = useQuery({
    queryKey: ["queues"],
    queryFn: () =>
      api<{ items: Queue[]; redis_available: boolean }>("/admin/queues"),
    refetchInterval: 5000,
  });
  const controls = useQuery({
    queryKey: ["queue-controls"],
    queryFn: () =>
      api<Record<string, { paused: boolean }>>("/admin/queue-controls"),
    refetchInterval: 5000,
  });
  const action = useAction();
  const local = useLocalPage(q.data?.items ?? []);
  return (
    <div className="space-y-6">
      <PageHeading
        title="Queues"
        description="Durable job counts and Redis delivery depth. Updates every 5 seconds."
      />
      <p className="text-sm text-secondary">
        Pausing prevents new attempts. Submissions and retries continue; running
        handlers finish.
      </p>
      <QueryState query={q} />
      <QueryState query={controls} />
      {q.data && !q.data.redis_available && (
        <p className="notice" role="status">
          Redis is unavailable. Durable counts remain visible; delivery depth
          cannot be read.
        </p>
      )}
      <Panel title="Queue state">
        {q.data?.items.length === 0 && (
          <EmptyRows
            label="queues yet"
            description="Queues appear when jobs are submitted to a released Job Type."
          />
        )}
        {!!q.data?.items.length && (
          <DataTable label="Queues">
            <thead>
              <tr>
                <th>Queue</th>
                <th>Claims</th>
                <th className="numeric">Durable jobs</th>
                <th className="numeric">Ready</th>
                <th className="numeric">In flight</th>
                <th>Lifecycle</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {local.items.map((row) => {
                const known = !!controls.data && !controls.error;
                const paused = controls.data?.[row.queue]?.paused ?? false;
                return (
                  <tr key={row.queue}>
                    <td>
                      <Link
                        className="row-title"
                        to={`/admin/jobs?queue=${encodeURIComponent(row.queue)}`}
                      >
                        {row.queue}
                      </Link>
                    </td>
                    <td>
                      {known ? (
                        <span
                          className={paused ? "text-warning" : "text-secondary"}
                        >
                          {paused ? "Paused" : "Accepting claims"}
                        </span>
                      ) : (
                        <span className="text-muted">Unavailable</span>
                      )}
                    </td>
                    <td className="numeric">{row.durable_jobs}</td>
                    <td className="numeric">
                      {row.redis_ready_jobs ?? "Unavailable"}
                    </td>
                    <td className="numeric">
                      {row.redis_inflight_jobs ?? "Unavailable"}
                    </td>
                    <td>
                      <details>
                        <summary className="text-link">Status counts</summary>
                        <div className="space-y-2 pt-3">
                          {Object.entries(row.status_counts).map(
                            ([status, count]) => (
                              <div
                                key={status}
                                className="flex justify-between gap-5"
                              >
                                <StatusBadge status={status} />
                                <code>{count}</code>
                              </div>
                            ),
                          )}
                        </div>
                      </details>
                    </td>
                    <td>
                      <Button
                        variant="secondary"
                        disabled={action.busy || !known}
                        onClick={() =>
                          void action.run(
                            () =>
                              write(
                                `/admin/queues/${encodeURIComponent(row.queue)}/${paused ? "resume" : "pause"}`,
                              ),
                            paused ? "Queue resumed" : "Queue paused",
                          )
                        }
                      >
                        {paused ? "Resume queue" : "Pause queue"}
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </DataTable>
        )}
        {local.pager}
      </Panel>
    </div>
  );
}

interface Key {
  credential_id: string;
  name: string;
  key_prefix: string;
  expires_at: string;
  revoked_at: string | null;
}
export function KeysPage() {
  const q = useQuery({
    queryKey: ["api-keys"],
    queryFn: () => api<Key[]>("/auth/api-keys"),
  });
  const action = useAction();
  const [name, setName] = useState("");
  const [days, setDays] = useState(90);
  const [secret, setSecret] = useState("");
  const local = useLocalPage(q.data ?? []);
  return (
    <div className="space-y-6">
      <PageHeading
        title="API keys"
        description="Credentials for programmatic access to your Producer account."
      />
      <Card title="Create an API key">
        <p className="text-sm text-muted">
          Optional credentials for programmatic submissions. Dashboard
          submissions use your browser session.
        </p>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            void action.run(async () => {
              const result = await write<{ key: string }>("/auth/api-keys", {
                name,
                expires_in_days: days,
              });
              setSecret(result.key);
              setName("");
            }, "Key created. Save it now; it cannot be displayed again.");
          }}
        >
          <Field label="Key name">
            <input
              className={inputClass}
              required
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Expires in days">
            <input
              className={inputClass}
              type="number"
              required
              min={1}
              max={365}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            />
          </Field>
          <Button disabled={action.busy}>Create key</Button>
        </form>
        {secret && (
          <div className="space-y-3">
            <code className="block break-all bg-raised p-3">{secret}</code>
            <Button
              variant="secondary"
              onClick={() =>
                void action.run(
                  () => navigator.clipboard.writeText(secret),
                  "Key copied",
                )
              }
            >
              Copy key
            </Button>
            <Button variant="ghost" onClick={() => setSecret("")}>
              Hide key
            </Button>
          </div>
        )}
      </Card>
      <Panel title="Your API keys">
        <QueryState query={q} />
        {q.data?.length === 0 && (
          <EmptyRows
            label="API keys yet"
            description="Create a key above to submit and read your jobs programmatically."
          />
        )}
        {!!q.data?.length && (
          <DataTable label="API keys">
            <thead>
              <tr>
                <th>Name</th>
                <th>Key prefix</th>
                <th>Status</th>
                <th className="numeric">Expires</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {local.items.map((k) => (
                <tr key={k.credential_id}>
                  <td className="row-title">{k.name}</td>
                  <td>
                    <code>{k.key_prefix}…</code>
                  </td>
                  <td>
                    <StatusBadge
                      status={
                        k.revoked_at
                          ? "REVOKED"
                          : Date.parse(k.expires_at) < Date.now()
                            ? "EXPIRED"
                            : "ACTIVE"
                      }
                    />
                  </td>
                  <td className="numeric">
                    <TimeCell value={k.expires_at} />
                  </td>
                  <td>
                    {!k.revoked_at && (
                      <Button
                        variant="danger"
                        disabled={action.busy}
                        onClick={async () => {
                          if (
                            await action.confirm({
                              title: "Revoke API key?",
                              description: `${k.name} (${k.key_prefix}…) will immediately stop authenticating requests. This cannot be undone.`,
                              label: "Revoke key",
                            })
                          )
                            void action.run(
                              () =>
                                write(
                                  `/auth/api-keys/${k.credential_id}`,
                                  undefined,
                                  "DELETE",
                                ),
                              "API key revoked",
                            );
                        }}
                      >
                        Revoke
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
        {local.pager}
      </Panel>
    </div>
  );
}

export function WorkerActivityPage({
  kind,
}: {
  kind: "assignments" | "attempts";
}) {
  const [worker, setWorker] = useState("");
  const [status, setStatus] = useState("");
  const params = new URLSearchParams();
  if (worker) params.set("worker_id", worker);
  if (status && kind === "attempts") params.set("status", status);
  return (
    <div className="space-y-5">
      <PageHeading
        title={
          kind === "assignments" ? "Current assignments" : "Attempt history"
        }
        description="Execution metadata for your agents. Updates every 15 seconds."
      />
      <p className="text-sm text-muted">
        Only your agents’ execution metadata is shown. Payloads, results, and
        credentials are excluded.
      </p>
      <div className="filters">
        <Field label="Agent name">
          <input
            className={inputClass}
            value={worker}
            onChange={(e) => setWorker(e.target.value)}
          />
        </Field>
        {kind === "attempts" && (
          <Field label="Attempt status">
            <select
              className={inputClass}
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">All outcomes</option>
              <option>RUNNING</option>
              <option>COMPLETED</option>
              <option>FAILED</option>
            </select>
          </Field>
        )}
      </div>
      <WorkerActivityRows
        key={params.toString()}
        path={`/worker-management/${kind}?${params}`}
        kind={kind}
      />
    </div>
  );
}
function WorkerActivityRows({
  path,
  kind,
}: {
  path: string;
  kind: "assignments" | "attempts";
}) {
  const q = usePage<WorkerAssignment | WorkerAttempt>(path);
  return (
    <Panel
      title="Execution records"
      description="Newest first · 25 records per page"
    >
      <QueryState query={q} />
      {q.data?.items.length === 0 && (
        <EmptyRows
          label="matching records"
          description="Assignments appear when an agent claims a job. Each execution produces an attempt record."
        />
      )}
      {!!q.data?.items.length && (
        <DataTable label="Execution records">
          <thead>
            <tr>
              <th>Job / ID</th>
              <th>Agent</th>
              <th>Queue</th>
              <th>Outcome</th>
              <th className="numeric">Attempt</th>
              <th className="numeric">
                {kind === "assignments" ? "Assigned" : "Started"}
              </th>
              <th>
                {kind === "assignments"
                  ? "Lease expires"
                  : "Duration / details"}
              </th>
            </tr>
          </thead>
          <tbody>
            {q.data.items.map((row) => {
              const attempt = "attempt_id" in row;
              return (
                <tr key={attempt ? row.attempt_id : row.job_id}>
                  <td>
                    <p className="row-title">{row.type}</p>
                    <IdCell value={row.job_id} />
                  </td>
                  <td>
                    <code>{row.worker_id}</code>
                  </td>
                  <td>
                    <code>{row.queue}</code>
                  </td>
                  <td>
                    <StatusBadge
                      status={attempt ? row.attempt_status : row.status}
                    />
                  </td>
                  <td className="numeric">{row.attempt_number}</td>
                  <td className="numeric">
                    <TimeCell
                      value={attempt ? row.started_at : row.assigned_at}
                    />
                  </td>
                  <td>
                    {attempt ? (
                      duration(row.duration_ms)
                    ) : (
                      <TimeCell value={row.lease_expires_at} />
                    )}
                    <div className="mt-2">
                      <Json value={row} label="Execution metadata" collapsed />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </DataTable>
      )}
      {q.pager}
    </Panel>
  );
}
