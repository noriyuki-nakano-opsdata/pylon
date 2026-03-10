/* ── Mission Control Types ── */

// ── Tasks ──

export interface TaskPayload {
  phase?: string;
  run_id?: string;
  node_id?: string;
  [key: string]: unknown;
}

export interface Task {
  id: string;
  title: string;
  name?: string;
  description: string;
  status: "backlog" | "in_progress" | "review" | "done";
  priority: "low" | "medium" | "high" | "critical";
  assignee: string;
  assigneeType: "human" | "ai";
  payload?: TaskPayload;
  created_at: string;
  updated_at?: string;
}

// ── Memory ──

export interface MemoryRecord {
  id: number;
  entry_id: number;
  tenant_id: string;
  event_type: string;
  actor: string;
  category: string;
  title: string;
  content: string;
  details: Record<string, unknown>;
  timestamp: string;
}

// ── Agents Activity ──

export interface AgentActivity {
  id: string;
  name: string;
  model: string;
  role: string;
  autonomy: string;
  tools: string[];
  sandbox: string;
  status: string;
  team?: string;
  tenant_id: string;
  current_task: Task | null;
  uptime_seconds: number;
}

// ── Events (Calendar) ──

export interface ScheduledEvent {
  id: string;
  title: string;
  description: string;
  start: string;
  end: string;
  type: string;
  agentId: string;
  created_at: string;
}

// ── Content Pipeline ──

export interface ContentItem {
  id: string;
  title: string;
  description: string;
  type: string;
  stage: string;
  assignee: string;
  assigneeType: "human" | "ai";
  created_at: string;
  updated_at: string;
}
