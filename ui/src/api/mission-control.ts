import { apiFetch } from "./client";
import type {
  Task,
  MemoryRecord,
  AgentActivity,
  ScheduledEvent,
  ContentItem,
} from "@/types/mission-control";

export type {
  Task,
  MemoryRecord,
  AgentActivity,
  ScheduledEvent,
  ContentItem,
} from "@/types/mission-control";

// ── Tasks ──

export async function listTasks(status?: string): Promise<Task[]> {
  const qs = status ? `?status=${status}` : "";
  return apiFetch<Task[]>(`/v1/tasks${qs}`);
}

export async function getTask(taskId: string): Promise<Task> {
  return apiFetch<Task>(`/v1/tasks/${taskId}`);
}

export async function createTask(
  task: Omit<Task, "id" | "created_at" | "updated_at">,
): Promise<Task> {
  return apiFetch<Task>("/v1/tasks", {
    method: "POST",
    body: JSON.stringify(task),
  });
}

export async function updateTask(
  taskId: string,
  updates: Partial<Task>,
): Promise<Task> {
  return apiFetch<Task>(`/v1/tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export async function deleteTask(taskId: string): Promise<void> {
  return apiFetch<void>(`/v1/tasks/${taskId}`, { method: "DELETE" });
}

// ── Memory ──

export async function listMemories(): Promise<MemoryRecord[]> {
  return apiFetch<MemoryRecord[]>("/v1/memories");
}

export async function createMemory(
  memory: Pick<MemoryRecord, "title" | "content" | "category" | "actor"> & {
    tags?: string[];
    details?: Record<string, unknown>;
  },
): Promise<MemoryRecord> {
  return apiFetch<MemoryRecord>("/v1/memories", {
    method: "POST",
    body: JSON.stringify(memory),
  });
}

export async function deleteMemory(entryId: number): Promise<void> {
  return apiFetch<void>(`/v1/memories/${entryId}`, { method: "DELETE" });
}

// ── Agents Activity ──

export async function listAgentsActivity(): Promise<AgentActivity[]> {
  return apiFetch<AgentActivity[]>("/v1/agents/activity");
}

export async function getAgentActivity(
  agentId: string,
): Promise<AgentActivity> {
  return apiFetch<AgentActivity>(`/v1/agents/${agentId}/activity`);
}

// ── Events (Calendar) ──

export async function listEvents(): Promise<ScheduledEvent[]> {
  return apiFetch<ScheduledEvent[]>("/v1/events");
}

export async function createEvent(
  event: Omit<ScheduledEvent, "id" | "created_at">,
): Promise<ScheduledEvent> {
  return apiFetch<ScheduledEvent>("/v1/events", {
    method: "POST",
    body: JSON.stringify(event),
  });
}

export async function deleteEvent(eventId: string): Promise<void> {
  return apiFetch<void>(`/v1/events/${eventId}`, { method: "DELETE" });
}

// ── Content Pipeline ──

export async function listContent(): Promise<ContentItem[]> {
  return apiFetch<ContentItem[]>("/v1/content");
}

export async function createContent(
  item: Omit<ContentItem, "id" | "created_at" | "updated_at">,
): Promise<ContentItem> {
  return apiFetch<ContentItem>("/v1/content", {
    method: "POST",
    body: JSON.stringify(item),
  });
}

export async function updateContent(
  contentId: string,
  updates: Partial<ContentItem>,
): Promise<ContentItem> {
  return apiFetch<ContentItem>(`/v1/content/${contentId}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export async function deleteContent(contentId: string): Promise<void> {
  return apiFetch<void>(`/v1/content/${contentId}`, { method: "DELETE" });
}

// ── Agents CRUD ──

export async function createAgent(data: {
  name: string;
  model: string;
  role: string;
  team?: string;
  tools?: string[];
  autonomy?: string;
  sandbox?: string;
}): Promise<AgentActivity> {
  return apiFetch<AgentActivity>("/v1/agents", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateAgent(
  id: string,
  patch: Partial<{
    name: string;
    model: string;
    role: string;
    team: string;
    tools: string[];
    autonomy: string;
    sandbox: string;
    status: string;
  }>,
): Promise<AgentActivity> {
  return apiFetch<AgentActivity>(`/v1/agents/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteAgent(id: string): Promise<void> {
  await apiFetch(`/v1/agents/${id}`, { method: "DELETE" });
}

// ── Teams ──

export interface TeamDef {
  id: string;
  name: string;
  nameJa: string;
  icon: string;
  color: string;
  bg: string;
}

export async function listTeams(): Promise<TeamDef[]> {
  return apiFetch<TeamDef[]>("/v1/teams");
}

export async function createTeam(data: {
  id?: string;
  name: string;
  nameJa?: string;
  icon?: string;
  color?: string;
  bg?: string;
}): Promise<TeamDef> {
  return apiFetch<TeamDef>("/v1/teams", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateTeam(
  id: string,
  patch: Partial<TeamDef>,
): Promise<TeamDef> {
  return apiFetch<TeamDef>(`/v1/teams/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteTeam(id: string): Promise<void> {
  await apiFetch(`/v1/teams/${id}`, { method: "DELETE" });
}
