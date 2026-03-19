import { useQuery } from "@tanstack/react-query";
import { GitBranch } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { PageSkeleton } from "@/components/PageSkeleton";
import { queryKeys } from "@/lib/queryKeys";
import { workflowsApi } from "@/api/workflows";
import { useI18n } from "@/contexts/I18nContext";

export function Workflows() {
  const { t } = useI18n();
  const query = useQuery({
    queryKey: queryKeys.workflows.list(),
    queryFn: () => workflowsApi.list(),
  });

  if (query.isLoading) return <PageSkeleton />;

  const workflows = query.data ?? [];

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t("workflows.title")}</h1>
        <p className="text-sm text-muted-foreground">
          {t("workflows.definedCount", { count: workflows.length })}
        </p>
      </div>

      {workflows.length === 0 ? (
        <EmptyState
          icon={GitBranch}
          title={t("workflows.empty.title")}
          description={t("workflows.empty.description")}
          action={{ label: t("workflows.empty.action"), onClick: () => window.location.reload() }}
        />
      ) : (
        <div className="space-y-2">
          {workflows.map((wf) => (
            <div
              key={wf.id}
              className="flex items-center justify-between rounded-lg border border-border p-4"
            >
              <div>
                <p className="font-medium">{wf.project_name}</p>
                <p className="text-xs text-muted-foreground">
                  {t("workflows.agentNodeCount", { agents: wf.agent_count, nodes: wf.node_count })}
                </p>
              </div>
              <StatusBadge status={wf.goal_enabled ? "active" : "ready"} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
