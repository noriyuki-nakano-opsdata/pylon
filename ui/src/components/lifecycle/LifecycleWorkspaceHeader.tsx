import { Menu, PanelLeft, PanelRightClose, PanelRightOpen, Save, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { LifecyclePhase, PhaseStatus } from "@/types/lifecycle";

const PHASE_META: Record<LifecyclePhase, { label: string; description: string }> = {
  research: { label: "調査", description: "市場調査・競合分析を整理し、企画の前提を固めます。" },
  planning: { label: "企画", description: "ペルソナ、ストーリー、優先度、IA を統合してスコープを定義します。" },
  design: { label: "デザイン", description: "複数案を比較し、実装に渡す UX 方針を選びます。" },
  approval: { label: "承認", description: "企画と設計の説明責任を担保し、次工程への gate を閉じます。" },
  development: { label: "開発", description: "自律開発の進行と品質到達を確認します。" },
  deploy: { label: "デプロイ", description: "release gate を通して成果物を検証し、公開準備を整えます。" },
  iterate: { label: "改善", description: "フィードバックを次の iteration backlog に変換します。" },
};

interface LifecycleWorkspaceHeaderProps {
  currentPhase: LifecyclePhase;
  projectLabel: string;
  phaseStatuses: PhaseStatus[];
  phaseNavCollapsed: boolean;
  isMobile: boolean;
  consoleOpen: boolean;
  saveState: "idle" | "saving" | "saved" | "error";
  lastSavedAt: string | null;
  onTogglePhaseNav: () => void;
  onToggleConsole: () => void;
}

function formatSavedTime(lastSavedAt: string | null): string {
  if (!lastSavedAt) return "未保存";
  return new Date(lastSavedAt).toLocaleTimeString("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function LifecycleWorkspaceHeader({
  currentPhase,
  projectLabel,
  phaseStatuses,
  phaseNavCollapsed,
  isMobile,
  consoleOpen,
  saveState,
  lastSavedAt,
  onTogglePhaseNav,
  onToggleConsole,
}: LifecycleWorkspaceHeaderProps) {
  const completed = phaseStatuses.filter((item) => item.status === "completed").length;
  const currentIndex = phaseStatuses.findIndex((item) => item.phase === currentPhase);
  const total = phaseStatuses.length;
  const meta = PHASE_META[currentPhase];
  const progress = total === 0 ? 0 : ((Math.max(completed, currentIndex + 1)) / total) * 100;

  return (
    <header className="border-b border-border bg-background/90 px-4 py-3 backdrop-blur">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex items-center gap-2">
          <button
            onClick={onTogglePhaseNav}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            aria-label={isMobile ? "フェーズナビを開く" : phaseNavCollapsed ? "フェーズナビを展開" : "フェーズナビを折りたたむ"}
          >
            {isMobile ? <Menu className="h-4 w-4" /> : <PanelLeft className="h-4 w-4" />}
          </button>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/70">
                lifecycle workspace
              </span>
              <span className="rounded-full border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                {projectLabel}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <h1 className="text-base font-semibold text-foreground">{meta.label}</h1>
              <span className="text-xs text-muted-foreground">
                {Math.min(completed + 1, total)}/{total}
              </span>
            </div>
          </div>
        </div>

        <div className="min-w-[15rem] flex-1">
          <p className="text-sm text-muted-foreground">{meta.description}</p>
          <div className="mt-2 flex items-center gap-2">
            <div className="h-1.5 flex-1 rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="text-[11px] text-muted-foreground">
              {completed} / {total} 完了
            </span>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <div className={cn(
            "inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs",
            saveState === "error"
              ? "border-destructive/30 bg-destructive/10 text-destructive"
              : "border-border bg-card text-muted-foreground",
          )}>
            {saveState === "saving" ? (
              <Sparkles className="h-3.5 w-3.5 animate-pulse" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            <span>
              {saveState === "saving" && "自動保存中"}
              {saveState === "saved" && `保存済み ${formatSavedTime(lastSavedAt)}`}
              {saveState === "error" && "保存に失敗"}
              {saveState === "idle" && "自動保存待機"}
            </span>
          </div>
          <button
            onClick={onToggleConsole}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-card px-3 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            {consoleOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
            <span>{isMobile ? "運用パネル" : consoleOpen ? "運用パネルを閉じる" : "運用パネルを開く"}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
