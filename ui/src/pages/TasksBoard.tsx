import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useKanbanDragDrop } from "@/hooks/useKanbanDragDrop";
import { useParams } from "react-router-dom";
import { formatDateTime, timeAgo } from "@/lib/time";
import {
  Bot,
  User,
  Plus,
  Filter,
  GripVertical,
  Clock,
  AlertCircle,
  CheckCircle2,
  ListTodo,
  Kanban,
  X,
  Loader2,
  ChevronRight,
  Calendar,
  Workflow,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import {
  listTasks,
  createTask,
  updateTask,
  deleteTask,
  type Task,
} from "@/api/mission-control";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TaskStatus = "backlog" | "in_progress" | "review" | "done";
type TaskPriority = "low" | "medium" | "high" | "critical";
type AssigneeType = "human" | "ai";
type FilterType = "all" | "me" | "ai";
type TimeRange = "1h" | "24h" | "7d" | "30d" | "all";

interface Column {
  id: TaskStatus;
  label: string;
  icon: typeof ListTodo;
  accentClass: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const COLUMNS: Column[] = [
  { id: "backlog", label: "Backlog", icon: ListTodo, accentClass: "bg-muted-foreground" },
  { id: "in_progress", label: "In Progress", icon: Clock, accentClass: "bg-blue-500" },
  { id: "review", label: "Review", icon: AlertCircle, accentClass: "bg-yellow-500" },
  { id: "done", label: "Done", icon: CheckCircle2, accentClass: "bg-green-500" },
];

const PRIORITY_CONFIG: Record<TaskPriority, { label: string; variant: "default" | "secondary" | "destructive" | "warning" }> = {
  low: { label: "Low", variant: "secondary" },
  medium: { label: "Medium", variant: "default" },
  high: { label: "High", variant: "warning" },
  critical: { label: "Critical", variant: "destructive" },
};

const TIME_RANGES: { value: TimeRange; label: string; ms: number }[] = [
  { value: "1h", label: "1h", ms: 3_600_000 },
  { value: "24h", label: "24h", ms: 86_400_000 },
  { value: "7d", label: "7d", ms: 604_800_000 },
  { value: "30d", label: "30d", ms: 2_592_000_000 },
  { value: "all", label: "All", ms: 0 },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TasksBoard() {
  const { projectSlug } = useParams<{ projectSlug: string }>();
  const slug = projectSlug ?? "default";

  const queryClient = useQueryClient();
  const { data: tasksData, isLoading: loading, error: queryError } = useQuery({
    queryKey: ["tasks"],
    queryFn: () => listTasks(),
  });
  const error = queryError ? (queryError instanceof Error ? queryError.message : "タスクの取得に失敗しました") : null;

  const [tasks, setTasks] = useState<Task[]>([]);
  useEffect(() => { if (tasksData) setTasks(tasksData); }, [tasksData]);

  const [filter, setFilter] = useState<FilterType>("all");
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [showForm, setShowForm] = useState(false);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);

  // -- Drag & Drop ----------------------------------------------------------

  const {
    draggedId: draggedTaskId,
    dragOverColumn,
    handleDragStart,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    handleDragEnd,
  } = useKanbanDragDrop<Task, TaskStatus>({
    items: tasks,
    setItems: setTasks,
    getId: (t) => t.id,
    getColumn: (t) => t.status,
    setColumn: (t, s) => ({ ...t, status: s }),
    onMove: async (id, _from, to) => {
      await updateTask(id, { status: to });
    },
  });

  // -- Task CRUD ------------------------------------------------------------

  const createMutation = useMutation({
    mutationFn: createTask,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      setShowForm(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteTask,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      setSelectedTask(null);
    },
  });

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: TaskStatus }) =>
      updateTask(id, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  const addTask = (task: { title: string; description: string; status: TaskStatus; priority: TaskPriority; assignee: string; assigneeType: AssigneeType }) => {
    createMutation.mutate(task);
  };

  // -- Filters --------------------------------------------------------------

  const now = Date.now();
  const filteredTasks = tasks.filter((t) => {
    // Assignee filter
    if (filter === "ai" && t.assigneeType !== "ai") return false;
    if (filter === "me" && t.assigneeType !== "human") return false;

    // Time range filter
    if (timeRange !== "all") {
      const range = TIME_RANGES.find((r) => r.value === timeRange);
      if (range && range.ms > 0) {
        const taskTime = new Date(t.updated_at || t.created_at).getTime();
        if (now - taskTime > range.ms) return false;
      }
    }

    return true;
  });

  const tasksByColumn = (status: TaskStatus) =>
    filteredTasks.filter((t) => t.status === status);

  // -- Render ---------------------------------------------------------------

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {/* Main content */}
      <div className={cn("flex-1 space-y-6 p-6 transition-all", selectedTask && "pr-0")}>
        {/* Header */}
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <Kanban className="h-6 w-6 text-muted-foreground" />
            <div>
              <h1 className="text-2xl font-bold tracking-tight">
                Tasks Board
              </h1>
              <p className="text-sm text-muted-foreground">
                {slug} / Kanban
                <span className="ml-2 text-xs">({filteredTasks.length}/{tasks.length} tasks)</span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Time range filter */}
            <div className="flex items-center gap-1 rounded-md border border-border p-1">
              <Calendar className="ml-1 h-3.5 w-3.5 text-muted-foreground" />
              {TIME_RANGES.map((r) => (
                <button
                  key={r.value}
                  onClick={() => setTimeRange(r.value)}
                  className={cn(
                    "rounded px-2 py-1 text-xs font-medium transition-colors",
                    timeRange === r.value
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent",
                  )}
                >
                  {r.label}
                </button>
              ))}
            </div>

            {/* Assignee filter */}
            <div className="flex items-center gap-1 rounded-md border border-border p-1">
              <Filter className="ml-1 h-4 w-4 text-muted-foreground" />
              {(["all", "me", "ai"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={cn(
                    "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                    filter === f
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent",
                  )}
                >
                  {f === "all" && "All"}
                  {f === "me" && "Me"}
                  {f === "ai" && "AI"}
                </button>
              ))}
            </div>

            <Button size="sm" onClick={() => setShowForm(true)}>
              <Plus className="h-4 w-4" />
              New
            </Button>
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
            {error}
          </div>
        )}

        {/* New Task Form */}
        {showForm && (
          <NewTaskForm onSubmit={addTask} onCancel={() => setShowForm(false)} />
        )}

        {/* Kanban Columns */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {COLUMNS.map((col) => {
            const colTasks = tasksByColumn(col.id);
            const Icon = col.icon;
            return (
              <div
                key={col.id}
                className={cn(
                  "flex flex-col rounded-lg border border-border bg-card/50 transition-colors",
                  dragOverColumn === col.id && "border-primary/50 bg-primary/5",
                )}
                onDragOver={(e) => handleDragOver(e, col.id)}
                onDragLeave={handleDragLeave}
                onDrop={(e) => handleDrop(e, col.id)}
              >
                {/* Column Header */}
                <div className="flex items-center gap-2 border-b border-border p-3">
                  <span className={cn("h-2 w-2 rounded-full", col.accentClass)} />
                  <Icon className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium">{col.label}</span>
                  <Badge variant="secondary" className="ml-auto text-xs">
                    {colTasks.length}
                  </Badge>
                </div>

                {/* Cards */}
                <div className="flex flex-1 flex-col gap-2 p-2">
                  {colTasks.length === 0 && (
                    <p className="py-8 text-center text-xs text-muted-foreground">
                      No tasks
                    </p>
                  )}
                  {colTasks.map((task) => (
                    <TaskCard
                      key={task.id}
                      task={task}
                      isDragging={draggedTaskId === task.id}
                      isSelected={selectedTask?.id === task.id}
                      onDragStart={handleDragStart}
                      onDragEnd={handleDragEnd}
                      onClick={() => setSelectedTask(task)}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Detail Panel (slide-over) */}
      {selectedTask && (
        <TaskDetailPanel
          task={selectedTask}
          onClose={() => setSelectedTask(null)}
          onDelete={(id) => deleteMutation.mutate(id)}
          onStatusChange={(id, status) => statusMutation.mutate({ id, status })}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TaskCard
// ---------------------------------------------------------------------------

function TaskCard({
  task,
  isDragging,
  isSelected,
  onDragStart,
  onDragEnd,
  onClick,
}: {
  task: Task;
  isDragging: boolean;
  isSelected: boolean;
  onDragStart: (e: React.DragEvent, id: string) => void;
  onDragEnd: () => void;
  onClick: () => void;
}) {
  const prio = PRIORITY_CONFIG[task.priority];

  return (
    <Card
      draggable
      onDragStart={(e) => onDragStart(e, task.id)}
      onDragEnd={onDragEnd}
      onClick={onClick}
      className={cn(
        "cursor-pointer select-none p-3 transition-all active:cursor-grabbing",
        isDragging && "opacity-40",
        isSelected && "ring-2 ring-primary",
        !isSelected && "hover:border-primary/30",
      )}
    >
      <div className="flex items-start gap-2">
        <GripVertical className="mt-0.5 h-4 w-4 shrink-0 cursor-grab text-muted-foreground/50" />
        <div className="min-w-0 flex-1 space-y-1.5">
          <p className="text-sm font-medium leading-snug">{task.title}</p>
          {task.description && (
            <p className="line-clamp-2 text-xs text-muted-foreground">
              {task.description}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant={prio.variant} className="text-[10px]">
              {prio.label}
            </Badge>
            <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
              {task.assigneeType === "ai" ? (
                <Bot className="h-3 w-3" />
              ) : (
                <User className="h-3 w-3" />
              )}
              {task.assignee}
            </span>
            {task.payload?.phase && (
              <Badge variant="outline" className="text-[10px]">
                {task.payload.phase}
              </Badge>
            )}
          </div>
          <p className="text-[10px] text-muted-foreground/70">
            {timeAgo(task.updated_at || task.created_at)}
          </p>
        </div>
        <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/30" />
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// TaskDetailPanel
// ---------------------------------------------------------------------------

function TaskDetailPanel({
  task,
  onClose,
  onDelete,
  onStatusChange,
}: {
  task: Task;
  onClose: () => void;
  onDelete: (id: string) => void;
  onStatusChange: (id: string, status: TaskStatus) => void;
}) {
  const prio = PRIORITY_CONFIG[task.priority];

  return (
    <div className="w-96 shrink-0 border-l border-border bg-card overflow-y-auto">
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-card px-4 py-3">
        <h2 className="text-sm font-bold text-foreground truncate">タスク詳細</h2>
        <button
          onClick={onClose}
          className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="space-y-5 p-4">
        {/* Title */}
        <div>
          <p className="text-base font-semibold text-foreground leading-snug">{task.title}</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground font-mono">{task.id}</p>
        </div>

        {/* Status */}
        <DetailSection label="ステータス" icon={Clock}>
          <div className="flex gap-1.5">
            {COLUMNS.map((col) => (
              <button
                key={col.id}
                onClick={() => onStatusChange(task.id, col.id)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors border",
                  task.status === col.id
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                {col.label}
              </button>
            ))}
          </div>
        </DetailSection>

        {/* Priority */}
        <DetailSection label="優先度" icon={AlertCircle}>
          <Badge variant={prio.variant}>{prio.label}</Badge>
        </DetailSection>

        {/* Assignee */}
        <DetailSection label="担当者" icon={task.assigneeType === "ai" ? Bot : User}>
          <div className="flex items-center gap-2">
            <div className={cn(
              "flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold",
              task.assigneeType === "ai"
                ? "bg-blue-500/10 text-blue-500"
                : "bg-orange-500/10 text-orange-500",
            )}>
              {task.assigneeType === "ai" ? <Bot className="h-3.5 w-3.5" /> : <User className="h-3.5 w-3.5" />}
            </div>
            <div>
              <p className="text-sm text-foreground">{task.assignee}</p>
              <p className="text-[10px] text-muted-foreground">{task.assigneeType === "ai" ? "AI Agent" : "Human"}</p>
            </div>
          </div>
        </DetailSection>

        {/* Description */}
        <DetailSection label="説明" icon={ListTodo}>
          {task.description ? (
            <p className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">{task.description}</p>
          ) : (
            <p className="text-xs text-muted-foreground italic">説明なし</p>
          )}
        </DetailSection>

        {/* Workflow Info */}
        {task.payload && (task.payload.phase || task.payload.run_id || task.payload.node_id) && (
          <DetailSection label="ワークフロー" icon={Workflow}>
            <div className="space-y-2 rounded-lg border border-border bg-accent/30 p-3">
              {task.payload.phase && (
                <DetailRow label="Phase" value={task.payload.phase} />
              )}
              {task.payload.run_id && (
                <DetailRow label="Run ID" value={task.payload.run_id} mono />
              )}
              {task.payload.node_id && (
                <DetailRow label="Node ID" value={task.payload.node_id} mono />
              )}
            </div>
          </DetailSection>
        )}

        {/* Timestamps */}
        <DetailSection label="タイムスタンプ" icon={Calendar}>
          <div className="space-y-2">
            <DetailRow label="作成" value={formatDateTime(task.created_at)} />
            {task.updated_at && (
              <DetailRow label="更新" value={formatDateTime(task.updated_at)} />
            )}
            <DetailRow label="経過" value={timeAgo(task.updated_at || task.created_at)} />
          </div>
        </DetailSection>

        {/* Actions */}
        <div className="pt-2 border-t border-border">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start gap-2 text-destructive hover:text-destructive hover:bg-destructive/10"
            onClick={() => onDelete(task.id)}
          >
            <Trash2 className="h-3.5 w-3.5" />
            タスクを削除
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail helpers
// ---------------------------------------------------------------------------

function DetailSection({
  label,
  icon: Icon,
  children,
}: {
  label: string;
  icon: typeof Clock;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">{label}</span>
      </div>
      {children}
    </div>
  );
}

function DetailRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-xs text-muted-foreground shrink-0">{label}</span>
      <span className={cn("text-xs text-foreground text-right truncate", mono && "font-mono")}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// NewTaskForm
// ---------------------------------------------------------------------------

function NewTaskForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (task: { title: string; description: string; status: TaskStatus; priority: TaskPriority; assignee: string; assigneeType: AssigneeType }) => void;
  onCancel: () => void;
}) {
  const titleRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [assignee, setAssignee] = useState("");
  const [assigneeType, setAssigneeType] = useState<AssigneeType>("human");
  const [priority, setPriority] = useState<TaskPriority>("medium");
  const [status, setStatus] = useState<TaskStatus>("backlog");

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    onSubmit({
      title: title.trim(),
      description: description.trim(),
      assignee: assignee.trim() || (assigneeType === "ai" ? "AI Agent" : "Me"),
      assigneeType,
      priority,
      status,
    });
  };

  return (
    <Card className="p-4">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">New Task</h2>
          <button
            type="button"
            onClick={onCancel}
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="mb-1 block text-xs text-muted-foreground">
              Title
            </label>
            <Input
              ref={titleRef}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Task title"
              required
            />
          </div>

          <div className="sm:col-span-2">
            <label className="mb-1 block text-xs text-muted-foreground">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Task description (optional)"
              rows={2}
              className="flex w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs text-muted-foreground">
              Assignee
            </label>
            <div className="flex gap-2">
              <Input
                value={assignee}
                onChange={(e) => setAssignee(e.target.value)}
                placeholder={assigneeType === "ai" ? "AI Agent" : "My name"}
                className="flex-1"
              />
              <Button
                type="button"
                variant={assigneeType === "ai" ? "default" : "outline"}
                size="icon"
                onClick={() =>
                  setAssigneeType((t) => (t === "ai" ? "human" : "ai"))
                }
                title={assigneeType === "ai" ? "AI" : "Human"}
              >
                {assigneeType === "ai" ? (
                  <Bot className="h-4 w-4" />
                ) : (
                  <User className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>

          <div>
            <label className="mb-1 block text-xs text-muted-foreground">
              Priority
            </label>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as TaskPriority)}
              className="flex h-9 w-full rounded-md border border-border bg-transparent px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </div>

          <div>
            <label className="mb-1 block text-xs text-muted-foreground">
              Column
            </label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as TaskStatus)}
              className="flex h-9 w-full rounded-md border border-border bg-transparent px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {COLUMNS.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" size="sm">
            <Plus className="h-4 w-4" />
            Add
          </Button>
        </div>
      </form>
    </Card>
  );
}
