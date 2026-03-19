import { apiFetch, apiStream } from "./client";

export interface ExperimentMetric {
  name: string;
  direction: string;
  unit?: string;
  parser?: string;
  regex?: string;
  value?: number;
  evidence?: string;
}

export interface ExperimentPlanner {
  type: string;
  command?: string;
  prompt?: string;
  model?: string;
  approval_policy?: string;
  sandbox_mode?: string;
}

export interface ExperimentSandbox {
  tier: string;
  allow_internet: boolean;
  allowed_hosts: string[];
  blocked_ports: number[];
  timeout_seconds: number;
  max_cpu_ms: number;
  max_memory_bytes: number;
  max_network_bytes: number;
  provider?: string;
}

export interface ExperimentCleanup {
  runtime_ttl_seconds: number;
  preserve_failed_worktrees: boolean;
}

export interface ExperimentContextBundle {
  runtime_root: string;
  workspace_root: string;
  files: Record<string, string>;
  mutable_files: string[];
}

export interface ExperimentApproval {
  required: boolean;
  status: string;
  request_id?: string | null;
  action?: string | null;
  message?: string | null;
  created_at?: string | null;
  expires_at?: string | null;
  decided_at?: string | null;
  target_branch?: string | null;
  reason?: string | null;
}

export interface ExperimentCampaign {
  id: string;
  tenant_id: string;
  project_slug?: string;
  name: string;
  objective: string;
  status: string;
  repo_path: string;
  repo_root: string;
  base_ref: string;
  metric: ExperimentMetric;
  planner: ExperimentPlanner;
  sandbox: ExperimentSandbox;
  cleanup: ExperimentCleanup;
  context_bundle?: ExperimentContextBundle;
  approval: ExperimentApproval;
  benchmark_command: string;
  checks_command?: string;
  max_iterations: number;
  progress: {
    baseline_measured: boolean;
    completed_iterations: number;
    failed_iterations: number;
    max_iterations: number;
  };
  baseline?: {
    iteration_id: string;
    value: number;
    captured_at: string;
  } | null;
  best?: {
    iteration_id: string;
    value: number;
    ref: string;
    branch: string;
    delta?: number | null;
    improvement_ratio?: number | null;
    diff_stat?: string;
    changed_files?: string[];
    updated_at?: string;
  } | null;
  promotion: {
    branch: string;
    status: string;
    promoted_ref?: string | null;
    promoted_at?: string | null;
  };
  control: {
    pause_requested: boolean;
    cancel_requested: boolean;
  };
  current_iteration_id?: string | null;
  events: Array<{
    timestamp: string;
    level: string;
    kind: string;
    message: string;
  }>;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  last_error?: string | null;
}

export interface ExperimentIteration {
  id: string;
  campaign_id: string;
  tenant_id: string;
  sequence: number;
  kind: string;
  status: string;
  outcome?: string | null;
  base_ref: string;
  branch?: string;
  worktree_path?: string;
  started_at: string;
  updated_at: string;
  completed_at?: string;
  planner?: ExperimentStep | null;
  benchmark?: ExperimentStep | null;
  checks?: ExperimentStep | null;
  metric?: ExperimentMetric | null;
  decision?: {
    kept: boolean;
    reason: string;
    reference_value?: number | null;
    delta?: number | null;
    improvement_ratio?: number | null;
  } | null;
  commit_ref?: string | null;
  diff_stat?: string;
  changed_files?: string[];
}

export interface ExperimentStep {
  command: string;
  step?: string;
  exit_code: number;
  duration_ms: number;
  stdout: string;
  stderr: string;
  timed_out?: boolean;
  completed_at: string;
  planner_type?: string;
  session_id?: string;
  sandbox?: Record<string, unknown>;
  resource_usage?: {
    cpu_ms: number;
    memory_bytes: number;
    network_bytes_in: number;
    network_bytes_out: number;
  };
  policy_blocked?: boolean;
}

export interface ExperimentCampaignDetail {
  campaign: ExperimentCampaign;
  iterations: ExperimentIteration[];
  count: number;
}

interface ExperimentListResponse {
  campaigns: ExperimentCampaign[];
  count: number;
}

interface ExperimentIterationsResponse {
  iterations: ExperimentIteration[];
  count: number;
}

export interface CreateExperimentCampaignRequest {
  name?: string;
  objective: string;
  project_slug?: string;
  repo_path: string;
  benchmark_command: string;
  planner_command: string;
  checks_command?: string;
  metric_name: string;
  metric_direction: "minimize" | "maximize";
  metric_unit?: string;
  metric_parser?: "metric-line" | "regex";
  metric_regex?: string;
  max_iterations: number;
  base_ref?: string;
  benchmark_timeout_seconds?: number;
  planner_timeout_seconds?: number;
  checks_timeout_seconds?: number;
  promotion_branch?: string;
  sandbox?: Partial<ExperimentSandbox>;
  cleanup?: Partial<ExperimentCleanup>;
}

export const experimentsApi = {
  list: async (projectSlug?: string): Promise<ExperimentCampaign[]> => {
    const suffix = projectSlug ? `?project_slug=${encodeURIComponent(projectSlug)}` : "";
    const response = await apiFetch<ExperimentListResponse>(`/v1/experiments${suffix}`);
    return response.campaigns;
  },
  create: (payload: CreateExperimentCampaignRequest) =>
    apiFetch<ExperimentCampaignDetail>("/v1/experiments", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  get: (campaignId: string) =>
    apiFetch<ExperimentCampaignDetail>(`/v1/experiments/${campaignId}`),
  listIterations: async (campaignId: string): Promise<ExperimentIteration[]> => {
    const response = await apiFetch<ExperimentIterationsResponse>(
      `/v1/experiments/${campaignId}/iterations`,
    );
    return response.iterations;
  },
  start: (campaignId: string) =>
    apiFetch<ExperimentCampaignDetail>(`/v1/experiments/${campaignId}/start`, {
      method: "POST",
    }),
  pause: (campaignId: string) =>
    apiFetch<ExperimentCampaignDetail>(`/v1/experiments/${campaignId}/pause`, {
      method: "POST",
    }),
  resume: (campaignId: string) =>
    apiFetch<ExperimentCampaignDetail>(`/v1/experiments/${campaignId}/resume`, {
      method: "POST",
    }),
  cancel: (campaignId: string) =>
    apiFetch<ExperimentCampaignDetail>(`/v1/experiments/${campaignId}/cancel`, {
      method: "POST",
    }),
  promote: (campaignId: string, branchName?: string) =>
    apiFetch<ExperimentCampaignDetail>(`/v1/experiments/${campaignId}/promote`, {
      method: "POST",
      body: JSON.stringify(branchName ? { branch_name: branchName } : {}),
    }),
  stream: (
    campaignId: string,
    options: Parameters<typeof apiStream>[1],
  ) => apiStream(`/v1/experiments/${campaignId}/events`, options),
};
