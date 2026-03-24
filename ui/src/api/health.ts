import { apiFetch } from "./client";

export interface HealthCheck {
  name: string;
  status: string;
  message: string;
  backend?: string;
  readiness_tier?: string;
  production_capable?: boolean;
  workflow_count?: number;
  [key: string]: unknown;
}

export interface HealthResponse {
  status: string;
  checks: HealthCheck[];
  timestamp: number;
}

export interface ReadinessResponse extends HealthResponse {
  ready: boolean;
}

export const healthApi = {
  get: () => apiFetch<HealthResponse>("/health"),
  getReadiness: () =>
    apiFetch<ReadinessResponse>("/ready", {}, { allowStatuses: [503] }),
};
