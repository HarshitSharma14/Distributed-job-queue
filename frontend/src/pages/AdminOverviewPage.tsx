import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AdminOverview } from "../api/types";
import { PageError, PageSkeleton } from "../components/Feedback";
import {
  EmptyRows,
  PageHeading,
  Panel,
  RefreshButton,
  StatCard,
  StatusBadge,
  statusTone,
} from "../components/DashboardPrimitives";
import { api } from "../lib/api";
import { compactNumber, duration, percent } from "../lib/format";

export function AdminOverviewPage() {
  const [window, setWindow] = useState("24h");
  const [selected, setSelected] = useState("");
  const overview = useQuery({
    queryKey: ["admin-overview", window],
    queryFn: () => api<AdminOverview>(`/admin/overview?window=${window}`),
    refetchInterval: 30_000,
  });
  if (overview.isPending) return <PageSkeleton />;
  if (overview.isError)
    return (
      <PageError message={overview.error.message} retry={overview.refetch} />
    );
  const { exact, operational } = overview.data;
  const seriesKey = (item: (typeof operational.series)[number]) =>
    `${item.metric}:${JSON.stringify(item.labels)}`;
  const series =
    operational.series.find((item) => seriesKey(item) === selected) ??
    operational.series.find((item) => item.metric === "job_submission_rate") ??
    operational.series[0];
  const chartData =
    series?.points.map((point) => ({
      time: new Date(point.timestamp).getTime(),
      value: point.value,
    })) ?? [];
  const shortTime = (timestamp: number) =>
    new Date(timestamp).toLocaleString(
      [],
      window === "7d"
        ? { month: "short", day: "numeric" }
        : { hour: "2-digit", minute: "2-digit" },
    );
  return (
    <div className="space-y-6">
      <PageHeading
        title="System overview"
        description="Platform execution and delivery. Updates every 30 seconds."
        action={
          <RefreshButton
            refresh={overview.refetch}
            busy={overview.isFetching}
          />
        }
      />
      <div className="stats-grid">
        <StatCard
          label="Total jobs"
          value={compactNumber(exact.total_jobs)}
          note="All durable jobs"
        />
        <StatCard
          label="Terminal success"
          value={percent(exact.terminal_success_rate)}
          note={`${exact.terminal_jobs.toLocaleString()} terminal jobs`}
        />
        <StatCard
          label="Average completion"
          value={duration(exact.average_completion_latency_ms)}
          note="Created to completed"
        />
        <StatCard
          label="Total attempts"
          value={compactNumber(exact.total_attempts)}
          note={`${exact.average_attempts?.toFixed(2) ?? "—"} per job`}
        />
      </div>
      {(exact.status_counts.DEAD_LETTERED ?? 0) > 0 && (
        <div className="notice flex flex-wrap items-center justify-between gap-3">
          <span>
            {exact.status_counts.DEAD_LETTERED.toLocaleString()} jobs exhausted
            their attempts.
          </span>
          <Link className="text-link" to="/admin/dead-letters">
            Inspect dead letters →
          </Link>
        </div>
      )}
      <div className="grid gap-6 xl:grid-cols-[1.6fr_1fr]">
        <Panel
          title="Operational trends"
          description="Prometheus samples · separate from the all-time totals above"
          action={
            <select
              className="input"
              aria-label="Trend time range"
              value={window}
              onChange={(event) => setWindow(event.target.value)}
            >
              {["1h", "6h", "24h", "7d"].map((w) => (
                <option key={w} value={w}>
                  Last {w}
                </option>
              ))}
            </select>
          }
        >
          {!!operational.series.length && (
            <div className="flex flex-wrap items-center gap-3 px-5 pt-4">
              <select
                className="input"
                aria-label="Operational metric"
                value={series ? seriesKey(series) : ""}
                onChange={(event) => setSelected(event.target.value)}
              >
                {operational.series.map((item) => (
                  <option key={seriesKey(item)} value={seriesKey(item)}>
                    {item.metric.replaceAll("_", " ")}{" "}
                    {Object.values(item.labels).length
                      ? `· ${Object.entries(item.labels)
                          .map(([k, v]) => `${k}: ${v}`)
                          .join(", ")}`
                      : ""}
                  </option>
                ))}
              </select>
              <span className="text-xs text-muted">
                {series?.unit.replaceAll("_", " ")}
              </span>
            </div>
          )}
          <div className="h-72 px-4 py-5">
            {operational.available &&
            chartData.some((p) => p.value !== null) ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={chartData}
                  margin={{ top: 5, right: 14, bottom: 4, left: 0 }}
                >
                  <CartesianGrid stroke="#303640" vertical={false} />
                  <XAxis
                    dataKey="time"
                    tickFormatter={shortTime}
                    tick={{ fontSize: 10, fill: "#969fae" }}
                    axisLine={false}
                    tickLine={false}
                    minTickGap={40}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: "#969fae" }}
                    axisLine={false}
                    tickLine={false}
                    width={46}
                  />
                  <Tooltip
                    content={({ active, payload, label }) =>
                      active && payload?.length ? (
                        <div className="chart-tooltip">
                          <p className="text-muted">
                            {new Date(Number(label)).toLocaleString()}
                          </p>
                          <p>
                            {payload[0].value}{" "}
                            {series?.unit.replaceAll("_", " ")}
                          </p>
                        </div>
                      ) : null
                    }
                  />
                  <Line
                    type="linear"
                    dataKey="value"
                    stroke="#8eafff"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <EmptyRows
                label={
                  operational.available
                    ? "metric samples in this window"
                    : "operational metrics available"
                }
                description={
                  operational.available
                    ? "Choose another time range or metric."
                    : operational.unavailable_reason === "not_configured"
                      ? "Prometheus is not configured. Durable job totals remain available."
                      : "Prometheus could not be reached. Durable job totals remain available; use Refresh to retry."
                }
              />
            )}
          </div>
        </Panel>
        <Panel
          title="Job lifecycle"
          description="Current state of all durable jobs"
        >
          {!exact.total_jobs ? (
            <EmptyRows
              label="jobs yet"
              description="Lifecycle counts appear after jobs are submitted."
            />
          ) : (
            <div className="py-3">
              {Object.entries(exact.status_counts).map(([status, count]) => (
                <Link
                  className={`lifecycle-row status-${statusTone(status)}`}
                  key={status}
                  to={`/admin/jobs?status=${status}`}
                >
                  <StatusBadge status={status} />
                  <span className="bar">
                    <span
                      style={{
                        width: `${exact.total_jobs ? (count / exact.total_jobs) * 100 : 0}%`,
                      }}
                    />
                  </span>
                  <span className="count">{count.toLocaleString()}</span>
                </Link>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
