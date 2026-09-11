import {
  useId,
  cloneElement,
  type ReactElement,
  useRef,
  useState,
  type ReactNode,
  type ButtonHTMLAttributes,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { api } from "../lib/api";
import { CopyButton } from "./DashboardPrimitives";
import { PageError, TableSkeleton } from "./Feedback";
import { useInteraction } from "./InteractionProvider";

export const inputClass = "input";
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactElement<{ id?: string }>;
}) {
  const generatedId = useId();
  const id = children.props.id ?? generatedId;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {cloneElement(children, { id })}
    </div>
  );
}
export function Button({
  children,
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
}) {
  return (
    <button {...props} className={`button button-${variant} ${className}`}>
      {children}
    </button>
  );
}
export function Card({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="section">
      <h2>{title}</h2>
      <div className="section-body">{children}</div>
    </section>
  );
}
// Bound the rendered code to 100 lines even for very large payloads/errors.
export function Json({
  value,
  label = "JSON",
  collapsed = false,
}: {
  value: unknown;
  label?: string;
  collapsed?: boolean;
}) {
  const text = JSON.stringify(value, null, 2) ?? "null";
  const lines = text.split("\n");
  const [page, setPage] = useState(0);
  const pages = Math.ceil(lines.length / 100);
  const current = Math.min(page, pages - 1);
  return (
    <details className="code-block" open={!collapsed}>
      <summary>
        <span>{label}</span>
        <span className="text-muted">
          {lines.length} {lines.length === 1 ? "line" : "lines"}
        </span>
      </summary>
      <div className="code-toolbar">
        <span>JSON</span>
        <CopyButton value={text} label={`Copy ${label}`} />
      </div>
      <pre tabIndex={0}>
        {lines.slice(current * 100, (current + 1) * 100).join("\n")}
      </pre>
      {pages > 1 && (
        <Pagination
          page={current + 1}
          previous={() => setPage(current - 1)}
          next={() => setPage(current + 1)}
          hasPrevious={current > 0}
          hasNext={current + 1 < pages}
        />
      )}
    </details>
  );
}
export function useAction() {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);
  const { notify, confirm } = useInteraction();
  async function run(task: () => Promise<unknown>, success = "Saved") {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    try {
      await task();
      await client.invalidateQueries();
      notify(success);
    } catch (e) {
      notify(
        e instanceof Error ? e.message : "Request failed. Try again.",
        true,
      );
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  return { busy, run, confirm };
}
export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}
export function Pagination({
  page,
  previous,
  next,
  hasPrevious,
  hasNext,
  busy,
}: {
  page: number;
  previous: () => void;
  next: () => void;
  hasPrevious: boolean;
  hasNext: boolean;
  busy?: boolean;
}) {
  return (
    <nav className="pagination" aria-label="Pagination">
      <span>Page {page}</span>
      <div>
        <Button
          variant="secondary"
          disabled={!hasPrevious || busy}
          onClick={previous}
        >
          <ChevronLeft size={14} />
          Previous
        </Button>
        <Button variant="secondary" disabled={!hasNext || busy} onClick={next}>
          Next
          <ChevronRight size={14} />
        </Button>
      </div>
    </nav>
  );
}
export function usePage<T>(path: string) {
  const [state, setState] = useState<{ path: string; cursors: string[] }>({
    path,
    cursors: [],
  });
  const cursors = state.path === path ? state.cursors : [];
  const cursor = cursors.at(-1);
  const query = useQuery({
    queryKey: [path, cursor],
    queryFn: () =>
      api<Page<T>>(
        `${path}${path.includes("?") ? "&" : "?"}limit=25${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      ),
    refetchInterval: 15_000,
  });
  return {
    ...query,
    pager: (
      <Pagination
        page={cursors.length + 1}
        hasPrevious={!!cursors.length}
        hasNext={!!query.data?.next_cursor}
        busy={query.isFetching}
        previous={() => setState({ path, cursors: cursors.slice(0, -1) })}
        next={() =>
          setState({ path, cursors: [...cursors, query.data!.next_cursor!] })
        }
      />
    ),
  };
}
export function QueryState({
  query,
}: {
  query: { isPending: boolean; error: Error | null; refetch?: () => unknown };
}) {
  return query.isPending ? (
    <TableSkeleton />
  ) : query.error ? (
    <PageError message={query.error.message} retry={query.refetch} />
  ) : null;
}
export async function write<T>(
  path: string,
  body?: unknown,
  method = "POST",
  headers?: HeadersInit,
) {
  return api<T>(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function useLocalPage<T>(items: T[]) {
  const [page, setPage] = useState(0);
  const current = Math.min(page, Math.max(0, Math.ceil(items.length / 25) - 1));
  return {
    items: items.slice(current * 25, (current + 1) * 25),
    pager:
      items.length > 25 ? (
        <Pagination
          page={current + 1}
          hasPrevious={current > 0}
          hasNext={(current + 1) * 25 < items.length}
          previous={() => setPage(current - 1)}
          next={() => setPage(current + 1)}
        />
      ) : null,
  };
}
