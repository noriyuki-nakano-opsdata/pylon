import { apiFetch } from "./client";

export interface FeatureManifest {
  contract_version: string;
  canonical_prefix: string;
  legacy_aliases_enabled: boolean;
  tenant_id?: string;
  surfaces: {
    admin: Record<string, boolean>;
    project: Record<string, boolean>;
  };
}

export const fallbackFeatureManifest: FeatureManifest = {
  contract_version: "fallback",
  canonical_prefix: "/api/v1",
  legacy_aliases_enabled: true,
  surfaces: {
    admin: {
      dashboard: true,
      workflows: true,
      agents: true,
      costs: true,
      providers: true,
      models: true,
      skills: true,
      settings: true,
    },
    project: {
      runs: true,
      approvals: true,
      experiments: true,
      studio: false,
      lifecycle: true,
      gtm: true,
      tasks: true,
      team: true,
      memory: true,
      calendar: true,
      content: true,
      ads: true,
      issues: false,
      pulls: false,
    },
  },
};

export const featuresApi = {
  get: () => apiFetch<FeatureManifest>("/v1/features"),
};
