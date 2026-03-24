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
  Target,
  FolderPlus,
  Search,
  Wand2,
  Beaker,
  Loader2,
  X,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useFeatureFlags } from "@/contexts/FeatureFlagsContext";
import { useI18n } from "@/contexts/I18nContext";
import { useTenantProject } from "@/contexts/TenantProjectContext";
import { useClickOutside } from "@/hooks/useClickOutside";
import { useState, useRef, useCallback, useMemo } from "react";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  lockCollapsed?: boolean;
}

const PROJECT_NAV = [
  { to: "lifecycle", icon: Layers, labelKey: "sidebar.projectLifecycle", feature: "lifecycle" },
  { to: "experiments", icon: Beaker, labelKey: "sidebar.experiments", feature: "experiments" },
  { to: "studio", icon: Sparkles, labelKey: "sidebar.quickBuild", badge: "β", feature: "studio" },
  { to: "gtm", icon: Target, labelKey: "sidebar.gtm", feature: "gtm" },
  { to: "tasks", icon: Kanban, labelKey: "sidebar.tasks", feature: "tasks" },
  { to: "team", icon: Users, labelKey: "sidebar.team", feature: "team" },
  { to: "memory", icon: Brain, labelKey: "sidebar.memory", feature: "memory" },
  { to: "calendar", icon: CalendarDays, labelKey: "sidebar.calendar", feature: "calendar" },
  { to: "content", icon: FileText, labelKey: "sidebar.content", feature: "content" },
  { to: "ads", icon: Megaphone, labelKey: "sidebar.ads", feature: "ads" },
  { to: "issues", icon: CircleDot, labelKey: "sidebar.issues", feature: "issues" },
  { to: "pulls", icon: GitPullRequest, labelKey: "sidebar.pulls", feature: "pulls" },
  { to: "runs", icon: Play, labelKey: "sidebar.runs", feature: "runs" },
  { to: "approvals", icon: ShieldCheck, labelKey: "sidebar.approvals", feature: "approvals" },
] as const;

const ADMIN_ITEMS = [
  { to: "/dashboard", icon: LayoutDashboard, labelKey: "sidebar.dashboard", feature: "dashboard" },
  { to: "/workflows", icon: GitBranch, labelKey: "sidebar.workflows", feature: "workflows" },
  { to: "/agents", icon: Bot, labelKey: "sidebar.agents", feature: "agents" },
  { to: "/costs", icon: DollarSign, labelKey: "sidebar.costs", feature: "costs" },
  { to: "/providers", icon: Server, labelKey: "sidebar.providers", feature: "providers" },
  { to: "/models", icon: Cpu, labelKey: "sidebar.models", feature: "models" },
  { to: "/skills", icon: Wand2, labelKey: "sidebar.skills", feature: "skills" },
] as const;
const QUICK_ADMIN_ITEMS = [
  { to: "/projects/new", icon: FolderPlus, labelKey: "sidebar.newProject" },
] as const;

const BOTTOM_ITEMS = [
  { to: "/settings", icon: Settings, labelKey: "sidebar.settings", feature: "settings" },
] as const;

