import { api } from "./api";

describe("api", () => {
  it("sends browser credentials and the CSRF token for mutations", async () => {
    document.cookie = "djq_csrf=csrf-value; path=/";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await api("/jobs", { method: "POST", body: JSON.stringify({}) });

    const [, options] = fetchMock.mock.calls[0];
    expect(options?.credentials).toBe("include");
    expect(new Headers(options?.headers).get("X-CSRF-Token")).toBe("csrf-value");
  });

  it("preserves the stable backend error contract", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "AUTHENTICATION_REQUIRED", message: "Authentication required" } }),
        { status: 401, headers: { "Content-Type": "application/json" } },
      ),
    );

    await expect(api("/auth/me")).rejects.toEqual(
      expect.objectContaining({
        status: 401,
        code: "AUTHENTICATION_REQUIRED",
        message: "Authentication required",
      }),
    );
  });
});
