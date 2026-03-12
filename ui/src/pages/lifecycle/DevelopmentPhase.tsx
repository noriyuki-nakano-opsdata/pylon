import { useState, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Loader2, Check, ArrowRight, Rocket,
  Flag, RefreshCw, Bot, CircleCheck, CircleX, Eye,
  ExternalLink, Zap, BarChart3, AlertCircle,
  Maximize2, Minimize2, FileCode2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { useLifecycle } from "./LifecycleContext";
import { useWorkflowRun } from "@/hooks/useWorkflowRun";
import { lifecycleApi } from "@/api/lifecycle";

/* ── Utility: extract CSS / JS / body sections from a single HTML string ── */
interface HtmlSections {
  css: string;
  js: string;
  body: string;
  full: string;
}

function extractSections(html: string): HtmlSections {
  const cssMatch = html.match(/<style[^>]*>([\s\S]*?)<\/style>/gi);
  const jsMatch = html.match(/<script(?![^>]*src)[^>]*>([\s\S]*?)<\/script>/gi);
  const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);

  const css = cssMatch ? cssMatch.map(s => s.replace(/<\/?style[^>]*>/gi, "")).join("\n\n") : "";
  const js = jsMatch ? jsMatch.map(s => s.replace(/<\/?script[^>]*>/gi, "")).join("\n\n") : "";
  const body = bodyMatch ? bodyMatch[1] : "";

  return { css, js, body, full: html };
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  return kb < 1024 ? `${kb.toFixed(1)} KB` : `${(kb / 1024).toFixed(2)} MB`;
}

function estimateQuality(sections: HtmlSections): { label: string; score: number; details: string[] } {
  const details: string[] = [];
  let score = 50;

  if (sections.css.length > 0) { score += 15; details.push("CSS 分離済み"); }
  if (sections.js.length > 0) { score += 10; details.push("JS あり"); }
  if (sections.body.includes("aria-")) { score += 10; details.push("ARIA 属性あり"); }
  if (sections.full.includes("<meta name=\"viewport\"")) { score += 10; details.push("レスポンシブ対応"); }
  if (sections.full.includes("lang=")) { score += 5; details.push("言語属性あり"); }

  const label = score >= 80 ? "良好" : score >= 60 ? "普通" : "基本";
  return { label, score: Math.min(score, 100), details };
}

type CodeTab = "full" | "css" | "js" | "body";

