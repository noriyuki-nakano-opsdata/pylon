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
    case "completed": return <Check className="h-3.5 w-3.5 text-success" />;
    case "in_progress": return <Loader2 className="h-3.5 w-3.5 text-primary animate-spin" />;
    case "review": return <ShieldCheck className="h-3.5 w-3.5 text-warning" />;
    case "locked": return <Lock className="h-3.5 w-3.5 text-muted-foreground/40" />;
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
      "flex h-full flex-col gap-0.5 border-r border-border bg-card/70 py-3",
      collapsed ? "w-14 px-1" : "w-56 px-2",
      className,
    )}>
      {!collapsed && (
        <p className="px-3 pb-2 pt-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">
          Product Lifecycle
        </p>
      )}
      {PHASES.map((phase, i) => {
        const ps = phaseStatuses.find((s) => s.phase === phase.key);
        const status = ps?.status ?? (i === 0 ? "available" : "locked");
        const isLocked = status === "locked";
        const to = `${basePath}/lifecycle/${phase.key}`;
        const isActive = location.pathname.startsWith(to);

        return (
          <div key={phase.key} className="relative">
            {/* connector line */}
            {i > 0 && (
              <div className={cn(
                "absolute left-5 -top-0.5 h-0.5 w-px",
                collapsed ? "left-[1.35rem]" : "left-5",
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

      {/* Version indicator */}
      {!collapsed && (
        <div className="mt-auto border-t border-border px-3 pt-3">
          <div className="flex items-center justify-between text-[10px] text-muted-foreground">
            <span>バージョン</span>
            <span className="font-mono">v{phaseStatuses.filter((s) => s.status === "completed").length + 1}.0</span>
          </div>
          <div className="mt-1.5 flex gap-0.5">
            {PHASES.map((phase) => {
              const ps = phaseStatuses.find((s) => s.phase === phase.key);
              const status = ps?.status ?? "locked";
              return (
                <div
                  key={phase.key}
                  className={cn(
                    "h-1 flex-1 rounded-full",
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
        "relative flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors",
        isActive ? "bg-primary text-primary-foreground" :
        status === "completed" ? "bg-success/10 text-success" :
        status === "in_progress" ? "bg-primary/10 text-primary" :
        "bg-muted text-muted-foreground",
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
            "truncate",
            isActive ? "text-foreground" : "text-muted-foreground group-hover:text-foreground",
          )}>
            {label}
          </p>
          <p className="truncate text-[10px] text-muted-foreground/70">
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
    "group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all",
    collapsed && "justify-center px-2",
  );

  if (isLocked) {
    return (
      <div className={cn(baseClassName, "opacity-40 cursor-not-allowed")} aria-disabled="true">
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
        isActive ? "bg-accent shadow-sm" : "hover:bg-accent/50",
      )}
    >
      {inner}
    </NavLink>
  );
}
