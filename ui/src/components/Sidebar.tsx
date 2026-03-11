import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Bot,
  GitBranch,
  Play,
  ShieldCheck,
  DollarSign,
  Sparkles,
  Server,
  Cpu,
  Settings,
  ChevronLeft,
  CircleDot,
  GitPullRequest,
  ChevronsUpDown,
  Building2,
  FolderKanban,
  Layers,
  Kanban,
  Users,
  Brain,
  CalendarDays,
  FileText,
  Megaphone,
  FolderPlus,
  Search,
  Wand2,
  Loader2,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useFeatureFlags } from "@/contexts/FeatureFlagsContext";
import { useTenantProject } from "@/contexts/TenantProjectContext";
import { useClickOutside } from "@/hooks/useClickOutside";
import { useState, useRef, useCallback, useMemo } from "react";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  lockCollapsed?: boolean;
}

const PROJECT_NAV = [
  { to: "lifecycle", icon: Layers, label: "プロダクトライフサイクル", feature: "lifecycle" },
  { to: "studio", icon: Sparkles, label: "クイックビルド", badge: "β", feature: "studio" },
  { to: "tasks", icon: Kanban, label: "タスクボード", feature: "tasks" },
  { to: "team", icon: Users, label: "エージェント監視", feature: "team" },
  { to: "memory", icon: Brain, label: "メモリー", feature: "memory" },
  { to: "calendar", icon: CalendarDays, label: "カレンダー", feature: "calendar" },
  { to: "content", icon: FileText, label: "コンテンツパイプライン", feature: "content" },
  { to: "ads", icon: Megaphone, label: "広告監査", feature: "ads" },
  { to: "issues", icon: CircleDot, label: "イシュー", feature: "issues" },
  { to: "pulls", icon: GitPullRequest, label: "プルリクエスト", feature: "pulls" },
  { to: "runs", icon: Play, label: "履歴", feature: "runs" },
  { to: "approvals", icon: ShieldCheck, label: "承認", feature: "approvals" },
] as const;

const ADMIN_ITEMS = [
  { to: "/dashboard", icon: LayoutDashboard, label: "ダッシュボード", feature: "dashboard" },
  { to: "/workflows", icon: GitBranch, label: "ワークフロー", feature: "workflows" },
  { to: "/agents", icon: Bot, label: "エージェント", feature: "agents" },
  { to: "/costs", icon: DollarSign, label: "コスト", feature: "costs" },
  { to: "/providers", icon: Server, label: "プロバイダー", feature: "providers" },
  { to: "/models", icon: Cpu, label: "モデル管理", feature: "models" },
  { to: "/skills", icon: Wand2, label: "スキル", feature: "skills" },
] as const;
const QUICK_ADMIN_ITEMS = [
  { to: "/projects/new", icon: FolderPlus, label: "新規プロジェクト" },
] as const;

const BOTTOM_ITEMS = [
  { to: "/settings", icon: Settings, label: "設定", feature: "settings" },
] as const;

