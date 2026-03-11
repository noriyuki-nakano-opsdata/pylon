import { useState, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Search, Check, ArrowRight, Globe, TrendingUp,
  ShieldAlert, Lightbulb, BarChart3, Zap, Plus, X, AlertCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useLifecycle } from "./LifecycleContext";
import { useWorkflowRun } from "@/hooks/useWorkflowRun";
import { lifecycleApi } from "@/api/lifecycle";
import { AgentProgressView } from "@/components/lifecycle/AgentProgressView";

const RESEARCH_AGENTS = [
  { id: "competitor-analyst", label: "競合分析" },
  { id: "market-researcher", label: "市場調査" },
  { id: "user-researcher", label: "ユーザー調査" },
  { id: "tech-evaluator", label: "技術評価" },
  { id: "research-synthesizer", label: "統合分析" },
];

export function ResearchPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycle();
  const workflow = useWorkflowRun("research", projectSlug ?? "");
  const researchAgents = lc.blueprints.research.team.length > 0
    ? lc.blueprints.research.team.map((agent) => ({ id: agent.id, label: agent.label }))
    : RESEARCH_AGENTS;
  const [competitorUrls, setCompetitorUrls] = useState<string[]>([]);
  const [newUrl, setNewUrl] = useState("");
  const [depth, setDepth] = useState<"quick" | "standard" | "deep">("standard");
  const syncedRunRef = useRef<string | null>(null);

  // Handle workflow completion
  useEffect(() => {
    if (workflow.status !== "completed" || !workflow.runId || !projectSlug) return;
    if (syncedRunRef.current === workflow.runId) return;
    syncedRunRef.current = workflow.runId;
    void lifecycleApi.syncPhaseRun(projectSlug, "research", workflow.runId).then(({ project }) => {
      lc.applyProject(project);
    });
  }, [workflow.runId, workflow.status, projectSlug, lc]);

  const runResearch = () => {
    if (!lc.spec.trim()) return;
    lc.advancePhase("research");
    workflow.start({
      spec: lc.spec,
      competitor_urls: competitorUrls,
      depth,
    });
  };

  const addUrl = () => {
    if (newUrl.trim()) {
      setCompetitorUrls([...competitorUrls, newUrl.trim()]);
      setNewUrl("");
    }
  };

  const goNext = () => {
    navigate(`/p/${projectSlug}/lifecycle/planning`);
  };

  const isRunning = workflow.status === "starting" || workflow.status === "running";

  // Input state
  if (!lc.research && !isRunning && workflow.status !== "failed") {
    return (
      <div className="flex h-full flex-col">
        <div className="border-b border-border px-6 py-4">
          <h1 className="flex items-center gap-2 text-lg font-bold text-foreground">
            <Search className="h-5 w-5 text-primary" />
            市場調査・競合分析
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            プロダクトアイデアを入力すると、AIが市場調査と競合分析を実施します
          </p>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          <div className="mx-auto max-w-2xl space-y-6">
            {/* Spec input */}
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">プロダクト概要</label>
              <textarea
                value={lc.spec}
                onChange={(e) => lc.setSpec(e.target.value)}
                placeholder="例: AIエージェントを活用した自律開発プラットフォーム。調査から企画、開発、デプロイまでを一気通貫で管理..."
                rows={5}
                className="w-full rounded-lg border border-border bg-background p-4 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                autoFocus
              />
            </div>

            {/* Competitor URLs */}
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">競合URL（任意）</label>
              <div className="flex gap-2">
                <input
                  value={newUrl}
                  onChange={(e) => setNewUrl(e.target.value)}
                  placeholder="https://competitor.com"
                  className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                  onKeyDown={(e) => e.key === "Enter" && addUrl()}
                />
                <button onClick={addUrl} className="rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
                  <Plus className="h-4 w-4" />
                </button>
              </div>
              {competitorUrls.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {competitorUrls.map((url, i) => (
                    <Badge key={i} variant="secondary" className="gap-1 pr-1">
                      <Globe className="h-3 w-3" />{new URL(url).hostname}
                      <button onClick={() => setCompetitorUrls(competitorUrls.filter((_, j) => j !== i))} className="ml-0.5 rounded-full hover:bg-foreground/10 p-0.5">
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                </div>
              )}
            </div>

            {/* Depth */}
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">調査深度</label>
              <div className="grid grid-cols-3 gap-2">
                {([["quick", "Quick", "基本的な競合分析"], ["standard", "Standard", "市場分析 + 技術評価"], ["deep", "Deep", "包括的調査 + SWOT"]] as const).map(([val, label, desc]) => (
                  <button
                    key={val}
                    onClick={() => setDepth(val)}
                    className={cn(
                      "rounded-lg border p-3 text-left transition-colors",
                      depth === val ? "border-primary bg-primary/5" : "border-border hover:bg-accent/50",
                    )}
                  >
                    <p className="text-sm font-medium text-foreground">{label}</p>
                    <p className="text-[11px] text-muted-foreground">{desc}</p>
                  </button>
                ))}
              </div>
            </div>

            <Button
              onClick={runResearch}
              disabled={!lc.spec.trim()}
              className="w-full gap-2"
              size="lg"
            >
              <Search className="h-4 w-4" />
              調査を開始
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (workflow.status === "failed") {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-md w-full space-y-4 text-center">
          <AlertCircle className="h-12 w-12 text-destructive mx-auto" />
          <h2 className="text-lg font-bold text-foreground">エラーが発生しました</h2>
          <p className="text-sm text-muted-foreground">{workflow.error ?? "ワークフローの実行に失敗しました"}</p>
          <Button variant="default" onClick={() => workflow.reset()}>
            やり直す
          </Button>
        </div>
      </div>
    );
  }

  // Running state
  if (isRunning) {
    return (
      <AgentProgressView
        agents={researchAgents}
        progress={workflow.agentProgress}
        elapsedMs={workflow.elapsedMs}
        title="市場調査中..."
        subtitle="Research swarm が競合・市場・ユーザー・技術の観点から並列に証拠を集めています"
      />
    );
  }

  // Results
  const r = lc.research!;
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-col gap-3 border-b border-border px-6 py-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="flex items-center gap-2 text-lg font-bold text-foreground">
          <Check className="h-5 w-5 text-success" />
          調査結果
        </h1>
        <button onClick={goNext} className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors">
          企画へ進む <ArrowRight className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-5xl space-y-6">
          {/* Market overview */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground mb-2">
                <BarChart3 className="h-4 w-4" /> 市場規模
              </div>
              <p className="text-sm text-foreground">{r.market_size}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground mb-2">
                <Zap className="h-4 w-4" /> 技術実現性
              </div>
              <div className="flex items-center gap-2">
                <div className="h-2 flex-1 rounded-full bg-muted overflow-hidden">
                  <div className="h-full rounded-full bg-success" style={{ width: `${r.tech_feasibility.score * 100}%` }} />
                </div>
                <span className="text-sm font-bold text-foreground">{(r.tech_feasibility.score * 100).toFixed(0)}%</span>
              </div>
              <p className="mt-1 text-[11px] text-muted-foreground">{r.tech_feasibility.notes}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground mb-2">
                <TrendingUp className="h-4 w-4" /> 競合数
              </div>
              <p className="text-3xl font-bold text-foreground">{r.competitors.length}</p>
            </div>
          </div>

          {/* Competitors */}
          <div>
            <h3 className="text-sm font-bold text-foreground mb-3">競合分析</h3>
            <div className="grid gap-3 lg:grid-cols-3">
              {r.competitors.map((c, i) => (
                <div key={i} className="rounded-xl border border-border bg-card p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="font-bold text-foreground">{c.name}</h4>
                    <Badge variant="outline" className="text-[10px]">{c.pricing}</Badge>
                  </div>
                  <p className="text-[11px] text-muted-foreground">{c.target}</p>
                  <div>
                    <p className="text-[10px] font-medium text-success mb-1">強み</p>
                    {c.strengths.map((s, j) => (
                      <p key={j} className="text-xs text-foreground flex items-start gap-1"><Check className="h-3 w-3 mt-0.5 text-success shrink-0" />{s}</p>
                    ))}
                  </div>
                  <div>
                    <p className="text-[10px] font-medium text-destructive mb-1">弱み</p>
                    {c.weaknesses.map((w, j) => (
                      <p key={j} className="text-xs text-foreground flex items-start gap-1"><ShieldAlert className="h-3 w-3 mt-0.5 text-destructive shrink-0" />{w}</p>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* SWOT-like grid */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <div className="rounded-xl border-2 border-success/20 bg-success/5 p-4">
              <h3 className="flex items-center gap-1.5 text-sm font-bold text-success mb-2"><Lightbulb className="h-4 w-4" /> 機会</h3>
              {r.opportunities.map((o, i) => <p key={i} className="text-xs text-foreground py-0.5">• {o}</p>)}
            </div>
            <div className="rounded-xl border-2 border-destructive/20 bg-destructive/5 p-4">
              <h3 className="flex items-center gap-1.5 text-sm font-bold text-destructive mb-2"><ShieldAlert className="h-4 w-4" /> 脅威</h3>
              {r.threats.map((t, i) => <p key={i} className="text-xs text-foreground py-0.5">• {t}</p>)}
            </div>
          </div>

          {/* Trends */}
          <div className="rounded-xl border border-border bg-card p-4">
            <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground mb-3"><TrendingUp className="h-4 w-4 text-primary" /> 市場トレンド</h3>
            <div className="flex flex-wrap gap-2">
              {r.trends.map((t, i) => (
                <Badge key={i} variant="secondary" className="text-xs">{t}</Badge>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
