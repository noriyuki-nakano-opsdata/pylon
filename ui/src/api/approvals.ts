import { apiFetch } from "./client";

export interface Approval {
  id: string;
  agent_id: string;
  action: string;
  autonomy_level: string;
  status: "pending" | "approved" | "rejected" | "expired";
  created_at: string;
  expires_at: string;
  plan_hash: string;
  effect_hash: string | null;
  context: Record<string, unknown>;
}

interface ApprovalListResponse {
  approvals: Approval[];
  count: number;
}

export const approvalsApi = {
  list: async (): Promise<Approval[]> => {
    const res = await apiFetch<ApprovalListResponse>("/v1/approvals");
    return res.approvals;
  },
  approve: (id: string) =>
    apiFetch<void>(`/v1/approvals/${id}/approve`, { method: "POST" }),
  reject: (id: string, reason?: string) =>
    apiFetch<void>(`/v1/approvals/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
};
