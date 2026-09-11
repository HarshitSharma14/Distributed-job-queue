import { useState, type FormEvent } from "react";
import { Brand } from "../layout/DashboardLayout";
import { Button, Field, inputClass } from "../components/Management";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import { ApiError } from "../lib/api";

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
    <main className="auth-page">
      <div className="auth-brand">
        <Brand />
      </div>
      <section className="auth-form">
        <h1>Sign in to Relay</h1>
        <p className="page-description">
          Use your platform account to continue.
        </p>
        <form onSubmit={submit}>
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
      </section>
      <p className="auth-footer">
        Account access is managed by your platform administrator.
      </p>
    </main>
  );
}
