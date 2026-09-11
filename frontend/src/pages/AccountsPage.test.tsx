import { InteractionProvider } from "../components/InteractionProvider";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { vi, test, expect } from "vitest";
import { PasswordPage } from "./AccountsPage";
import { AuthProvider } from "../auth/AuthProvider";

test("temporary password can be replaced through the labeled form before entering the workspace", async () => {
  let changed = false;
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input) === "/auth/password") {
        expect(JSON.parse(String(options?.body))).toEqual({
          current_password: "temporary-password",
          new_password: "replacement-password",
        });
        changed = true;
        return new Response(null, { status: 204 });
      }
      return new Response(
        JSON.stringify({
          user_id: "u",
          email: "user@example.com",
          display_name: "User",
          roles: ["PRODUCER"],
          password_change_required: !changed,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  try {
    render(
      <QueryClientProvider client={client}>
        <InteractionProvider>
          <AuthProvider>
            <MemoryRouter initialEntries={["/password"]}>
              <Routes>
                <Route path="password" element={<PasswordPage />} />
                <Route path="/" element={<p>Workspace unlocked</p>} />
              </Routes>
            </MemoryRouter>
          </AuthProvider>
        </InteractionProvider>
      </QueryClientProvider>,
    );
    await userEvent.type(
      screen.getByLabelText("Current password"),
      "temporary-password",
    );
    await userEvent.type(
      screen.getByLabelText("New password"),
      "replacement-password",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Change password" }),
    );
    await waitFor(() =>
      expect(screen.getByText("Workspace unlocked")).toBeInTheDocument(),
    );
    expect(changed).toBe(true);
  } finally {
    client.clear();
    vi.unstubAllGlobals();
  }
});
