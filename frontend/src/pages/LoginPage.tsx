import { useState, type FormEvent } from "react";
import { ArrowRight, RadioTower, ShieldCheck } from "lucide-react";
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
      const destination = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(destination, { replace: true });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Unable to sign in right now");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="grid min-h-screen bg-[#101827] lg:grid-cols-[1.1fr_0.9fr]">
      <section className="relative hidden overflow-hidden p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_15%,rgba(99,102,241,0.32),transparent_36%),radial-gradient(circle_at_80%_75%,rgba(16,185,129,0.18),transparent_32%)]" />
        <div className="absolute inset-0 opacity-[0.07] [background-image:linear-gradient(rgba(255,255,255,.5)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.5)_1px,transparent_1px)] [background-size:40px_40px]" />
        <div className="relative flex items-center gap-3"><div className="grid h-11 w-11 place-items-center rounded-xl bg-indigo-500"><RadioTower className="h-5 w-5" /></div><span className="text-lg font-semibold">Relay</span></div>
        <div className="relative max-w-xl"><p className="text-sm font-semibold uppercase tracking-[0.25em] text-indigo-300">Infrastructure, made visible</p><h1 className="mt-5 text-5xl font-semibold leading-[1.08] tracking-tight">Every job. Every worker. One clear signal.</h1><p className="mt-6 max-w-lg text-base leading-7 text-slate-300">Operate distributed work without losing sight of ownership, retries, leases, or results.</p></div>
        <div className="relative flex items-center gap-2 text-xs text-slate-400"><ShieldCheck className="h-4 w-4 text-emerald-400" />Infrastructure credentials never enter this browser.</div>
      </section>
      <section className="grid place-items-center bg-[#f6f7f2] px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-10 flex items-center gap-3 lg:hidden"><RadioTower className="h-6 w-6 text-indigo-600" /><span className="font-semibold">Relay</span></div>
          <p className="text-xs font-bold uppercase tracking-[0.22em] text-indigo-600">Control room</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight">Welcome back</h2>
          <p className="mt-2 text-sm text-slate-500">Use your platform account to continue.</p>
          <form className="mt-8 space-y-5" onSubmit={submit}>
            <label className="block"><span className="text-sm font-medium text-slate-700">Email</span><input className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
            <label className="block"><span className="text-sm font-medium text-slate-700">Password</span><input className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
            {error && <p className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700" role="alert">{error}</p>}
            <button disabled={submitting} className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-indigo-600/20 transition hover:bg-indigo-500 disabled:opacity-60">{submitting ? "Signing in…" : "Sign in"}<ArrowRight className="h-4 w-4" /></button>
          </form>
        </div>
      </section>
    </main>
  );
}
