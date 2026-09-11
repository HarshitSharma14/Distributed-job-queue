import { useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthProvider";
import { api } from "../lib/api";
import {
  DataTable,
  EmptyRows,
  IdCell,
  PageHeading,
  Panel,
  StatusBadge,
  TimeCell,
} from "../components/DashboardPrimitives";
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

export interface Release {
  job_type_id: string;
  name: string;
  version: number;
  queue: string;
  status: string;
  publisher_id: string;
  supersedes_job_type_id?: string | null;
}
interface Artifact {
  artifact_id: string;
  artifact_status: string;
  rejection_reason: string | null;
  actual_sha256: string | null;
  approved_at: string | null;
  rejected_at: string | null;
}
export function ReleasesPage({ role }: { role: "admin" | "publisher" }) {
  const [status, setStatus] = useState("");
  const [name, setName] = useState("");
  const [queue, setQueue] = useState("");
  const action = useAction();
  const navigate = useNavigate();
  return (
    <div className="space-y-6">
      <PageHeading
        title="Job Types & releases"
        description="Versioned handlers, validation, and release approval."
      />

      {role === "publisher" && (
        <Card title="Create Job Type">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              void action.run(async () => {
                const release = await write<Release>("/job-types", {
                  name,
                  queue,
                });
                navigate(`/${role}/releases/${release.job_type_id}`);
              });
            }}
          >
            <Field label="Name">
              <input
                className={inputClass}
                required
                pattern="[A-Za-z0-9_.-]+"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field label="Queue">
              <input
                className={inputClass}
                required
                pattern="[A-Za-z0-9_.-]+"
                value={queue}
                onChange={(e) => setQueue(e.target.value)}
              />
            </Field>
            <Button disabled={action.busy}>Create draft</Button>
          </form>
        </Card>
      )}
      <div className="filters">
        <Field label="Release status">
          <select
            className={inputClass}
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="">All releases</option>
            {["DRAFT", "PENDING_APPROVAL", "ACTIVE", "DISABLED"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </Field>
      </div>
      <ReleaseList key={status} role={role} status={status} />
    </div>
  );
}
function ReleaseList({ role, status }: { role: string; status: string }) {
  const list = usePage<Release>(`/management/job-types?status=${status}`);
  return (
    <Panel
      title="Releases"
      description="Immutable handler versions · 25 releases per page"
    >
      <QueryState query={list} />
      {list.data?.items.length === 0 && (
        <EmptyRows
          label="releases found"
          description="Publishers create a draft and upload a handler before an administrator approves the release."
        />
      )}
      {!!list.data?.items.length && (
        <DataTable label="Releases">
          <thead>
            <tr>
              <th>Job Type</th>
              <th>Version</th>
              <th>Status</th>
              <th>Queue</th>
              <th>Publisher</th>
            </tr>
          </thead>
          <tbody>
            {list.data.items.map((r) => (
              <tr key={r.job_type_id}>
                <td>
                  <Link
                    className="row-title"
                    to={`/${role}/releases/${r.job_type_id}`}
                  >
                    {r.name}
                  </Link>
                  <div>
                    <IdCell value={r.job_type_id} />
                  </div>
                </td>
                <td>
                  <code>v{r.version}</code>
                </td>
                <td>
                  <StatusBadge status={r.status} />
                </td>
                <td>
                  <code>{r.queue}</code>
                </td>
                <td>
                  <IdCell value={r.publisher_id} />
                </td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      {list.pager}
    </Panel>
  );
}
export function ReleaseDetailPage({ role }: { role: "admin" | "publisher" }) {
  const { id } = useParams();
  const query = useQuery({
    queryKey: ["release", id],
    queryFn: () => api<Release>(`/job-types/${id}`),
  });
  const action = useAction();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [reason, setReason] = useState("");
  const [newQueue, setNewQueue] = useState("");
  const list = usePage<Artifact>(`/job-types/${id}/artifacts`);
  const r = query.data;
  return (
    <div className="space-y-6">
      <Link to={`/${role}/releases`} className="text-accent">
        ← Releases
      </Link>
      <QueryState query={query} />

      {r && (
        <>
          <PageHeading
            eyebrow="Release details"
            title={`${r.name} · v${r.version}`}
          />
          <Card title="Release configuration">
            <div className="flex flex-wrap items-center gap-5">
              <StatusBadge status={r.status} />
              <IdCell value={r.job_type_id} />
            </div>
            <dl className="metadata">
              <div>
                <dt>Queue</dt>
                <dd>
                  <code>{r.queue}</code>
                </dd>
              </div>
              <div>
                <dt>Publisher</dt>
                <dd>
                  <IdCell value={r.publisher_id} />
                </dd>
              </div>
              {r.supersedes_job_type_id && (
                <div>
                  <dt>Previous version</dt>
                  <dd>
                    <Link
                      className="text-link"
                      to={`/${role}/releases/${r.supersedes_job_type_id}`}
                    >
                      View previous release →
                    </Link>
                  </dd>
                </div>
              )}
            </dl>
            {r.status !== "DISABLED" && (
              <Button
                disabled={action.busy}
                variant="danger"
                onClick={async () => {
                  if (
                    await action.confirm({
                      title: "Disable this release?",
                      description:
                        "New submissions and enrollments for this version will be blocked. Existing jobs retain their pinned release.",
                      label: "Disable release",
                    })
                  )
                    void action.run(
                      () => write(`/job-types/${id}/disable`),
                      "Release disabled",
                    );
                }}
              >
                Disable release
              </Button>
            )}
            {role === "publisher" &&
              r.publisher_id === user?.user_id &&
              ["ACTIVE", "DISABLED"].includes(r.status) && (
                <form
                  className="version-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void action.run(async () => {
                      const next = await write<Release>(
                        `/job-types/${id}/versions`,
                        newQueue ? { queue: newQueue } : {},
                      );
                      navigate(`/publisher/releases/${next.job_type_id}`);
                    });
                  }}
                >
                  <Field label="Queue for next version">
                    <input
                      className={inputClass}
                      placeholder={`Keep queue: ${r.queue}`}
                      pattern="[A-Za-z0-9_.-]+"
                      value={newQueue}
                      onChange={(e) => setNewQueue(e.target.value)}
                    />
                  </Field>
                  <Button disabled={action.busy}>Create next version</Button>
                </form>
              )}
          </Card>
          {role === "publisher" && r.status === "DRAFT" && (
            <Card title="Upload handler">
              <div className="space-y-4 text-sm text-secondary">
                <p>
                  Package the code for <strong>{r.name}</strong> as a ZIP. Put
                  the files directly at the ZIP root—do not wrap them in an
                  extra folder.
                </p>
                <ol className="list-decimal space-y-2 pl-5">
                  <li>
                    Add <code>manifest.json</code> with the exact Job Type name
                    and a Python entrypoint in <code>module:function</code>
                    format.
                  </li>
                  <li>
                    Add that Python module and define the entrypoint function.
                    It receives the submitted JSON payload and must return a
                    JSON-serializable value.
                  </li>
                  <li>
                    ZIP the files themselves, download the example below if
                    useful, then upload the ZIP for validation.
                  </li>
                  <li>
                    After validation shows <code>PENDING_APPROVAL</code>, ask an
                    Admin to review and approve the release.
                  </li>
                </ol>
                <div className="grid gap-4 lg:grid-cols-2">
                  <div>
                    <p className="font-medium">Required ZIP structure</p>
                    <pre className="mt-2 overflow-x-auto rounded-lg bg-canvas p-4 text-xs text-primary">{`example-handler.zip
├── manifest.json
└── handler.py`}</pre>
                    <p className="mt-2 text-xs text-muted">
                      Invalid: <code>example-handler/manifest.json</code>. The
                      manifest must be at the archive root.
                    </p>
                  </div>
                  <div>
                    <p className="font-medium">manifest.json</p>
                    <pre className="mt-2 overflow-x-auto rounded-lg bg-canvas p-4 text-xs text-primary">
                      {JSON.stringify(
                        { job_type: r.name, entrypoint: "handler:run" },
                        null,
                        2,
                      )}
                    </pre>
                  </div>
                </div>
                <div>
                  <p className="font-medium">handler.py</p>
                  <pre className="mt-2 overflow-x-auto rounded-lg bg-canvas p-4 text-xs text-primary">{`def run(payload):
    # payload is the JSON object submitted by the Producer
    return {"message": "Handler completed", "input": payload}`}</pre>
                </div>
                <p className="rounded-lg border border-line bg-raised p-3 text-warning">
                  Runtime limits: Python standard library only, no network
                  access, no host secrets, and a read-only isolated container.
                  Do not include symlinks or unsafe paths such as{" "}
                  <code>../</code>.
                </p>
              </div>
              <a
                className="inline-block font-medium text-accent underline"
                href={`/job-types/${id}/example.zip`}
              >
                Download a ready-to-edit example ZIP
              </a>
              <form
                className="space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (file)
                    void action.run(async () => {
                      const result = await api<Artifact>(
                        `/job-types/${id}/upload`,
                        {
                          method: "POST",
                          headers: { "Content-Type": "application/zip" },
                          body: file,
                        },
                      );
                      if (result.artifact_status === "REJECTED")
                        throw new Error(
                          result.rejection_reason ?? "Invalid bundle",
                        );
                      setFile(null);
                    }, "Uploaded and verified. Awaiting Admin approval.");
                }}
              >
                <input
                  aria-label="Handler ZIP"
                  type="file"
                  accept=".zip,application/zip"
                  required
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
                <Button disabled={action.busy || !file}>
                  Upload and validate
                </Button>
              </form>
            </Card>
          )}
          <Card title="Artifact history">
            <QueryState query={list} />
            {list.data?.items.length === 0 && (
              <EmptyRows
                label="artifacts yet"
                description="Upload a handler ZIP to begin validation and review."
              />
            )}
            {list.data?.items.map((a) => (
              <article
                key={a.artifact_id}
                className="space-y-3 border-b border-line py-4"
              >
                <div className="flex flex-wrap items-center gap-4">
                  <StatusBadge status={a.artifact_status} />
                  <IdCell value={a.artifact_id} />
                  {(a.approved_at || a.rejected_at) && (
                    <TimeCell value={a.approved_at ?? a.rejected_at} />
                  )}
                </div>
                <Json value={a} label="Artifact metadata" collapsed />
                {role === "admin" &&
                  r.status === "PENDING_APPROVAL" &&
                  a.artifact_status === "VERIFIED" && (
                    <div className="flex flex-wrap items-end gap-3">
                      <Button
                        disabled={action.busy}
                        onClick={async () => {
                          if (
                            !(await action.confirm({
                              title: "Approve this release?",
                              description:
                                "Sign this exact handler artifact and enable job submissions and worker enrollments for this version.",
                              label: "Approve release",
                              destructive: false,
                            }))
                          )
                            return;
                          void action.run(
                            () =>
                              write(
                                `/job-types/${id}/handler-artifacts/${a.artifact_id}/approve`,
                              ),
                            "Release approved and signed",
                          );
                        }}
                      >
                        Approve release
                      </Button>
                      <Field label="Rejection reason">
                        <input
                          className={inputClass}
                          value={reason}
                          maxLength={2000}
                          onChange={(e) => setReason(e.target.value)}
                        />
                      </Field>
                      <Button
                        variant="danger"
                        disabled={action.busy || !reason.trim()}
                        onClick={async () => {
                          if (
                            !(await action.confirm({
                              title: "Reject this release?",
                              description: `The publisher will see this reason: ${reason}`,
                              label: "Reject release",
                            }))
                          )
                            return;
                          void action.run(
                            () =>
                              write(
                                `/job-types/${id}/handler-artifacts/${a.artifact_id}/reject`,
                                { reason },
                              ),
                            "Release rejected",
                          );
                        }}
                      >
                        Reject release
                      </Button>
                    </div>
                  )}
              </article>
            ))}
            {list.pager}
          </Card>
        </>
      )}
    </div>
  );
}
