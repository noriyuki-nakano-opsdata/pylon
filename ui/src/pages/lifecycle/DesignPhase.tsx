import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Palette, ArrowRight, ArrowLeft,
  Eye, Code2, Star, ExternalLink, Zap,
  Monitor, Tablet, Smartphone, BarChart3, AlertCircle,
  ChevronDown, ChevronUp, Maximize2, Minimize2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useLifecycleActions, useLifecycleState } from "./LifecycleContext";
import { useWorkflowRun } from "@/hooks/useWorkflowRun";
import { lifecycleApi } from "@/api/lifecycle";
import { AgentProgressView } from "@/components/lifecycle/AgentProgressView";
import { buildDesignWorkflowInput } from "@/lifecycle/inputs";
import {
  selectPhaseTeam,
  selectSelectedFeatureCount,
} from "@/lifecycle/selectors";
import type { DesignVariant } from "@/types/lifecycle";

const DESIGN_AGENTS = [
  { id: "claude-designer", label: "Claude Sonnet 4.6", role: "案出し", autonomy: "A2", tools: [], skills: [] },
  { id: "openai-designer", label: "GPT-5 Mini", role: "案出し", autonomy: "A2", tools: [], skills: [] },
  { id: "gemini-designer", label: "Gemini 3 Flash", role: "案出し", autonomy: "A2", tools: [], skills: [] },
  { id: "design-evaluator", label: "デザイン審査", role: "評価", autonomy: "A2", tools: [], skills: [] },
];

