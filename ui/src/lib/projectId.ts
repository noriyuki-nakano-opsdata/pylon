function fallbackProjectId(): string {
  return `prj-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function generateProjectId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return fallbackProjectId();
}
