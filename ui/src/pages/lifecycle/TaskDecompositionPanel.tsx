import type { TaskDecomposition, TaskItem } from "../../types/lifecycle";

const PRIORITY_BADGE: Record<string, { label: string; color: string }> = {
  must: { label: "必須", color: "bg-red-100 text-red-700" },
  should: { label: "推奨", color: "bg-yellow-100 text-yellow-700" },
  could: { label: "任意", color: "bg-gray-100 text-gray-600" },
};

function EffortBar({ hours, max }: { hours: number; max: number }) {
  const pct = max > 0 ? Math.min((hours / max) * 100, 100) : 0;
  return (
    <div className="h-1.5 w-20 rounded-full bg-gray-200">
      <div className="h-1.5 rounded-full bg-blue-500" style={{ width: `${pct}%` }} />
    </div>
  );
}

function TaskRow({ task, isCritical, maxEffort }: { task: TaskItem; isCritical: boolean; maxEffort: number }) {
  const badge = PRIORITY_BADGE[task.priority] ?? PRIORITY_BADGE.should;
  return (
    <div className={`flex items-center gap-3 rounded px-3 py-2 text-sm ${isCritical ? "bg-amber-50 border-l-2 border-amber-400" : "bg-white"}`}>
      <span className="font-mono text-xs font-semibold text-gray-500 w-20 shrink-0">{task.id}</span>
      <span className="flex-1 text-gray-800 truncate">{task.title}</span>
      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${badge.color}`}>{badge.label}</span>
      <div className="flex items-center gap-1.5 w-28 shrink-0">
        <EffortBar hours={task.effortHours} max={maxEffort} />
        <span className="text-xs text-gray-400 w-10 text-right">{task.effortHours}h</span>
      </div>
    </div>
  );
}

export function TaskDecompositionPanel({ decomposition }: { decomposition: TaskDecomposition | null }) {
  if (!decomposition || !decomposition.tasks.length) return null;
  const criticalSet = new Set(decomposition.criticalPath);
  const maxEffort = Math.max(...decomposition.tasks.map((t) => t.effortHours), 1);
  const phases = decomposition.phaseMilestones;
  const tasksByPhase = new Map<string, TaskItem[]>();
  for (const t of decomposition.tasks) {
    const list = tasksByPhase.get(t.phase) ?? [];
    list.push(t);
    tasksByPhase.set(t.phase, list);
  }
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-gray-900">タスク分解 (TASK-XXXX)</h3>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span>合計: {decomposition.totalEffortHours}h</span>
          <span>タスク数: {decomposition.tasks.length}</span>
          {decomposition.hasCycles && <span className="text-red-600 font-medium">循環検出</span>}
        </div>
      </div>
      {phases.map((pm) => {
        const phaseTasks = tasksByPhase.get(pm.phase) ?? [];
        if (!phaseTasks.length) return null;
        return (
          <div key={pm.phase} className="space-y-1">
            <div className="flex items-center justify-between text-xs font-medium text-gray-600 px-1">
              <span>{pm.phase}</span>
              <span>{pm.totalHours.toFixed(0)}h / {pm.durationDays}d</span>
            </div>
            <div className="space-y-0.5">
              {phaseTasks.map((t) => (
                <TaskRow key={t.id} task={t} isCritical={criticalSet.has(t.id)} maxEffort={maxEffort} />
              ))}
            </div>
          </div>
        );
      })}
      {decomposition.criticalPath.length > 0 && (
        <div className="text-xs text-gray-500 px-1">
          <span className="font-medium">Critical Path:</span>{" "}
          {decomposition.criticalPath.join(" → ")}
        </div>
      )}
    </section>
  );
}
