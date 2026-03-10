import { useState, useCallback, useRef, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { formatDuration } from "@/lib/time";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Send,
  Loader2,
  Sparkles,
  Copy,
  Check,
  ExternalLink,
  Eye,
  Code2,
  Info,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { queryKeys } from "@/lib/queryKeys";
import { workflowsApi, type Workflow } from "@/api/workflows";
import { apiFetch } from "@/api/client";
import { cn } from "@/lib/utils";
import {
  type ChatMessage,
  type MessageRole,
  type RunDetail,
  PLACEHOLDERS,
  createMessage,
} from "./types";
import { MessageBubble, AgentAvatar, ElapsedTimer, ApprovalBubble } from "./MessageBubble";
import { WelcomeScreen } from "./WelcomeScreen";

// ─── Helpers ──────────────────────────────────────────

function resolveWorkflow(
  input: string,
  workflows: Workflow[],
): { workflow: Workflow; reasoning: string } | null {
  if (workflows.length === 0) return null;
  const wf = workflows[0];
  const hasCodeKeywords = /build|create|make|write|develop|implement|design|generate/i.test(input);
  const hasResearchKeywords = /analyze|research|investigate|compare|report|study/i.test(input);

  let reasoning: string;
  if (hasCodeKeywords) {
    reasoning = `Selected **${wf.project_name}** workflow (${wf.agent_count} agents) for code generation task.`;
  } else if (hasResearchKeywords) {
    reasoning = `Selected **${wf.project_name}** workflow (${wf.agent_count} agents) for analysis task.`;
  } else {
    reasoning = `Selected **${wf.project_name}** workflow (${wf.agent_count} agents).`;
  }
  return { workflow: wf, reasoning };
}

// ─── Component ────────────────────────────────────────

export function Studio() {
  const { projectSlug } = useParams<{ projectSlug: string }>();
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [showCode, setShowCode] = useState(false);
  const [copiedCode, setCopiedCode] = useState(false);
  const [runStartTime, setRunStartTime] = useState<number | null>(null);
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const prevRunStatus = useRef<string | null>(null);

  // Rotate placeholder
  useEffect(() => {
    const interval = setInterval(() => {
      setPlaceholderIndex((i) => (i + 1) % PLACEHOLDERS.length);
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Fetch workflows silently
  const workflowsQuery = useQuery({
    queryKey: queryKeys.workflows.list(),
    queryFn: () => workflowsApi.list(),
    retry: false,
  });

  // Poll active run
  const runQuery = useQuery({
    queryKey: ["studio", "run", activeRunId],
    queryFn: async () => {
      if (!activeRunId) return null;
      return apiFetch<RunDetail>(`/v1/runs/${activeRunId}`);
    },
    enabled: !!activeRunId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 2000;
      if (["completed", "failed", "rejected"].includes(data.status)) return false;
      return 2000;
    },
  });

  // React to run status changes
  useEffect(() => {
    const run = runQuery.data;
    if (!run) return;
    const status = run.status;
    if (prevRunStatus.current === status) return;
    prevRunStatus.current = status;

    if (status === "completed" && run.state) {
      const code = run.state.code as string | undefined;
      const cost = run.state.estimated_cost_usd as number | undefined;
      const planIn = Number(run.state.plan_tokens_in ?? 0);
      const planOut = Number(run.state.plan_tokens_out ?? 0);
      const implIn = Number(run.state.implement_tokens_in ?? 0);
      const implOut = Number(run.state.implement_tokens_out ?? 0);
      const tokensIn = planIn + implIn;
      const tokensOut = planOut + implOut;
      const elapsed = runStartTime ? Date.now() - runStartTime : 0;

      setMessages((prev) => {
        const next = [...prev];

        // Agent flow message (event_log + execution_summary)
        if (run.event_log && run.event_log.length > 0) {
          next.push(
            createMessage("flow", "Execution Flow", {
              runId: run.id,
              eventLog: run.event_log,
              executionSummary: run.execution_summary,
              startedAt: run.started_at,
              completedAt: run.completed_at ?? undefined,
            }),
          );
        }

        // Artifact message
        if (code) {
          next.push(
            createMessage("artifact", code, {
              runId: run.id,
              code,
              status: "completed",
              cost: cost ?? ((tokensIn * 3 + tokensOut * 15) / 1_000_000),
              tokens: { in: tokensIn, out: tokensOut },
            }),
          );
        }
        // Completion message
        next.push(
          createMessage(
            "system",
            `Task completed${elapsed > 0 ? ` in ${formatDuration(elapsed)}` : ""}.${
              cost ? ` Cost: $${cost.toFixed(4)}` : ""
            }${tokensIn > 0 ? ` | ${tokensIn.toLocaleString()} input + ${tokensOut.toLocaleString()} output tokens` : ""}`,
            { status: "completed" },
          ),
        );
        return next;
      });
      setRunStartTime(null);
    } else if (status === "failed") {
      setMessages((prev) => [
        ...prev,
        createMessage("system", "Execution failed. Check agent logs for details.", {
          status: "failed",
        }),
      ]);
      setRunStartTime(null);
    }
  }, [runQuery.data, runStartTime]);

  // Start run mutation
  const startRun = useMutation({
    mutationFn: async (spec: string) => {
      const workflows = workflowsQuery.data ?? [];
      const resolved = resolveWorkflow(spec, workflows);
      if (!resolved) throw new Error("No workflows available. Start the backend first.");
      return { run: await workflowsApi.startRun(resolved.workflow.id, { spec }), reasoning: resolved.reasoning };
    },
    onSuccess: ({ run, reasoning }) => {
      setActiveRunId(run.id);
      setRunStartTime(Date.now());
      prevRunStatus.current = null;
      setShowPreview(false);
      setShowCode(false);
      setMessages((prev) => [
        ...prev,
        createMessage("system", reasoning),
        createMessage("agent", "Starting autonomous agents... I'll handle planning and implementation.", {
          runId: run.id,
          status: "running",
        }),
      ]);
      queryClient.invalidateQueries({ queryKey: queryKeys.runs.list() });
    },
    onError: (error) => {
      setMessages((prev) => [
        ...prev,
        createMessage("system", `Error: ${(error as Error).message}`, { status: "failed" }),
      ]);
    },
  });

  // Submit handler
  const handleSubmit = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed || startRun.isPending) return;
    setMessages((prev) => [...prev, createMessage("user", trimmed)]);
    setInput("");
    startRun.mutate(trimmed);
  }, [input, startRun]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit],
  );

  const handleCopyCode = useCallback((code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  }, []);

  const isRunning = activeRunId && runQuery.data &&
    !["completed", "failed", "rejected"].includes(runQuery.data.status);
  const hasPendingApproval = runQuery.data?.execution_summary?.pending_approval === true;
  const latestArtifact = [...messages].reverse().find((m) => m.role === "artifact");
  const approvalsPath = `/p/${projectSlug}/approvals`;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Sparkles className="h-4 w-4 text-primary" />
          </div>
          <div>
            <h1 className="text-sm font-semibold">Pylon Studio</h1>
            <p className="text-[11px] text-muted-foreground">
              Autonomous AI agents at your service
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {latestArtifact?.meta?.code && (
            <>
              <Button
                variant={showPreview ? "default" : "ghost"}
                size="sm"
                onClick={() => { setShowPreview(!showPreview); setShowCode(false); }}
                className="gap-1.5"
              >
                <Eye className="h-3.5 w-3.5" />
                Preview
              </Button>
              <Button
                variant={showCode ? "default" : "ghost"}
                size="sm"
                onClick={() => { setShowCode(!showCode); setShowPreview(false); }}
                className="gap-1.5"
              >
                <Code2 className="h-3.5 w-3.5" />
                Code
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Lifecycle guidance banner */}
      <div className="flex items-center gap-2 border-b border-border bg-muted/30 px-4 py-2 text-xs text-muted-foreground">
        <Info className="h-3.5 w-3.5 shrink-0" />
        <span>
          プロダクトを段階的に構築する場合は{" "}
          <Link to={`/p/${projectSlug}/lifecycle/research`} className="text-primary hover:underline font-medium">
            Product Lifecycle
          </Link>{" "}
          をご利用ください
        </span>
      </div>

      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Chat panel */}
        <div className={cn(
          "flex flex-1 flex-col transition-all",
          (showPreview || showCode) && "lg:max-w-[50%]",
        )}>
          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-4">
            {messages.length === 0 ? (
              <WelcomeScreen onExampleClick={(text) => {
                setInput(text);
                inputRef.current?.focus();
              }} />
            ) : (
              <div className="mx-auto max-w-3xl space-y-4">
                {messages.map((msg) => (
                  <MessageBubble
                    key={msg.id}
                    message={msg}
                    onCopyCode={handleCopyCode}
                    copiedCode={copiedCode}
                    onShowPreview={() => { setShowPreview(true); setShowCode(false); }}
                  />
                ))}

                {/* Pending approval notification */}
                {hasPendingApproval && (
                  <ApprovalBubble approvalsPath={approvalsPath} />
                )}

                {/* Typing indicator */}
                {(isRunning || startRun.isPending) && (
                  <div className="flex items-start gap-3">
                    <AgentAvatar />
                    <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm bg-card px-4 py-3 text-sm">
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                      <span className="text-muted-foreground">
                        {startRun.isPending ? "Analyzing your request..." : "Agents working..."}
                      </span>
                      {runStartTime && (
                        <ElapsedTimer startTime={runStartTime} />
                      )}
                    </div>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          {/* Input */}
          <div className="border-t border-border bg-background px-4 py-3">
            <div className="mx-auto max-w-3xl">
              <div className="relative flex items-end rounded-xl border border-border bg-card shadow-sm transition-shadow focus-within:shadow-md focus-within:ring-1 focus-within:ring-ring">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={PLACEHOLDERS[placeholderIndex]}
                  rows={1}
                  className="max-h-36 min-h-[44px] flex-1 resize-none bg-transparent px-4 py-3 text-sm placeholder:text-muted-foreground/60 focus:outline-none"
                  style={{ height: "auto", overflow: "hidden" }}
                  onInput={(e) => {
                    const target = e.target as HTMLTextAreaElement;
                    target.style.height = "auto";
                    target.style.height = `${Math.min(target.scrollHeight, 144)}px`;
                  }}
                />
                <Button
                  size="icon"
                  variant="ghost"
                  className="m-1.5 h-8 w-8 shrink-0 rounded-lg"
                  onClick={handleSubmit}
                  disabled={!input.trim() || startRun.isPending || !!isRunning}
                >
                  <Send className={cn(
                    "h-4 w-4 transition-colors",
                    input.trim() ? "text-primary" : "text-muted-foreground",
                  )} />
                </Button>
              </div>
              <p className="mt-1.5 text-center text-[10px] text-muted-foreground/50">
                AI agents will autonomously plan, build, and deliver. Shift+Enter for new line.
              </p>
            </div>
          </div>
        </div>

        {/* Artifact panel (preview / code) */}
        {(showPreview || showCode) && latestArtifact?.meta?.code && (
          <div className="hidden flex-1 border-l border-border lg:flex lg:flex-col">
            <div className="flex items-center justify-between border-b border-border px-4 py-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                {showPreview ? (
                  <>
                    <Eye className="h-4 w-4" />
                    Live Preview
                  </>
                ) : (
                  <>
                    <Code2 className="h-4 w-4" />
                    Source Code
                  </>
                )}
              </div>
              <div className="flex items-center gap-1">
                {showCode && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleCopyCode(latestArtifact.meta!.code!)}
                    className="gap-1.5"
                  >
                    {copiedCode ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                    {copiedCode ? "Copied" : "Copy"}
                  </Button>
                )}
                {showPreview && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      const blob = new Blob([latestArtifact.meta!.code!], { type: "text/html" });
                      window.open(URL.createObjectURL(blob), "_blank");
                    }}
                    className="gap-1.5"
                  >
                    <ExternalLink className="h-3 w-3" />
                    Open
                  </Button>
                )}
              </div>
            </div>
            <div className="flex-1 overflow-hidden">
              {showPreview ? (
                <iframe
                  srcDoc={latestArtifact.meta.code}
                  title="Generated App Preview"
                  className="h-full w-full bg-white"
                  sandbox="allow-scripts allow-same-origin"
                />
              ) : (
                <pre className="h-full overflow-auto bg-muted/30 p-4 text-xs font-mono leading-relaxed">
                  {latestArtifact.meta.code}
                </pre>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
