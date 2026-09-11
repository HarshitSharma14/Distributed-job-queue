import { useEffect, useState } from "react";
import {
  Link,
  useParams,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthProvider";
import { api } from "../lib/api";
import type { JobSummary } from "../api/types";
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
} from "../components/Management";
import {
  DataTable,
  EmptyRows,
  IdCell,
  PageHeading,
  Panel,
  StatusBadge,
  TimeCell,
} from "../components/DashboardPrimitives";
import { JobTable } from "../components/JobTable";
import { duration } from "../lib/format";

export function JobsPage({
  role,
  deadLetters = false,
}: {
  role: string;
  deadLetters?: boolean;
}) {
  const [search, setSearch] = useSearchParams();
  const [draft, setDraft] = useState(() => ({
    status: search.get("status") ?? "",
    job_type_id: search.get("job_type_id") ?? "",
    queue: search.get("queue") ?? "",
    after: search.get("after") ?? "",
  }));
  useEffect(() => {
    setDraft({
      status: search.get("status") ?? "",
      job_type_id: search.get("job_type_id") ?? "",
      queue: search.get("queue") ?? "",
      after: search.get("after") ?? "",
    });
  }, [search]);
  const params = new URLSearchParams();
  if (search.get("status") && !deadLetters)
    params.set("status", search.get("status")!);
  if (search.get("job_type_id"))
    params.set("job_type_id", search.get("job_type_id")!);
  if (search.get("queue") && role === "admin")
    params.set("queue", search.get("queue")!);
  if (search.get("after") && !Number.isNaN(Date.parse(search.get("after")!)))
    params.set("created_after", new Date(search.get("after")!).toISOString());
  return (
    <div>
      <PageHeading
        title={deadLetters ? "Dead letters" : "Jobs"}
        description={
          deadLetters
            ? "Jobs that exhausted their attempts. Inspect the error before replaying."
            : "Inspect execution state, attempts, and results. Updates every 15 seconds."
        }
        action={
          role === "producer" ? (
            <Link className="button button-primary" to="/producer/submit">
              Submit a job
            </Link>
          ) : undefined
        }
      />
      <form
        className="filters"
        onSubmit={(event) => {
          event.preventDefault();
          setSearch(
            Object.fromEntries(Object.entries(draft).filter(([, v]) => v)),
          );
        }}
      >
        {!deadLetters && (
          <Field label="Status">
            <select
              className={inputClass}
              value={draft.status}
              onChange={(e) => setDraft({ ...draft, status: e.target.value })}
            >
              <option value="">All statuses</option>
              {[
                "CREATED",
                "QUEUED",
                "RUNNING",
                "RETRY_WAIT",
                "COMPLETED",
                "FAILED",
                "DEAD_LETTERED",
              ].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Job Type ID">
          <input
            className={inputClass}
            value={draft.job_type_id}
            onChange={(e) =>
              setDraft({ ...draft, job_type_id: e.target.value })
            }
            placeholder="Filter by UUID"
            pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
          />
        </Field>
        {role === "admin" && (
          <Field label="Queue">
            <input
              className={inputClass}
              value={draft.queue}
              onChange={(e) => setDraft({ ...draft, queue: e.target.value })}
              placeholder="All queues"
            />
          </Field>
        )}
        <Field label="Created after">
          <input
            className={inputClass}
            type="datetime-local"
            value={draft.after}
            onChange={(e) => setDraft({ ...draft, after: e.target.value })}
          />
        </Field>
        <Button variant="secondary">Apply filters</Button>
        {(search.size > 0 || Object.values(draft).some(Boolean)) && (
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setDraft({ status: "", job_type_id: "", queue: "", after: "" });
              setSearch({});
            }}
          >
            Clear
          </Button>
        )}
      </form>
      <JobRows
        path={`/${role}/${deadLetters ? "dead-letters" : "jobs"}?${params}`}
      />
    </div>
  );
}
function JobRows({ path }: { path: string }) {
  const q = usePage<JobSummary>(path);
  return (
    <Panel
      title="Execution history"
      description="Newest first · 25 jobs per page"
    >
      <QueryState query={q} />
      {q.data && <JobTable jobs={q.data.items} bare />}
      {q.pager}
    </Panel>
  );
}
interface Attempt {
  attempt_number: number;
  worker_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  error: unknown;
}
interface Detail extends JobSummary {
  job_type_id: string;
  producer_id: string;
  publisher_id: string;
  payload: unknown;
  result_ref: string | null;
  error: unknown;
  attempt_history: Attempt[];
  replay_of_job_id: string | null;
  available_at: string;
  worker_id: string | null;
  lease_expires_at: string | null;
  updated_at: string;
  completed_at: string | null;
  dead_lettered_at: string | null;
}
export function JobDetailPage({ role }: { role: string }) {
  const { id } = useParams();
  const q = useQuery({
    queryKey: ["job-detail", id],
    queryFn: () => api<Detail>(`/jobs/${id}`),
    refetchInterval: 5000,
  });
  const action = useAction();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const j = q.data;
  return (
    <div className="space-y-6">
      <Link to={`/${role}/jobs`} className="text-link">
        ← Jobs
      </Link>
      <QueryState query={q} />
      {j && (
        <>
          <PageHeading
            eyebrow="Job details · refreshes every 5 seconds"
            title={j.type}
            action={
              <>
                {j.status === "COMPLETED" && j.result_ref && (
                  <a
                    className="button button-primary"
                    href={`/jobs/${id}/result`}
                  >
                    Download result
                  </a>
                )}
                {j.status === "DEAD_LETTERED" &&
                  (user?.roles.includes("ADMIN") ||
                    (user?.roles.includes("PRODUCER") &&
                      user.user_id === j.producer_id)) && (
                    <Button
                      disabled={action.busy}
                      onClick={async () => {
                        if (
                          await action.confirm({
                            title: "Replay this job?",
                            description:
                              "Create a new job with the same payload and original release. The original remains unchanged; the new job may execute immediately.",
                            label: "Replay job",
                            destructive: false,
                          })
                        )
                          void action.run(async () => {
                            const next = await write<{ job_id: string }>(
                              `/jobs/${id}/replay`,
                              undefined,
                              "POST",
                              { "Idempotency-Key": key },
                            );
                            setKey(crypto.randomUUID());
                            navigate(`/${role}/jobs/${next.job_id}`);
                          }, "Job replayed");
                      }}
                    >
                      Replay as new job
                    </Button>
                  )}
              </>
            }
          />
          <div className="flex flex-wrap items-center gap-5">
            <StatusBadge status={j.status} />
            <IdCell value={j.job_id} />
            {j.replay_of_job_id && (
              <Link
                className="text-link"
                to={`/${role}/jobs/${j.replay_of_job_id}`}
              >
                View original job
              </Link>
            )}
          </div>
          <dl className="metadata border-y border-line">
            <div>
              <dt>Queue</dt>
              <dd>
                <code>{j.queue}</code>
              </dd>
            </div>
            <div>
              <dt>Attempts</dt>
              <dd>
                {j.attempt_count} / {j.max_attempts}
              </dd>
            </div>
            <div>
              <dt>Priority</dt>
              <dd>{j.priority}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>
                <TimeCell value={j.created_at} />
              </dd>
            </div>
            <div>
              <dt>Job Type</dt>
              <dd>
                {role !== "producer" ? (
                  <Link
                    className="text-link"
                    to={`/${role}/releases/${j.job_type_id}`}
                  >
                    View release →
                  </Link>
                ) : (
                  <IdCell value={j.job_type_id} />
                )}
              </dd>
            </div>
            <div>
              <dt>Current worker</dt>
              <dd>{j.worker_id ?? "Unassigned"}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>
                <TimeCell value={j.updated_at} />
              </dd>
            </div>
            <div>
              <dt>
                {j.completed_at
                  ? "Completed"
                  : j.dead_lettered_at
                    ? "Dead lettered"
                    : "Available"}
              </dt>
              <dd>
                <TimeCell
                  value={j.completed_at ?? j.dead_lettered_at ?? j.available_at}
                />
              </dd>
            </div>
            {j.lease_expires_at && (
              <div>
                <dt>Lease expires</dt>
                <dd>
                  <TimeCell value={j.lease_expires_at} />
                </dd>
              </div>
            )}
            <div>
              <dt>Publisher</dt>
              <dd>
                <IdCell value={j.publisher_id} />
              </dd>
            </div>
            <div>
              <dt>Producer</dt>
              <dd>
                <IdCell value={j.producer_id} />
              </dd>
            </div>
          </dl>
          {j.error != null && (
            <Card title="Latest error">
              <Json value={j.error} label="Error details" />
            </Card>
          )}
          <Panel
            title="Execution attempts"
            description="Attempt outcomes and errors reported by workers"
          >
            {j.attempt_history.length === 0 ? (
              <EmptyRows
                label="attempts yet"
                description="An attempt appears when a worker claims this job."
              />
            ) : (
              <DataTable label="Execution attempts">
                <thead>
                  <tr>
                    <th>Attempt</th>
                    <th>Worker</th>
                    <th>Outcome</th>
                    <th className="numeric">Started</th>
                    <th className="numeric">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {j.attempt_history.map((a) => (
                    <tr key={a.attempt_number}>
                      <td className="numeric">{a.attempt_number}</td>
                      <td>
                        <code>{a.worker_id}</code>
                      </td>
                      <td>
                        <StatusBadge status={a.status} />
                        {a.error != null && (
                          <div className="mt-2">
                            <Json
                              value={a.error}
                              label={`Attempt ${a.attempt_number} error`}
                              collapsed
                            />
                          </div>
                        )}
                      </td>
                      <td className="numeric">
                        <TimeCell value={a.started_at} />
                      </td>
                      <td className="numeric">
                        {duration(
                          a.finished_at
                            ? Date.parse(a.finished_at) -
                                Date.parse(a.started_at)
                            : null,
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            )}
          </Panel>
          <Card title="Payload">
            <Json value={j.payload} label="Input payload" />
          </Card>
        </>
      )}
    </div>
  );
}
export function SubmitPage() {
  return (
    <div className="max-w-3xl">
      <PageHeading
        title="Submit a job"
        description="Run an approved handler with a JSON payload."
      />
      <Card title="Job configuration">
        <p className="text-sm text-muted">
          Select an active, approved release. Payloads must be JSON objects.
        </p>
        <Submission />
      </Card>
    </div>
  );
}
function Submission() {
  const q = usePage<Release>("/catalog/job-types");
  const [id, setId] = useState("");
  const [selectedRelease, setSelectedRelease] = useState<Release>();
  const [payload, setPayload] = useState("{}");
  const [priority, setPriority] = useState(0);
  const [attempts, setAttempts] = useState(5);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const action = useAction();
  const navigate = useNavigate();
  return (
    <>
      <QueryState query={q} />
      {q.data?.items.length === 0 && (
        <p className="notice">
          No active releases available. A publisher must upload a handler and an
          administrator must approve it before you can submit jobs.
        </p>
      )}

      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void action.run(async () => {
            const parsed = JSON.parse(payload);
            if (!parsed || Array.isArray(parsed) || typeof parsed !== "object")
              throw new Error("Payload must be a JSON object");
            const job = await write<{ job_id: string }>(
              "/jobs",
              {
                job_type_id: id,
                payload: parsed,
                priority,
                max_attempts: attempts,
              },
              "POST",
              { "Idempotency-Key": key },
            );
            setKey(crypto.randomUUID());
            navigate(`/producer/jobs/${job.job_id}`);
          }, "Job submitted");
        }}
      >
        <Field label="Active release">
          <select
            className={inputClass}
            required
            value={id}
            onChange={(e) => {
              setId(e.target.value);
              setSelectedRelease(
                q.data?.items.find((r) => r.job_type_id === e.target.value),
              );
              setKey(crypto.randomUUID());
            }}
          >
            <option value="">Choose a release</option>
            {selectedRelease &&
              !q.data?.items.some(
                (r) => r.job_type_id === selectedRelease.job_type_id,
              ) && (
                <option value={selectedRelease.job_type_id}>
                  {selectedRelease.name} v{selectedRelease.version} ·{" "}
                  {selectedRelease.publisher_id}
                </option>
              )}
            {q.data?.items.map((r) => (
              <option key={r.job_type_id} value={r.job_type_id}>
                {r.name} v{r.version} · {r.publisher_id}
              </option>
            ))}
          </select>
        </Field>
        <div className="catalog-pagination">
          <span>Release catalog</span>
          {q.pager}
        </div>
        <Field label="JSON payload">
          <textarea
            className={`${inputClass} min-h-40 font-mono`}
            required
            value={payload}
            onChange={(e) => {
              setPayload(e.target.value);
              setKey(crypto.randomUUID());
            }}
          />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Priority">
            <input
              className={inputClass}
              type="number"
              min={0}
              max={1000000}
              required
              value={priority}
              onChange={(e) => {
                setPriority(Number(e.target.value));
                setKey(crypto.randomUUID());
              }}
            />
          </Field>
          <Field label="Maximum attempts">
            <input
              className={inputClass}
              type="number"
              min={1}
              max={100}
              required
              value={attempts}
              onChange={(e) => {
                setAttempts(Number(e.target.value));
                setKey(crypto.randomUUID());
              }}
            />
          </Field>
        </div>
        <Button disabled={action.busy || !id}>Submit job</Button>
      </form>
    </>
  );
}
