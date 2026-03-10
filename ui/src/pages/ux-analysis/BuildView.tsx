import { useState, useRef, useEffect } from "react";
import {
  ArrowRight, Loader2,
  Check, AlertTriangle, Rocket, Eye, ExternalLink, RotateCcw,
  RefreshCw, Flag, CircleCheck, CircleX, Bot,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { Milestone, MilestoneResult } from "@/types/ux-analysis";

/* ── Step 5: Building ── */
export function BuildingStep({ milestones, iteration, milestoneResults }: {
  milestones: Milestone[];
  iteration: number;
  milestoneResults: MilestoneResult[];
}) {
  const isAutonomous = milestones.length > 0;
  const phases = isAutonomous
    ? ["ビルドプラン作成中...", "アーキテクチャ設計", "コード生成中...", "マイルストーン評価", "レビュー・改善"]
    : ["ビルドプラン作成中...", "アーキテクチャ設計", "コンポーネント設計", "コード生成中...", "スタイリング", "テストデータ作成", "最終統合"];
  const [current, setCurrent] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setCurrent((c) => Math.min(c + 1, phases.length - 1)), 2500);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="flex items-center justify-center h-full p-6">
      <div className="w-full max-w-2xl space-y-6">
        <div className="text-center">
          <Rocket className="h-12 w-12 text-primary mx-auto animate-bounce" />
          <h2 className="text-xl font-bold text-foreground mt-3">
            {isAutonomous ? "AIが自律開発中..." : "AIが開発中..."}
          </h2>
          <p className="text-sm text-muted-foreground">
            {isAutonomous
              ? `マイルストーン達成まで自律的に改善を繰り返します（イテレーション ${iteration + 1}/5）`
              : "選択された機能を基にプロダクトを構築しています"
            }
          </p>
        </div>

        <div className="grid gap-6" style={{ gridTemplateColumns: isAutonomous ? "1fr 1fr" : "1fr" }}>
          {/* Build phases */}
          <div className="space-y-2">
            <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">開発フェーズ</h3>
            {phases.map((s, i) => (
              <div key={i} className={cn("flex items-center gap-2 rounded-md px-4 py-2 text-sm transition-all",
                i < current && "text-success", i === current && "text-primary font-medium", i > current && "text-muted-foreground/50",
              )}>
                {i < current ? <Check className="h-4 w-4" /> : i === current ? <Loader2 className="h-4 w-4 animate-spin" /> : <div className="h-4 w-4" />}
                {s}
              </div>
            ))}
          </div>

          {/* Milestone progress (autonomous only) */}
          {isAutonomous && (
            <div className="space-y-2">
              <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                <Flag className="inline h-3 w-3 mr-1" />
                マイルストーン進捗
              </h3>
              {milestones.map((ms) => {
                const result = milestoneResults.find((r) => r.id === ms.id);
                const isSatisfied = result?.status === "satisfied";
                const isChecked = result != null;
                return (
                  <div key={ms.id} className={cn(
                    "flex items-start gap-2 rounded-md border px-3 py-2 text-sm transition-all",
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

              {iteration > 0 && (
                <div className="flex items-center gap-2 rounded-md bg-primary/5 border border-primary/20 px-3 py-2 text-xs text-primary mt-2">
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                  改善イテレーション {iteration + 1} 実行中...
                </div>
              )}

              {/* Agent coordination visualization */}
              <div className="mt-3 rounded-md border border-border bg-card p-3">
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">エージェント連携</p>
                <div className="flex items-center gap-2 text-xs">
                  <div className="flex items-center gap-1 rounded-full bg-accent px-2 py-1">
                    <Bot className="h-3 w-3" /> Architect
                  </div>
                  <ArrowRight className="h-3 w-3 text-muted-foreground" />
                  <div className="flex items-center gap-1 rounded-full bg-accent px-2 py-1">
                    <Bot className="h-3 w-3" /> Builder
                  </div>
                  <ArrowRight className="h-3 w-3 text-muted-foreground" />
                  <div className={cn("flex items-center gap-1 rounded-full px-2 py-1", iteration > 0 ? "bg-primary/10 text-primary" : "bg-accent")}>
                    <Bot className="h-3 w-3" /> Reviewer
                  </div>
                  {iteration > 0 && (
                    <>
                      <RefreshCw className="h-3 w-3 text-primary" />
                    </>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Step 6: Complete ── */
export function CompleteStep({ code, cost, iteration, milestoneResults, onReset }: {
  code: string | null;
  cost: number;
  iteration: number;
  milestoneResults: MilestoneResult[];
  onReset: () => void;
}) {
  const [showPreview, setShowPreview] = useState(true);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    if (code) {
      const blob = new Blob([code], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      setBlobUrl(url);
      return () => URL.revokeObjectURL(url);
    }
  }, [code]);

  if (!code) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <AlertTriangle className="h-12 w-12 text-destructive mx-auto mb-4" />
          <h2 className="text-xl font-bold text-foreground">ビルドに失敗しました</h2>
          <button onClick={onReset} className="mt-4 rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground">やり直す</button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-3 border-b border-border px-6 py-3">
        <div className="flex items-center gap-2">
          <Check className="h-4 w-4 text-success" />
          <span className="text-sm font-medium text-foreground">プロダクト完成</span>
        </div>
        {cost > 0 && <Badge variant="secondary" className="text-[10px]">${cost.toFixed(4)}</Badge>}
        {iteration > 0 && <Badge variant="outline" className="text-[10px]">{iteration} iterations</Badge>}
        {milestoneResults.length > 0 && (
          <Badge variant="outline" className="text-[10px]">
            {milestoneResults.filter((r) => r.status === "satisfied").length}/{milestoneResults.length} milestones
          </Badge>
        )}
        <div className="flex-1" />
        <div className="flex gap-1">
          <button onClick={() => setShowPreview(true)} className={cn("rounded-md px-3 py-1.5 text-xs font-medium transition-colors", showPreview ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground")}>
            <Eye className="inline h-3.5 w-3.5 mr-1" />プレビュー
          </button>
          <button onClick={() => setShowPreview(false)} className={cn("rounded-md px-3 py-1.5 text-xs font-medium transition-colors", !showPreview ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground")}>
            コード
          </button>
        </div>
        {blobUrl && (
          <a href={blobUrl} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-primary hover:underline">
            <ExternalLink className="h-3.5 w-3.5" /> 新しいタブで開く
          </a>
        )}
        <button onClick={onReset} className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors">
          <RotateCcw className="h-3.5 w-3.5" /> 新しいプロダクト
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {showPreview ? (
          <iframe
            ref={iframeRef}
            srcDoc={code}
            className="h-full w-full border-0 bg-white"
            sandbox="allow-scripts allow-same-origin"
            title="Product Preview"
          />
        ) : (
          <pre className="h-full overflow-auto p-6 text-xs text-foreground bg-card font-mono whitespace-pre-wrap">{code}</pre>
        )}
      </div>
    </div>
  );
}
