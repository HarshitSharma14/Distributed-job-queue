export function compactNumber(value: number): string {
  return new Intl.NumberFormat("en", { notation: "compact" }).format(value);
}

export function percent(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export function duration(milliseconds: number | null): string {
  if (milliseconds === null) return "—";
  if (milliseconds < 1_000) return `${Math.round(milliseconds)} ms`;
  return `${(milliseconds / 1_000).toFixed(1)} s`;
}

export function relativeTime(value: string): string {
  const difference = Date.now() - new Date(value).getTime();
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const minutes = Math.round(difference / 60_000);
  if (Math.abs(minutes) < 60) return formatter.format(-minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(-hours, "hour");
  return formatter.format(-Math.round(hours / 24), "day");
}