export function Sidebar({ collapsed, onToggle, lockCollapsed = false }: SidebarProps) {
  const { currentProject } = useTenantProject();
  const { isEnabled } = useFeatureFlags();
  const projectBase = currentProject ? `/p/${currentProject.slug}` : null;
  const projectItems = PROJECT_NAV.filter((item) => isEnabled("project", item.feature));
  const adminItems = ADMIN_ITEMS.filter((item) => isEnabled("admin", item.feature));
  const bottomItems = BOTTOM_ITEMS.filter((item) => isEnabled("admin", item.feature));

  return (
    <aside
      className={cn(
        "flex h-full flex-col border-r border-border bg-sidebar transition-all duration-200",
        collapsed ? "w-16" : "w-60",
      )}
    >
      {/* Logo */}
      <div className="flex h-14 items-center border-b border-border px-4">
        {!collapsed && (
          <span className="text-lg font-bold tracking-tight text-foreground">Pylon</span>
        )}
        {!lockCollapsed && (
          <Button
            variant="ghost"
            size="icon"
            className={cn("ml-auto h-8 w-8", collapsed && "mx-auto")}
            onClick={onToggle}
          >
            <ChevronLeft className={cn("h-4 w-4 transition-transform", collapsed && "rotate-180")} />
          </Button>
        )}
      </div>

      {/* Tenant & Project selectors */}
      {!collapsed && (
        <div className="space-y-1 border-b border-border p-2">
          <TenantSelector />
          <ProjectSelector />
        </div>
      )}

      {/* Project nav */}
      <nav className="space-y-1 p-2">
        {!collapsed && (
          <p className="px-3 pb-1 pt-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/50">
            Project
          </p>
        )}
        {projectItems.map((item) => (
          <SidebarNavItem
            key={item.to}
            to={projectBase ? `${projectBase}/${item.to}` : ""}
            icon={item.icon}
            label={item.label}
            collapsed={collapsed}
            disabled={!projectBase}
            badge={"badge" in item ? item.badge : undefined}
          />
        ))}
      </nav>

      {/* Admin nav */}
      <nav className="flex-1 space-y-1 border-t border-border p-2">
        {!collapsed && (
          <p className="px-3 pb-1 pt-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/50">
            Admin
          </p>
        )}
        {QUICK_ADMIN_ITEMS.map((item) => (
          <SidebarNavItem key={item.to} to={item.to} icon={item.icon} label={item.label} collapsed={collapsed} />
        ))}
        {adminItems.map((item) => (
          <SidebarNavItem key={item.to} to={item.to} icon={item.icon} label={item.label} collapsed={collapsed} />
        ))}
      </nav>

      {/* Bottom nav */}
      <nav className="border-t border-border p-2">
        {bottomItems.map((item) => (
          <SidebarNavItem key={item.to} to={item.to} icon={item.icon} label={item.label} collapsed={collapsed} />
        ))}
      </nav>
    </aside>
  );
}

