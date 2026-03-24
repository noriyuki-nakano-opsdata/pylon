import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Bot, GitBranch, DollarSign, FolderPlus, ShieldCheck } from "lucide-react";
import { MetricCard } from "@/components/MetricCard";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { PageSkeleton } from "@/components/PageSkeleton";
import { queryKeys } from "@/lib/queryKeys";
import { healthApi } from "@/api/health";
import { agentsApi, type Agent } from "@/api/agents";
import { approvalsApi } from "@/api/approvals";
import { workflowsApi } from "@/api/workflows";
import { useI18n } from "@/contexts/I18nContext";

export function Dashboard() {
  const { t } = useI18n();
  const healthQuery = useQuery({
    queryKey: queryKeys.health,
    queryFn: () => healthApi.get(),
    refetchInterval: 10_000,
  });

  const agentsQuery = useQuery({
    queryKey: queryKeys.agents.list(),
    queryFn: () => agentsApi.list(),
    refetchInterval: 10_000,
  });

  const approvalsQuery = useQuery({
    queryKey: queryKeys.approvals.list("all"),
    queryFn: () => approvalsApi.list(),
    refetchInterval: 10_000,
  });

  const workflowsQuery = useQuery({
    queryKey: queryKeys.workflows.list(),
    queryFn: () => workflowsApi.list(),
    refetchInterval: 10_000,
  });

  if (healthQuery.isLoading) return <PageSkeleton />;

  const health = healthQuery.data;
  const agents = agentsQuery.data ?? [];
  const approvals = approvalsQuery.data ?? [];
  const workflows = workflowsQuery.data ?? [];
  const activeAgents = agents.filter((a) => a.status === "running");
  const pendingApprovals = approvals.filter((a) => a.status === "pending");

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t("dashboard.title")}</h1>
        <p className="text-sm text-muted-foreground">
          {t("dashboard.description")}
        </p>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title={t("dashboard.activeAgents")}
          value={activeAgents.length}
          icon={Bot}
          description={t("dashboard.totalAgents", { count: agents.length })}
        />
        <MetricCard
          title={t("dashboard.workflows")}
          value={workflows.length}
          icon={GitBranch}
          description={t("dashboard.workflowsRegistered")}
        />
        <MetricCard
          title={t("dashboard.systemStatus")}
          value={health?.status ? t(`status.${health.status}`) : t("common.status.unknown")}
          icon={DollarSign}
          description={t("dashboard.healthChecks", { count: health?.checks.length ?? 0 })}
        />
        <MetricCard
          title={t("dashboard.pendingApprovals")}
          value={pendingApprovals.length}
          icon={ShieldCheck}
          description={t("dashboard.totalApprovals", { count: approvals.length })}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("common.quickActions")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 text-sm">
            <p className="text-muted-foreground">
              {t("dashboard.quickActions.description")}
            </p>
            <Link
              to="/projects/new"
              className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-accent hover:text-foreground transition-colors"
            >
              <FolderPlus className="h-4 w-4" />
              {t("dashboard.quickActions.createProject")}
            </Link>
          </div>
        </CardContent>
      </Card>

      {/* Two columns */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Agents Panel */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t("dashboard.agentsPanel", { count: agents.length })}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {agents.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("dashboard.noAgents")}</p>
            ) : (
              <div className="space-y-3">
                {agents.slice(0, 8).map((agent) => (
                  <AgentRow key={agent.id} agent={agent} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Pending Approvals */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t("dashboard.pendingApprovalsPanel", { count: pendingApprovals.length })}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {pendingApprovals.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t("dashboard.noPendingApprovals")}
              </p>
            ) : (
              <div className="space-y-3">
                {pendingApprovals.slice(0, 5).map((a) => (
                  <div
                    key={a.id}
                    className="flex items-center justify-between rounded-md border border-border p-3"
                  >
                    <div>
                      <p className="text-sm font-medium">{a.agent_id}</p>
                      <p className="text-xs text-muted-foreground">
                        {a.action}
                      </p>
                    </div>
                    <StatusBadge status={a.status} />
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function AgentRow({ agent }: { agent: Agent }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-border p-3">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{agent.name}</p>
        <p className="text-xs text-muted-foreground">{agent.model}</p>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">{agent.autonomy}</span>
        <StatusBadge status={agent.status} />
      </div>
    </div>
  );
}
