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

interface ApiStreamOptions {
  headers?: Record<string, string>;
  signal?: AbortSignal;
  onEvent: (event: { event: string; data: string; id?: string }) => void;
}

function parseSseChunk(
  chunk: string,
  onEvent: ApiStreamOptions["onEvent"],
): void {
  let eventName = "message";
  let eventId: string | undefined;
  const dataLines: string[] = [];

  const emit = () => {
    if (dataLines.length === 0) return;
    onEvent({
      event: eventName,
      data: dataLines.join("\n"),
      id: eventId,
    });
    eventName = "message";
    eventId = undefined;
    dataLines.length = 0;
  };

  for (const rawLine of chunk.split(/\r?\n/)) {
    if (rawLine === "") {
      emit();
      continue;
    }
    if (rawLine.startsWith(":")) {
      continue;
    }
    const separator = rawLine.indexOf(":");
    const field = separator >= 0 ? rawLine.slice(0, separator) : rawLine;
    const rawValue = separator >= 0 ? rawLine.slice(separator + 1) : "";
    const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue;
    if (field === "event") {
      eventName = value || "message";
      continue;
    }
    if (field === "id") {
      eventId = value;
      continue;
    }
    if (field === "data") {
      dataLines.push(value);
    }
  }
}

export async function apiStream(
  path: string,
  options: ApiStreamOptions,
): Promise<void> {
  const url = `${BASE}${path}`;
  const response = await fetch(url, {
    method: "GET",
    headers: {
      Accept: "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Tenant-ID": _currentTenantId,
      ...(options.headers ?? {}),
    },
    credentials: "include",
    signal: options.signal,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      body?.error ?? body?.message ?? `Request failed: ${response.status}`,
      response.status,
      body,
    );
  }
  if (!response.body) {
    throw new Error("Streaming response body is unavailable");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let match = buffer.match(/\r?\n\r?\n/);
    let boundary = match ? match.index ?? -1 : -1;
    while (boundary !== -1) {
      const chunk = buffer.slice(0, boundary);
      const separatorLength = match?.[0].length ?? 2;
      buffer = buffer.slice(boundary + separatorLength);
      parseSseChunk(chunk, options.onEvent);
      match = buffer.match(/\r?\n\r?\n/);
      boundary = match ? match.index ?? -1 : -1;
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) {
    parseSseChunk(buffer, options.onEvent);
  }
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