/* ── Tenant Selector ── */
function TenantSelector() {
  const { tenants, currentTenant, setCurrentTenant } = useTenantProject();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);

  useClickOutside(ref, close);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-sm text-sidebar-foreground hover:bg-accent hover:text-sidebar-active transition-colors"
      >
        <Building2 className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate flex-1 text-left">{currentTenant?.name}</span>
        <ChevronsUpDown className="h-3 w-3 shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 rounded-md border border-border bg-card py-1 shadow-lg">
          {tenants.map((t) => (
            <button
              key={t.id}
              onClick={() => { setCurrentTenant(t); setOpen(false); }}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-1.5 text-sm transition-colors",
                t.id === currentTenant?.id
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              <Building2 className="h-3.5 w-3.5" />
              {t.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Project Selector ── */
function ProjectSelector() {
  const { projects, currentProject, setCurrentProject, projectsLoading } = useTenantProject();
  const [open, setOpen] = useState(false);
  const [projectFilter, setProjectFilter] = useState("");
  const navigate = useNavigate();
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  const toggleOpen = useCallback(() => {
    setOpen((prev) => {
      if (!prev) {
        setProjectFilter("");
      }
      return !prev;
    });
  }, []);

  useClickOutside(ref, close);

  const filteredProjects = useMemo(() => {
    const normalized = projectFilter.trim().toLowerCase();
    if (!normalized) return projects;
    return projects.filter((project) => {
      const target = `${project.name} ${project.description ?? ""}`.toLowerCase();
      return target.includes(normalized);
    });
  }, [projects, projectFilter]);

  const goCreateProject = useCallback(() => {
    setOpen(false);
    navigate("/projects/new");
  }, [navigate]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={toggleOpen}
        className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-sm text-sidebar-foreground hover:bg-accent hover:text-sidebar-active transition-colors"
      >
        <FolderKanban className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate flex-1 text-left">{currentProject?.name ?? "プロジェクトを選択"}</span>
        <ChevronsUpDown className="h-3 w-3 shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-80 min-w-0 overflow-hidden rounded-md border border-border bg-card shadow-lg">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <p className="text-xs font-medium text-foreground">プロジェクト</p>
            <button
              type="button"
              onClick={goCreateProject}
              className="flex items-center gap-1 text-xs font-medium text-primary transition-colors hover:text-primary/80"
            >
              <FolderPlus className="h-3.5 w-3.5" />
              新規作成
            </button>
          </div>
          <div className="border-b border-border p-2">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
              <input
                value={projectFilter}
                onChange={(event) => setProjectFilter(event.target.value)}
                placeholder="プロジェクトを検索"
                className="w-full rounded-md border border-input bg-background py-1.5 pl-7 pr-7 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              />
              {projectFilter && (
                <button
                  type="button"
                  onClick={() => setProjectFilter("")}
                  className="absolute right-2 top-1.5 text-muted-foreground hover:text-foreground"
                  aria-label="検索条件をクリア"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </label>
          </div>
          {projectsLoading && (
            <div className="flex items-center gap-2 px-3 py-3 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              プロジェクトを読み込み中...
            </div>
          )}
          {!projectsLoading && projects.length === 0 && (
            <div className="px-3 py-3 text-xs text-muted-foreground">
              まだプロジェクトがありません。
              <button
                type="button"
                onClick={goCreateProject}
                className="ml-1 text-primary underline-offset-4 hover:underline"
              >
                新規作成
              </button>
            </div>
          )}
          {filteredProjects.length === 0 ? (
            <div className="px-3 py-3 text-xs text-muted-foreground">
              該当するプロジェクトが見つかりませんでした。
            </div>
          ) : (
            <div className="max-h-56 overflow-y-auto">
              {filteredProjects.map((p) => (
                <button
                  key={p.id}
                  onClick={() => { setCurrentProject(p); setOpen(false); }}
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-1.5 text-sm transition-colors",
                    p.id === currentProject?.id
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )}
                >
                  <FolderKanban className="h-3.5 w-3.5" />
                  <div className="text-left">
                    <div>{p.name}</div>
                    {p.description && (
                      <div className="text-[11px] text-muted-foreground">{p.description}</div>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
          {projectFilter && filteredProjects.length > 0 && filteredProjects.length < projects.length && (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              {filteredProjects.length}件の表示
            </p>
          )}
          <p className="rounded-b-md border-t border-border px-3 py-2 text-xs text-muted-foreground">
            {projectsLoading ? "読み込み中..." : `${projects.length}件`}
            {projectFilter.trim() && filteredProjects.length !== projects.length
              ? ` / 条件に一致: ${filteredProjects.length}件`
              : ""}
          </p>
        </div>
      )}
    </div>
  );
}

/* ── Nav Item ── */
interface SidebarNavItemProps {
  to: string;
  icon: React.ElementType;
  label: string;
  collapsed: boolean;
  disabled?: boolean;
  badge?: number | string;
}

function SidebarNavItem({ to, icon: Icon, label, collapsed, disabled = false, badge }: SidebarNavItemProps) {
  if (disabled) {
    return (
      <div
        className={cn(
          "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground/50",
          collapsed && "justify-center px-2",
        )}
      >
        <Icon className="h-4 w-4 shrink-0" />
        {!collapsed && <span className="truncate">{label}</span>}
      </div>
    );
  }
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
          isActive
            ? "bg-accent text-sidebar-active"
            : "text-sidebar-foreground hover:bg-accent hover:text-sidebar-active",
          collapsed && "justify-center px-2",
        )
      }
    >
      <Icon className="h-4 w-4 shrink-0" />
      {!collapsed && <span className="truncate">{label}</span>}
      {!collapsed && badge != null && (typeof badge === "string" ? (
        <span className="ml-auto flex h-5 items-center justify-center rounded-md bg-primary/10 px-1.5 text-[10px] font-semibold text-primary">
          {badge}
        </span>
      ) : badge > 0 ? (
        <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1.5 text-xs text-primary-foreground">
          {badge}
        </span>
      ) : null)}
    </NavLink>
  );
}
