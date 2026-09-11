import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { InteractionProvider } from "./InteractionProvider";
import { Json, Pagination, useAction, usePage } from "./Management";
import { QueuesPage } from "../pages/OperationsPage";
import { MemoryRouter } from "react-router-dom";
function mount(children: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <InteractionProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </InteractionProvider>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
});
test("confirmation cancel and Escape block the mutation; confirm invokes it once", async () => {
  const task = vi.fn().mockResolvedValue(undefined);
  function Action() {
    const action = useAction();
    return (
      <button
        onClick={async () => {
          if (
            await action.confirm({
              title: "Revoke key?",
              description: "Requests will stop authenticating.",
              label: "Revoke key",
            })
          )
            await action.run(task, "Key revoked");
        }}
      >
        Open action
      </button>
    );
  }
  mount(<Action />);
  await userEvent.click(screen.getByText("Open action"));
  expect(screen.getByRole("dialog")).toHaveAccessibleDescription(
    "Requests will stop authenticating.",
  );
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(task).not.toHaveBeenCalled();
  await userEvent.click(screen.getByText("Open action"));
  fireEvent(screen.getByRole("dialog"), new Event("cancel"));
  expect(task).not.toHaveBeenCalled();
  await userEvent.click(screen.getByText("Open action"));
  await userEvent.click(screen.getByRole("button", { name: /^Revoke key$/ }));
  await waitFor(() => expect(task).toHaveBeenCalledTimes(1));
  expect(await screen.findByRole("status")).toHaveTextContent("Key revoked");
});
test("changing a filtered list resets its cursor instead of reusing the previous page", async () => {
  const paths: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    paths.push(String(input));
    return new Response(JSON.stringify({ items: [], next_cursor: "page-two" }));
  });
  function List() {
    const [path, setPath] = useState("/admin/jobs?status=QUEUED");
    const q = usePage(path);
    return (
      <>
        <button onClick={() => setPath("/admin/jobs?status=COMPLETED")}>
          Change filter
        </button>
        {q.pager}
      </>
    );
  }
  mount(<List />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled(),
  );
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() =>
    expect(paths.some((p) => p.includes("cursor=page-two"))).toBe(true),
  );
  await userEvent.click(screen.getByText("Change filter"));
  await waitFor(() =>
    expect(paths.at(-1)).toBe("/admin/jobs?status=COMPLETED&limit=25"),
  );
  expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
});
test("large JSON remains bounded and exposes subsequent lines", async () => {
  mount(<Json value={Array.from({ length: 500 }, (_, i) => `row-${i}`)} />);
  const pre = document.querySelector("pre")!;
  expect(pre.textContent?.split("\n")).toHaveLength(100);
  expect(pre).not.toHaveTextContent("row-499");
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(pre).toHaveTextContent("row-100");
});
test("queue-control failure retains durable counts and does not claim queues are running", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
    String(input).includes("queue-controls")
      ? new Response(
          JSON.stringify({ error: { message: "Control service unavailable" } }),
          { status: 503 },
        )
      : new Response(
          JSON.stringify({
            redis_available: false,
            items: [
              {
                queue: "reports",
                durable_jobs: 17,
                redis_ready_jobs: null,
                redis_inflight_jobs: null,
                status_counts: { QUEUED: 17 },
              },
            ],
          }),
        ),
  );
  mount(<QueuesPage />);
  expect(
    await screen.findByText("Control service unavailable"),
  ).toBeInTheDocument();
  expect(screen.getByText("17", { selector: "td" })).toBeInTheDocument();
  expect(screen.queryByText("Accepting claims")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Pause queue" })).toBeDisabled();
});

test("catalog pagination never submits its surrounding form", async () => {
  const submitted = vi.fn((event) => event.preventDefault());
  const next = vi.fn();
  mount(
    <form onSubmit={submitted}>
      <Pagination
        page={1}
        hasPrevious={false}
        hasNext
        previous={() => {}}
        next={next}
      />
    </form>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(next).toHaveBeenCalledOnce();
  expect(submitted).not.toHaveBeenCalled();
});
