import { Check, Copy, Inbox, RefreshCw, type LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { relativeTime } from "../lib/format";
import { useInteraction } from "./InteractionProvider";

export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {action && <div className="page-actions">{action}</div>}
    </header>
  );
}
export function StatCard({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: string;
  icon?: LucideIcon;
  tone?: string;
}) {
  return (
    <article className="stat">
      <p className="stat-label">{label}</p>
      <p className="stat-value">{value}</p>
      <p className="stat-note">{note}</p>
    </article>
  );
}
export function Panel({
  title,
  description,
  children,
  className = "",
  action,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-heading">
        <div>
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}
export function statusTone(status: string) {
  if (
    ["COMPLETED", "ONLINE", "ACTIVE", "APPROVED", "VERIFIED"].includes(status)
  )
    return "success";
  if (
    ["FAILED", "DEAD_LETTERED", "OFFLINE", "REJECTED", "REVOKED"].includes(
      status,
    )
  )
    return "danger";
  if (status === "RUNNING") return "running";
  if (["RETRY_WAIT", "PENDING_APPROVAL", "PAUSED"].includes(status))
    return "warning";
  return "neutral";
}
export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`status status-${statusTone(status)}`}>
      <span className="status-dot" aria-hidden="true" />
      {status.replaceAll("_", " ")}
    </span>
  );
}
export function EmptyRows({
  label,
  description,
  action,
}: {
  label: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <Inbox size={23} aria-hidden="true" />
      <p>No {label}.</p>
      <span>
        {description ??
          "Records will appear here when they are available. If filters are applied, try broadening them."}
      </span>
      {action}
    </div>
  );
}
export function TimeCell({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted">—</span>;
  return (
    <time
      className="time-cell"
      dateTime={value}
      title={new Date(value).toLocaleString()}
    >
      {relativeTime(value)}
    </time>
  );
}
export function CopyButton({
  value,
  label = "Copy",
}: {
  value: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);
  const { notify } = useInteraction();
  return (
    <button
      className="icon-button"
      aria-label={label}
      title={label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          notify(`${label} — copied`);
        } catch {
          notify(
            "Clipboard unavailable. Select and copy the text manually.",
            true,
          );
        }
      }}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
    </button>
  );
}
export function IdCell({ value }: { value: string }) {
  return (
    <span className="id-cell">
      <code title={value}>
        {value.length > 22 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value}
      </code>
      <CopyButton value={value} label="Copy ID" />
    </span>
  );
}
export function DataTable({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  return (
    <div className="table-scroll" role="region" aria-label={label} tabIndex={0}>
      <table className="data-table">{children}</table>
    </div>
  );
}
export function RefreshButton({
  refresh,
  busy,
}: {
  refresh: () => unknown;
  busy?: boolean;
}) {
  return (
    <button
      className="button button-secondary"
      disabled={busy}
      onClick={() => void refresh()}
    >
      <RefreshCw size={14} className={busy ? "animate-spin" : ""} />
      Refresh
    </button>
  );
}
