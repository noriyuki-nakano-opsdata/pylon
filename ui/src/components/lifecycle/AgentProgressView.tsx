import { Loader2, Check, XCircle, Bot, ArrowRight, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatElapsed } from "@/lib/time";
import type { AgentProgress } from "@/hooks/useWorkflowRun";

interface AgentProgressViewProps {
  agents: { id: string; label: string }[];
  progress: AgentProgress[];
  elapsedMs: number;
  title: string;
  subtitle?: string;
  onCancel?: () => void;
}

export function AgentProgressView({
  agents,
  progress,
  elapsedMs,
  title,
  subtitle,
  onCancel,
}: AgentProgressViewProps) {
  const getStatus = (agentId: string) => {
    const p = progress.find((a) => a.nodeId === agentId || a.agent === agentId);
    return p?.status ?? "pending";
  };

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-lg space-y-6 text-center">
        <Loader2 className="h-12 w-12 text-primary mx-auto animate-spin" />
        <h2 className="text-lg font-bold text-foreground">{title}</h2>
        {subtitle && (
          <p className="text-sm text-muted-foreground">{subtitle}</p>
        )}

        {/* Agent flow */}
        <div className="flex flex-wrap items-center justify-center gap-2">
          {agents.map((agent, i) => {
            const status = getStatus(agent.id);
            return (
              <div key={agent.id} className="flex items-center gap-2">
                <div
                  className={cn(
                    "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all",
                    status === "completed"
                      ? "bg-success/10 text-success"
                      : status === "running"
                        ? "bg-primary/10 text-primary"
                        : status === "failed"
                          ? "bg-destructive/10 text-destructive"
                          : "bg-muted text-muted-foreground",
                  )}
                >
                  {status === "completed" ? (
                    <Check className="h-3 w-3" />
                  ) : status === "running" ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : status === "failed" ? (
                    <XCircle className="h-3 w-3" />
                  ) : (
                    <Bot className="h-3 w-3" />
                  )}
                  {agent.label}
                </div>
                {i < agents.length - 1 && (
                  <ArrowRight className="h-3 w-3 text-muted-foreground/40" />
                )}
              </div>
            );
          })}
        </div>

        {/* Elapsed time */}
        <p className="text-xs text-muted-foreground font-mono">
          経過時間: {formatElapsed(elapsedMs)}
        </p>

        {onCancel && (
          <button
            onClick={onCancel}
            className="inline-flex items-center gap-2 rounded-md bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 transition-colors"
          >
            <Square className="h-4 w-4" />
            中断
          </button>
        )}
      </div>
    </div>
  );
}
