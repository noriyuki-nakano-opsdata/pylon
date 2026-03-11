import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Search, Check, ArrowRight, Globe, TrendingUp,
  ShieldAlert, Lightbulb, BarChart3, Zap, Plus, X, AlertCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useLifecycle } from "./LifecycleContext";
import { lifecycleApi } from "@/api/lifecycle";
import { AgentProgressView } from "@/components/lifecycle/AgentProgressView";

const RESEARCH_AGENTS = [
  { id: "competitor-analyst", label: "競合分析" },
  { id: "market-researcher", label: "市場調査" },
  { id: "user-researcher", label: "ユーザー調査" },
  { id: "tech-evaluator", label: "技術評価" },
  { id: "research-synthesizer", label: "統合分析" },
];

function formatCompetitorHost(raw: string): string {
  try {
    return new URL(raw).hostname || raw;
  } catch {
    return raw;
  }
}

export function ResearchPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycle();
  const researchAgents = lc.blueprints.research.team.length > 0
    ? lc.blueprints.research.team.map((agent) => ({ id: agent.id, label: agent.label }))
    : RESEARCH_AGENTS;
  const [newUrl, setNewUrl] = useState("");
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [isLaunching, setIsLaunching] = useState(false);
  const competitorUrls = lc.researchConfig.competitorUrls;
  const depth = lc.researchConfig.depth;

  const runResearch = () => {
    if (!lc.spec.trim() || !projectSlug) return;
    setLaunchError(null);
    setIsLaunching(true);
    const researchConfig = {
      competitorUrls,
      depth,
    };
    lc.setOrchestrationMode("autonomous");
    lc.setAutonomyLevel("A4");
    lc.setResearchConfig(researchConfig);
    void lifecycleApi.saveProject(
      projectSlug,
      {
        spec: lc.spec,
        orchestrationMode: "autonomous",
        autonomyLevel: "A4",
        researchConfig,
      },
      { autoRun: true, maxSteps: 8 },
    )
      .then((response) => {
        lc.applyProject(response.project);
      })
      .catch((err) => {
        setLaunchError(err instanceof Error ? err.message : "自律実行の開始に失敗しました");
      })
      .finally(() => {
        setIsLaunching(false);
      });
  };

  const addUrl = () => {
    if (newUrl.trim()) {
      lc.setResearchConfig({
        ...lc.researchConfig,
        competitorUrls: [...competitorUrls, newUrl.trim()],
      });
      setNewUrl("");
    }
  };

  const goNext = () => {
    navigate(`/p/${projectSlug}/lifecycle/planning`);
  };

  const isRunning = isLaunching;
  const research = lc.research;

  const stableResearch = research ?? {
    competitors: [],
    market_size: "調査結果を取得できませんでした",
    trends: [],
    opportunities: [],
    threats: [],
    tech_feasibility: {
      score: 0,
      notes: "データが不完全なため、調査結果を再取得してください。",
    },
    claims: [],
    evidence: [],
    dissent: [],
    open_questions: [],
    winning_theses: [],
    confidence_summary: {
      average: 0,
      floor: 0,
      accepted: 0,
    },
  };
  const r = stableResearch;

  // Input state
  if (!lc.research && !isRunning && !launchError) {
    return (
      <div className="flex h-full flex-col">
        <div className="border-b border-border px-6 py-4">
          <h1 className="flex items-center gap-2 text-lg font-bold text-foreground">
            <Search className="h-5 w-5 text-primary" />
            市場調査・競合分析
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            プロダクトアイデアを入力すると、A4 自律モードで調査からリリース準備までを一気通貫で進めます
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
                      <Globe className="h-3 w-3" />{formatCompetitorHost(url)}
                      <button
                        onClick={() => lc.setResearchConfig({
                          ...lc.researchConfig,
                          competitorUrls: competitorUrls.filter((_, j) => j !== i),
                        })}
                        className="ml-0.5 rounded-full hover:bg-foreground/10 p-0.5"
                      >
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
                {([["quick", "Quick", "競合2-3社の基本分析（最速・低コスト）"], ["standard", "Standard", "競合3-5社 + 市場調査 + 技術評価"], ["deep", "Deep", "競合5-8社 + 包括的SWOT + 戦略提言（最高品質）"]] as const).map(([val, label, desc]) => (
                  <button
                    key={val}
                    onClick={() => lc.setResearchConfig({ ...lc.researchConfig, depth: val })}
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
              disabled={!lc.spec.trim() || isLaunching}
              className="w-full gap-2"
              size="lg"
            >
              <Search className="h-4 w-4" />
              完全自律で開始
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (launchError) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-md w-full space-y-4 text-center">
          <AlertCircle className="h-12 w-12 text-destructive mx-auto" />
          <h2 className="text-lg font-bold text-foreground">エラーが発生しました</h2>
          <p className="text-sm text-muted-foreground">{launchError}</p>
          <Button variant="default" onClick={() => setLaunchError(null)}>
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
        progress={researchAgents.map((agent) => ({ nodeId: agent.id, agent: agent.label, status: "running" as const }))}
        elapsedMs={0}
        title="Lifecycle を自律実行中..."
        subtitle="Research から release gate までを A4 full-autonomy で連続実行しています"
      />
    );
  }

  // Results
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
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
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
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground mb-2">
                <Check className="h-4 w-4" /> 判定信頼度
              </div>
              <p className="text-3xl font-bold text-foreground">{((r.confidence_summary?.average ?? 0) * 100).toFixed(0)}%</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                accepted {r.confidence_summary?.accepted ?? 0} / claims {r.claims?.length ?? 0}
              </p>
            </div>
          </div>

          {!!r.winning_theses?.length && (
            <div className="rounded-2xl border border-primary/20 bg-primary/5 p-5">
              <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-primary/80">Winning theses</p>
              <div className="mt-3 grid gap-2 lg:grid-cols-3">
                {r.winning_theses.map((thesis, index) => (
                  <div key={index} className="rounded-xl border border-primary/10 bg-background/70 p-3 text-sm text-foreground">
                    {thesis}
                  </div>
                ))}
              </div>
              {r.judge_summary && <p className="mt-3 text-xs text-muted-foreground">{r.judge_summary}</p>}
            </div>
          )}

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

          {!!r.user_research && (
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-border bg-card p-4">
                <h3 className="text-sm font-bold text-foreground mb-3">ユーザーシグナル</h3>
                <div className="space-y-2">
                  {r.user_research.signals.map((signal, index) => (
                    <p key={index} className="text-xs text-foreground">• {signal}</p>
                  ))}
                </div>
              </div>
              <div className="rounded-xl border border-border bg-card p-4">
                <h3 className="text-sm font-bold text-foreground mb-3">痛みと friction</h3>
                <div className="space-y-2">
                  {r.user_research.pain_points.map((pain, index) => (
                    <p key={index} className="text-xs text-foreground">• {pain}</p>
                  ))}
                </div>
              </div>
            </div>
          )}

          {!!r.claims?.length && (
            <div>
              <h3 className="text-sm font-bold text-foreground mb-3">Claim ledger</h3>
              <div className="grid gap-3 lg:grid-cols-2">
                {r.claims.map((claim) => (
                  <div key={claim.id} className="rounded-xl border border-border bg-card p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-foreground">{claim.statement}</p>
                        <p className="mt-1 text-[11px] text-muted-foreground">{claim.owner} · {claim.category}</p>
                      </div>
                      <Badge variant={claim.status === "accepted" ? "default" : "secondary"} className="shrink-0 text-[10px]">
                        {claim.status}
                      </Badge>
                    </div>
                    <div className="mt-3 flex items-center gap-3 text-[11px] text-muted-foreground">
                      <span>confidence {(claim.confidence * 100).toFixed(0)}%</span>
                      <span>evidence {claim.evidence_ids.length}</span>
                      <span>counter {claim.counterevidence_ids.length}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground mb-3">
                <ShieldAlert className="h-4 w-4 text-destructive" /> Dissent
              </h3>
              <div className="space-y-2">
                {(r.dissent ?? []).map((item) => (
                  <div key={item.id} className="rounded-lg border border-border/80 bg-background px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-medium text-foreground">{item.argument}</p>
                      <Badge variant="outline" className="text-[10px]">{item.severity}</Badge>
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {item.resolved ? "resolved" : "open"} · {item.recommended_test ?? "追加検証を定義"}
                    </p>
                  </div>
                ))}
                {!(r.dissent ?? []).length && <p className="text-xs text-muted-foreground">重大な dissent はありません。</p>}
              </div>
            </div>
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground mb-3">
                <AlertCircle className="h-4 w-4 text-primary" /> Open questions
              </h3>
              <div className="space-y-2">
                {(r.open_questions ?? []).map((question, index) => (
                  <p key={index} className="rounded-lg border border-border/80 bg-background px-3 py-2 text-xs text-foreground">
                    {question}
                  </p>
                ))}
                {!(r.open_questions ?? []).length && <p className="text-xs text-muted-foreground">未解決の問いはありません。</p>}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
