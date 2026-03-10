import { type Approval } from "@/api/approvals";

// ─── Types ────────────────────────────────────────────

export interface EventLogEntry {
  seq: number;
  step: number;
  node_id: string;
  agent: string;
  attempt_id: number;
  loop_iteration: number;
  state_patch: Record<string, unknown>;
  output: Record<string, unknown>;
  metrics: Record<string, unknown>;
  timestamp: string;
  requires_approval: boolean;
  approval_reason: string;
  edge_resolutions: Array<{
    from_node: string;
    to_node: string;
    edge_index: number;
    condition?: string;
    taken: boolean;
  }>;
  verification: { disposition?: string } | null;
}

export interface ExecutionSummary {
  total_events: number;
  attempt_count: number;
  replan_count: number;
  last_node: string;
  node_sequence: string[];
  timeline: Array<{
    seq: number;
    node_id: string;
    attempt_id: number;
    loop_iteration: number;
    verification: string | null;
  }>;
  critical_path: Array<{
    node_id: string;
    attempt_id: number;
    loop_iteration: number;
  }>;
  decision_points: Array<{
    type: string;
    source_node?: string;
    edges?: unknown[];
    [key: string]: unknown;
  }>;
  goal_satisfied: boolean;
  pending_approval: boolean;
}

export interface RunDetail {
  id: string;
  workflow_id: string;
  status: string;
  spec?: string;
  started_at: string;
  completed_at?: string | null;
  state?: {
    plan?: string;
    code?: string;
    estimated_cost_usd?: number;
    plan_tokens_in?: number;
    plan_tokens_out?: number;
    implement_tokens_in?: number;
    implement_tokens_out?: number;
    execution?: {
      node_status: Record<string, string>;
      edge_status: Record<string, string>;
      started_at: string;
      elapsed_seconds?: number;
    };
    [key: string]: unknown;
  };
  event_log?: EventLogEntry[];
  execution_summary?: ExecutionSummary;
}

export type MessageRole = "user" | "system" | "agent" | "artifact" | "approval" | "flow";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: number;
  meta?: {
    runId?: string;
    node?: string;
    status?: string;
    code?: string;
    approval?: Approval;
    cost?: number;
    tokens?: { in: number; out: number };
    eventLog?: EventLogEntry[];
    executionSummary?: ExecutionSummary;
    startedAt?: string;
    completedAt?: string;
  };
}

// ─── Constants ────────────────────────────────────────

export const PLACEHOLDERS = [
  "Build a weather dashboard with live API integration...",
  "Analyze competitor SaaS pricing and create a comparison report...",
  "Create a landing page for a AI productivity tool...",
  "Design a REST API for a task management system...",
  "Write a business plan for a mobile fitness app...",
  "Build an interactive data visualization of climate change data...",
];

export const EXAMPLES = [
  { icon: "Lightbulb" as const, text: "Build a kanban board app with drag & drop", category: "Build" },
  { icon: "Search" as const, text: "Analyze the top 5 project management tools and compare features", category: "Research" },
  { icon: "FileText" as const, text: "Create a landing page for a SaaS analytics product", category: "Design" },
  { icon: "BarChart3" as const, text: "Build a real-time stock ticker dashboard", category: "Data" },
];

// ─── Helpers ──────────────────────────────────────────

let msgCounter = 0;
export function createMessage(
  role: MessageRole,
  content: string,
  meta?: ChatMessage["meta"],
): ChatMessage {
  return {
    id: `msg_${++msgCounter}_${Date.now()}`,
    role,
    content,
    timestamp: Date.now(),
    meta,
  };
}
