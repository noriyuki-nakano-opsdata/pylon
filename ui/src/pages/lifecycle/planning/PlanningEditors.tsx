import {
  ArrowDown,
  Bot,
  Check,
  CheckSquare,
  ChevronRight,
  Clock,
  DollarSign,
  Flag,
  GanttChart,
  Layers,
  Plus,
  Sparkles,
  Square,
  Trash2,
  Users,
  Wrench,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import type {
  FeatureSelection,
  Milestone,
  PlanEstimate,
  PlanPreset,
  RecommendedMilestone,
  WbsItem,
} from "@/types/lifecycle";

export function FeaturesContent({ features, setFeatures }: { features: FeatureSelection[]; setFeatures: (f: FeatureSelection[]) => void }) {
  const toggle = (idx: number) => {
    const next = [...features];
    if (next[idx].category === "must-be") return;
    next[idx] = { ...next[idx], selected: !next[idx].selected };
    setFeatures(next);
  };

  const setPriority = (idx: number, priority: FeatureSelection["priority"]) => {
    const next = [...features];
    next[idx] = { ...next[idx], priority };
    setFeatures(next);
  };

  const selectPreset = (preset: "minimal" | "recommended" | "full") => {
    setFeatures(features.map((feature) => {
      if (feature.category === "must-be") return { ...feature, selected: true };
      if (preset === "minimal") return { ...feature, selected: false };
      if (preset === "full") return { ...feature, selected: true };
      return {
        ...feature,
        selected:
          feature.category === "one-dimensional"
          || (feature.category === "attractive" && feature.user_delight >= 0.7),
      };
    }));
  };

  const selectedCount = features.filter((feature) => feature.selected).length;
  const groups = [
    { title: "Must-Be（必須機能）", desc: "製品として必須。除外不可。", category: "must-be", locked: true },
    { title: "One-Dimensional（性能機能）", desc: "実装の質に比例して満足度が上がる。", category: "one-dimensional", locked: false },
    { title: "Attractive（魅力機能）", desc: "あると感動する差別化機能。", category: "attractive", locked: false },
  ] as const;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-xs text-muted-foreground">{selectedCount}/{features.length} 選択中</span>
        <div className="flex flex-wrap gap-1">
          {(["minimal", "recommended", "full"] as const).map((preset) => (
            <button key={preset} onClick={() => selectPreset(preset)} className="rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
              {preset === "minimal" ? "最小" : preset === "recommended" ? "推奨" : "全機能"}
            </button>
          ))}
        </div>
      </div>

      {groups.map((group) => {
        const groupFeatures = features.filter((feature) => feature.category === group.category);
        if (groupFeatures.length === 0) return null;
        return (
          <div key={group.category}>
            <h3 className="text-sm font-bold text-foreground">{group.title}</h3>
            <p className="text-xs text-muted-foreground mb-3">{group.desc}</p>
            <div className="space-y-2">
              {groupFeatures.map((feature) => {
                const idx = features.indexOf(feature);
                const catColor: Record<string, string> = {
                  "must-be": "border-destructive/30 bg-destructive/5",
                  "one-dimensional": "border-primary/30 bg-primary/5",
                  attractive: "border-success/30 bg-success/5",
                };
                return (
                  <div key={feature.feature} className={cn("flex items-center gap-3 rounded-lg border p-3 transition-colors", feature.selected ? catColor[feature.category] || "border-border" : "border-border bg-card opacity-60")}>
                    <button onClick={() => toggle(idx)} disabled={group.locked} className={cn(group.locked && "cursor-not-allowed")}>
                      {feature.selected ? <CheckSquare className="h-5 w-5 text-primary" /> : <Square className="h-5 w-5 text-muted-foreground" />}
                    </button>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-foreground">{feature.feature}</p>
                      <p className="text-xs text-muted-foreground truncate">{feature.rationale}</p>
                    </div>
                    <Badge variant="outline" className="text-[10px] capitalize shrink-0">{feature.implementation_cost}</Badge>
                    {feature.selected && !group.locked && (
                      <div className="flex gap-0.5 shrink-0">
                        {(["must", "should", "could"] as const).map((priority) => (
                          <button key={priority} onClick={() => setPriority(idx, priority)} className={cn(
                            "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase transition-colors",
                            feature.priority === priority ? (priority === "must" ? "bg-destructive/20 text-destructive" : priority === "should" ? "bg-warning/20 text-warning" : "bg-primary/20 text-primary") : "text-muted-foreground hover:text-foreground",
                          )}>{priority}</button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

const PHASE_MILESTONE_STYLE: Record<string, { bg: string; text: string; label: string }> = {
  alpha: { bg: "bg-amber-500/15 border-amber-500/30", text: "text-amber-400", label: "Alpha" },
  beta: { bg: "bg-blue-500/15 border-blue-500/30", text: "text-blue-400", label: "Beta" },
  release: { bg: "bg-green-500/15 border-green-500/30", text: "text-green-400", label: "Release" },
};

export function MilestonesContent({ milestones, setMilestones, recommended }: { milestones: Milestone[]; setMilestones: (m: Milestone[]) => void; recommended?: RecommendedMilestone[] }) {
  const addMilestone = () => setMilestones([...milestones, { id: `ms-${Date.now()}`, name: "", criteria: "", status: "pending" }]);
  const update = (idx: number, field: "name" | "criteria", value: string) => {
    const next = [...milestones];
    next[idx] = { ...next[idx], [field]: value };
    setMilestones(next);
  };
  const remove = (idx: number) => setMilestones(milestones.filter((_, index) => index !== idx));
  const addPreset = (type: "feature" | "quality" | "responsive") => {
    const presets: Record<string, Milestone> = {
      feature: { id: `ms-${Date.now()}`, name: "全機能実装", criteria: "選択されたすべての機能が動作可能", status: "pending" },
      quality: { id: `ms-${Date.now() + 1}`, name: "コード品質", criteria: "エラーハンドリング、バリデーション、ローディング状態の適切な実装", status: "pending" },
      responsive: { id: `ms-${Date.now() + 2}`, name: "レスポンシブ", criteria: "モバイル・タブレット・デスクトップで正しく表示", status: "pending" },
    };
    setMilestones([...milestones, presets[type]]);
  };
  const adoptRecommended = (item: RecommendedMilestone) => {
    if (milestones.some((milestone) => milestone.id === item.id)) return;
    setMilestones([...milestones, { id: item.id, name: item.name, criteria: item.criteria, status: "pending" }]);
  };
  const adoptAll = () => {
    if (!recommended) return;
    const existing = new Set(milestones.map((milestone) => milestone.id));
    const nextMilestones = recommended
      .filter((item) => !existing.has(item.id))
      .map((item) => ({ id: item.id, name: item.name, criteria: item.criteria, status: "pending" as const }));
    if (nextMilestones.length > 0) setMilestones([...milestones, ...nextMilestones]);
  };
  const isAdopted = (id: string) => milestones.some((milestone) => milestone.id === id);

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-bold text-foreground"><Flag className="h-4 w-4 text-primary" />マイルストーン（完成条件）</h3>
          <p className="text-xs text-muted-foreground">条件をクリアするまでAIが自律的に改善を繰り返します（最大5回）</p>
        </div>
        <button onClick={addMilestone} className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors cursor-pointer">
          <Plus className="h-3.5 w-3.5" /> 追加
        </button>
      </div>
      {recommended && recommended.length > 0 && (
        <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <span className="text-sm font-medium text-foreground">AIおすすめマイルストーン</span>
              <span className="text-[10px] text-muted-foreground">（分析結果に基づく推奨）</span>
            </div>
            <button onClick={adoptAll} className="flex items-center gap-1 rounded-md bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary hover:bg-primary/20 transition-colors cursor-pointer">
              <Plus className="h-3 w-3" /> すべて採用
            </button>
          </div>
          <div className="space-y-2">
            {(["alpha", "beta", "release"] as const).map((phase) => {
              const items = recommended.filter((item) => item.phase === phase);
              if (items.length === 0) return null;
              const style = PHASE_MILESTONE_STYLE[phase];
              return (
                <div key={phase}>
                  <p className={cn("text-[10px] font-medium uppercase tracking-wide mb-1.5", style.text)}>{style.label} Phase</p>
                  <div className="space-y-1.5">
                    {items.map((item) => {
                      const adopted = isAdopted(item.id);
                      return (
                        <div key={item.id} className={cn("flex items-start gap-3 rounded-lg border p-3 transition-colors", adopted ? "border-success/30 bg-success/5" : "border-border bg-card hover:border-primary/30")}>
                          <button onClick={() => adoptRecommended(item)} disabled={adopted} className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded-full mt-0.5 transition-colors cursor-pointer", adopted ? "bg-success/20 text-success" : "bg-muted hover:bg-primary/20 hover:text-primary")}>
                            {adopted ? <Check className="h-3 w-3" /> : <Plus className="h-3 w-3" />}
                          </button>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-foreground">{item.name}</p>
                            <p className="text-xs text-muted-foreground mt-0.5">{item.criteria}</p>
                            <p className="text-[11px] text-muted-foreground/70 mt-1 italic">{item.rationale}</p>
                            {item.depends_on_use_cases && item.depends_on_use_cases.length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-1.5">
                                {item.depends_on_use_cases.map((useCase) => (
                                  <Badge key={useCase} variant="outline" className="text-[9px]">{useCase}</Badge>
                                ))}
                              </div>
                            )}
                          </div>
                          <Badge variant="outline" className={cn("text-[10px] shrink-0", style.text)}>{style.label}</Badge>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      {milestones.length === 0 && !recommended?.length && (
        <div className="rounded-lg border-2 border-dashed border-border p-8 text-center">
          <Flag className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" />
          <p className="text-sm text-muted-foreground mb-3">マイルストーン未定義（定義しなくても開発は可能）</p>
          <div className="flex flex-wrap items-center justify-center gap-2">
            <button onClick={() => addPreset("feature")} className="rounded-md bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 cursor-pointer">全機能実装</button>
            <button onClick={() => addPreset("quality")} className="rounded-md bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 cursor-pointer">コード品質</button>
            <button onClick={() => addPreset("responsive")} className="rounded-md bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 cursor-pointer">レスポンシブ</button>
          </div>
        </div>
      )}
      {milestones.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">採用済みマイルストーン ({milestones.length})</p>
          {milestones.map((milestone, index) => (
            <div key={milestone.id} className="flex gap-3 rounded-lg border border-border bg-card p-3">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary mt-0.5">{index + 1}</div>
              <div className="flex-1 space-y-2">
                <input value={milestone.name} onChange={(event) => update(index, "name", event.target.value)} placeholder="マイルストーン名" className="w-full rounded border border-border bg-background px-2.5 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring" />
                <textarea value={milestone.criteria} onChange={(event) => update(index, "criteria", event.target.value)} placeholder="完成条件の詳細" rows={2} className="w-full rounded border border-border bg-background px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-none" />
              </div>
              <button onClick={() => remove(index)} className="shrink-0 text-muted-foreground hover:text-destructive transition-colors mt-0.5 cursor-pointer"><Trash2 className="h-4 w-4" /></button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const PRESET_CONFIG: Record<PlanPreset, { label: string; color: string; bg: string; desc: string }> = {
  minimal: { label: "Minimal", color: "text-green-500", bg: "bg-green-500/10 border-green-500/30", desc: "Must-haveのみ、最短・低コスト" },
  standard: { label: "Standard", color: "text-blue-500", bg: "bg-blue-500/10 border-blue-500/30", desc: "Must + Shouldの機能でバランス型" },
  full: { label: "Full", color: "text-purple-500", bg: "bg-purple-500/10 border-purple-500/30", desc: "全機能、最高品質、フルスキル活用" },
};

function PresetSelector({ plans, selected, onSelect }: {
  plans: PlanEstimate[];
  selected: PlanPreset;
  onSelect: (preset: PlanPreset) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {(["minimal", "standard", "full"] as const).map((preset) => {
        const plan = plans.find((item) => item.preset === preset);
        const cfg = PRESET_CONFIG[preset];
        const isActive = selected === preset;
        return (
          <button key={preset} onClick={() => onSelect(preset)} className={cn("rounded-xl border-2 p-4 text-left transition-all", isActive ? `${cfg.bg} border-current ${cfg.color}` : "border-border hover:border-primary/30")}>
            <div className="flex items-center justify-between mb-2">
              <span className={cn("text-sm font-bold", isActive ? cfg.color : "text-foreground")}>{cfg.label}</span>
              {isActive && <Check className="h-4 w-4" />}
            </div>
            <p className="text-[11px] text-muted-foreground mb-3">{cfg.desc}</p>
            {plan ? (
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <p className="text-[10px] text-muted-foreground">工数</p>
                  <p className="text-sm font-bold text-foreground">{plan.total_effort_hours}h</p>
                </div>
                <div>
                  <p className="text-[10px] text-muted-foreground">予算</p>
                  <p className="text-sm font-bold text-foreground">${plan.total_cost_usd.toFixed(0)}</p>
                </div>
                <div>
                  <p className="text-[10px] text-muted-foreground">期間</p>
                  <p className="text-sm font-bold text-foreground">{plan.duration_weeks}w</p>
                </div>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground italic">データなし</p>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function EpicsWbsContent({ planEstimates, selectedPreset, onSelectPreset }: {
  planEstimates: PlanEstimate[];
  selectedPreset: PlanPreset;
  onSelectPreset: (preset: PlanPreset) => void;
}) {
  const plan = planEstimates.find((item) => item.preset === selectedPreset);
  if (planEstimates.length === 0) {
    return (
      <div className="rounded-lg border-2 border-dashed border-border p-12 text-center">
        <Layers className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
        <p className="text-sm text-muted-foreground">プランデータが生成されていません</p>
        <p className="text-xs text-muted-foreground mt-1">分析を実行するとエピック/WBS/ガントチャートが生成されます</p>
      </div>
    );
  }
  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <PresetSelector plans={planEstimates} selected={selectedPreset} onSelect={onSelectPreset} />
      {plan && (
        <>
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-1.5 text-muted-foreground"><Bot className="h-3.5 w-3.5" /><span>{plan.agents_used.length} agents</span></div>
            <div className="flex items-center gap-1.5 text-muted-foreground"><Wrench className="h-3.5 w-3.5" /><span>{plan.skills_used.length} skills</span></div>
            <div className="flex items-center gap-1.5 text-muted-foreground"><Layers className="h-3.5 w-3.5" /><span>{plan.epics.length} epics / {plan.wbs.length} tasks</span></div>
          </div>
          {plan.epics.map((epic, index) => {
            const epicWbs = plan.wbs.filter((item) => item.epic_id === epic.id);
            return (
              <div key={epic.id} className="rounded-xl border border-border bg-card overflow-hidden">
                <div className="flex items-start gap-3 border-b border-border px-4 py-3 bg-accent/20">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-xs font-bold text-primary">E{index + 1}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-bold text-foreground">{epic.name}</p>
                      <Badge variant={epic.priority === "must" ? "destructive" : epic.priority === "should" ? "warning" : "secondary"} className="text-[10px]">{epic.priority}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{epic.description}</p>
                  </div>
                </div>
                {epic.use_cases.length > 0 && (
                  <div className="border-b border-border px-4 py-2.5 bg-accent/10">
                    <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">ユースケース</p>
                    <div className="flex flex-wrap gap-1.5">
                      {epic.use_cases.map((useCase, useCaseIndex) => (
                        <span key={useCaseIndex} className="rounded-md bg-background border border-border px-2 py-0.5 text-[11px] text-foreground">{useCase}</span>
                      ))}
                    </div>
                  </div>
                )}
                {epicWbs.length > 0 && (
                  <div className="divide-y divide-border">
                    <div className="flex items-center gap-3 px-4 py-1.5 bg-accent/5 text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                      <div className="w-48 shrink-0">タスク</div>
                      <div className="w-28 shrink-0">担当</div>
                      <div className="flex-1">スキル</div>
                      <div className="w-16 shrink-0 text-right">工数</div>
                      <div className="w-16 shrink-0 text-right">期間</div>
                      <div className="w-16 shrink-0">依存</div>
                    </div>
                    {epicWbs.map((item) => (
                      <WbsRow key={item.id} item={item} allItems={plan.wbs} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

function WbsRow({ item, allItems }: { item: WbsItem; allItems: WbsItem[] }) {
  const deps = item.depends_on
    .map((depId) => allItems.find((entry) => entry.id === depId))
    .filter(Boolean);
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 hover:bg-accent/20 transition-colors">
      <div className="w-48 shrink-0">
        <p className="text-xs font-medium text-foreground truncate">{item.title}</p>
        {item.description && <p className="text-[10px] text-muted-foreground truncate">{item.description}</p>}
      </div>
      <div className="flex items-center gap-1 w-28 shrink-0">
        {item.assignee_type === "agent" ? <Bot className="h-3 w-3 text-blue-500" /> : <Users className="h-3 w-3 text-orange-500" />}
        <span className="text-[11px] text-muted-foreground truncate">{item.assignee}</span>
      </div>
      <div className="flex gap-1 flex-1 min-w-0">
        {item.skills.slice(0, 3).map((skill) => (
          <Badge key={skill} variant="outline" className="text-[9px] shrink-0">{skill}</Badge>
        ))}
      </div>
      <div className="text-right w-16 shrink-0"><span className="text-xs font-mono text-foreground">{item.effort_hours}h</span></div>
      <div className="text-right w-16 shrink-0"><span className="text-[11px] text-muted-foreground">{item.duration_days}d</span></div>
      <div className="w-16 shrink-0">
        {deps.length > 0 ? (
          <span className="flex items-center gap-1 text-[10px] text-muted-foreground"><ArrowDown className="h-3 w-3" />{deps.length}</span>
        ) : (
          <span className="text-[10px] text-muted-foreground">—</span>
        )}
      </div>
    </div>
  );
}

export function GanttContent({ planEstimates, selectedPreset, onSelectPreset }: {
  planEstimates: PlanEstimate[];
  selectedPreset: PlanPreset;
  onSelectPreset: (preset: PlanPreset) => void;
}) {
  const plan = planEstimates.find((item) => item.preset === selectedPreset);
  if (planEstimates.length === 0) {
    return (
      <div className="rounded-lg border-2 border-dashed border-border p-12 text-center">
        <GanttChart className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
        <p className="text-sm text-muted-foreground">プランデータが生成されていません</p>
      </div>
    );
  }
  const wbs = plan?.wbs ?? [];
  const maxDay = Math.max(...wbs.map((item) => item.start_day + item.duration_days), 1);
  const totalWeeks = Math.ceil(maxDay / 7);
  const weekMarkers = Array.from({ length: totalWeeks }, (_, index) => index + 1);
  const epicIds = [...new Set(wbs.map((item) => item.epic_id))];
  const epics = plan?.epics ?? [];
  const epicColors = ["bg-blue-500", "bg-green-500", "bg-purple-500", "bg-orange-500", "bg-pink-500", "bg-cyan-500"];

  return (
    <div className="max-w-full mx-auto space-y-6">
      <PresetSelector plans={planEstimates} selected={selectedPreset} onSelect={onSelectPreset} />
      {plan && (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="flex items-center gap-3 border-b border-border px-4 py-2.5 bg-accent/20">
            <GanttChart className="h-4 w-4 text-primary" />
            <span className="text-sm font-bold text-foreground">プロジェクトタイムライン — {plan.duration_weeks}週間</span>
            <div className="flex-1" />
            <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
              <span><Clock className="h-3 w-3 inline mr-1" />{plan.total_effort_hours}h</span>
              <span><DollarSign className="h-3 w-3 inline mr-1" />${plan.total_cost_usd.toFixed(0)}</span>
            </div>
          </div>
          <div className="overflow-x-auto">
            <div style={{ minWidth: Math.max(600, totalWeeks * 100 + 200) }}>
              <div className="flex border-b border-border">
                <div className="w-48 shrink-0 px-3 py-1.5 text-[10px] font-medium text-muted-foreground border-r border-border">タスク</div>
                <div className="flex-1 flex">
                  {weekMarkers.map((week) => (
                    <div key={week} className="flex-1 px-1 py-1.5 text-center text-[10px] text-muted-foreground border-r border-border last:border-r-0">W{week}</div>
                  ))}
                </div>
              </div>
              {epicIds.map((epicId, groupIdx) => {
                const epic = epics.find((entry) => entry.id === epicId);
                const items = wbs.filter((entry) => entry.epic_id === epicId);
                const barColor = epicColors[groupIdx % epicColors.length];
                return (
                  <div key={epicId}>
                    <div className="flex border-b border-border bg-accent/10">
                      <div className="w-48 shrink-0 px-3 py-1.5 flex items-center gap-1.5">
                        <span className={cn("h-2 w-2 rounded-full", barColor)} />
                        <span className="text-[11px] font-bold text-foreground truncate">{epic?.name ?? epicId}</span>
                      </div>
                      <div className="flex-1" />
                    </div>
                    {items.map((item) => {
                      const leftPct = (item.start_day / maxDay) * 100;
                      const widthPct = Math.max((item.duration_days / maxDay) * 100, 2);
                      return (
                        <div key={item.id} className="flex border-b border-border last:border-b-0 hover:bg-accent/10 transition-colors">
                          <div className="w-48 shrink-0 px-3 py-2 flex items-center gap-2">
                            {item.assignee_type === "agent" ? <Bot className="h-3 w-3 text-blue-500 shrink-0" /> : <Users className="h-3 w-3 text-orange-500 shrink-0" />}
                            <div className="min-w-0">
                              <p className="text-[11px] text-foreground truncate">{item.title}</p>
                              <p className="text-[9px] text-muted-foreground truncate">{item.assignee} · {item.effort_hours}h</p>
                            </div>
                          </div>
                          <div className="flex-1 relative py-2">
                            <div className="absolute inset-0 flex">
                              {weekMarkers.map((week) => (
                                <div key={week} className="flex-1 border-r border-border/30 last:border-r-0" />
                              ))}
                            </div>
                            <div className={cn("absolute top-2.5 h-4 rounded-full flex items-center px-1.5", barColor, "opacity-80")} style={{ left: `${leftPct}%`, width: `${widthPct}%` }} title={`${item.title}: Day ${item.start_day}–${item.start_day + item.duration_days} (${item.effort_hours}h)`}>
                              <span className="text-[8px] text-white font-medium truncate">{item.duration_days}d</span>
                            </div>
                            {item.depends_on.length > 0 && (
                              <div className="absolute top-1 right-1">
                                <ChevronRight className="h-2.5 w-2.5 text-muted-foreground/50" />
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          </div>
          <div className="flex items-center gap-4 border-t border-border px-4 py-2">
            {epicIds.map((epicId, index) => {
              const epic = epics.find((entry) => entry.id === epicId);
              return (
                <div key={epicId} className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                  <span className={cn("h-2 w-2 rounded-full", epicColors[index % epicColors.length])} />
                  {epic?.name ?? epicId}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