export function DevelopmentPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycle();
  const workflow = useWorkflowRun("development", projectSlug ?? "");
  const buildTeam = lc.blueprints.development.team.length > 0
    ? lc.blueprints.development.team
    : [
        { id: "planner", label: "ビルド設計", role: "作業分解", autonomy: "A2", tools: [], skills: [] },
        { id: "frontend-builder", label: "フロントエンド", role: "UI 実装", autonomy: "A2", tools: [], skills: [] },
        { id: "backend-builder", label: "バックエンド", role: "Domain 設計", autonomy: "A2", tools: [], skills: [] },
        { id: "integrator", label: "インテグレーター", role: "統合", autonomy: "A2", tools: [], skills: [] },
        { id: "reviewer", label: "リリースレビュー", role: "品質判定", autonomy: "A2", tools: [], skills: [] },
      ];
  const syncedRunRef = useRef<string | null>(null);

  // Sync terminal workflow runs back into the lifecycle project.
  useEffect(() => {
    if ((workflow.status !== "completed" && workflow.status !== "failed") || !workflow.runId || !projectSlug) return;
    if (syncedRunRef.current === workflow.runId) return;
    syncedRunRef.current = workflow.runId;
    void lifecycleApi.syncPhaseRun(projectSlug, "development", workflow.runId).then(({ project }) => {
      lc.applyProject(project);
    });
  }, [workflow.runId, workflow.status, projectSlug, lc]);

  // Track build iteration from workflow state
  useEffect(() => {
    if (workflow.state._build_iteration != null) {
      const iteration = Number(workflow.state._build_iteration) || 1;
      lc.setBuildIteration(iteration);
    }
    if (workflow.state.review) {
      const review = workflow.state.review as Record<string, unknown>;
      if (Array.isArray(review.milestone_results)) {
        lc.setMilestoneResults(review.milestone_results as any);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow.state]);

  const isBuilding = workflow.status === "starting" || workflow.status === "running";

  const startBuild = () => {
    lc.advancePhase("development");
    workflow.start({
      spec: lc.spec,
      selected_features: lc.features
        .filter((f) => f.selected)
        .map((f) => ({ feature: f.feature, priority: f.priority, category: f.category })),
      analysis: lc.analysis,
      design: lc.selectedDesignId
        ? lc.designVariants.find((v) => v.id === lc.selectedDesignId)
        : undefined,
      milestones: lc.milestones.map((m) => ({
        id: m.id,
        name: m.name,
        criteria: m.criteria,
      })),
    });
  };

  const goNext = () => {
    lc.completePhase("development");
    navigate(`/p/${projectSlug}/lifecycle/deploy`);
  };

  // Error view
  if (workflow.status === "failed") {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-md w-full space-y-4 text-center">
          <AlertCircle className="h-12 w-12 text-destructive mx-auto" />
          <h2 className="text-lg font-bold text-foreground">開発エラー</h2>
          <p className="text-sm text-muted-foreground">{workflow.error ?? "ワークフローの実行に失敗しました"}</p>
          <button onClick={() => workflow.reset()} className="rounded-lg bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">やり直す</button>
        </div>
      </div>
    );
  }

  // Pre-build view
  if (!isBuilding && !lc.buildCode) {
    const selectedFeatureCount = lc.features.filter((f) => f.selected).length;
    const selectedDesign = lc.designVariants.find((variant) => variant.id === lc.selectedDesignId);
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-4xl w-full space-y-6">
          <div className="text-center">
            <Rocket className="h-12 w-12 text-primary mx-auto" />
            <h2 className="text-xl font-bold text-foreground">自律開発</h2>
            <p className="text-sm text-muted-foreground">
              {lc.milestones.length > 0
                ? `${lc.milestones.length}個のマイルストーン達成まで、AIエージェントが自律的に改善を繰り返します`
                : "AIエージェントがプロダクトを構築します"}
            </p>
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
            <div className="space-y-4 rounded-xl border border-border bg-card p-5 text-left">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div className="rounded-lg border border-border bg-background p-3">
                  <p className="text-xs text-muted-foreground">機能数</p>
                  <p className="text-lg font-bold text-foreground">{selectedFeatureCount}</p>
                </div>
                <div className="rounded-lg border border-border bg-background p-3">
                  <p className="text-xs text-muted-foreground">マイルストーン</p>
                  <p className="text-lg font-bold text-foreground">{lc.milestones.length}</p>
                </div>
                <div className="rounded-lg border border-border bg-background p-3">
                  <p className="text-xs text-muted-foreground">最大イテレーション</p>
                  <p className="text-lg font-bold text-foreground">{lc.milestones.length > 0 ? 5 : 1}</p>
                </div>
              </div>

              <div className="rounded-lg border border-border bg-background p-4">
                <p className="text-xs font-medium text-muted-foreground mb-2">引き継ぎサマリー</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <p className="text-xs text-muted-foreground">承認状態</p>
                    <p className="mt-1 text-sm font-medium text-foreground">
                      {lc.approvalStatus === "approved" ? "承認済み" : "未承認"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">選択デザイン</p>
                    <p className="mt-1 text-sm font-medium text-foreground">
                      {selectedDesign ? `${selectedDesign.pattern_name} / ${selectedDesign.model}` : "未選択"}
                    </p>
                  </div>
                </div>
                <p className="mt-3 text-sm text-muted-foreground">
                  設計意図、選択機能、マイルストーンをまとめてビルドチームに渡し、レビュアーが品質判定まで閉じます。
                </p>
              </div>

              <div className="rounded-lg border border-border bg-background p-4">
                <p className="text-xs font-medium text-muted-foreground mb-3">エージェントチーム</p>
                <div className="flex flex-wrap justify-center gap-3">
                  {buildTeam.map((agent, i, arr) => (
                    <div key={agent.id} className="flex items-center gap-2">
                      <div className="flex flex-col items-center">
                        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                          <Bot className="h-5 w-5 text-primary" />
                        </div>
                        <p className="mt-1 text-[10px] font-medium text-foreground">{agent.label}</p>
                        <p className="text-[9px] text-muted-foreground">{agent.role}</p>
                      </div>
                      {i < arr.length - 1 && <ArrowRight className="mt-[-16px] h-3 w-3 text-muted-foreground" />}
                    </div>
                  ))}
                  {lc.milestones.length > 0 && <RefreshCw className="ml-1 mt-[-16px] h-3 w-3 text-primary" />}
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-border bg-card p-5 text-left">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground/70">開始前チェック</p>
              <h3 className="mt-2 text-base font-semibold text-foreground">開始前チェック</h3>
              <div className="mt-4 space-y-2">
                {[
                  { label: "選択機能が存在する", done: selectedFeatureCount > 0 },
                  { label: "比較済みのデザインが選択されている", done: selectedDesign != null },
                  { label: "承認ゲートを通過している", done: lc.approvalStatus === "approved" },
                ].map((item) => (
                  <div key={item.label} className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm">
                    <span className={cn("h-2.5 w-2.5 rounded-full", item.done ? "bg-success" : "bg-warning")} />
                    <span className={item.done ? "text-foreground" : "text-muted-foreground"}>{item.label}</span>
                  </div>
                ))}
              </div>
              {lc.approvalStatus !== "approved" && (
                <p className="mt-3 rounded-lg border border-warning/20 bg-warning/5 px-3 py-2 text-xs text-warning">
                  本来は承認後に進むフェーズです。設計確認が未完了なら先に承認へ戻してください。
                </p>
              )}
              <div className="mt-4 flex gap-2">
                <button onClick={() => navigate(`/p/${projectSlug}/lifecycle/approval`)} className="flex-1 rounded-lg border border-border px-4 py-3 text-sm font-medium text-foreground hover:bg-accent transition-colors">
                  承認に戻る
                </button>
                <button
                  onClick={startBuild}
                  disabled={lc.approvalStatus !== "approved" || selectedFeatureCount === 0 || selectedDesign == null}
                  className={cn(
                    "flex-1 flex items-center justify-center gap-2 rounded-lg py-3 text-sm font-medium transition-colors",
                    lc.approvalStatus === "approved" && selectedFeatureCount > 0 && selectedDesign != null
                      ? "bg-primary text-primary-foreground hover:bg-primary/90"
                      : "bg-muted text-muted-foreground cursor-not-allowed",
                  )}
                >
                  <Zap className="h-4 w-4" /> 開発を開始
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Building view
  if (isBuilding) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="w-full max-w-3xl space-y-6">
          <div className="text-center">
            <Rocket className="h-12 w-12 text-primary mx-auto animate-bounce" />
            <h2 className="text-xl font-bold text-foreground mt-3">AIが自律開発中...</h2>
            <p className="text-sm text-muted-foreground">
              {lc.milestones.length > 0
                ? `マイルストーン達成まで自律改善（イテレーション ${lc.buildIteration + 1}/5）`
                : "プロダクトを構築しています"}
            </p>
            <p className="text-xs text-muted-foreground font-mono mt-1">
              経過時間: {Math.floor(workflow.elapsedMs / 60000)}:{(Math.floor(workflow.elapsedMs / 1000) % 60).toString().padStart(2, "0")}
            </p>
          </div>

          <div className={cn("grid gap-6", lc.milestones.length > 0 ? "grid-cols-1 lg:grid-cols-2" : "grid-cols-1 max-w-md mx-auto")}>
            {/* Agent progress */}
            <div className="space-y-2">
              <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">エージェント進捗</h3>
              {buildTeam.map((agent) => {
                const p = workflow.agentProgress.find((a) => a.nodeId === agent.id || a.agent === agent.id);
                const status = p?.status ?? "pending";
                return (
                  <div key={agent.id} className={cn("flex items-center gap-2 rounded-md px-4 py-2.5 text-sm transition-all",
                    status === "completed" ? "text-success" : status === "running" ? "text-primary font-medium" : "text-muted-foreground/50",
                  )}>
                    {status === "completed" ? <Check className="h-4 w-4" /> : status === "running" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />}
                    {agent.label}
                  </div>
                );
              })}
            </div>

            {/* Milestone progress */}
            {lc.milestones.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                  <Flag className="inline h-3 w-3 mr-1" /> マイルストーン進捗
                </h3>
                {lc.milestones.map((ms) => {
                  const result = lc.milestoneResults.find((r) => r.id === ms.id);
                  const isSatisfied = result?.status === "satisfied";
                  const isChecked = result != null;
                  return (
                    <div key={ms.id} className={cn("flex items-start gap-2 rounded-md border px-3 py-2 text-sm",
                      isSatisfied ? "border-success/30 bg-success/5 text-success" :
                      isChecked ? "border-destructive/30 bg-destructive/5 text-destructive" :
                      "border-border text-muted-foreground",
                    )}>
                      {isSatisfied ? <CircleCheck className="h-4 w-4 mt-0.5 shrink-0" /> :
                       isChecked ? <CircleX className="h-4 w-4 mt-0.5 shrink-0" /> :
                       <Loader2 className="h-4 w-4 mt-0.5 shrink-0 animate-spin" />}
                      <div>
                        <p className="font-medium">{ms.name}</p>
                        {result?.reason && <p className="text-xs mt-0.5 opacity-70">{result.reason}</p>}
                      </div>
                    </div>
                  );
                })}
                {lc.buildIteration > 0 && (
                  <div className="flex items-center gap-2 rounded-md bg-primary/5 border border-primary/20 px-3 py-2 text-xs text-primary mt-2">
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    改善イテレーション {lc.buildIteration + 1} 実行中...
                  </div>
                )}

                {/* Agent flow */}
                <div className="mt-3 rounded-md border border-border bg-card p-3">
                  <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">エージェント連携</p>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    {buildTeam.map((agent, index) => (
                      <div key={agent.id} className="flex items-center gap-2">
                        <div className={cn("flex items-center gap-1 rounded-full px-2 py-1", index === buildTeam.length - 1 && lc.buildIteration > 0 ? "bg-primary/10 text-primary" : "bg-accent")}>
                          <Bot className="h-3 w-3" /> {agent.label}
                        </div>
                        {index < buildTeam.length - 1 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
                      </div>
                    ))}
                    {lc.buildIteration > 0 && <RefreshCw className="h-3 w-3 text-primary" />}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // Complete view
  return <BuildCompleteView onNext={goNext} />;
}

function BuildCompleteView({ onNext }: { onNext: () => void }) {
  const lc = useLifecycle();
  const [viewMode, setViewMode] = useState<"preview" | "code">("preview");
  const [codeTab, setCodeTab] = useState<CodeTab>("full");
  const [fullscreen, setFullscreen] = useState(false);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  const sections = lc.buildCode ? extractSections(lc.buildCode) : null;
  const quality = sections ? estimateQuality(sections) : null;

  useEffect(() => {
    if (lc.buildCode) {
      const blob = new Blob([lc.buildCode], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      setBlobUrl(url);
      return () => URL.revokeObjectURL(url);
    }
  }, [lc.buildCode]);

  if (!lc.buildCode || !sections || !quality) return null;

  const codeTabItems: { key: CodeTab; label: string; charCount: number }[] = [
    { key: "full", label: "HTML 全体", charCount: sections.full.length },
    { key: "css", label: "CSS", charCount: sections.css.length },
    { key: "js", label: "JavaScript", charCount: sections.js.length },
    { key: "body", label: "構造", charCount: sections.body.length },
  ];

  const activeCode = sections[codeTab];

  // Fullscreen preview
  if (fullscreen) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col bg-background">
        <div className="flex items-center gap-3 border-b border-border px-4 py-2">
          <span className="text-sm font-medium text-foreground">フルスクリーンプレビュー</span>
          <div className="flex-1" />
          {blobUrl && (
            <a href={blobUrl} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-primary hover:underline">
              <ExternalLink className="h-3.5 w-3.5" /> 新しいタブ
            </a>
          )}
          <button onClick={() => setFullscreen(false)} className="flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent/80">
            <Minimize2 className="h-3.5 w-3.5" /> 閉じる
          </button>
        </div>
        <iframe srcDoc={lc.buildCode} className="flex-1 border-0 bg-white" sandbox="allow-scripts allow-same-origin" title="フルスクリーンプレビュー" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* ── Header bar ── */}
      <div className="flex items-center gap-3 border-b border-border px-6 py-3">
        <div className="flex items-center gap-2">
          <Check className="h-4 w-4 text-success" />
          <span className="text-sm font-medium text-foreground">ビルド完了</span>
        </div>
        <Badge variant="secondary" className="text-[10px]">{formatBytes(new Blob([lc.buildCode]).size)}</Badge>
        {lc.buildCost > 0 && <Badge variant="secondary" className="text-[10px]">${lc.buildCost.toFixed(4)}</Badge>}
        {lc.buildIteration > 0 && <Badge variant="outline" className="text-[10px]">{lc.buildIteration} 回反復</Badge>}
        {lc.milestoneResults.length > 0 && (
          <Badge variant="outline" className="text-[10px]">
            {lc.milestoneResults.filter((r) => r.status === "satisfied").length}/{lc.milestoneResults.length} マイルストーン
          </Badge>
        )}
        {/* Quality badge */}
        <Badge
          variant="outline"
          className={cn("text-[10px]",
            quality.score >= 80 ? "border-success/50 text-success" :
            quality.score >= 60 ? "border-yellow-500/50 text-yellow-600" :
            "border-muted-foreground/50 text-muted-foreground",
          )}
          title={quality.details.join(", ")}
        >
          <BarChart3 className="inline h-3 w-3 mr-0.5" />
          {quality.label} ({quality.score})
        </Badge>
        <div className="flex-1" />
        {/* View mode toggle */}
        <div className="flex gap-1">
          <button onClick={() => setViewMode("preview")} className={cn("rounded-md px-3 py-1.5 text-xs font-medium", viewMode === "preview" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground")}>
            <Eye className="inline h-3.5 w-3.5 mr-1" />プレビュー
          </button>
          <button onClick={() => setViewMode("code")} className={cn("rounded-md px-3 py-1.5 text-xs font-medium", viewMode === "code" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground")}>
            <FileCode2 className="inline h-3.5 w-3.5 mr-1" />コード
          </button>
        </div>
        {viewMode === "preview" && (
          <button onClick={() => setFullscreen(true)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground" title="フルスクリーン">
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
        )}
        {blobUrl && (
          <a href={blobUrl} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-primary hover:underline">
            <ExternalLink className="h-3.5 w-3.5" /> 新しいタブ
          </a>
        )}
        <button onClick={onNext} className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90">
          デプロイへ <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* ── Content area ── */}
      <div className="flex-1 overflow-hidden">
        {viewMode === "preview" ? (
          <iframe srcDoc={lc.buildCode} className="h-full w-full border-0 bg-white" sandbox="allow-scripts allow-same-origin" title="プレビュー" />
        ) : (
          <div className="flex h-full flex-col">
            {/* Code section tabs */}
            <div className="flex items-center gap-1 border-b border-border bg-card px-4 py-1.5">
              {codeTabItems.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setCodeTab(tab.key)}
                  className={cn(
                    "rounded-md px-3 py-1 text-xs font-medium transition-colors",
                    codeTab === tab.key
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
                  )}
                >
                  {tab.label}
                  <span className="ml-1.5 text-[10px] opacity-60">
                    ({tab.charCount.toLocaleString()} chars)
                  </span>
                </button>
              ))}
            </div>
            {/* Code content */}
            <div className="flex-1 overflow-auto bg-zinc-950">
              <pre className="p-4">
                <code className="text-xs font-mono text-zinc-200 whitespace-pre-wrap break-words">
                  {activeCode || "(empty)"}
                </code>
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
