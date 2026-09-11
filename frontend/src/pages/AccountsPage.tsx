import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthProvider";
import { Brand } from "../layout/DashboardLayout";
import {
  DataTable,
  EmptyRows,
  IdCell,
  PageHeading,
  Panel,
  StatusBadge,
  TimeCell,
} from "../components/DashboardPrimitives";
import type { UserRole } from "../lib/api";
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

const roles: UserRole[] = ["ADMIN", "PUBLISHER", "PRODUCER", "WORKER"];
interface Account {
  user_id: string;
  email: string;
  display_name: string;
  roles: UserRole[];
  status: string;
}
const blank = {
  email: "",
  display_name: "",
  roles: ["PRODUCER"] as UserRole[],
  status: "ACTIVE",
};
export function AccountsPage() {
  const list = usePage<Account>("/admin/users");
  const action = useAction();
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState(blank);
  const [password, setPassword] = useState("");
  const [reset, setReset] = useState<Account | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (
      editing &&
      !(await action.confirm({
        title: "Update account access?",
        description: `Save roles and status for ${form.email}. Removing roles or disabling the account revokes affected access.`,
        label: "Save changes",
      }))
    )
      return;
    void action.run(async () => {
      await write(
        editing ? `/admin/users/${editing}` : "/admin/users",
        editing ? form : { ...form, temporary_password: password },
        editing ? "PUT" : "POST",
      );
      setForm(blank);
      setEditing(null);
      setPassword("");
    });
  }
  return (
    <div className="space-y-6">
      <PageHeading
        title="Accounts"
        description="Manage platform identities, roles, and account access."
      />

      <Card title={editing ? "Edit account" : "Create account"}>
        <form className="grid gap-4 md:grid-cols-2" onSubmit={submit}>
          <Field label="Email">
            <input
              className={inputClass}
              type="email"
              required
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </Field>
          <Field label="Display name">
            <input
              className={inputClass}
              required
              value={form.display_name}
              onChange={(e) =>
                setForm({ ...form, display_name: e.target.value })
              }
            />
          </Field>
          <fieldset className="flex flex-wrap gap-4">
            <legend className="mb-2 text-sm font-medium">Roles</legend>
            {roles.map((r) => (
              <label key={r} className="text-sm">
                <input
                  type="checkbox"
                  checked={form.roles.includes(r)}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      roles: e.target.checked
                        ? [...form.roles, r]
                        : form.roles.filter((v) => v !== r),
                    })
                  }
                />{" "}
                {r}
              </label>
            ))}
          </fieldset>
          <Field label="Status">
            <select
              className={inputClass}
              value={form.status}
              onChange={(e) => setForm({ ...form, status: e.target.value })}
            >
              <option>ACTIVE</option>
              <option>DISABLED</option>
            </select>
          </Field>
          {!editing && (
            <Field label="Temporary password (at least 12 characters)">
              <input
                className={inputClass}
                type="password"
                autoComplete="new-password"
                required
                minLength={12}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
          )}
          <div className="flex items-end gap-3">
            <Button disabled={action.busy || !form.roles.length}>
              Save account
            </Button>
            {editing && (
              <Button
                variant="secondary"
                type="button"
                onClick={() => {
                  setEditing(null);
                  setForm(blank);
                }}
              >
                Cancel edit
              </Button>
            )}
          </div>
        </form>
      </Card>
      <Panel
        title="All accounts"
        description="Role changes and password resets affect account access"
      >
        <QueryState query={list} />
        {list.data?.items.length === 0 && (
          <EmptyRows
            label="accounts found"
            description="Create an account above to grant platform access."
          />
        )}
        {!!list.data?.items.length && (
          <DataTable label="Accounts">
            <thead>
              <tr>
                <th>Account</th>
                <th>Roles</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((u) => (
                <tr key={u.user_id}>
                  <td>
                    <p className="row-title">{u.display_name}</p>
                    <p className="text-muted">{u.email}</p>
                  </td>
                  <td>{u.roles.join(", ")}</td>
                  <td>
                    <StatusBadge status={u.status} />
                  </td>
                  <td>
                    <div className="flex gap-2">
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setEditing(u.user_id);
                          setForm({
                            email: u.email,
                            display_name: u.display_name,
                            roles: u.roles,
                            status: u.status,
                          });
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                      >
                        Edit
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setReset(u);
                          setPassword("");
                        }}
                      >
                        Reset password
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
        {list.pager}
      </Panel>
      {reset && (
        <Card title={`Reset password: ${reset.email}`}>
          <form
            className="flex flex-wrap gap-3"
            onSubmit={async (e) => {
              e.preventDefault();
              if (
                !(await action.confirm({
                  title: "Reset password and revoke access?",
                  description: `${reset.email} must use the temporary password and replace it on sign-in. Existing sessions and credentials will be revoked.`,
                  label: "Reset password",
                }))
              )
                return;
              void action.run(async () => {
                await write(`/admin/users/${reset.user_id}/reset-password`, {
                  temporary_password: password,
                });
                setReset(null);
                setPassword("");
              });
            }}
          >
            <input
              autoFocus
              aria-label="New temporary password"
              className={inputClass}
              required
              type="password"
              minLength={12}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <Button variant="danger" disabled={action.busy}>
              Reset and revoke access
            </Button>
            <Button
              variant="secondary"
              type="button"
              onClick={() => setReset(null)}
            >
              Cancel
            </Button>
          </form>
        </Card>
      )}
    </div>
  );
}
export function PasswordPage() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const action = useAction();
  const navigate = useNavigate();
  const client = useQueryClient();
  const { user } = useAuth();
  return (
    <div className="auth-page">
      <div className="auth-brand">
        <Brand />
      </div>
      <div className="auth-form">
        <h1>Change password</h1>
        <p className="text-sm text-muted">
          {user?.password_change_required
            ? "Replace your temporary password to access your workspace."
            : "Choose a new password. Other browser sessions will be signed out."}
        </p>

        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void action.run(async () => {
              await write("/auth/password", {
                current_password: current,
                new_password: next,
              });
              await client.invalidateQueries({ queryKey: ["current-user"] });
              navigate("/");
            });
          }}
        >
          <Field label="Current password">
            <input
              className={inputClass}
              required
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </Field>
          <Field label="New password">
            <input
              className={inputClass}
              required
              minLength={12}
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
          </Field>
          <Button disabled={action.busy}>Change password</Button>
        </form>
      </div>
      {!user?.password_change_required && (
        <Link className="auth-footer text-link" to="/">
          ← Back to workspace
        </Link>
      )}
    </div>
  );
}
export function AuditPage() {
  const query = usePage<{
    id: string;
    action: string;
    actor_id: string;
    target_id: string;
    created_at: string;
    details: unknown;
  }>("/admin/audit");
  return (
    <div>
      <PageHeading
        title="Action history"
        description="Administrative changes recorded by the platform."
      />
      <Panel title="Audit records">
        <QueryState query={query} />
        {query.data?.items.length === 0 && (
          <EmptyRows
            label="actions recorded"
            description="Account, release, queue, and credential changes will appear here."
          />
        )}
        {!!query.data?.items.length && (
          <DataTable label="Action history">
            <thead>
              <tr>
                <th>Action</th>
                <th>Actor</th>
                <th>Target</th>
                <th className="numeric">Time</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((e) => (
                <tr key={e.id}>
                  <td>
                    <code className="row-title">{e.action}</code>
                  </td>
                  <td>
                    <IdCell value={e.actor_id} />
                  </td>
                  <td>
                    <IdCell value={e.target_id} />
                  </td>
                  <td className="numeric">
                    <TimeCell value={e.created_at} />
                  </td>
                  <td>
                    <Json value={e.details} label="Change details" collapsed />
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
        {query.pager}
      </Panel>
    </div>
  );
}
