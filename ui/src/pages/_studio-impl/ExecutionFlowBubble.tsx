import { useState } from "react";
import { formatDuration, formatTimestamp } from "@/lib/time";
import {
  CheckCircle2,
  Bot,
  ArrowRight,
  Clock,
  Zap,
  ChevronDown,
  ChevronRight,
  GitBranch,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { type EventLogEntry, type ExecutionSummary } from "./types";

// ─── Agent Colors ─────────────────────────────────────

const AGENT_COLORS: Record<string, string> = {
  planner: "text-blue-400 bg-blue-400/10 border-blue-400/20",
  coder: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
  reviewer: "text-amber-400 bg-amber-400/10 border-amber-400/20",
  tester: "text-purple-400 bg-purple-400/10 border-purple-400/20",
};

function getAgentColor(agent: string): string {
  return AGENT_COLORS[agent] ?? "text-cyan-400 bg-cyan-400/10 border-cyan-400/20";
}

// ─── Execution Flow Bubble ────────────────────────────

export function ExecutionFlowBubble({
  eventLog,
  executionSummary,
  startedAt,
  completedAt,
}: {
  eventLog: EventLogEntry[];
  executionSummary?: ExecutionSummary;
  startedAt?: string;
  completedAt?: string;
}) {
  const [expanded, setExpanded] = useState(true);

  const elapsedMs = startedAt && completedAt
    ? new Date(completedAt).getTime() - new Date(startedAt).getTime()
    : 0;

  return (
    <div className="flex items-start gap-3">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-violet-500/10">
        <GitBranch className="h-3.5 w-3.5 text-violet-400" />
      </div>
      <div className="max-w-[90%] space-y-2">
        {/* Header */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex w-full items-center gap-2 rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-2.5 text-left transition-colors hover:bg-accent/30"
        >
          {expanded ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
          <span className="text-sm font-medium">Agent Execution Flow</span>
          <Badge variant="secondary" className="text-[10px]">
            {eventLog.length} steps
          </Badge>
          {elapsedMs > 0 && (
            <span className="ml-auto flex items-center gap-1 text-[10px] text-muted-foreground">
              <Clock className="h-3 w-3" />
              {formatDuration(elapsedMs)}
            </span>
          )}
        </button>

        {/* Expanded flow */}
        {expanded && (
          <div className="ml-1 space-y-0">
            {/* Flow diagram */}
            <div className="rounded-xl border border-border bg-card/50 p-3">
              {/* Node flow bar */}
              {executionSummary && (
                <div className="mb-3 flex items-center gap-1.5">
                  {executionSummary.node_sequence.map((nodeId, i) => (
                    <div key={`${nodeId}-${i}`} className="flex items-center gap-1.5">
                      {i > 0 && <ArrowRight className="h-3 w-3 text-muted-foreground/40" />}
                      <div className="flex items-center gap-1 rounded-md bg-muted/50 px-2 py-0.5">
                        <Zap className="h-2.5 w-2.5 text-primary" />
                        <span className="text-[10px] font-medium">{nodeId}</span>
                      </div>
                    </div>
                  ))}
                  <ArrowRight className="h-3 w-3 text-muted-foreground/40" />
                  <div className="flex items-center gap-1 rounded-md bg-green-500/10 px-2 py-0.5">
                    <CheckCircle2 className="h-2.5 w-2.5 text-green-500" />
                    <span className="text-[10px] font-medium text-green-500">END</span>
                  </div>
                </div>
              )}

              {/* Event timeline */}
              {eventLog.map((event, i) => {
                const agentColor = getAgentColor(event.agent);
                const patchKeys = Object.keys(event.state_patch).filter(
                  (k) => !k.endsWith("_done") && k !== "runtime_metrics" && k !== "execution",
                );
                const isLast = i === eventLog.length - 1;

                return (
                  <div key={event.seq} className="relative flex gap-3">
                    {/* Timeline line */}
                    <div className="flex flex-col items-center">
                      <div className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded-full border", agentColor)}>
                        <Bot className="h-3 w-3" />
                      </div>
                      {!isLast && <div className="w-px flex-1 bg-border" />}
                    </div>

                    {/* Event content */}
                    <div className={cn("flex-1 pb-4", isLast && "pb-1")}>
                      <div className="flex items-center gap-2">
                        <span className={cn("text-xs font-semibold", agentColor.split(" ")[0])}>
                          {event.agent}
                        </span>
                        <span className="text-[10px] text-muted-foreground">
                          → {event.node_id}
                        </span>
                        <Badge variant="outline" className="h-4 border-green-500/30 px-1 text-[9px] text-green-500">
                          step {event.step}
                        </Badge>
                        {event.timestamp && (
                          <span className="ml-auto text-[9px] text-muted-foreground/50">
                            {formatTimestamp(event.timestamp)}
                          </span>
                        )}
                      </div>

                      {/* State changes */}
                      {patchKeys.length > 0 && (
                        <div className="mt-1.5 space-y-1">
                          {patchKeys.map((key) => {
                            const val = event.state_patch[key];
                            const isTokenKey = key.includes("tokens");
                            const preview = typeof val === "string"
                              ? val.slice(0, 120) + (val.length > 120 ? "..." : "")
                              : isTokenKey
                                ? String(val)
                                : JSON.stringify(val)?.slice(0, 80);

                            return (
                              <div key={key} className="flex items-start gap-1.5 text-[11px]">
                                <span className="mt-px shrink-0 rounded bg-muted px-1 py-0.5 font-mono text-[10px] text-muted-foreground">
                                  {key}
                                </span>
                                <span className="text-foreground/70 break-all line-clamp-2">
                                  {preview}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {/* Edge resolutions */}
                      {event.edge_resolutions?.length > 0 && (
                        <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground/60">
                          <ArrowRight className="h-2.5 w-2.5" />
                          {event.edge_resolutions
                            .filter((e) => e.taken)
                            .map((e) => e.to_node === "END" ? "END" : e.to_node)
                            .join(", ")}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Decision points */}
            {executionSummary && executionSummary.decision_points.length > 0 && (
              <div className="mt-2 rounded-lg border border-border bg-card/30 px-3 py-2">
                <p className="mb-1 text-[10px] font-medium text-muted-foreground">Decision Points</p>
                <div className="space-y-0.5">
                  {executionSummary.decision_points.map((dp, i) => (
                    <div key={i} className="flex items-center gap-1.5 text-[10px] text-muted-foreground/70">
                      <span className="rounded bg-muted/50 px-1 py-0.5 text-[9px] font-medium">
                        {dp.type.replace(/_/g, " ")}
                      </span>
                      {dp.source_node && <span>at {dp.source_node}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
