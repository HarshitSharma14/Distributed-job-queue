import { useState, type FormEvent } from "react";
import { Brand } from "../layout/DashboardLayout";
import { Button, Field, inputClass } from "../components/Management";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Box,
  KeyRound,
  Send,
  Server,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

import { useAuth } from "../auth/AuthProvider";
import { ApiError } from "../lib/api";
import { demoEmails, demoPassword } from "../lib/demo";

const demoAccounts: {
  role: string;
  email: string;
  description: string;
  icon: LucideIcon;
}[] = [
  {
    role: "Publisher",
    email: demoEmails.Publisher,
    description: "Create and release job handlers",
    icon: Box,
  },
  {
    role: "Producer",
    email: demoEmails.Producer,
    description: "Submit jobs and inspect results",
    icon: Send,
  },
  {
    role: "Worker",
    email: demoEmails.Worker,
    description: "Enroll and monitor worker agents",
    icon: Server,
  },
];

const roles: { name: string; description: string; icon: LucideIcon }[] = [
  {
    name: "Publisher",
    description:
      "Packages application code into reviewed, versioned job handlers.",
    icon: Box,
  },
  {
    name: "Producer",
    description:
      "Sends work to an approved handler and follows every job to a result.",
    icon: Send,
  },
  {
    name: "Worker",
    description:
      "Runs approved handlers in isolated containers and reports each attempt.",
    icon: Server,
  },
  {
    name: "Administrator",
    description:
      "Approves releases and watches queues, failures, workers, and access.",
    icon: ShieldCheck,
  },
];

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  if (user) return <Navigate to="/" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await login(email, password);
      const destination =
        (location.state as { from?: string } | null)?.from ?? "/";
      navigate(destination, { replace: true });
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Unable to sign in right now",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-overview" aria-labelledby="login-introduction">
        <Brand />
        <div className="login-introduction">
          <p className="eyebrow">A job queue you can operate</p>
          <h1 id="login-introduction">
            Follow work from submission to execution.
          </h1>
          <p>
            Relay connects the people who publish executable work, the systems
            that request it, and the workers that run it. Every job remains
            visible through its full lifecycle.
          </p>
        </div>

        <div className="role-guide">
          <h2>The four roles</h2>
          <div className="role-guide-list">
            {roles.map(({ name, description, icon: Icon }) => (
              <div className="role-guide-item" key={name}>
                <span className="role-guide-icon" aria-hidden="true">
                  <Icon size={17} />
                </span>
                <div>
                  <h3>{name}</h3>
                  <p>{description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p className="login-flow" aria-label="Typical workflow">
          <span>Publish</span>
          <ArrowRight size={13} aria-hidden="true" />
          <span>Submit</span>
          <ArrowRight size={13} aria-hidden="true" />
          <span>Execute</span>
          <ArrowRight size={13} aria-hidden="true" />
          <span>Observe</span>
        </p>
      </section>

      <section className="login-access" aria-labelledby="login-heading">
        <div className="login-access-inner">
          <div className="login-heading">
            <p className="eyebrow">Workspace access</p>
            <h1 id="login-heading">Sign in to Relay</h1>
            <p>Use your own account or choose a scoped demo role.</p>
          </div>

          <div className="demo-access">
            <div className="demo-access-heading">
              <h2>Preview by role</h2>
              <p>
                Preconfigured demo accounts help reviewers explore without
                setup. Each one opens only its assigned tools.
              </p>
            </div>
            <div className="demo-account-list">
              {demoAccounts.map(
                ({ role, email: demoEmail, description, icon: Icon }) => (
                  <button
                    className="demo-account"
                    key={role}
                    type="button"
                    onClick={() => {
                      setEmail(demoEmail);
                      setPassword(demoPassword);
                      setError("");
                    }}
                    aria-label={`Use ${role} demo account`}
                  >
                    <span className="demo-account-icon" aria-hidden="true">
                      <Icon size={16} />
                    </span>
                    <span className="demo-account-copy">
                      <strong>{role}</strong>
                      <span>{description}</span>
                      <code>{demoEmail}</code>
                    </span>
                    <ArrowRight size={15} aria-hidden="true" />
                  </button>
                ),
              )}
            </div>
            <p className="demo-password">
              <KeyRound size={14} aria-hidden="true" />
              Shared demo password: <code>{demoPassword}</code>
            </p>
            <p className="demo-access-note">
              These accounts are shared, so recent activity may include other
              visitors.
            </p>
          </div>

          <form className="login-form" onSubmit={submit}>
            <Field label="Email">
              <input
                className={inputClass}
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </Field>
            <Field label="Password">
              <input
                className={inputClass}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </Field>
            {error && (
              <p className="error-state" role="alert">
                {error}
              </p>
            )}
            <Button disabled={submitting}>
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>

          <p className="login-access-note">
            Administrator access is private because it controls accounts,
            approvals, and queues.
          </p>
        </div>
      </section>
    </main>
  );
}
