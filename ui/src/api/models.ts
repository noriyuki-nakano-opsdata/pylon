import { apiFetch } from "./client";

export interface ModelInfo {
  id: string;
  name: string;
  version?: string;
  created?: string;
}

export interface ProviderInfo {
  models: ModelInfo[];
  status: "available" | "unavailable" | "error";
  default_model: string;
  policy: string;
  pin?: string;
}

export interface ModelsResponse {
  providers: Record<string, ProviderInfo>;
  fallback_chain: string[];
  policies: Record<string, { policy: string; pin?: string }>;
}

export interface HealthResponse {
  [provider: string]: {
    status: "ok" | "error";
    latency_ms: number;
    model: string;
    error?: string;
  };
}

export const modelsApi = {
  list: () => apiFetch<ModelsResponse>("/v1/models"),
  updatePolicy: (provider: string, policy: string, pin?: string) =>
    apiFetch<{ ok: boolean }>("/v1/models/policy", {
      method: "POST",
      body: JSON.stringify({ provider, policy, pin }),
    }),
  refresh: () =>
    apiFetch<ModelsResponse>("/v1/models/refresh", { method: "POST" }),
  health: () => apiFetch<HealthResponse>("/v1/models/health"),
};
