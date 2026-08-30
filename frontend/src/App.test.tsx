import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { App } from "./App";
import { AuthProvider } from "./auth/AuthProvider";

function renderApp(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("dashboard routing", () => {
  it("sends anonymous users to the login page", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "AUTHENTICATION_REQUIRED", message: "Authentication required" } }),
        { status: 401, headers: { "Content-Type": "application/json" } },
      ),
    );

    renderApp("/admin");

    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
  });
});
