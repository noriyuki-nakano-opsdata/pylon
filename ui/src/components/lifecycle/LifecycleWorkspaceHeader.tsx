import { Menu, PanelLeft, PanelRightClose, PanelRightOpen, Save, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { LifecycleGovernanceMode, LifecyclePhase, PhaseStatus } from "@/types/lifecycle";

const PHASE_META: Record<LifecyclePhase, { label: string; description: string }> = {
  research: { label: "調査", description: "市場調査・競合分析を整理し、企画の前提を固めます。" },
  planning: { label: "企画", description: "ペルソナ、ストーリー、優先度、情報設計を統合してスコープを定義します。" },
  design: { label: "デザイン", description: "複数案を比較し、実装に渡す UX 方針を選びます。" },
  approval: { label: "承認", description: "企画と設計の内容をレビューし、次工程への進行を判断します。" },
  development: { label: "開発", description: "自律開発の進行と品質到達を確認します。" },
  deploy: { label: "デプロイ", description: "リリース前チェックを通して成果物を検証し、公開準備を整えます。" },
  iterate: { label: "改善", description: "フィードバックを次のイテレーションのバックログに変換します。" },
};

interface LifecycleWorkspaceHeaderProps {
  currentPhase: LifecyclePhase;
  projectLabel: string;
  phaseStatuses: PhaseStatus[];
  governanceMode?: LifecycleGovernanceMode;
  pendingHumanDecisions?: number;
  phaseNavCollapsed: boolean;
  isMobile: boolean;
  consoleOpen: boolean;
  saveState: "idle" | "saving" | "saved" | "error";
  runtimeConnectionState?: "inactive" | "connecting" | "live" | "reconnecting";
  lastSavedAt: string | null;
  onSelectGovernanceMode?: (mode: LifecycleGovernanceMode) => void;
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

function governanceModeLabel(governanceMode?: LifecycleGovernanceMode): string {
  return governanceMode === "complete_autonomy" ? "complete autonomy" : "governed";
}

export function LifecycleWorkspaceHeader({
  currentPhase,
  projectLabel,
  phaseStatuses,
  governanceMode,
  pendingHumanDecisions = 0,
  phaseNavCollapsed,
  isMobile,
  consoleOpen,
  saveState,
  runtimeConnectionState = "inactive",
  lastSavedAt,
  onSelectGovernanceMode,
  onTogglePhaseNav,
  onToggleConsole,
}: LifecycleWorkspaceHeaderProps) {
  const completed = phaseStatuses.filter((item) => item.status === "completed").length;
  const currentIndex = phaseStatuses.findIndex((item) => item.phase === currentPhase);
  const currentStep = currentIndex >= 0 ? currentIndex + 1 : 1;
  const total = phaseStatuses.length;
  const meta = PHASE_META[currentPhase];
  const progress = total === 0 ? 0 : (currentStep / total) * 100;
  const activeStatus = phaseStatuses.find((item) => item.phase === currentPhase)?.status ?? "available";

  return (
    <header className="border-b border-border bg-black/20 px-4 py-3 backdrop-blur-xl">
      <div className="flex flex-wrap items-start gap-3 xl:items-center">
        <div className="flex items-center gap-2.5">
          <button
            onClick={onTogglePhaseNav}
            className="inline-flex h-9 w-9 items-center justify-center rounded-2xl border border-border bg-card/80 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            aria-label={isMobile ? "フェーズナビを開く" : phaseNavCollapsed ? "フェーズナビを展開" : "フェーズナビを折りたたむ"}
          >
            {isMobile ? <Menu className="h-4 w-4" /> : <PanelLeft className="h-4 w-4" />}
          </button>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">
              <span className="rounded-full border border-border bg-card/70 px-2.5 py-1 text-[10px]">
                Workbench
              </span>
              <span className="truncate font-mono normal-case tracking-[0.02em] text-foreground/85">
                {`pylon://${projectLabel || "untitled"}/lifecycle/${currentPhase}`}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card/80 px-3 py-1.5">
                <span className="font-mono text-[11px] text-primary">{`${String(currentStep).padStart(2, "0")}/${String(total).padStart(2, "0")}`}</span>
                <h1 className="text-sm font-semibold text-foreground">{`${meta.label}.phase.tsx`}</h1>
              </div>
              <span className="rounded-full border border-border bg-card/70 px-2.5 py-1 text-[11px] text-muted-foreground">
                {activeStatus}
              </span>
            </div>
          </div>
        </div>

        <div className="min-w-[15rem] flex-1">
          <p className="text-sm text-muted-foreground">{meta.description}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <div className="h-1.5 min-w-[12rem] flex-1 rounded-full bg-muted/80">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
            {phaseStatuses.map((status) => (
              <span
                key={status.phase}
                className={cn(
                  "inline-flex h-2.5 w-2.5 rounded-full border",
                  status.phase === currentPhase
                    ? "border-primary bg-primary shadow-[0_0_0_4px_rgba(97,208,255,0.18)]"
                    : status.status === "completed"
                      ? "border-success/40 bg-success"
                      : status.status === "in_progress"
                        ? "border-primary/40 bg-primary/70"
                        : status.status === "review"
                          ? "border-warning/40 bg-warning"
                          : "border-border bg-muted",
                )}
                title={status.phase}
              />
            ))}
            <span className="text-[11px] font-mono text-muted-foreground">
              {`done:${completed} current:${currentStep}/${total}`}
            </span>
          </div>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className={cn(
            "inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs",
            saveState === "error"
              ? "border-destructive/30 bg-destructive/10 text-destructive"
              : "border-border bg-card/80 text-muted-foreground",
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
          <div className={cn(
            "inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs",
            runtimeConnectionState === "live"
              ? "border-primary/30 bg-primary/10 text-primary"
              : "border-border bg-card/80 text-muted-foreground",
          )}>
            <span className={cn(
              "h-2 w-2 rounded-full",
              runtimeConnectionState === "live" ? "bg-primary" : "bg-muted-foreground/50",
            )} />
            <span>
              {runtimeConnectionState === "live" && "ライブ接続"}
              {runtimeConnectionState === "connecting" && "接続中"}
              {runtimeConnectionState === "reconnecting" && "再接続中"}
              {runtimeConnectionState === "inactive" && "ライブ停止"}
            </span>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card/80 px-3 py-2 text-xs text-muted-foreground">
            <span className={cn(
              "h-2 w-2 rounded-full",
              governanceMode === "complete_autonomy" ? "bg-emerald-400" : "bg-amber-300",
            )} />
            <span>{governanceModeLabel(governanceMode)}</span>
          </div>
          {onSelectGovernanceMode ? (
            <div className="inline-flex items-center gap-1 rounded-full border border-border bg-card/80 p-1 text-xs">
              {(["governed", "complete_autonomy"] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => onSelectGovernanceMode(mode)}
                  className={cn(
                    "rounded-full px-2.5 py-1 transition-colors",
                    governanceMode === mode
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )}
                >
                  {mode === "governed" ? "governed" : "full auto"}
                </button>
              ))}
            </div>
          ) : null}
          <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card/80 px-3 py-2 text-xs text-muted-foreground">
            <span className={cn("h-2 w-2 rounded-full", pendingHumanDecisions > 0 ? "bg-amber-300" : "bg-muted-foreground/50")} />
            <span>{pendingHumanDecisions > 0 ? `human gates ${pendingHumanDecisions}` : "human gates clear"}</span>
          </div>
          <button
            onClick={onToggleConsole}
            className="inline-flex h-9 items-center gap-2 rounded-full border border-border bg-card/80 px-3 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            {consoleOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
            <span>{isMobile ? "Console" : consoleOpen ? "Console close" : "Console open"}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
