import { apiFetch } from "./client";

export interface Workflow {
  id: string;
  project_name: string;
  tenant_id: string;
  agent_count: number;
  node_count: number;
  goal_enabled: boolean;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  runtime_metrics?: {
    estimated_cost_usd: number;
  };
  execution_mode: string;
  project: string;
  /** Event log entries emitted by workflow nodes */
  event_log?: Array<{
    seq: number;
    node_id: string;
    agent: string;
    output?: unknown;
  }>;
  /** Per-node execution status map */
  node_status?: Record<string, string>;
  /** Workflow state bag (plan, code, output, etc.) */
  state?: Record<string, unknown>;
  /** Post-run execution summary */
  execution_summary?: unknown;
}

interface WorkflowListResponse {
  workflows: Workflow[];
  count: number;
}

interface WorkflowRunListResponse {
  runs: WorkflowRun[];
  count?: number;
}

export const workflowsApi = {
  list: async (): Promise<Workflow[]> => {
    const res = await apiFetch<WorkflowListResponse>("/v1/workflows");
    return res.workflows;
  },
  get: (id: string) => apiFetch<Workflow>(`/v1/workflows/${id}`),
  create: (data: Partial<Workflow>) =>
    apiFetch<Workflow>("/v1/workflows", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  listRuns: async (workflowId: string): Promise<WorkflowRun[]> => {
    const res = await apiFetch<WorkflowRunListResponse>(
      `/v1/workflows/${workflowId}/runs`,
    );
    return res.runs;
  },
  startRun: (workflowId: string, input?: Record<string, unknown>) =>
    apiFetch<WorkflowRun>(`/v1/workflows/${workflowId}/runs`, {
      method: "POST",
      body: JSON.stringify({ input: input ?? {} }),
    }),
};
