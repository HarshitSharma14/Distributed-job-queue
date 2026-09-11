import { TriangleAlert } from "lucide-react";

export function TableSkeleton() {
  return (
    <div className="table-skeleton" role="status" aria-label="Loading records">
      <span className="sr-only">Loading records</span>
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i}>
          <span />
          <span />
          <span />
          <span />
        </div>
      ))}
    </div>
  );
}
export function PageSkeleton() {
  return (
    <div className="page-skeleton" role="status" aria-label="Loading page">
      <div className="skeleton-title" />
      <div className="stats-grid">
        {[1, 2, 3, 4].map((n) => (
          <div key={n} className="skeleton-stat" />
        ))}
      </div>
      <TableSkeleton />
    </div>
  );
}
export function FullPageLoader() {
  return (
    <div className="full-loader">
      <PageSkeleton />
    </div>
  );
}
export function PageError({
  message = "This view could not be loaded.",
  retry,
}: {
  message?: string;
  retry?: () => unknown;
}) {
  return (
    <div className="error-state" role="alert">
      <TriangleAlert size={20} />
      <div>
        <p className="font-semibold">Unable to load data</p>
        <p>{message}</p>
      </div>
      <button
        className="button button-secondary"
        onClick={() => (retry ? void retry() : window.location.reload())}
      >
        Try again
      </button>
    </div>
  );
}
