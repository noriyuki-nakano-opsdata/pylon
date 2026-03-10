import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Palette, Loader2, Check, ArrowRight, ArrowLeft,
  Eye, Code2, Merge, Star, ExternalLink, Zap,
  Monitor, Tablet, Smartphone, BarChart3, AlertCircle,
  ChevronDown, ChevronUp, Maximize2, Minimize2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useLifecycle } from "./LifecycleLayout";
import { useWorkflowRun } from "@/hooks/useWorkflowRun";
import { parseDesignOutput } from "@/api/lifecycle";
import { AgentProgressView } from "@/components/lifecycle/AgentProgressView";
import type { DesignVariant } from "@/types/lifecycle";

const DESIGN_AGENTS = [
  { id: "claude-designer", label: "Claude Sonnet 4.6" },
  { id: "openai-designer", label: "GPT-5 Mini" },
  { id: "gemini-designer", label: "Gemini 3 Flash" },
  { id: "design-evaluator", label: "評価・スコアリング" },
];

export function DesignPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycle();
  const workflow = useWorkflowRun("design", projectSlug ?? "");
  const [previewDevice, setPreviewDevice] = useState<"desktop" | "tablet" | "mobile">("desktop");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Handle workflow completion — stable dependency via JSON key check
  const stateHasVariants = "variants" in workflow.state || "design" in workflow.state;
  useEffect(() => {
    if (workflow.status === "completed" && stateHasVariants) {
      const variants = parseDesignOutput(workflow.state);
      if (variants.length > 0) {
        lc.setDesignVariants(variants);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow.status, stateHasVariants]);

  const isGenerating = workflow.status === "starting" || workflow.status === "running";

  const generate = () => {
    lc.advancePhase("design");
    workflow.start({
      spec: lc.spec,
      features: lc.features.filter((f) => f.selected),
      analysis: lc.analysis,
    });
  };

  const goNext = () => {
    lc.completePhase("design");
    navigate(`/p/${projectSlug}/lifecycle/approval`);
  };
  const goBack = () => navigate(`/p/${projectSlug}/lifecycle/planning`);

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  if (lc.designVariants.length === 0 && !isGenerating) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-xl w-full space-y-6 text-center">
          <Palette className="h-12 w-12 text-primary mx-auto" />
          <h2 className="text-xl font-bold text-foreground">デザインパターン比較</h2>
          <p className="text-sm text-muted-foreground">
            複数のAIモデルが同時にデザインパターンを生成。Side-by-Sideで比較し、ベストを選択できます。
          </p>
          <div className="rounded-lg border border-border bg-card p-4 text-left">
            <p className="text-xs font-medium text-muted-foreground mb-2">生成モデル</p>
            <div className="flex flex-wrap gap-2">
              {["Claude Sonnet 4.6", "GPT-5 Mini", "Gemini 3 Flash"].map((m) => (
                <Badge key={m} variant="secondary">{m}</Badge>
              ))}
            </div>
          </div>
          <div className="rounded-lg border border-border bg-card p-4 text-left">
            <p className="text-xs font-medium text-muted-foreground mb-1">選択中の機能</p>
            <p className="text-sm text-foreground">{lc.features.filter((f) => f.selected).length}個の機能が選択されています</p>
          </div>
          <Button onClick={generate} className="w-full gap-2" size="lg">
            <Zap className="h-4 w-4" /> 3パターンを並行生成
          </Button>
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
        agents={DESIGN_AGENTS}
        progress={workflow.agentProgress}
        elapsedMs={workflow.elapsedMs}
        title="3つのAIモデルが並行生成中..."
        subtitle="Claude Sonnet 4.6 / GPT-5 Mini / Gemini 3 Flash がそれぞれ異なるデザインパターンを生成し、品質評価を行います"
      />
    );
  }

  const variants = lc.designVariants;
  const deviceWidth = previewDevice === "desktop" ? "100%" : previewDevice === "tablet" ? "768px" : "375px";

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-2 border-b border-border px-6 py-2.5">
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
        <div className="mx-auto max-w-7xl space-y-4">
          {variants.map((v) => (
            <DesignCard
              key={v.id}
              variant={v}
              deviceWidth={deviceWidth}
              isSelected={lc.selectedDesignId === v.id}
              isExpanded={expandedId === v.id}
              onSelect={() => lc.setSelectedDesignId(v.id)}
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
          </div>
          {!isExpanded && (
            <div className="flex gap-2 ml-4">
              {Object.entries(variant.scores).slice(0, 3).map(([key, val]) => {
                const labels: Record<string, string> = { ux_quality: "UX", code_quality: "Code", performance: "Perf" };
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
