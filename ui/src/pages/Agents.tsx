import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, Link } from "react-router-dom";
import { Bot, Plus, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { PageSkeleton } from "@/components/PageSkeleton";
import { queryKeys } from "@/lib/queryKeys";
import { agentsApi, type Agent } from "@/api/agents";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "paused", label: "Paused" },
  { key: "error", label: "Error" },
] as const;

const TAB_FILTERS: Record<string, (a: Agent) => boolean> = {
  all: () => true,
  active: (a) => a.status === "running" || a.status === "ready",
  paused: (a) => a.status === "paused",
  error: (a) => a.status === "failed" || a.status === "killed",
};

export function Agents() {
  const [currentTab, setCurrentTab] = useState("all");
  const navigate = useNavigate();

  const query = useQuery({
    queryKey: queryKeys.agents.list(),
    queryFn: () => agentsApi.list(),
    refetchInterval: 10_000,
  });

  if (query.isLoading) return <PageSkeleton />;

  const agents = query.data ?? [];
  const filterFn = TAB_FILTERS[currentTab] ?? TAB_FILTERS["all"];
  const filtered = agents.filter(filterFn);

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">エージェント一覧</h1>
          <p className="text-sm text-muted-foreground">
            {agents.length} エージェント登録済み
          </p>
        </div>
        <Button size="sm" onClick={() => navigate("/agents/new")}>
          <Plus className="mr-1 h-4 w-4" />
          エージェント追加
        </Button>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-border">
        {TABS.map((tab) => {
          const isActive = currentTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setCurrentTab(tab.key)}
              className={cn(
                "border-b-2 px-4 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Agent list */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={Bot}
          title="No agents found"
          description="Create your first agent to get started."
          action={{ label: "New Agent", onClick: () => navigate("/agents/new") }}
        />
      ) : (
        <div className="space-y-2">
          {filtered.map((agent) => (
            <Link
              key={agent.id}
              to={`/agents/${agent.id}`}
              className="flex items-center justify-between rounded-lg border border-border p-4 transition-colors hover:bg-accent"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Bot className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium">{agent.name}</span>
                </div>
                <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                  <span>{agent.model}</span>
                  <span>|</span>
                  <span>{agent.role}</span>
                  <span>|</span>
                  <span>{agent.autonomy}</span>
                  {agent.skills && agent.skills.length > 0 && (
                    <>
                      <span>|</span>
                      <span className="inline-flex items-center gap-1">
                        <Wand2 className="h-3 w-3" />
                        {agent.skills.length} スキル
                      </span>
                    </>
                  )}
                </div>
              </div>
              <StatusBadge status={agent.status} />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