export function Sidebar({ collapsed, onToggle, lockCollapsed = false }: SidebarProps) {
  const { t } = useI18n();
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
            {t("common.project")}
          </p>
        )}
        {projectItems.map((item) => (
          <SidebarNavItem
            key={item.to}
            to={projectBase ? `${projectBase}/${item.to}` : ""}
            icon={item.icon}
            label={t(item.labelKey)}
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
            {t("common.admin")}
          </p>
        )}
        {QUICK_ADMIN_ITEMS.map((item) => (
          <SidebarNavItem key={item.to} to={item.to} icon={item.icon} label={t(item.labelKey)} collapsed={collapsed} />
        ))}
        {adminItems.map((item) => (
          <SidebarNavItem key={item.to} to={item.to} icon={item.icon} label={t(item.labelKey)} collapsed={collapsed} />
        ))}
      </nav>

      {/* Bottom nav */}
      <nav className="border-t border-border p-2">
        {bottomItems.map((item) => (
          <SidebarNavItem key={item.to} to={item.to} icon={item.icon} label={t(item.labelKey)} collapsed={collapsed} />
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
  const { t } = useI18n();
  const { projects, currentProject, setCurrentProject, deleteProject, projectsLoading } = useTenantProject();
  const [open, setOpen] = useState(false);
  const [projectFilter, setProjectFilter] = useState("");
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null);
  const [projectPendingDelete, setProjectPendingDelete] = useState<{ slug: string; name: string } | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
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

  const handleDeleteProject = useCallback(async () => {
    if (!projectPendingDelete) return;
    setDeleteError(null);
    setDeletingProjectId(projectPendingDelete.slug);
    try {
      await deleteProject(projectPendingDelete.slug);
      setProjectPendingDelete(null);
      setOpen(false);
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : t("sidebar.deleteProjectFailed"));
    } finally {
      setDeletingProjectId(null);
    }
  }, [deleteProject, projectPendingDelete, t]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={toggleOpen}
        className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-sm text-sidebar-foreground hover:bg-accent hover:text-sidebar-active transition-colors"
      >
        <FolderKanban className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate flex-1 text-left">{currentProject?.name ?? t("common.selectProject")}</span>
        <ChevronsUpDown className="h-3 w-3 shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-80 min-w-0 overflow-hidden rounded-md border border-border bg-card shadow-lg">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <p className="text-xs font-medium text-foreground">{t("sidebar.projects")}</p>
            <button
              type="button"
              onClick={goCreateProject}
              className="flex items-center gap-1 text-xs font-medium text-primary transition-colors hover:text-primary/80"
            >
              <FolderPlus className="h-3.5 w-3.5" />
              {t("common.create")}
            </button>
          </div>
          <div className="border-b border-border p-2">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
              <input
                value={projectFilter}
                onChange={(event) => setProjectFilter(event.target.value)}
                placeholder={t("common.searchProjects")}
                className="w-full rounded-md border border-input bg-background py-1.5 pl-7 pr-7 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              />
              {projectFilter && (
                <button
                  type="button"
                  onClick={() => setProjectFilter("")}
                  className="absolute right-2 top-1.5 text-muted-foreground hover:text-foreground"
                  aria-label={t("common.clearSearch")}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </label>
          </div>
          {projectsLoading && (
            <div className="flex items-center gap-2 px-3 py-3 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t("sidebar.projectsLoading")}
            </div>
          )}
          {!projectsLoading && projects.length === 0 && (
            <div className="px-3 py-3 text-xs text-muted-foreground">
              {t("sidebar.noProjects")}
              <button
                type="button"
                onClick={goCreateProject}
                className="ml-1 text-primary underline-offset-4 hover:underline"
              >
                {t("common.create")}
              </button>
            </div>
          )}
          {filteredProjects.length === 0 ? (
            <div className="px-3 py-3 text-xs text-muted-foreground">
              {t("sidebar.noProjectsFound")}
            </div>
          ) : (
            <div className="max-h-56 overflow-y-auto">
              {filteredProjects.map((p) => (
                <div
                  key={p.id}
                  className={cn(
                    "group flex items-start gap-2 px-2 py-1.5 text-sm transition-colors",
                    p.id === currentProject?.id
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => { setCurrentProject(p); setOpen(false); }}
                    className="flex min-w-0 flex-1 items-start gap-2 rounded-md px-1 py-0.5 text-left"
                  >
                    <FolderKanban className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <div className="min-w-0">
                      <div className="truncate">{p.name}</div>
                      {p.description && (
                        <div className="line-clamp-2 text-[11px] text-muted-foreground">{p.description}</div>
                      )}
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      setDeleteError(null);
                      setProjectPendingDelete({ slug: p.slug, name: p.name });
                    }}
                    disabled={deletingProjectId === p.slug}
                    className={cn(
                      "mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground/70 transition-colors hover:bg-background hover:text-destructive disabled:cursor-not-allowed disabled:opacity-60",
                      deletingProjectId !== p.slug && "opacity-60 group-hover:opacity-100 group-focus-within:opacity-100",
                    )}
                    aria-label={t("sidebar.deleteProject", { name: p.name })}
                    title={t("sidebar.deleteProject", { name: p.name })}
                  >
                    {deletingProjectId === p.slug ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                  </button>
                </div>
              ))}
            </div>
          )}
          {projectFilter && filteredProjects.length > 0 && filteredProjects.length < projects.length && (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              {t("common.resultsCount", { count: filteredProjects.length })}
            </p>
          )}
          <p className="rounded-b-md border-t border-border px-3 py-2 text-xs text-muted-foreground">
            {projectsLoading ? t("common.loading") : t("common.totalCount", { count: projects.length })}
            {projectFilter.trim() && filteredProjects.length !== projects.length
              ? t("common.matchingCount", { count: filteredProjects.length })
              : ""}
          </p>
        </div>
      )}
      {projectPendingDelete && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center p-4">
          <button
            type="button"
            className="absolute inset-0 bg-slate-950/72 backdrop-blur-sm"
            onClick={() => {
              if (!deletingProjectId) {
                setProjectPendingDelete(null);
              }
            }}
            aria-label={t("sidebar.closeDeleteProjectDialog")}
          />
          <div className="relative w-full max-w-md overflow-hidden rounded-[28px] border border-white/10 bg-[#07111f] text-slate-50 shadow-[0_32px_120px_rgba(2,6,23,0.56)]">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(248,113,113,0.18),transparent_36%),radial-gradient(circle_at_85%_15%,rgba(56,189,248,0.12),transparent_24%),linear-gradient(180deg,rgba(7,17,31,0.96),rgba(7,12,24,0.98))]" />
            <div className="relative space-y-5 p-6">
              <div className="inline-flex h-11 w-11 items-center justify-center rounded-2xl border border-rose-300/20 bg-rose-300/12 text-rose-100">
                <Trash2 className="h-5 w-5" />
              </div>
              <div className="space-y-2">
                <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-rose-100/75">
                  {t("sidebar.deleteProjectEyebrow")}
                </p>
                <h3 className="text-2xl font-semibold tracking-tight text-white">
                  {t("sidebar.deleteProjectTitle")}
                </h3>
                <p className="text-sm leading-6 text-slate-300">
                  {t("sidebar.deleteProjectDescription", { name: projectPendingDelete.name })}
                </p>
              </div>
              {deleteError && (
                <div className="rounded-2xl border border-rose-300/20 bg-rose-300/10 px-4 py-3 text-sm text-rose-100">
                  {deleteError}
                </div>
              )}
              <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                <p className="text-[11px] uppercase tracking-[0.22em] text-slate-400">
                  {t("sidebar.deleteProjectImpactTitle")}
                </p>
                <ul className="mt-3 space-y-2 text-sm text-slate-200">
                  <li>{t("sidebar.deleteProjectImpactOne")}</li>
                  <li>{t("sidebar.deleteProjectImpactTwo")}</li>
                  <li>{t("sidebar.deleteProjectImpactThree")}</li>
                </ul>
              </div>
              <div className="flex items-center justify-end gap-3">
                <Button
                  type="button"
                  variant="ghost"
                  className="rounded-xl border border-white/10 bg-white/[0.04] px-4 text-slate-200 hover:bg-white/[0.08] hover:text-white"
                  onClick={() => setProjectPendingDelete(null)}
                  disabled={!!deletingProjectId}
                >
                  {t("common.cancel")}
                </Button>
                <Button
                  type="button"
                  className="rounded-xl bg-rose-500 px-4 text-white hover:bg-rose-400"
                  onClick={() => void handleDeleteProject()}
                  disabled={!!deletingProjectId}
                >
                  {deletingProjectId ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                  {t("sidebar.deleteProjectAction")}
                </Button>
              </div>
            </div>
          </div>
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
