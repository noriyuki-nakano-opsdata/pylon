import { AlertCircle, ArrowRight, Bot, Check, Loader2, Radar, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

export type AgentStatus = "pending" | "running" | "completed" | "failed";
export type TimelineStatus = "pending" | "running" | "completed";

export interface CollaborationAgent {
  id: string;
  label: string;
  status: AgentStatus;
  currentTask?: string;
  delegatedTo?: string;
}

export interface CollaborationAction {
  id: string;
  label: string;
  summary: string;
  status: string;
  from?: string;
  to?: string;
}

export interface CollaborationEvent {
  id: string;
  label: string;
  summary: string;
  timestamp?: string;
}

export interface CollaborationTimelineStep {
  id: string;
  label: string;
  detail: string;
  status: TimelineStatus;
  owner?: string;
  artifact?: string;
}

interface MultiAgentCollaborationPulseProps {
  title: string;
  subtitle?: string;
  elapsedLabel: string;
  agents: CollaborationAgent[];
  actions?: CollaborationAction[];
  events?: CollaborationEvent[];
  timeline?: CollaborationTimelineStep[];
  compact?: boolean;
}

interface LedgerEntry {
  id: string;
  title: string;
  detail: string;
  kind: "handoff" | "signal";
  meta?: string;
  timestamp?: string;
}

function statusLabel(status: AgentStatus): string {
  if (status === "running") return "実行中";
  if (status === "completed") return "完了";
  if (status === "failed") return "要再確認";
  return "待機";
}

function statusIcon(status: AgentStatus) {
  if (status === "running") return <Loader2 className="h-3.5 w-3.5 animate-spin" />;
  if (status === "completed") return <Check className="h-3.5 w-3.5" />;
  if (status === "failed") return <AlertCircle className="h-3.5 w-3.5" />;
  return <Bot className="h-3.5 w-3.5" />;
}

function timelinePillLabel(status: string): string {
  if (status === "running") return "進行中";
  if (status === "completed") return "通過済み";
  return "待機列";
}

function buildLedgerEntries(
  actions: CollaborationAction[],
  events: CollaborationEvent[],
  agents: CollaborationAgent[],
  compact: boolean,
): LedgerEntry[] {
  const actionEntries = actions.map((action) => ({
    id: `handoff:${action.id}`,
    title: action.from && action.to ? `${action.from} → ${action.to}` : action.label,
    detail: action.summary,
    kind: "handoff" as const,
    meta: action.status,
  }));
  const eventEntries = events.map((event) => ({
    id: `signal:${event.id}`,
    title: event.label,
    detail: event.summary,
    kind: "signal" as const,
    timestamp: event.timestamp,
  }));

  const merged = [...actionEntries, ...eventEntries].slice(0, compact ? 4 : 6);
  if (merged.length > 0) return merged;

  return agents
    .slice(0, compact ? 4 : 5)
    .map((agent, index) => ({
      id: `warmup:${agent.id}`,
      title: agent.delegatedTo ? `${agent.label} → ${agent.delegatedTo}` : agent.label,
      detail: agent.currentTask ?? "共有コンテキストを準備しています。",
      kind: index === 0 ? "handoff" : "signal",
      meta: statusLabel(agent.status),
    }));
}

export function MultiAgentCollaborationPulse({
  title,
  subtitle,
  elapsedLabel,
  agents,
  actions = [],
  events = [],
  timeline,
  compact = false,
}: MultiAgentCollaborationPulseProps) {
  const visibleAgents = agents.slice(0, compact ? 5 : 6);
  const normalizedTimeline = (timeline && timeline.length > 0
    ? timeline
    : [
        {
          id: "collect",
          label: "Signal collection",
          detail: "市場、競合、ユーザー、技術のシグナルを並列収集します。",
          status: visibleAgents.some((agent) => agent.status === "completed" || agent.status === "running") ? "completed" : "pending",
          owner: visibleAgents[0]?.label,
          artifact: "Raw evidence",
        },
        {
          id: "challenge",
          label: "Claim challenge",
          detail: "弱い主張を隣接シグナルで突き合わせ、精度を上げます。",
          status: actions.length > 0 ? "running" : "pending",
          owner: actions[0]?.from,
          artifact: "Confidence checks",
        },
        {
          id: "synthesis",
          label: "Synthesis pass",
          detail: "最も強い根拠を束ねて brief に変換します。",
          status: visibleAgents.some((agent) => agent.label.toLowerCase().includes("synth") && agent.status === "running")
            ? "running"
            : visibleAgents.some((agent) => agent.label.toLowerCase().includes("synth") && agent.status === "completed")
              ? "completed"
              : "pending",
          owner: visibleAgents.find((agent) => agent.label.toLowerCase().includes("synth"))?.label,
          artifact: "Research brief",
        },
        {
          id: "handoff",
          label: "Planning handoff",
          detail: "企画フェーズに渡せる形で論点を圧縮します。",
          status: visibleAgents.every((agent) => agent.status === "completed") ? "completed" : "pending",
          owner: visibleAgents.at(-1)?.label,
          artifact: "Planning packet",
        },
      ]).slice(0, compact ? 3 : 4);
  const ledgerEntries = buildLedgerEntries(actions, events, visibleAgents, compact);
  const activeAgents = visibleAgents.filter((agent) => agent.status === "running").length;
  const completedAgents = visibleAgents.filter((agent) => agent.status === "completed").length;
  const pulseLead = visibleAgents.find((agent) => agent.status === "running") ?? visibleAgents[0];

  return (
    <section
      className={cn(
        "group relative overflow-hidden rounded-[32px] border border-white/10 bg-[#07111f] text-slate-50 shadow-[0_28px_100px_rgba(2,6,23,0.48)]",
        compact ? "p-4" : "p-6",
      )}
    >
      <style>{`
        @keyframes pylon-agent-beam {
          0% { transform: translateX(-28px); opacity: 0; }
          18% { opacity: 1; }
          82% { opacity: 1; }
          100% { transform: translateX(calc(100% + 28px)); opacity: 0; }
        }
        @keyframes pylon-agent-glow {
          0%, 100% { box-shadow: 0 0 0 0 rgba(56,189,248,0.0); }
          50% { box-shadow: 0 0 0 12px rgba(56,189,248,0.08); }
        }
        @keyframes pylon-orbit {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
        @keyframes pylon-pulse-bar {
          0% { transform: translateX(-40%); opacity: 0; }
          20% { opacity: 1; }
          100% { transform: translateX(180%); opacity: 0; }
        }
      `}</style>

      <div className="pointer-events-none absolute inset-0">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(56,189,248,0.18),transparent_28%),radial-gradient(circle_at_85%_20%,rgba(245,158,11,0.12),transparent_24%),linear-gradient(180deg,rgba(7,17,31,0.88),rgba(7,17,31,0.98))]" />
        <div className="absolute inset-0 opacity-[0.16]" style={{ backgroundImage: "linear-gradient(rgba(148,163,184,0.18) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,0.14) 1px, transparent 1px)", backgroundSize: "28px 28px" }} />
        <div className="absolute left-[-8%] top-[-12%] h-44 w-44 rounded-full border border-cyan-300/10" style={{ animation: "pylon-orbit 28s linear infinite" }} />
        <div className="absolute right-[-10%] bottom-[-18%] h-56 w-56 rounded-full border border-amber-200/10" style={{ animation: "pylon-orbit 34s linear infinite reverse" }} />
      </div>

      <div className="relative z-10 space-y-5">
        <div className={cn("flex flex-col gap-4", compact ? "xl:flex-row xl:items-start xl:justify-between" : "2xl:flex-row 2xl:items-start 2xl:justify-between")}>
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-300/8 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.28em] text-cyan-100/90">
              <Sparkles className="h-3.5 w-3.5 text-cyan-300" />
              Multi-agent live
            </div>
            <div className="space-y-2">
              <h2 className={cn("max-w-3xl font-serif tracking-tight text-white", compact ? "text-[1.45rem]" : "text-[2rem] leading-tight")}>
                {title}
              </h2>
              {subtitle && (
                <p className={cn("max-w-3xl text-slate-300/90", compact ? "text-xs leading-5" : "text-sm leading-6")}>
                  {subtitle}
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 sm:gap-3">
            {[
              { label: "Agents", value: `${visibleAgents.length}`, tone: "text-white" },
              { label: "Active", value: `${activeAgents}`, tone: activeAgents > 0 ? "text-cyan-200" : "text-slate-300" },
              { label: "Elapsed", value: elapsedLabel, tone: "text-amber-100" },
            ].map((metric) => (
              <div
                key={metric.label}
                className="min-w-[88px] rounded-[20px] border border-white/10 bg-white/[0.04] px-3 py-3 backdrop-blur-sm"
              >
                <p className="text-[10px] uppercase tracking-[0.2em] text-slate-400">{metric.label}</p>
                <p className={cn("mt-1 font-semibold", compact ? "text-sm" : "text-lg", metric.tone)}>{metric.value}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-[22px] border border-cyan-300/12 bg-cyan-300/[0.05] px-4 py-3">
            <p className="text-[10px] uppercase tracking-[0.24em] text-cyan-100/70">Parallel lanes</p>
            <p className="mt-1 text-sm text-slate-200">複数の専門エージェントが同時に証拠を集め、互いの主張を強化します。</p>
          </div>
          <div className="rounded-[22px] border border-white/10 bg-white/[0.03] px-4 py-3">
            <p className="text-[10px] uppercase tracking-[0.24em] text-slate-400">Sequential handoff</p>
            <p className="mt-1 text-sm text-slate-200">集まった根拠は、統合担当を経由して次フェーズへ順番に圧縮されます。</p>
          </div>
        </div>

        <div className={cn("grid gap-4", compact ? "xl:grid-cols-[1.25fr_0.75fr]" : "xl:grid-cols-[1.32fr_0.68fr]")}>
          <div className="rounded-[28px] border border-white/10 bg-[linear-gradient(180deg,rgba(10,18,34,0.92),rgba(7,12,24,0.84))] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Parallel swarm</p>
                <p className="mt-1 text-sm text-slate-300">同時進行している担当レーン。ここでは並列処理だけを見せます。</p>
              </div>
              <div className="inline-flex items-center gap-2 rounded-full border border-cyan-300/15 bg-cyan-300/8 px-3 py-1 text-[11px] text-cyan-100">
                <Radar className="h-3.5 w-3.5" />
                lead: {pulseLead?.label ?? "dispatch"}
              </div>
            </div>

            <div className={cn("grid gap-3", compact ? "md:grid-cols-2" : "md:grid-cols-2 xl:grid-cols-3")}>
              {visibleAgents.map((agent) => {
                const running = agent.status === "running";
                const completed = agent.status === "completed";
                const failed = agent.status === "failed";
                return (
                  <div key={agent.id} className="relative">
                    <article
                      className={cn(
                        "relative h-full min-h-[138px] overflow-hidden rounded-[24px] border px-4 py-4 transition-all",
                        running && "border-cyan-300/30 bg-cyan-300/[0.12]",
                        completed && "border-emerald-300/25 bg-emerald-300/[0.12]",
                        failed && "border-rose-300/25 bg-rose-300/[0.12]",
                        !running && !completed && !failed && "border-white/10 bg-white/[0.03]",
                      )}
                      style={running ? { animation: "pylon-agent-glow 2.8s ease-in-out infinite" } : undefined}
                    >
                      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/20 to-transparent" />
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <span
                            className={cn(
                              "flex h-8 w-8 items-center justify-center rounded-full border",
                              running && "border-cyan-300/35 bg-cyan-300/15 text-cyan-100",
                              completed && "border-emerald-300/35 bg-emerald-300/15 text-emerald-100",
                              failed && "border-rose-300/35 bg-rose-300/15 text-rose-100",
                              !running && !completed && !failed && "border-white/10 bg-white/5 text-slate-300",
                            )}
                          >
                            {statusIcon(agent.status)}
                          </span>
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-white">{agent.label}</p>
                            <p className="text-[11px] uppercase tracking-[0.16em] text-slate-400">{statusLabel(agent.status)}</p>
                          </div>
                        </div>
                        {agent.delegatedTo && (
                          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-300">
                            → {agent.delegatedTo}
                          </span>
                        )}
                      </div>

                      <p className="mt-4 line-clamp-3 text-[12px] leading-5 text-slate-300">
                        {agent.currentTask || "上流の文脈を待ちながら次の dispatch に備えています。"}
                      </p>
                    </article>
                  </div>
                );
              })}
            </div>

            <div className="mt-4 rounded-[24px] border border-white/10 bg-black/20 px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[11px] uppercase tracking-[0.22em] text-slate-400">Current pulse</p>
                  <p className="mt-1 text-sm text-slate-200">
                    {completedAgents > 0
                      ? `${completedAgents} 個の担当が一次調査を完了し、次の検証へ流れています。`
                      : "最初の調査ウェーブを立ち上げています。"}
                  </p>
                </div>
                <div className="relative hidden h-2 w-32 overflow-hidden rounded-full bg-white/10 md:block">
                  <div
                    className="absolute inset-y-0 left-0 w-14 rounded-full bg-gradient-to-r from-cyan-300 via-sky-300 to-transparent"
                    style={{ animation: "pylon-pulse-bar 2.6s linear infinite" }}
                  />
                </div>
              </div>
            </div>
          </div>

          <aside className="rounded-[28px] border border-white/10 bg-[linear-gradient(180deg,rgba(9,15,28,0.94),rgba(8,12,23,0.84))] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Live dispatch log</p>
                <p className="mt-1 text-sm text-slate-300">handoff と signal を時系列で追う、運用者向けの台帳です。</p>
              </div>
              <div className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] uppercase tracking-[0.18em] text-slate-300">
                {ledgerEntries.length} entries
              </div>
            </div>

            <div className="mt-4 space-y-3">
              {ledgerEntries.map((entry, index) => (
                <div key={entry.id} className="rounded-[22px] border border-white/8 bg-white/[0.03] px-3 py-3">
                  <div className="flex items-start gap-3">
                    <div
                      className={cn(
                        "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border",
                        entry.kind === "handoff"
                          ? "border-cyan-300/25 bg-cyan-300/12 text-cyan-100"
                          : "border-amber-200/20 bg-amber-200/10 text-amber-100",
                      )}
                    >
                      {entry.kind === "handoff" ? <ArrowRight className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p className="truncate text-sm font-medium text-white">{entry.title}</p>
                        <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
                          {entry.timestamp ?? entry.meta ?? `lane ${index + 1}`}
                        </span>
                      </div>
                      <p className="mt-1 text-[12px] leading-5 text-slate-400">{entry.detail}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </aside>
        </div>

        <div className="rounded-[28px] border border-white/10 bg-[linear-gradient(180deg,rgba(9,15,28,0.9),rgba(8,12,23,0.82))] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Sequential handoff rail</p>
              <p className="mt-1 text-sm text-slate-300">証拠がどう集約され、どの順番で planning へ渡るかを一本の流れで見せます。</p>
            </div>
            <div className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] uppercase tracking-[0.18em] text-slate-300">
              live orchestration
            </div>
          </div>

          <div className={cn("grid gap-3", compact ? "md:grid-cols-3" : "xl:grid-cols-4")}>
            {normalizedTimeline.map((step, index) => {
              const isRunning = step.status === "running";
              const isCompleted = step.status === "completed";
              return (
                <div key={step.id} className="relative">
                  <div
                    className={cn(
                      "relative min-h-[154px] overflow-hidden rounded-[24px] border px-4 py-4",
                      isRunning && "border-cyan-300/30 bg-cyan-300/[0.10]",
                      isCompleted && "border-emerald-300/28 bg-emerald-300/[0.10]",
                      !isRunning && !isCompleted && "border-white/10 bg-white/[0.03]",
                    )}
                  >
                    <div className="absolute inset-x-0 top-0 h-1 bg-white/5">
                      <div
                        className={cn(
                          "h-full rounded-full",
                          isRunning ? "bg-gradient-to-r from-cyan-300 via-sky-300 to-transparent" : isCompleted ? "bg-emerald-300/80" : "bg-white/10",
                        )}
                        style={isRunning ? { animation: `pylon-pulse-bar ${2.4 + index * 0.3}s linear infinite` } : isCompleted ? { width: "100%" } : { width: "26%" }}
                      />
                    </div>

                    <div className="flex items-center gap-3">
                      <span
                        className={cn(
                          "flex h-9 w-9 items-center justify-center rounded-full border text-xs font-semibold",
                          isRunning && "border-cyan-300/35 bg-cyan-300/14 text-cyan-100",
                          isCompleted && "border-emerald-300/35 bg-emerald-300/15 text-emerald-100",
                          !isRunning && !isCompleted && "border-white/10 bg-white/5 text-slate-300",
                        )}
                      >
                        {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : isCompleted ? <Check className="h-4 w-4" /> : index + 1}
                      </span>
                      <div>
                        <p className="text-sm font-semibold text-white">{step.label}</p>
                        <p className="mt-1 text-[11px] uppercase tracking-[0.18em] text-slate-400">{timelinePillLabel(step.status)}</p>
                      </div>
                    </div>

                    <p className="mt-4 line-clamp-4 text-[12px] leading-5 text-slate-300">{step.detail}</p>

                    <div className="mt-4 flex flex-wrap gap-2">
                      {step.owner && (
                        <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-300">
                          {step.owner}
                        </span>
                      )}
                      {step.artifact && (
                        <span className="rounded-full border border-cyan-300/16 bg-cyan-300/10 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-cyan-100">
                          {step.artifact}
                        </span>
                      )}
                    </div>
                  </div>

                  {index < normalizedTimeline.length - 1 && (
                    <div className="pointer-events-none absolute -right-2 top-1/2 hidden h-px w-4 -translate-y-1/2 xl:block">
                      <div className="relative h-px w-full bg-white/10">
                        <div
                          className={cn(
                            "absolute inset-y-0 left-0 h-px w-4 rounded-full",
                            isRunning ? "bg-gradient-to-r from-cyan-300 via-sky-300 to-transparent" : isCompleted ? "bg-emerald-300/70" : "bg-white/20",
                          )}
                          style={isRunning ? { animation: `pylon-agent-beam ${2.1 + index * 0.25}s linear infinite` } : undefined}
                        />
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
