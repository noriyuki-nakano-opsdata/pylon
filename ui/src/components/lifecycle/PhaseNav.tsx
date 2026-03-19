import { NavLink, useLocation } from "react-router-dom";
import {
  Search, Lightbulb, Palette, ShieldCheck, Code2, Rocket, RefreshCw,
  Check, Lock, Loader2, ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { LifecyclePhase, PhaseStatus } from "@/types/lifecycle";

const PHASES: { key: LifecyclePhase; label: string; icon: React.ElementType; description: string }[] = [
  { key: "research", label: "調査", icon: Search, description: "市場調査・競合分析" },
  { key: "planning", label: "企画", icon: Lightbulb, description: "UX分析・機能定義" },
  { key: "design", label: "デザイン", icon: Palette, description: "パターン比較・選択" },
  { key: "approval", label: "承認", icon: ShieldCheck, description: "レビュー・承認" },
  { key: "development", label: "開発", icon: Code2, description: "自律開発・品質保証" },
  { key: "deploy", label: "デプロイ", icon: Rocket, description: "プレビュー・リリース" },
  { key: "iterate", label: "改善", icon: RefreshCw, description: "フィードバック・更新" },
];

function statusIcon(status: PhaseStatus["status"]) {
  switch (status) {
    case "completed": return <Check className="h-3.5 w-3.5 text-success" aria-label="完了" />;
    case "in_progress": return <Loader2 className="h-3.5 w-3.5 text-primary animate-spin" aria-label="進行中" />;
    case "review": return <ShieldCheck className="h-3.5 w-3.5 text-warning" aria-label="レビュー中" />;
    case "locked": return <Lock className="h-3.5 w-3.5 text-muted-foreground/40" aria-label="ロック中" />;
    default: return null;
  }
}

interface PhaseNavProps {
  basePath: string;
  phaseStatuses: PhaseStatus[];
  collapsed?: boolean;
  className?: string;
  onItemClick?: () => void;
}

export function PhaseNav({
  basePath,
  phaseStatuses,
  collapsed,
  className,
  onItemClick,
}: PhaseNavProps) {
  const location = useLocation();

  return (
    <nav className={cn(
      "flex h-full flex-col gap-0.5 border-r border-border bg-card/60 py-3 backdrop-blur",
      collapsed ? "w-16 px-1.5" : "w-72 px-2.5",
      className,
    )}>
      <div className={cn("border-b border-border/80 pb-3", collapsed ? "px-1" : "px-2.5")}>
        {!collapsed ? (
          <>
            <p className="px-2 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">
              Explorer
            </p>
            <div className="rounded-[1.1rem] border border-border bg-background/70 px-3 py-3">
              <p className="font-mono text-[11px] text-foreground">workflow://lifecycle</p>
              <p className="mt-1 text-xs text-muted-foreground">phases/{PHASES.length} modules</p>
            </div>
          </>
        ) : (
          <div className="flex justify-center pt-1">
            <div className="h-9 w-9 rounded-2xl border border-border bg-background/80" />
          </div>
        )}
      </div>
      {PHASES.map((phase, i) => {
        const ps = phaseStatuses.find((s) => s.phase === phase.key);
        const status = ps?.status ?? (i === 0 ? "available" : "locked");
        const isLocked = status === "locked";
        const to = `${basePath}/lifecycle/${phase.key}`;
        const isActive = location.pathname.startsWith(to);

        return (
          <div key={phase.key} className="relative">
            {i > 0 && (
              <div className={cn(
                "absolute w-px",
                collapsed ? "left-7 top-[-2px] h-2.5" : "left-7 top-[-6px] h-4",
                status === "locked" ? "bg-border" : "bg-primary/30",
              )} />
            )}
            <PhaseNavItem
              isLocked={isLocked}
              to={to}
              isActive={isActive}
              status={status}
              icon={phase.icon}
              label={phase.label}
              description={phase.description}
              collapsed={collapsed}
              onClick={onItemClick}
            />
          </div>
        );
      })}

      {!collapsed && (
        <div className="mt-auto border-t border-border px-3 pt-4">
          <div className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            <span>release</span>
            <span className="font-mono normal-case">v{phaseStatuses.filter((s) => s.status === "completed").length + 1}.0</span>
          </div>
          <div className="mt-2 flex gap-1">
            {PHASES.map((phase) => {
              const ps = phaseStatuses.find((s) => s.phase === phase.key);
              const status = ps?.status ?? "locked";
              return (
                <div
                  key={phase.key}
                  className={cn(
                    "h-1.5 flex-1 rounded-full",
                    status === "completed" ? "bg-success" :
                    status === "in_progress" ? "bg-primary animate-pulse" :
                    status === "review" ? "bg-warning" :
                    "bg-muted",
                  )}
                />
              );
            })}
          </div>
        </div>
      )}
    </nav>
  );
}

interface PhaseNavItemProps {
  isLocked: boolean;
  to: string;
  isActive: boolean;
  status: PhaseStatus["status"];
  icon: React.ElementType;
  label: string;
  description: string;
  collapsed?: boolean;
  onClick?: () => void;
}

function PhaseNavItem({
  isLocked,
  to,
  isActive,
  status,
  icon: Icon,
  label,
  description,
  collapsed,
  onClick,
}: PhaseNavItemProps) {
  const inner = (
    <>
      <div className={cn(
        "relative flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl border transition-colors",
        isActive ? "border-primary/30 bg-primary/15 text-primary" :
        status === "completed" ? "border-success/20 bg-success/10 text-success" :
        status === "in_progress" ? "border-primary/20 bg-primary/10 text-primary" :
        "border-border/70 bg-background/70 text-muted-foreground",
      )}>
        <Icon className="h-4 w-4" />
        {status !== "available" && (
          <span className="absolute -right-0.5 -top-0.5">
            {statusIcon(status)}
          </span>
        )}
      </div>
      {!collapsed && (
        <div className="min-w-0 flex-1">
          <p className={cn(
            "truncate font-medium",
            isActive ? "text-foreground" : "text-muted-foreground group-hover:text-foreground",
          )}>
            {label}
          </p>
          <p className="truncate font-mono text-[10px] text-muted-foreground/70">
            {description}
          </p>
        </div>
      )}
      {!collapsed && isActive && (
        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      )}
    </>
  );

  const baseClassName = cn(
    "group flex items-center gap-3 rounded-[1rem] border px-3 py-2.5 text-sm font-medium transition-all",
    collapsed && "justify-center px-2.5",
  );

  if (isLocked) {
    return (
      <div className={cn(baseClassName, "cursor-not-allowed border-transparent opacity-45")} aria-disabled="true" tabIndex={-1}>
        {inner}
      </div>
    );
  }

  return (
    <NavLink
      to={to}
      onClick={onClick}
      className={cn(
        baseClassName,
        isActive
          ? "border-primary/25 bg-primary/8 shadow-[0_14px_30px_rgba(2,6,23,0.28)]"
          : "border-transparent bg-transparent hover:border-border/70 hover:bg-accent/55",
      )}
    >
      {inner}
    </NavLink>
  );
}
