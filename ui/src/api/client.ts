export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE = "/api";

let _currentTenantId = "default";

export function setTenantId(id: string) {
  _currentTenantId = id;
}

export function getTenantId(): string {
  return _currentTenantId;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${BASE}${path}`;
  const headers: Record<string, string> = {
    "X-Tenant-ID": _currentTenantId,
    ...((options.headers as Record<string, string>) ?? {}),
  };

  if (options.body && typeof options.body === "string") {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(url, {
    ...options,
    headers,
    credentials: "include",
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(
      body?.error ?? body?.message ?? `Request failed: ${res.status}`,
      res.status,
      body,
    );
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}
