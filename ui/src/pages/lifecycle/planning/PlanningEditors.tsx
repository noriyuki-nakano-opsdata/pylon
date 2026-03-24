import { useMemo } from "react";
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
import {
  planningActionVariants,
  planningBodyLabelClassName,
  planningDetailCardVariants,
  planningEyebrowClassName,
  planningFieldClassName,
  planningMetricTileVariants,
  planningSectionTitleClassName,
  planningSoftBadgeVariants,
  planningSurfaceVariants,
} from "@/lifecycle/planningTheme";
import {
  buildPlanningFeatureDisplay,
  buildPlanningPlanEstimateDisplay,
  planningAssigneeTypeLabel,
  planningPresetDescription,
  planningPresetLabel,
  type PlanningDisplayWbsItem,
  type PlanningRecommendedMilestoneDisplay,
} from "@/lifecycle/planningDisplay";
import type {
  FeatureSelection,
  Milestone,
  PlanEstimate,
  PlanPreset,
} from "@/types/lifecycle";

export function FeaturesContent({ features, setFeatures }: { features: FeatureSelection[]; setFeatures: (f: FeatureSelection[]) => void }) {
  const displayFeatures = useMemo(() => buildPlanningFeatureDisplay(features), [features]);
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
    { category: "must-be", locked: true },
    { category: "one-dimensional", locked: false },
    { category: "attractive", locked: false },
  ] as const;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className={planningBodyLabelClassName}>{selectedCount}/{features.length} 選択中</span>
        <div className="flex flex-wrap gap-1">
          {(["minimal", "recommended", "full"] as const).map((preset) => (
            <button key={preset} onClick={() => selectPreset(preset)} className={cn(planningActionVariants({ tone: "secondary" }), "px-2.5 py-1 text-xs")}>
              {preset === "minimal" ? "最小" : preset === "recommended" ? "推奨" : "全機能"}
            </button>
          ))}
        </div>
      </div>

      {groups.map((group) => {
        const groupFeatures = displayFeatures.filter((feature) => feature.feature.category === group.category);
        if (groupFeatures.length === 0) return null;
        const groupMeta = groupFeatures[0];
        return (
          <div key={group.category}>
            <h3 className={planningSectionTitleClassName}>{groupMeta.categoryTitle}</h3>
            <p className={cn(planningBodyLabelClassName, "mb-3")}>{groupMeta.categoryDescription}</p>
            <div className="space-y-2">
              {groupFeatures.map((feature) => {
                const idx = feature.index;
                const catTone: Record<string, "danger" | "accent" | "success"> = {
                  "must-be": "danger",
                  "one-dimensional": "accent",
                  attractive: "success",
                };
                return (
                  <div key={feature.feature.feature} className={cn(
                    feature.feature.selected
                      ? planningDetailCardVariants({ tone: catTone[feature.feature.category] ?? "accent", padding: "sm" })
                      : planningSurfaceVariants({ tone: "inset", padding: "sm" }),
                    "flex items-center gap-3 transition-colors",
                    feature.feature.selected ? "" : "opacity-72",
                  )}>
                    <button onClick={() => toggle(idx)} disabled={group.locked} className={cn(group.locked && "cursor-not-allowed")}>
                      {feature.feature.selected ? <CheckSquare className="h-5 w-5 text-primary" /> : <Square className="h-5 w-5 text-muted-foreground" />}
                    </button>
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-medium text-foreground">{feature.displayFeature}</p>
                        <span className={cn(planningSoftBadgeVariants({ tone: "default" }), "shrink-0")}>{feature.costLabel}</span>
                      </div>
                      <p className={cn(planningBodyLabelClassName, "truncate")}>{feature.displayRationale}</p>
                    </div>
                    {feature.feature.selected && !group.locked && (
                      <div className="flex gap-1 shrink-0">
                        {(["must", "should", "could"] as const).map((priority) => (
                          <button key={priority} onClick={() => setPriority(idx, priority)} className={cn(
                            planningSoftBadgeVariants({
                              tone:
                                feature.feature.priority === priority
                                  ? priority === "must"
                                    ? "danger"
                                    : priority === "should"
                                      ? "warning"
                                      : "accent"
                                  : "default",
                            }),
                            "transition-colors",
                          )}>
                            {priority === "must" ? "必須" : priority === "should" ? "推奨" : "任意"}
                          </button>
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

const PHASE_MILESTONE_STYLE: Record<string, { tone: "warning" | "accent" | "success"; label: string }> = {
  alpha: { tone: "warning", label: "初期検証" },
  beta: { tone: "accent", label: "継続利用" },
  release: { tone: "success", label: "出荷準備" },
};

export function MilestonesContent({
  milestones,
  setMilestones,
  recommended,
}: {
  milestones: Milestone[];
  setMilestones: (m: Milestone[]) => void;
  recommended?: PlanningRecommendedMilestoneDisplay[];
}) {
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
  const adoptRecommended = (item: PlanningRecommendedMilestoneDisplay) => {
    if (milestones.some((milestone) => milestone.id === item.id)) return;
    setMilestones([...milestones, { id: item.canonical.id, name: item.canonical.name, criteria: item.canonical.criteria, status: "pending" }]);
  };
  const adoptAll = () => {
    if (!recommended) return;
    const existing = new Set(milestones.map((milestone) => milestone.id));
    const nextMilestones = recommended
      .filter((item) => !existing.has(item.id))
      .map((item) => ({ id: item.canonical.id, name: item.canonical.name, criteria: item.canonical.criteria, status: "pending" as const }));
    if (nextMilestones.length > 0) setMilestones([...milestones, ...nextMilestones]);
  };
  const isAdopted = (id: string) => milestones.some((milestone) => milestone.id === id);

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className={cn(planningSectionTitleClassName, "flex items-center gap-2")}><Flag className="h-4 w-4 text-primary" />マイルストーン（成功条件と停止条件）</h3>
          <p className={planningBodyLabelClassName}>何を満たせば進み、何が起きたら止めるかを先に決めておきます。</p>
        </div>
        <button onClick={addMilestone} className={cn(planningActionVariants({ tone: "secondary" }), "px-2.5 py-1 text-xs")}>
          <Plus className="h-3.5 w-3.5" /> 追加
        </button>
      </div>
      {recommended && recommended.length > 0 && (
        <div className={cn(planningSurfaceVariants({ tone: "accent", padding: "md" }), "space-y-3")}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <span className="text-sm font-medium text-foreground">AIおすすめマイルストーン</span>
              <span className="text-[10px] text-muted-foreground">（分析結果に基づく推奨）</span>
            </div>
            <button onClick={adoptAll} className={cn(planningActionVariants({ tone: "tonal" }), "px-2.5 py-1 text-xs")}>
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
                  <p className={cn(planningEyebrowClassName, "mb-1.5")}>{style.label}</p>
                  <div className="space-y-1.5">
                    {items.map((item) => {
                      const adopted = isAdopted(item.id);
                      return (
                        <div key={item.id} className={cn(
                          planningSurfaceVariants({ tone: adopted ? "success" : "inset", padding: "sm" }),
                          "flex items-start gap-3 transition-colors",
                        )}>
                          <button onClick={() => adoptRecommended(item)} disabled={adopted} className={cn("mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full transition-colors cursor-pointer", adopted ? planningSoftBadgeVariants({ tone: "success" }) : "bg-muted hover:bg-primary/20 hover:text-primary")}>
                            {adopted ? <Check className="h-3 w-3" /> : <Plus className="h-3 w-3" />}
                          </button>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-foreground">{item.displayName}</p>
                            <p className={cn(planningBodyLabelClassName, "mt-0.5")}>{item.displayCriteria}</p>
                            <p className="mt-1 text-[12px] italic text-[color:var(--planning-text-muted)]">{item.displayRationale}</p>
                            {item.displayDependsOnUseCases.length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-1.5">
                                {item.displayDependsOnUseCases.map((useCase) => (
                                  <span key={useCase} className={planningSoftBadgeVariants({ tone: "default" })}>{useCase}</span>
                                ))}
                              </div>
                            )}
                          </div>
                          <span className={cn(planningSoftBadgeVariants({ tone: style.tone }), "shrink-0")}>{style.label}</span>
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
        <div className={cn(planningSurfaceVariants({ tone: "subtle", padding: "lg" }), "border-dashed text-center")}>
          <Flag className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" />
          <p className={cn(planningBodyLabelClassName, "mb-3 text-sm")}>マイルストーン未定義（定義しなくても開発は可能）</p>
          <div className="flex flex-wrap items-center justify-center gap-2">
            <button onClick={() => addPreset("feature")} className={cn(planningActionVariants({ tone: "tonal" }), "px-3 py-1.5 text-xs")}>全機能実装</button>
            <button onClick={() => addPreset("quality")} className={cn(planningActionVariants({ tone: "tonal" }), "px-3 py-1.5 text-xs")}>コード品質</button>
            <button onClick={() => addPreset("responsive")} className={cn(planningActionVariants({ tone: "tonal" }), "px-3 py-1.5 text-xs")}>レスポンシブ</button>
          </div>
        </div>
      )}
      {milestones.length > 0 && (
        <div className="space-y-2">
          <p className={planningEyebrowClassName}>採用済みマイルストーン ({milestones.length})</p>
          {milestones.map((milestone, index) => (
            <div key={milestone.id} className={cn(planningSurfaceVariants({ tone: "inset", padding: "sm" }), "flex gap-3")}>
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary mt-0.5">{index + 1}</div>
              <div className="flex-1 space-y-2">
                <input value={milestone.name} onChange={(event) => update(index, "name", event.target.value)} placeholder="マイルストーン名" className={planningFieldClassName} />
                <textarea value={milestone.criteria} onChange={(event) => update(index, "criteria", event.target.value)} placeholder="成功条件 / 停止条件の詳細" rows={2} className={cn(planningFieldClassName, "min-h-20 resize-none text-[13px] leading-6")} />
              </div>
              <button onClick={() => remove(index)} className="shrink-0 text-muted-foreground hover:text-destructive transition-colors mt-0.5 cursor-pointer"><Trash2 className="h-4 w-4" /></button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const PRESET_CONFIG: Record<PlanPreset, { label: string; tone: "success" | "accent" | "warning"; desc: string }> = {
  minimal: { label: planningPresetLabel("minimal"), tone: "success", desc: planningPresetDescription("minimal") },
  standard: { label: planningPresetLabel("standard"), tone: "accent", desc: planningPresetDescription("standard") },
  full: { label: planningPresetLabel("full"), tone: "warning", desc: planningPresetDescription("full") },
};

const PLANNING_WORKDAYS_PER_WEEK = 5;

function PresetSelector({ plans, selected, onSelect }: {
  plans: PlanEstimate[];
  selected: PlanPreset;
  onSelect: (preset: PlanPreset) => void;
}) {
  const displayPlans = useMemo(() => buildPlanningPlanEstimateDisplay(plans), [plans]);
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {(["minimal", "standard", "full"] as const).map((preset) => {
        const plan = displayPlans.find((item) => item.plan.preset === preset);
        const cfg = PRESET_CONFIG[preset];
        const isActive = selected === preset;
        return (
          <button
            key={preset}
            onClick={() => onSelect(preset)}
            className={cn(
              planningSurfaceVariants({ tone: isActive ? "accent" : "inset", padding: "md" }),
              "text-left transition-all",
              isActive ? "" : "hover:border-[color:var(--planning-border-strong)]",
            )}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-bold text-foreground">{cfg.label}</span>
              {isActive && <Check className="h-4 w-4" />}
            </div>
            <div className="mb-3 flex items-center gap-2">
              <span className={planningSoftBadgeVariants({ tone: cfg.tone })}>{cfg.label}</span>
            </div>
            <p className={cn(planningBodyLabelClassName, "mb-3")}>{plan?.displayDescription ?? cfg.desc}</p>
            {plan ? (
              <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                <div>
                  <p className={planningEyebrowClassName}>工数</p>
                  <p className="text-sm font-bold text-foreground">{plan.plan.total_effort_hours}h</p>
                </div>
                <div>
                  <p className={planningEyebrowClassName}>予算</p>
                  <p className="text-sm font-bold text-foreground">${plan.plan.total_cost_usd.toFixed(0)}</p>
                </div>
                <div>
                  <p className={planningEyebrowClassName}>期間</p>
                  <p className="text-sm font-bold text-foreground">{plan.durationLabel}</p>
                  <p className="mt-0.5 text-[11px] text-[color:var(--planning-text-muted)]">{plan.durationNote}</p>
                </div>
                <div>
                  <p className={planningEyebrowClassName}>体制</p>
                  <p className="text-sm font-bold text-foreground">{plan.staffingLabel}</p>
                  <p className="mt-0.5 text-[11px] text-[color:var(--planning-text-muted)]">{plan.staffingNote}</p>
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
  const displayPlans = useMemo(() => buildPlanningPlanEstimateDisplay(planEstimates), [planEstimates]);
  const plan = displayPlans.find((item) => item.plan.preset === selectedPreset);
  if (planEstimates.length === 0) {
    return (
      <div className={cn(planningSurfaceVariants({ tone: "subtle", padding: "lg" }), "border-dashed text-center")}>
        <Layers className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
        <p className={cn(planningBodyLabelClassName, "text-sm")}>プランデータが生成されていません</p>
        <p className={cn(planningBodyLabelClassName, "mt-1")}>分析を実行するとエピック/WBS/ガントチャートが生成されます</p>
      </div>
    );
  }
  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <PresetSelector plans={planEstimates} selected={selectedPreset} onSelect={onSelectPreset} />
      {plan && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className={planningMetricTileVariants({ tone: "accent" })}>
              <div className="flex items-center gap-1.5 text-sm text-[color:var(--planning-text-soft)]">
                <Bot className="h-3.5 w-3.5" />
                <span>{plan.staffingLabel}</span>
              </div>
            </div>
            <div className={planningMetricTileVariants({ tone: "default" })}><div className="flex items-center gap-1.5 text-sm text-[color:var(--planning-text-soft)]"><Wrench className="h-3.5 w-3.5" /><span>{plan.plan.skills_used.length} スキル</span></div></div>
            <div className={planningMetricTileVariants({ tone: "default" })}><div className="flex items-center gap-1.5 text-sm text-[color:var(--planning-text-soft)]"><Layers className="h-3.5 w-3.5" /><span>{plan.plan.epics.length} エピック / {plan.plan.wbs.length} タスク</span></div></div>
          </div>
          {plan.displayEpics.map((epicDisplay, index) => {
            const epic = epicDisplay.epic;
            const epicWbs = plan.displayWbs.filter((entry) => entry.item.epic_id === epic.id);
            return (
              <div key={epic.id} className={cn(planningSurfaceVariants({ tone: "default" }), "overflow-hidden")}>
                <div className="flex items-start gap-3 border-b border-[color:var(--planning-border)] px-4 py-3 bg-[var(--planning-accent-soft)]">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-xs font-bold text-primary">E{index + 1}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-bold text-foreground">{epicDisplay.displayName}</p>
                      <span className={planningSoftBadgeVariants({ tone: epic.priority === "must" ? "danger" : epic.priority === "should" ? "warning" : "accent" })}>{epicDisplay.priorityLabel}</span>
                    </div>
                    <p className={cn(planningBodyLabelClassName, "mt-0.5")}>{epicDisplay.displayDescription}</p>
                  </div>
                </div>
                {epic.use_cases.length > 0 && (
                  <div className="border-b border-[color:var(--planning-border)] px-4 py-2.5 bg-[rgba(119,182,234,0.07)]">
                    <p className={cn(planningEyebrowClassName, "mb-1.5")}>ユースケース</p>
                    <div className="flex flex-wrap gap-1.5">
                      {epicDisplay.displayUseCases.map((useCase, useCaseIndex) => (
                        <span key={useCaseIndex} className={planningSoftBadgeVariants({ tone: "default" })}>{useCase}</span>
                      ))}
                    </div>
                  </div>
                )}
                {epicWbs.length > 0 && (
                  <div className="divide-y divide-border">
                    <div className="flex items-center gap-3 px-4 py-1.5 bg-[rgba(119,182,234,0.05)] text-[10px] font-medium text-[color:var(--planning-text-muted)] uppercase tracking-wider">
                      <div className="w-48 shrink-0">タスク</div>
                      <div className="w-28 shrink-0">担当</div>
                      <div className="flex-1">スキル</div>
                      <div className="w-16 shrink-0 text-right">工数</div>
                      <div className="w-16 shrink-0 text-right">期間</div>
                      <div className="w-16 shrink-0">依存</div>
                    </div>
                    {epicWbs.map((item) => (
                      <WbsRow key={item.item.id} item={item} allItems={plan.displayWbs} />
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

function WbsRow({ item, allItems }: { item: PlanningDisplayWbsItem; allItems: PlanningDisplayWbsItem[] }) {
  const deps = item.item.depends_on
    .map((depId) => allItems.find((entry) => entry.item.id === depId))
    .filter(Boolean);
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-[rgba(119,182,234,0.07)]">
      <div className="w-48 shrink-0">
        <p className="text-xs font-medium text-foreground truncate">{item.displayTitle}</p>
        {item.displayDescription && <p className="text-[11px] text-[color:var(--planning-text-muted)] truncate">{item.displayDescription}</p>}
      </div>
      <div className="flex items-center gap-1 w-28 shrink-0">
        {item.item.assignee_type === "agent" ? <Bot className="h-3 w-3 text-primary" /> : <Users className="h-3 w-3 text-[color:var(--planning-warning-strong)]" />}
        <span className="text-[12px] text-[color:var(--planning-text-soft)] truncate">{planningAssigneeTypeLabel(item.item.assignee_type)} · {item.displayAssignee}</span>
      </div>
      <div className="flex gap-1 flex-1 min-w-0">
        {item.displaySkills.slice(0, 3).map((skill) => (
          <span key={skill} className={cn(planningSoftBadgeVariants({ tone: "default" }), "shrink-0 px-2 py-0.5 text-[10px]")}>{skill}</span>
        ))}
      </div>
      <div className="text-right w-16 shrink-0"><span className="text-xs font-mono text-foreground">{item.item.effort_hours}h</span></div>
      <div className="text-right w-16 shrink-0"><span className="text-[11px] text-muted-foreground">{item.item.duration_days}日</span></div>
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
  const displayPlans = useMemo(() => buildPlanningPlanEstimateDisplay(planEstimates), [planEstimates]);
  const plan = displayPlans.find((item) => item.plan.preset === selectedPreset);
  if (planEstimates.length === 0) {
    return (
      <div className={cn(planningSurfaceVariants({ tone: "subtle", padding: "lg" }), "border-dashed text-center")}>
        <GanttChart className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
        <p className={cn(planningBodyLabelClassName, "text-sm")}>プランデータが生成されていません</p>
      </div>
    );
  }
  const wbs = plan?.displayWbs ?? [];
  const maxDay = Math.max(...wbs.map((item) => item.item.start_day + item.item.duration_days), 1);
  const totalWeeks = Math.ceil(maxDay / PLANNING_WORKDAYS_PER_WEEK);
  const weekMarkers = Array.from({ length: totalWeeks }, (_, index) => index + 1);
  const epicIds = [...new Set(wbs.map((item) => item.item.epic_id))];
  const epics = plan?.displayEpics ?? [];
  const epicColors = ["bg-blue-500", "bg-green-500", "bg-purple-500", "bg-orange-500", "bg-pink-500", "bg-cyan-500"];

  return (
    <div className="max-w-full mx-auto space-y-6">
      <PresetSelector plans={planEstimates} selected={selectedPreset} onSelect={onSelectPreset} />
      {plan && (
        <div className={cn(planningSurfaceVariants({ tone: "default" }), "overflow-hidden")}>
          <div className="flex items-center gap-3 border-b border-[color:var(--planning-border)] px-4 py-2.5 bg-[var(--planning-accent-soft)]">
            <GanttChart className="h-4 w-4 text-primary" />
            <div>
              <span className="text-sm font-bold text-foreground">プロジェクトタイムライン — {plan.durationLabel}</span>
              <p className="mt-0.5 text-[11px] text-[color:var(--planning-text-muted)]">{plan.durationNote}</p>
            </div>
            <div className="flex-1" />
            <div className="flex items-center gap-3 text-[11px] text-[color:var(--planning-text-soft)]">
              <span><Clock className="h-3 w-3 inline mr-1" />{plan.plan.total_effort_hours}h</span>
              <span><DollarSign className="h-3 w-3 inline mr-1" />${plan.plan.total_cost_usd.toFixed(0)}</span>
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
                const epic = epics.find((entry) => entry.epic.id === epicId);
                const items = wbs.filter((entry) => entry.item.epic_id === epicId);
                const barColor = epicColors[groupIdx % epicColors.length];
                return (
                  <div key={epicId}>
                    <div className="flex border-b border-border bg-accent/10">
                      <div className="w-48 shrink-0 px-3 py-1.5 flex items-center gap-1.5">
                        <span className={cn("h-2 w-2 rounded-full", barColor)} />
                        <span className="text-[12px] font-bold text-foreground truncate">{epic?.displayName ?? epicId}</span>
                      </div>
                      <div className="flex-1" />
                    </div>
                    {items.map((item) => {
                      const leftPct = (item.item.start_day / maxDay) * 100;
                      const widthPct = Math.max((item.item.duration_days / maxDay) * 100, 2);
                      return (
                        <div key={item.item.id} className="flex border-b border-border last:border-b-0 hover:bg-accent/10 transition-colors">
                          <div className="w-48 shrink-0 px-3 py-2 flex items-center gap-2">
                            {item.item.assignee_type === "agent" ? <Bot className="h-3 w-3 text-primary shrink-0" /> : <Users className="h-3 w-3 text-[color:var(--planning-warning-strong)] shrink-0" />}
                            <div className="min-w-0">
                              <p className="text-[12px] text-foreground truncate">{item.displayTitle}</p>
                              <p className="text-[10px] text-[color:var(--planning-text-soft)] truncate">{item.displayAssignee} · {item.item.effort_hours}h</p>
                            </div>
                          </div>
                          <div className="flex-1 relative py-2">
                            <div className="absolute inset-0 flex">
                              {weekMarkers.map((week) => (
                                <div key={week} className="flex-1 border-r border-border/30 last:border-r-0" />
                              ))}
                            </div>
                            <div className={cn("absolute top-2.5 h-4 rounded-full flex items-center px-1.5", barColor, "opacity-80")} style={{ left: `${leftPct}%`, width: `${widthPct}%` }} title={`${item.displayTitle}: 稼働日 ${item.item.start_day}–${item.item.start_day + item.item.duration_days} (${item.item.effort_hours}h)`}>
                              <span className="text-[8px] text-white font-medium truncate">{item.item.duration_days}日</span>
                            </div>
                            {item.item.depends_on.length > 0 && (
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
              const epic = epics.find((entry) => entry.epic.id === epicId);
              return (
                <div key={epicId} className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                  <span className={cn("h-2 w-2 rounded-full", epicColors[index % epicColors.length])} />
                  {epic?.displayName ?? epicId}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
