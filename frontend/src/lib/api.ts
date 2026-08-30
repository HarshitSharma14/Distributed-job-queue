export type UserRole = "ADMIN" | "PUBLISHER" | "PRODUCER" | "WORKER";

export interface CurrentUser {
  user_id: string;
  email: string;
  display_name: string;
  roles: UserRole[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
  }
}

function cookie(name: string): string | undefined {
  return document.cookie
    .split("; ")
    .find((entry) => entry.startsWith(`${name}=`))
    ?.split("=")
    .slice(1)
    .join("=");
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = cookie("djq_csrf");
    if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  }
  const response = await fetch(path, {
    ...options,
    method,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      body?.error?.message ?? `Request failed with status ${response.status}`,
      response.status,
      body?.error?.code ?? "REQUEST_FAILED",
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
