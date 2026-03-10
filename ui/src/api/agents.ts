import { apiFetch } from "./client";
import type { SkillInfo } from "./skills";

export interface Agent {
  id: string;
  name: string;
  model: string;
  role: string;
  autonomy: string;
  status: string;
  tools: string[];
  skills?: string[];
  sandbox: string;
  tenant_id: string;
  team?: string;
}

export interface AgentSkillsResponse {
  agent_id: string;
  agent_name: string;
  skills: SkillInfo[];
}

interface AgentListResponse {
  agents: Agent[];
  count: number;
}

export const agentsApi = {
  list: async (): Promise<Agent[]> => {
    const res = await apiFetch<AgentListResponse>("/v1/agents");
    return res.agents;
  },
  get: (id: string) => apiFetch<Agent>(`/v1/agents/${id}`),
  create: (data: Partial<Agent>) =>
    apiFetch<Agent>("/v1/agents", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  update: (id: string, data: Partial<Agent>) =>
    apiFetch<Agent>(`/v1/agents/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  delete: (id: string) =>
    apiFetch<void>(`/v1/agents/${id}`, { method: "DELETE" }),
  getSkills: (id: string) =>
    apiFetch<AgentSkillsResponse>(`/v1/agents/${id}/skills`),
  updateSkills: (id: string, skills: string[]) =>
    apiFetch<Agent>(`/v1/agents/${id}/skills`, {
      method: "PATCH",
      body: JSON.stringify({ skills }),
    }),
};
