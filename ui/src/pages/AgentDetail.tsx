import { useState, useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, X, Check, Plus, Loader2, Wand2 } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { PageSkeleton } from "@/components/PageSkeleton";
import { queryKeys } from "@/lib/queryKeys";
import { agentsApi } from "@/api/agents";
import { skillsApi, type SkillInfo } from "@/api/skills";
import { cn } from "@/lib/utils";

export function AgentDetail() {
  const { agentId } = useParams<{ agentId: string }>();
  const queryClient = useQueryClient();
  const [showSkillPanel, setShowSkillPanel] = useState(false);

  const query = useQuery({
    queryKey: queryKeys.agents.detail(agentId!),
    queryFn: () => agentsApi.get(agentId!),
    enabled: !!agentId,
  });

  const skillsQuery = useQuery({
    queryKey: [...queryKeys.agents.detail(agentId!), "skills"],
    queryFn: () => agentsApi.getSkills(agentId!),
    enabled: !!agentId,
  });

  const allSkillsQuery = useQuery({
    queryKey: queryKeys.skills.all,
    queryFn: () => skillsApi.list(),
    enabled: showSkillPanel,
  });

  const updateSkillsMutation = useMutation({
    mutationFn: (skills: string[]) => agentsApi.updateSkills(agentId!, skills),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.agents.detail(agentId!) });
      setShowSkillPanel(false);
    },
  });

  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data) {
    return (
      <div className="p-6">
        <p className="text-sm text-destructive">Agent not found</p>
      </div>
    );
  }

  const agent = query.data;
  const assignedSkills = skillsQuery.data?.skills ?? [];
  const assignedSkillIds = new Set(assignedSkills.map((s) => s.id));

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center gap-3">
        <Link to="/agents" className="rounded-md p-1 hover:bg-accent">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <Bot className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-2xl font-bold tracking-tight">{agent.name}</h1>
        <StatusBadge status={agent.status} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="space-y-3">
              <PropertyRow label="Model" value={agent.model} />
              <PropertyRow label="Role" value={agent.role} />
              <PropertyRow label="Autonomy" value={agent.autonomy} />
              <PropertyRow label="Status" value={agent.status} />
              <PropertyRow label="Sandbox" value={agent.sandbox} />
              <PropertyRow label="Tools" value={agent.tools.join(", ")} />
            </dl>
          </CardContent>
        </Card>

        {/* Assigned Skills */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">割り当てスキル</CardTitle>
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs"
                onClick={() => setShowSkillPanel(true)}
              >
                <Plus className="mr-1 h-3 w-3" />
                スキルを追加
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {skillsQuery.isLoading ? (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : assignedSkills.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-6 text-center">
                <Wand2 className="mb-2 h-8 w-8 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground">
                  スキルが割り当てられていません
                </p>
                <p className="mt-1 text-xs text-muted-foreground/70">
                  「スキルを追加」からスキルを割り当てできます
                </p>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {assignedSkills.map((skill) => (
                  <SkillBadge
                    key={skill.id}
                    skill={skill}
                    onRemove={() => {
                      const next = assignedSkills
                        .filter((s) => s.id !== skill.id)
                        .map((s) => s.id);
                      updateSkillsMutation.mutate(next);
                    }}
                  />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Skill Assignment Panel */}
      {showSkillPanel && (
        <SkillAssignmentPanel
          assignedSkillIds={assignedSkillIds}
          allSkills={allSkillsQuery.data?.skills ?? []}
          isLoading={allSkillsQuery.isLoading}
          isSaving={updateSkillsMutation.isPending}
          error={updateSkillsMutation.error}
          onSave={(ids) => updateSkillsMutation.mutate(ids)}
          onClose={() => setShowSkillPanel(false)}
        />
      )}
    </div>
  );
}

function PropertyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-border pb-2 last:border-0">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{value}</dd>
    </div>
  );
}

function SkillBadge({ skill, onRemove }: { skill: SkillInfo; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs font-medium text-foreground">
      <Wand2 className="h-3 w-3 text-muted-foreground" />
      {skill.name}
      <button
        onClick={onRemove}
        className="ml-0.5 rounded-full p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Skill Assignment Panel
// ---------------------------------------------------------------------------

const CATEGORY_COLORS: Record<string, string> = {
  development: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  security: "bg-red-500/10 text-red-400 border-red-500/20",
  devops: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  documentation: "bg-green-500/10 text-green-400 border-green-500/20",
};

function SkillAssignmentPanel({
  assignedSkillIds,
  allSkills,
  isLoading,
  isSaving,
  error,
  onSave,
  onClose,
}: {
  assignedSkillIds: Set<string>;
  allSkills: SkillInfo[];
  isLoading: boolean;
  isSaving: boolean;
  error: Error | null;
  onSave: (ids: string[]) => void;
  onClose: () => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set(assignedSkillIds));
  const [search, setSearch] = useState("");

  const grouped = useMemo(() => {
    const map = new Map<string, SkillInfo[]>();
    const lower = search.toLowerCase();
    for (const skill of allSkills) {
      if (lower && !skill.name.toLowerCase().includes(lower) && !skill.description.toLowerCase().includes(lower)) {
        continue;
      }
      const cat = skill.category || "other";
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(skill);
    }
    return map;
  }, [allSkills, search]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />
      <aside className="fixed inset-y-0 right-0 z-50 flex w-[480px] flex-col border-l border-border bg-background shadow-2xl animate-in slide-in-from-right duration-200">
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-foreground">スキル割り当て</h2>
            <p className="text-xs text-muted-foreground">
              {selected.size} 件選択中
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Search */}
        <div className="border-b border-border px-6 py-3">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="スキルを検索..."
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        {/* Skill list */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : grouped.size === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              スキルが見つかりません
            </p>
          ) : (
            Array.from(grouped.entries()).map(([category, skills]) => (
              <div key={category}>
                <h3 className="mb-2 flex items-center gap-2">
                  <span
                    className={cn(
                      "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
                      CATEGORY_COLORS[category] ?? "bg-muted text-muted-foreground border-border",
                    )}
                  >
                    {category}
                  </span>
                  <span className="text-xs text-muted-foreground">{skills.length}件</span>
                </h3>
                <div className="space-y-1">
                  {skills.map((skill) => {
                    const isChecked = selected.has(skill.id);
                    return (
                      <button
                        key={skill.id}
                        type="button"
                        onClick={() => toggle(skill.id)}
                        className={cn(
                          "flex w-full items-start gap-3 rounded-md border px-3 py-2.5 text-left transition-colors",
                          isChecked
                            ? "border-primary/40 bg-primary/5"
                            : "border-border hover:bg-accent/50",
                        )}
                      >
                        <div
                          className={cn(
                            "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors",
                            isChecked
                              ? "border-primary bg-primary text-primary-foreground"
                              : "border-muted-foreground/30",
                          )}
                        >
                          {isChecked && <Check className="h-3 w-3" />}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium text-foreground">
                            {skill.name}
                          </div>
                          <div className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                            {skill.description}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-border px-6 py-4">
          {error && (
            <div className="mb-3 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
              保存エラー: {error.message}
            </div>
          )}
          <div className="flex items-center justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={onClose}>
              キャンセル
            </Button>
            <Button
              size="sm"
              disabled={isSaving}
              onClick={() => onSave(Array.from(selected))}
            >
              {isSaving ? (
                <>
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                  保存中...
                </>
              ) : (
                "保存"
              )}
            </Button>
          </div>
        </div>
      </aside>
    </>
  );
}