export function DesignPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycleState();
  const actions = useLifecycleActions();
  const workflow = useWorkflowRun("design", projectSlug ?? "");
  const designAgents = selectPhaseTeam(lc, "design", DESIGN_AGENTS);
  const [previewDevice, setPreviewDevice] = useState<"desktop" | "tablet" | "mobile">("desktop");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [selectError, setSelectError] = useState<string | null>(null);
  const syncedRunRef = useRef<string | null>(null);

  useEffect(() => {
    if ((workflow.status !== "completed" && workflow.status !== "failed") || !workflow.runId || !projectSlug) return;
    if (syncedRunRef.current === workflow.runId) return;
    syncedRunRef.current = workflow.runId;
    void lifecycleApi.syncPhaseRun(projectSlug, "design", workflow.runId).then(({ project }) => {
      actions.applyProject(project);
    });
  }, [actions, workflow.runId, workflow.status, projectSlug]);

  const isGenerating = workflow.status === "starting" || workflow.status === "running";

  const generate = () => {
    actions.advancePhase("design");
    workflow.start(buildDesignWorkflowInput(lc));
  };

  const goNext = () => {
    actions.completePhase("design");
    navigate(`/p/${projectSlug}/lifecycle/approval`);
  };
  const goBack = () => navigate(`/p/${projectSlug}/lifecycle/planning`);

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  const selectDesign = (designId: string) => {
    setSelectError(null);
    if (!projectSlug) {
      actions.selectDesign(designId);
      return;
    }
    // Optimistically update local state
    actions.selectDesign(designId);
    void lifecycleApi.saveProject(projectSlug, { selectedDesignId: designId })
      .then((response) => {
        actions.applyProject(response.project);
      })
      .catch((err) => {
        setSelectError(err instanceof Error ? err.message : "デザインの保存に失敗しました");
      });
  };

  if (lc.designVariants.length === 0 && !isGenerating) {
    const selectedFeatureCount = selectSelectedFeatureCount(lc);
    const planningReady = Boolean(lc.analysis);
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-3xl w-full space-y-6">
          <div className="text-center">
            <Palette className="h-12 w-12 text-primary mx-auto" />
            <h2 className="text-xl font-bold text-foreground">デザインパターン比較</h2>
            <p className="text-sm text-muted-foreground">
              複数のAIモデルが同時にデザインパターンを生成。Side-by-Sideで比較し、ベストを選択できます。
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-[1.4fr_1fr]">
            <div className="rounded-xl border border-border bg-card p-5 text-left">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground/70">引き継ぎサマリー</p>
              <h3 className="mt-2 text-base font-semibold text-foreground">企画からデザインに渡る材料</h3>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <div className="rounded-lg border border-border bg-background p-3">
                  <p className="text-xs text-muted-foreground">分析結果</p>
                  <p className="mt-1 text-lg font-semibold text-foreground">{planningReady ? "準備完了" : "未完了"}</p>
                </div>
                <div className="rounded-lg border border-border bg-background p-3">
                  <p className="text-xs text-muted-foreground">選択機能</p>
                  <p className="mt-1 text-lg font-semibold text-foreground">{selectedFeatureCount}</p>
                </div>
                <div className="rounded-lg border border-border bg-background p-3">
                  <p className="text-xs text-muted-foreground">マイルストーン</p>
                  <p className="mt-1 text-lg font-semibold text-foreground">{lc.milestones.length}</p>
                </div>
              </div>
              <div className="mt-4 rounded-lg border border-border bg-background p-4">
                <p className="text-xs font-medium text-muted-foreground mb-2">生成モデル</p>
                <div className="flex flex-wrap gap-2">
                  {["Claude Sonnet 4.6", "GPT-5 Mini", "Gemini 3 Flash"].map((m) => (
                    <Badge key={m} variant="secondary">{m}</Badge>
                  ))}
                </div>
                <p className="mt-3 text-sm text-muted-foreground">
                  企画で選んだ機能と分析結果をもとに、比較可能な 3 案を一度に生成します。
                </p>
              </div>
            </div>
            <div className="rounded-xl border border-border bg-card p-5 text-left">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground/70">開始前チェック</p>
              <h3 className="mt-2 text-base font-semibold text-foreground">開始前チェック</h3>
              <div className="mt-4 space-y-2">
                {[
                  { label: "企画分析が完了している", done: planningReady },
                  { label: "少なくとも 1 つ機能が選択されている", done: selectedFeatureCount > 0 },
                  { label: "比較対象となる仕様が入力されている", done: lc.spec.trim().length > 0 },
                ].map((item) => (
                  <div key={item.label} className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm">
                    <span className={cn("h-2.5 w-2.5 rounded-full", item.done ? "bg-success" : "bg-warning")} />
                    <span className={item.done ? "text-foreground" : "text-muted-foreground"}>{item.label}</span>
                  </div>
                ))}
              </div>
              <div className="mt-4 flex gap-2">
                <Button variant="outline" onClick={goBack} className="flex-1">
                  企画に戻る
                </Button>
                <Button
                  onClick={generate}
                  disabled={!planningReady || selectedFeatureCount === 0 || lc.spec.trim().length === 0}
                  className="flex-1 gap-2"
                >
                  <Zap className="h-4 w-4" /> 3パターン生成
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (workflow.status === "failed") {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-md w-full space-y-4 text-center">
          <AlertCircle className="h-12 w-12 text-destructive mx-auto" />
          <h2 className="text-lg font-bold text-foreground">デザイン生成エラー</h2>
          <p className="text-sm text-muted-foreground">{workflow.error ?? "ワークフローの実行に失敗しました"}</p>
          <Button variant="default" onClick={() => workflow.reset()}>やり直す</Button>
        </div>
      </div>
    );
  }

  if (isGenerating) {
    return (
      <AgentProgressView
        agents={designAgents}
        progress={workflow.agentProgress}
        elapsedMs={workflow.elapsedMs}
        title="3つのAIモデルが並行生成中..."
        subtitle="デザイン陪審が複数案を生成し、審査員が品質比較を行っています"
      />
    );
  }

  const variants = lc.designVariants;
  const deviceWidth = previewDevice === "desktop" ? "100%" : previewDevice === "tablet" ? "768px" : "375px";

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-6 py-2.5">
        <button onClick={goBack} className="text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" /></button>
        <h1 className="flex items-center gap-2 text-sm font-bold text-foreground">
          <Palette className="h-4 w-4 text-primary" /> デザインパターン比較
        </h1>
        <div className="flex-1" />

        {/* Device switcher */}
        <div className="flex gap-0.5 rounded-md border border-border p-0.5">
          {([["desktop", Monitor], ["tablet", Tablet], ["mobile", Smartphone]] as const).map(([d, Icon]) => (
            <button key={d} onClick={() => setPreviewDevice(d)} className={cn("rounded p-1.5 transition-colors", previewDevice === d ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground")}>
              <Icon className="h-3.5 w-3.5" />
            </button>
          ))}
        </div>

        {expandedId && (
          <button
            onClick={() => setExpandedId(null)}
            className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <Minimize2 className="h-3 w-3" /> 全て表示
          </button>
        )}

        <Button onClick={goNext} size="sm" className="gap-1.5">
          承認へ <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {selectError && (
          <div className="mx-auto max-w-7xl mb-4">
            <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              {selectError}
            </p>
          </div>
        )}
        <div className="mx-auto max-w-7xl space-y-4">
          {variants.map((v) => (
            <DesignCard
              key={v.id}
              variant={v}
              deviceWidth={deviceWidth}
              isSelected={lc.selectedDesignId === v.id}
              isExpanded={expandedId === v.id}
              onSelect={() => selectDesign(v.id)}
              onToggleExpand={() => toggleExpand(v.id)}
            />
          ))}
        </div>

        {/* Score comparison table */}
        <div className="mt-8 max-w-4xl mx-auto">
          <h3 className="flex items-center gap-2 text-sm font-bold text-foreground mb-3">
            <BarChart3 className="h-4 w-4 text-primary" /> スコア比較
          </h3>
          <div className="rounded-xl border border-border bg-card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-accent/30">
                  <th className="text-left px-4 py-2 text-xs font-medium text-muted-foreground">項目</th>
                  {variants.map((v) => (
                    <th key={v.id} className="text-center px-4 py-2 text-xs font-medium text-muted-foreground">{v.model}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(["ux_quality", "code_quality", "performance", "accessibility"] as const).map((key) => {
                  const labels: Record<string, string> = { ux_quality: "UX品質", code_quality: "コード品質", performance: "パフォーマンス", accessibility: "アクセシビリティ" };
                  const best = Math.max(...variants.map((v) => v.scores[key]));
                  return (
                    <tr key={key} className="border-b border-border last:border-0">
                      <td className="px-4 py-2.5 text-xs text-foreground">{labels[key]}</td>
                      {variants.map((v) => {
                        const score = v.scores[key];
                        const isBest = score === best;
                        return (
                          <td key={v.id} className="px-4 py-2.5 text-center">
                            <div className="flex items-center justify-center gap-1.5">
                              <div className="h-1.5 w-16 rounded-full bg-muted overflow-hidden">
                                <div className={cn("h-full rounded-full", isBest ? "bg-success" : "bg-primary/60")} style={{ width: `${score * 100}%` }} />
                              </div>
                              <span className={cn("text-xs font-mono", isBest && "font-bold text-success")}>{(score * 100).toFixed(0)}</span>
                              {isBest && <Star className="h-3 w-3 text-success fill-success" />}
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
                <tr className="bg-accent/20">
                  <td className="px-4 py-2.5 text-xs font-medium text-foreground">コスト</td>
                  {variants.map((v) => (
                    <td key={v.id} className="px-4 py-2.5 text-center text-xs font-mono text-foreground">${v.cost_usd.toFixed(3)}</td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Design Card ── */
function DesignCard({ variant, deviceWidth, isSelected, isExpanded, onSelect, onToggleExpand }: {
  variant: DesignVariant;
  deviceWidth: string;
  isSelected: boolean;
  isExpanded: boolean;
  onSelect: () => void;
  onToggleExpand: () => void;
}) {
  const [showCode, setShowCode] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const openInNewTab = useCallback(() => {
    // Write HTML directly into a new window to avoid blob URL timing issues
    const win = window.open("", "_blank");
    if (win) {
      win.document.open();
      win.document.write(variant.preview_html);
      win.document.close();
    }
  }, [variant.preview_html]);

  // Collapsed height vs expanded height
  const previewHeight = isExpanded ? "calc(100vh - 220px)" : "200px";

  return (
    <div className={cn(
      "rounded-xl border-2 bg-card overflow-hidden transition-all",
      isSelected ? "border-primary shadow-lg shadow-primary/10" : "border-border hover:border-primary/30",
    )}>
      {/* Header — always visible, acts as toggle */}
      <div
        className="flex items-center justify-between border-b border-border px-4 py-2.5 cursor-pointer select-none hover:bg-accent/30 transition-colors"
        onClick={onToggleExpand}
      >
        <div className="flex items-center gap-3">
          {isExpanded ? (
            <ChevronUp className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          )}
          <div>
            <p className="text-sm font-bold text-foreground">{variant.pattern_name}</p>
            <p className="text-[11px] text-muted-foreground">{variant.model}</p>
            {variant.prototype && (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                <Badge variant="secondary" className="text-[10px]">{variant.prototype.screens.length} 画面</Badge>
                <Badge variant="secondary" className="text-[10px]">{variant.prototype.flows.length} フロー</Badge>
                <Badge variant="secondary" className="text-[10px]">{variant.prototype.app_shell.layout}</Badge>
              </div>
            )}
          </div>
          {!isExpanded && (
            <div className="flex gap-2 ml-4">
              {Object.entries(variant.scores).slice(0, 3).map(([key, val]) => {
                const labels: Record<string, string> = { ux_quality: "UX", code_quality: "コード", performance: "性能" };
                return (
                  <div key={key} className="flex items-center gap-1 text-[10px] text-muted-foreground">
                    <div className="h-1 w-8 rounded-full bg-muted overflow-hidden">
                      <div className="h-full rounded-full bg-primary" style={{ width: `${val * 100}%` }} />
                    </div>
                    {labels[key]}: {(val * 100).toFixed(0)}
                  </div>
                );
              })}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Badge variant="outline" className="text-[10px]">${variant.cost_usd.toFixed(3)}</Badge>
          <button onClick={openInNewTab} className="rounded-md p-1 text-muted-foreground hover:text-foreground transition-colors" title="新タブで開く">
            <ExternalLink className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={onToggleExpand}
            className="rounded-md p-1 text-muted-foreground hover:text-foreground transition-colors"
            title={isExpanded ? "折りたたむ" : "展開する"}
          >
            {isExpanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
          <button onClick={onSelect} className={cn(
            "rounded-md px-3 py-1 text-xs font-medium transition-colors",
            isSelected ? "bg-primary text-primary-foreground" : "bg-accent text-foreground hover:bg-primary hover:text-primary-foreground",
          )}>
            {isSelected ? "✓ 選択中" : "選択"}
          </button>
        </div>
      </div>

      {/* Preview — expandable */}
      <div
        className="relative bg-background overflow-hidden transition-all duration-300 ease-in-out"
        style={{ height: previewHeight }}
      >
        {showCode ? (
          <pre className="h-full overflow-auto p-3 text-[10px] text-foreground font-mono whitespace-pre-wrap">{variant.preview_html}</pre>
        ) : (
          <div className="flex justify-center h-full p-2">
            <iframe
              ref={iframeRef}
              srcDoc={variant.preview_html}
              className="h-full border border-border rounded-md bg-white"
              style={{ width: deviceWidth, maxWidth: "100%" }}
              sandbox="allow-scripts allow-same-origin"
              title={variant.pattern_name}
            />
          </div>
        )}
        <div className="absolute top-2 right-2 flex gap-0.5 rounded-md border border-border bg-card/80 backdrop-blur p-0.5">
          <button onClick={() => setShowCode(false)} className={cn("rounded p-1 text-xs transition-colors", !showCode ? "bg-accent" : "hover:bg-accent/50")}>
            <Eye className="h-3 w-3" />
          </button>
          <button onClick={() => setShowCode(true)} className={cn("rounded p-1 text-xs transition-colors", showCode ? "bg-accent" : "hover:bg-accent/50")}>
            <Code2 className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* Footer — only shown when expanded */}
      {isExpanded && (
        <div className="border-t border-border px-4 py-2.5">
          <p className="text-xs text-muted-foreground">{variant.description}</p>
          <div className="flex gap-3 mt-2">
            {Object.entries(variant.scores).map(([key, val]) => {
              const labels: Record<string, string> = { ux_quality: "UX品質", code_quality: "コード品質", performance: "パフォーマンス", accessibility: "アクセシビリティ" };
              return (
                <div key={key} className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <div className="h-1.5 w-12 rounded-full bg-muted overflow-hidden">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${val * 100}%` }} />
                  </div>
                  {labels[key] ?? key}: {(val * 100).toFixed(0)}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
