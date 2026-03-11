import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Play, Layers, Search, Lightbulb, Palette, ShieldCheck,
  Code2, Rocket, RefreshCw, Check, Clock, ChevronRight,
  ArrowRight, X, Star,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { PageSkeleton } from "@/components/PageSkeleton";
import { queryKeys } from "@/lib/queryKeys";
import { lifecycleApi } from "@/api/lifecycle";
import { apiFetch } from "@/api/client";
import type { WorkflowRun } from "@/api/workflows";
import type { LifecyclePhase, LifecycleProject, PhaseStatus } from "@/types/lifecycle";

interface RunListResponse {
  runs: WorkflowRun[];
  count?: number;
}

const PHASE_META: Record<LifecyclePhase, { label: string; icon: React.ElementType }> = {
  research: { label: "調査", icon: Search },
  planning: { label: "企画", icon: Lightbulb },
  design: { label: "デザイン", icon: Palette },
  approval: { label: "承認", icon: ShieldCheck },
  development: { label: "開発", icon: Code2 },
  deploy: { label: "デプロイ", icon: Rocket },
  iterate: { label: "改善", icon: RefreshCw },
};

export function Runs() {
  const [tab, setTab] = useState<"lifecycle" | "workflows">("lifecycle");

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">History</h1>
        <p className="text-sm text-muted-foreground">
          過去の生成物・実行履歴を確認
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        <button
          onClick={() => setTab("lifecycle")}
          className={cn(
            "flex items-center gap-2 border-b-2 px-4 py-2 text-sm font-medium transition-colors",
            tab === "lifecycle"
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          <Layers className="h-3.5 w-3.5" />
          Lifecycle
        </button>
        <button
          onClick={() => setTab("workflows")}
          className={cn(
            "flex items-center gap-2 border-b-2 px-4 py-2 text-sm font-medium transition-colors",
            tab === "workflows"
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          <Play className="h-3.5 w-3.5" />
          Workflows
        </button>
      </div>

      {tab === "lifecycle" ? <LifecycleHistory /> : <WorkflowHistory />}
    </div>
  );
}

/* ── Lifecycle History ── */
function LifecycleHistory() {
  const navigate = useNavigate();
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["lifecycle", "projects"],
    queryFn: async () => {
      const response = await lifecycleApi.listProjects();
      return response.projects;
    },
  });

  if (query.isLoading) return <PageSkeleton />;

  const projects = query.data ?? [];

  if (projects.length === 0) {
    return (
      <EmptyState
        icon={Layers}
        title="ライフサイクル履歴がありません"
        description="プロジェクトのライフサイクルを開始すると、ここに履歴が表示されます。"
        action={{ label: "再読み込み", onClick: () => window.location.reload() }}
      />
    );
  }

  const selected = projects.find((project) => project.projectId === selectedSlug);

  return (
    <div className="flex gap-6">
      {/* Project list */}
      <div className={cn("space-y-2", selected ? "w-80 shrink-0" : "flex-1 max-w-3xl")}>
        {projects.map((project) => {
          const completedPhases = project.phaseStatuses.filter((status) => status.status === "completed").length;
          const totalPhases = project.phaseStatuses.length;
          const slug = project.projectId;
          const isActive = slug === selectedSlug;

          return (
            <button
              key={slug}
              onClick={() => setSelectedSlug(isActive ? null : slug)}
              className={cn(
                "w-full rounded-xl border bg-card p-4 text-left transition-all",
                isActive ? "border-primary shadow-md shadow-primary/5" : "border-border hover:border-primary/30",
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-bold text-foreground truncate">{slug}</p>
                    {completedPhases === totalPhases && (
                      <Badge variant="default" className="text-[10px] shrink-0">完了</Badge>
                    )}
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground truncate">
                    {project.spec ? project.spec.slice(0, 80) + (project.spec.length > 80 ? "..." : "") : "（仕様未入力）"}
                  </p>
                </div>
                <ChevronRight className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", isActive && "rotate-90")} />
              </div>

              {/* Phase progress bar */}
              <div className="mt-3 flex gap-0.5">
                {project.phaseStatuses.map((ps) => (
                  <div
                    key={ps.phase}
                    className={cn(
                      "h-1.5 flex-1 rounded-full",
                      ps.status === "completed" ? "bg-success" :
                      ps.status === "in_progress" ? "bg-primary animate-pulse" :
                      ps.status === "review" ? "bg-warning" :
                      "bg-muted",
                    )}
                    title={PHASE_META[ps.phase].label}
                  />
                ))}
              </div>

              <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {new Date(project.savedAt).toLocaleString("ja-JP")}
                </span>
                <span>
                  {completedPhases}/{totalPhases} フェーズ完了
                </span>
              </div>
            </button>
          );
        })}
      </div>

      {/* Detail panel */}
      {selected && (
        <LifecycleDetail
          slug={selected.projectId}
          data={selected}
          onClose={() => setSelectedSlug(null)}
          onNavigate={(phase) => navigate(`/p/${selected.projectId}/lifecycle/${phase}`)}
        />
      )}
    </div>
  );
}

/* ── Lifecycle Detail ── */
function LifecycleDetail({ slug, data, onClose, onNavigate }: {
  slug: string;
  data: LifecycleProject;
  onClose: () => void;
  onNavigate: (phase: LifecyclePhase) => void;
}) {
  const [section, setSection] = useState<LifecyclePhase | null>(null);

  return (
    <div className="flex-1 rounded-xl border border-border bg-card overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <div>
          <h3 className="text-sm font-bold text-foreground">{slug}</h3>
          <p className="text-[11px] text-muted-foreground">
            最終更新: {new Date(data.savedAt).toLocaleString("ja-JP")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => onNavigate("research")}>
            <ArrowRight className="mr-1 h-3 w-3" /> 開く
          </Button>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Phase cards */}
      <div className="overflow-y-auto p-5 space-y-3" style={{ maxHeight: "calc(100vh - 280px)" }}>
        {/* Spec */}
        {data.spec && (
          <div className="rounded-lg border border-border bg-accent/20 p-4">
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1">プロダクト概要</p>
            <p className="text-sm text-foreground">{data.spec}</p>
          </div>
        )}

        {/* Phase summary cards */}
        {data.phaseStatuses.map((ps) => {
          const meta = PHASE_META[ps.phase];
          const Icon = meta.icon;
          const isExpanded = section === ps.phase;
          const hasData = phaseHasData(ps.phase, data);

          if (ps.status === "locked" && !hasData) return null;

          return (
            <div key={ps.phase} className="rounded-lg border border-border overflow-hidden">
              <button
                onClick={() => setSection(isExpanded ? null : ps.phase)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-accent/30 transition-colors"
              >
                <div className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-md",
                  ps.status === "completed" ? "bg-success/10 text-success" :
                  ps.status === "in_progress" ? "bg-primary/10 text-primary" :
                  "bg-muted text-muted-foreground",
                )}>
                  <Icon className="h-3.5 w-3.5" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground">{meta.label}</p>
                  <p className="text-[10px] text-muted-foreground">
                    {phaseStatusLabel(ps)}
                  </p>
                </div>
                {ps.status === "completed" && <Check className="h-4 w-4 text-success" />}
                {hasData && (
                  <ChevronRight className={cn("h-3.5 w-3.5 text-muted-foreground transition-transform", isExpanded && "rotate-90")} />
                )}
              </button>

              {isExpanded && hasData && (
                <div className="border-t border-border px-4 py-3 bg-accent/10">
                  <PhaseDetail phase={ps.phase} data={data} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Phase Detail Content ── */
function PhaseDetail({ phase, data }: { phase: LifecyclePhase; data: LifecycleProject }) {
  switch (phase) {
    case "research":
      if (!data.research) return <p className="text-xs text-muted-foreground">データなし</p>;
      return (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <MiniCard label="市場規模" value={data.research.market_size} />
            <MiniCard label="技術実現性" value={`${(data.research.tech_feasibility.score * 100).toFixed(0)}%`} />
          </div>
          <div>
            <p className="text-[10px] font-medium text-muted-foreground mb-1">競合 ({data.research.competitors.length}社)</p>
            <div className="flex flex-wrap gap-1.5">
              {data.research.competitors.map((c, i) => (
                <Badge key={i} variant="secondary" className="text-[10px]">{c.name} — {c.pricing}</Badge>
              ))}
            </div>
          </div>
          <div>
            <p className="text-[10px] font-medium text-muted-foreground mb-1">市場トレンド</p>
            <div className="flex flex-wrap gap-1">
              {data.research.trends.map((t, i) => (
                <Badge key={i} variant="outline" className="text-[10px]">{t}</Badge>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <p className="text-[10px] font-medium text-success mb-1">機会</p>
              {data.research.opportunities.map((o, i) => (
                <p key={i} className="text-[10px] text-foreground">• {o}</p>
              ))}
            </div>
            <div>
              <p className="text-[10px] font-medium text-destructive mb-1">脅威</p>
              {data.research.threats.map((t, i) => (
                <p key={i} className="text-[10px] text-foreground">• {t}</p>
              ))}
            </div>
          </div>
        </div>
      );

    case "planning":
      if (!data.analysis) return <p className="text-xs text-muted-foreground">データなし</p>;
      return (
        <div className="space-y-3">
          {data.analysis.personas.length > 0 && (
            <div>
              <p className="text-[10px] font-medium text-muted-foreground mb-1">ペルソナ ({data.analysis.personas.length})</p>
              <div className="flex flex-wrap gap-1.5">
                {data.analysis.personas.map((p, i) => (
                  <Badge key={i} variant="secondary" className="text-[10px]">{p.name} — {p.role}</Badge>
                ))}
              </div>
            </div>
          )}
          {data.analysis.user_stories.length > 0 && (
            <div>
              <p className="text-[10px] font-medium text-muted-foreground mb-1">ユーザーストーリー ({data.analysis.user_stories.length})</p>
              {data.analysis.user_stories.slice(0, 5).map((s, i) => (
                <p key={i} className="text-[10px] text-foreground">
                  <Badge variant={s.priority === "must" ? "default" : "outline"} className="text-[8px] mr-1">{s.priority.toUpperCase()}</Badge>
                  {s.role}として{s.action}
                </p>
              ))}
              {data.analysis.user_stories.length > 5 && (
                <p className="text-[10px] text-muted-foreground">…他{data.analysis.user_stories.length - 5}件</p>
              )}
            </div>
          )}
          {data.features.length > 0 && (
            <div>
              <p className="text-[10px] font-medium text-muted-foreground mb-1">
                機能選択: {data.features.filter((f) => f.selected).length}/{data.features.length} 選択
              </p>
              <div className="flex flex-wrap gap-1">
                {data.features.filter((f) => f.selected).map((f, i) => (
                  <Badge key={i} variant="secondary" className="text-[10px]">{f.feature}</Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      );

    case "design":
      if (data.designVariants.length === 0) return <p className="text-xs text-muted-foreground">データなし</p>;
      return (
        <div className="space-y-3">
          <p className="text-[10px] font-medium text-muted-foreground">
            {data.designVariants.length}パターン生成
            {data.selectedDesignId && ` — 「${data.designVariants.find((v) => v.id === data.selectedDesignId)?.pattern_name}」選択中`}
          </p>
          <div className="grid gap-2">
            {data.designVariants.map((v) => (
              <div
                key={v.id}
                className={cn(
                  "flex items-center gap-3 rounded-lg border p-3",
                  v.id === data.selectedDesignId ? "border-primary bg-primary/5" : "border-border",
                )}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-xs font-medium text-foreground">{v.pattern_name}</p>
                    <Badge variant="outline" className="text-[9px]">{v.model}</Badge>
                    {v.id === data.selectedDesignId && <Star className="h-3 w-3 text-primary fill-primary" />}
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-0.5">{v.description}</p>
                </div>
                <div className="text-right shrink-0">
                  <p className="text-[10px] font-mono text-foreground">${v.cost_usd.toFixed(3)}</p>
                  <div className="flex gap-1 mt-0.5">
                    {Object.entries(v.scores).slice(0, 2).map(([k, val]) => (
                      <span key={k} className="text-[9px] text-muted-foreground">{(val * 100).toFixed(0)}</span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      );

    case "approval":
      return (
        <div>
          <p className="text-xs text-foreground">
            ステータス:
            <Badge
              variant={data.approvalStatus === "approved" ? "default" : data.approvalStatus === "rejected" ? "destructive" : "secondary"}
              className="ml-2 text-[10px]"
            >
              {data.approvalStatus === "approved" ? "承認済み" :
               data.approvalStatus === "rejected" ? "却下" :
               data.approvalStatus === "revision_requested" ? "修正依頼" : "未承認"}
            </Badge>
          </p>
        </div>
      );

    case "development":
      return (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <MiniCard label="イテレーション" value={`${data.buildIteration}回`} />
            <MiniCard label="コスト" value={`$${data.buildCost.toFixed(3)}`} />
          </div>
          {data.milestoneResults.length > 0 && (
            <div>
              <p className="text-[10px] font-medium text-muted-foreground mb-1">マイルストーン結果</p>
              {data.milestoneResults.map((mr, i) => (
                <div key={i} className="flex items-center gap-1.5 text-[10px]">
                  {mr.status === "satisfied"
                    ? <Check className="h-3 w-3 text-success" />
                    : <X className="h-3 w-3 text-destructive" />}
                  <span className="text-foreground">{mr.name}</span>
                </div>
              ))}
            </div>
          )}
          {data.buildCode && (
            <p className="text-[10px] text-muted-foreground">コード生成済み ({data.buildCode.length.toLocaleString()}文字)</p>
          )}
        </div>
      );

    case "deploy":
      return data.deployChecks.length > 0 || data.releases.length > 0 ? (
        <div className="space-y-2">
          {data.deployChecks.length > 0 && (
            <div>
              <p className="text-[10px] font-medium text-muted-foreground mb-1">品質ゲート</p>
              {data.deployChecks.map((check) => (
                <div key={check.id} className="flex items-center gap-1.5 text-[10px]">
                  <Badge variant="outline" className="text-[9px] capitalize">{check.status}</Badge>
                  <span className="text-foreground">{check.label}</span>
                </div>
              ))}
            </div>
          )}
          {data.releases[0] && (
            <div className="text-[10px] text-foreground">
              最新 release: <span className="font-mono">{data.releases[0].version}</span>
            </div>
          )}
        </div>
      ) : <p className="text-xs text-muted-foreground">データなし</p>;
    case "iterate":
      return data.feedbackItems.length > 0 || data.recommendations.length > 0 ? (
        <div className="space-y-2">
          {data.feedbackItems.slice(0, 3).map((feedback) => (
            <div key={feedback.id} className="text-[10px] text-foreground">
              <span className="font-medium">{feedback.votes}票</span> {feedback.text}
            </div>
          ))}
          {data.recommendations.slice(0, 2).map((recommendation) => (
            <div key={recommendation.id} className="text-[10px] text-muted-foreground">
              {recommendation.title}
            </div>
          ))}
        </div>
      ) : <p className="text-xs text-muted-foreground">データなし</p>;
  }
}

function MiniCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-background px-3 py-2">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="text-sm font-bold text-foreground">{value}</p>
    </div>
  );
}

function phaseHasData(phase: LifecyclePhase, data: LifecycleProject): boolean {
  switch (phase) {
    case "research": return !!data.research;
    case "planning": return !!data.analysis || data.features.length > 0;
    case "design": return data.designVariants.length > 0;
    case "approval": return data.approvalStatus !== "pending";
    case "development": return data.buildIteration > 0 || !!data.buildCode;
    case "deploy": return data.deployChecks.length > 0 || data.releases.length > 0;
    case "iterate": return data.feedbackItems.length > 0 || data.recommendations.length > 0;
  }
}

function phaseStatusLabel(ps: PhaseStatus): string {
  switch (ps.status) {
    case "completed": return ps.completedAt ? `完了 (${new Date(ps.completedAt).toLocaleString("ja-JP")})` : "完了";
    case "in_progress": return "進行中";
    case "review": return "レビュー中";
    case "available": return "利用可能";
    case "locked": return "未開放";
  }
}

/* ── Workflow History (original Runs) ── */
function WorkflowHistory() {
  const query = useQuery({
    queryKey: queryKeys.runs.list(),
    queryFn: async () => {
      const res = await apiFetch<RunListResponse>("/v1/runs");
      return res.runs;
    },
  });

  if (query.isLoading) return <PageSkeleton />;

  const runs = query.data ?? [];

  if (runs.length === 0) {
    return (
      <EmptyState
        icon={Play}
        title="No runs yet"
        description="Start a workflow to see runs here."
        action={{ label: "再読み込み", onClick: () => window.location.reload() }}
      />
    );
  }

  return (
    <div className="space-y-2">
      {runs.map((run) => (
        <div
          key={run.id}
          className="flex items-center justify-between rounded-lg border border-border p-4"
        >
          <div>
            <p className="text-sm font-medium">{run.id.slice(0, 8)}</p>
            <p className="text-xs text-muted-foreground">
              Started {new Date(run.started_at).toLocaleString("ja-JP")}
              {run.runtime_metrics?.estimated_cost_usd
                ? ` | $${run.runtime_metrics.estimated_cost_usd.toFixed(4)}`
                : ""}
            </p>
          </div>
          <StatusBadge status={run.status} />
        </div>
      ))}
    </div>
  );
}
