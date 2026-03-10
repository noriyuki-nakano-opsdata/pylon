import { apiFetch } from "./client";

export interface HealthCheck {
  name: string;
  status: string;
  message: string;
}

export interface HealthResponse {
  status: string;
  checks: HealthCheck[];
  timestamp: number;
}

export const healthApi = {
  get: () => apiFetch<HealthResponse>("/health"),
};
