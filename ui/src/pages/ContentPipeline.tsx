import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useKanbanDragDrop } from "@/hooks/useKanbanDragDrop";
import { formatDateTime } from "@/lib/time";
import {
  Lightbulb,
  Search,
  PenTool,
  FileText,
  Eye,
  Rocket,
  CheckCircle2,
  Plus,
  X,
  Bot,
  Clock,
  GripVertical,
  ChevronRight,
  Trash2,
  Loader2,
  LayoutGrid,
  List,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import {
  listContent,
  createContent,
  updateContent,
  deleteContent,
  type ContentItem as ApiContentItem,
} from "@/api/mission-control";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Stage = "idea" | "research" | "draft" | "script" | "review" | "ready" | "published";

interface ActivityEntry {
  from: Stage;
  to: Stage;
  at: string;
}

interface ContentItem {
  id: string;
  title: string;
  description: string;
  stage: Stage;
  agent: string;
  updatedAt: string;
  createdAt: string;
  activity: ActivityEntry[];
}

interface StageConfig {
  id: Stage;
  label: string;
  icon: typeof Lightbulb;
  colorClass: string;
  badgeClass: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STAGES: StageConfig[] = [
  { id: "idea", label: "アイデア", icon: Lightbulb, colorClass: "bg-blue-500", badgeClass: "bg-blue-500/20 text-blue-400" },
  { id: "research", label: "調査", icon: Search, colorClass: "bg-cyan-500", badgeClass: "bg-cyan-500/20 text-cyan-400" },
  { id: "draft", label: "下書き", icon: PenTool, colorClass: "bg-yellow-500", badgeClass: "bg-yellow-500/20 text-yellow-400" },
  { id: "script", label: "スクリプト", icon: FileText, colorClass: "bg-orange-500", badgeClass: "bg-orange-500/20 text-orange-400" },
  { id: "review", label: "レビュー", icon: Eye, colorClass: "bg-purple-500", badgeClass: "bg-purple-500/20 text-purple-400" },
  { id: "ready", label: "公開準備", icon: Rocket, colorClass: "bg-green-500", badgeClass: "bg-green-500/20 text-green-400" },
  { id: "published", label: "公開済み", icon: CheckCircle2, colorClass: "bg-emerald-500", badgeClass: "bg-emerald-500/20 text-emerald-400" },
];

const STAGE_MAP = Object.fromEntries(STAGES.map((s) => [s.id, s])) as Record<Stage, StageConfig>;

function apiToItem(item: ApiContentItem): ContentItem {
  return {
    id: item.id,
    title: item.title,
    description: item.description,
    stage: (item.stage as Stage) || "idea",
    agent: item.assignee || "writer",
    updatedAt: item.updated_at,
    createdAt: item.created_at,
    activity: [],
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ContentPipeline() {
  const queryClient = useQueryClient();
  const { data: contentData, isLoading: loading, error: queryError } = useQuery({
    queryKey: ["content"],
    queryFn: async () => {
      const data = await listContent();
      return data.map(apiToItem);
    },
  });
  const error = queryError ? (queryError instanceof Error ? queryError.message : "コンテンツの取得に失敗しました") : null;

  const [items, setItems] = useState<ContentItem[]>([]);
  useEffect(() => { if (contentData) setItems(contentData); }, [contentData]);

  const [searchQuery, setSearchQuery] = useState("");
  const [stageFilter, setStageFilter] = useState<Stage | "all">("all");
  const [viewMode, setViewMode] = useState<"board" | "list">("board");
  const [showForm, setShowForm] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // -- Drag & Drop ----------------------------------------------------------

  const {
    draggedId,
    dragOverColumn: dragOverStage,
    handleDragStart,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    handleDragEnd,
  } = useKanbanDragDrop<ContentItem, Stage>({
    items,
    setItems,
    getId: (i) => i.id,
    getColumn: (i) => i.stage,
    setColumn: (item, newStage) => ({
      ...item,
      stage: newStage,
      updatedAt: new Date().toISOString(),
      activity: [
        ...item.activity,
        { from: item.stage, to: newStage, at: new Date().toISOString() },
      ],
    }),
    onMove: async (id, _from, to) => {
      await updateContent(id, { stage: to });
    },
  });

  // -- CRUD -----------------------------------------------------------------

  const createMutation = useMutation({
    mutationFn: (data: { title: string; description: string; stage: Stage; agent: string }) =>
      createContent({
        title: data.title,
        description: data.description,
        type: "article",
        stage: data.stage,
        assignee: data.agent,
        assigneeType: "ai",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["content"] });
      setShowForm(false);
    },
  });

  const addItem = (data: { title: string; description: string; stage: Stage; agent: string }) => {
    createMutation.mutate(data);
  };

  const updateMutation = useMutation({
    mutationFn: ({ id, apiPatch }: { id: string; apiPatch: Partial<ApiContentItem> }) =>
      updateContent(id, apiPatch),
    onError: () => queryClient.invalidateQueries({ queryKey: ["content"] }),
  });

  const handleUpdateItem = (id: string, patch: Partial<ContentItem>) => {
    setItems((prev) =>
      prev.map((item) => (item.id === id ? { ...item, ...patch, updatedAt: new Date().toISOString() } : item)),
    );
    const apiPatch: Partial<ApiContentItem> = {};
    if (patch.title) apiPatch.title = patch.title;
    if (patch.description) apiPatch.description = patch.description;
    if (patch.agent) apiPatch.assignee = patch.agent;
    if (patch.stage) apiPatch.stage = patch.stage;
    updateMutation.mutate({ id, apiPatch });
  };

  const moveItem = (id: string, newStage: Stage) => {
    setItems((prev) =>
      prev.map((item) => {
        if (item.id !== id || item.stage === newStage) return item;
        return {
          ...item,
          stage: newStage,
          updatedAt: new Date().toISOString(),
          activity: [...item.activity, { from: item.stage, to: newStage, at: new Date().toISOString() }],
        };
      }),
    );
    updateMutation.mutate({ id, apiPatch: { stage: newStage } });
  };

  const deleteMutation = useMutation({
    mutationFn: deleteContent,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["content"] });
      setSelectedId(null);
    },
  });

  const handleDeleteItem = (id: string) => {
    deleteMutation.mutate(id);
  };

  // -- Filtering ------------------------------------------------------------

  const filtered = items.filter((item) => {
    if (stageFilter !== "all" && item.stage !== stageFilter) return false;
    if (searchQuery && !item.title.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    return true;
  });

  const itemsByStage = (stage: Stage) => filtered.filter((item) => item.stage === stage);

  const selectedItem = selectedId ? items.find((i) => i.id === selectedId) ?? null : null;

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">コンテンツパイプライン</h1>
          <p className="text-sm text-muted-foreground">アイデアから公開まで</p>
        </div>
        <Button size="sm" onClick={() => setShowForm(true)}>
          <Plus className="h-4 w-4" />
          新規作成
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Badge variant="secondary" className="text-xs">合計 {items.length} 件</Badge>
        {STAGES.map((s) => {
          const count = items.filter((i) => i.stage === s.id).length;
          if (count === 0) return null;
          const Icon = s.icon;
          return (
            <Badge key={s.id} variant="outline" className={cn("text-xs gap-1", s.badgeClass)}>
              <Icon className="h-3 w-3" />
              {s.label} {count}
            </Badge>
          );
        })}
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="タイトルで検索..." className="pl-9" />
        </div>
        <select
          value={stageFilter}
          onChange={(e) => setStageFilter(e.target.value as Stage | "all")}
          className="flex h-9 rounded-md border border-border bg-transparent px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <option value="all">すべてのステージ</option>
          {STAGES.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
        <div className="flex rounded-lg border border-border bg-muted/50 p-0.5">
          <button
            onClick={() => setViewMode("board")}
            className={cn("flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors", viewMode === "board" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}
          >
            <LayoutGrid className="h-4 w-4" />
            ボード
          </button>
          <button
            onClick={() => setViewMode("list")}
            className={cn("flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors", viewMode === "list" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}
          >
            <List className="h-4 w-4" />
            リスト
          </button>
        </div>
      </div>

      {showForm && <NewContentForm onSubmit={addItem} onCancel={() => setShowForm(false)} />}

      {viewMode === "board" ? (
        <div className="flex gap-3 overflow-x-auto pb-4">
          {STAGES.map((stage) => {
            const stageItems = itemsByStage(stage.id);
            const Icon = stage.icon;
            return (
              <div
                key={stage.id}
                className={cn(
                  "flex w-64 shrink-0 flex-col rounded-lg border border-border bg-card/50 transition-colors",
                  dragOverStage === stage.id && "border-primary/50 bg-primary/5",
                )}
                onDragOver={(e) => handleDragOver(e, stage.id)}
                onDragLeave={handleDragLeave}
                onDrop={(e) => handleDrop(e, stage.id)}
              >
                <div className="flex items-center gap-2 border-b border-border p-3">
                  <span className={cn("h-2 w-2 rounded-full", stage.colorClass)} />
                  <Icon className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium">{stage.label}</span>
                  <Badge variant="secondary" className="ml-auto text-xs">{stageItems.length}</Badge>
                </div>
                <div className="flex flex-1 flex-col gap-2 p-2 min-h-[120px]">
                  {stageItems.length === 0 && (
                    <p className="py-8 text-center text-xs text-muted-foreground">アイテムなし</p>
                  )}
                  {stageItems.map((item) => (
                    <ContentCard
                      key={item.id}
                      item={item}
                      isDragging={draggedId === item.id}
                      onDragStart={handleDragStart}
                      onDragEnd={handleDragEnd}
                      onClick={() => setSelectedId(item.id)}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50">
                <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">タイトル</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">ステージ</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">タイプ</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">担当</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">更新日</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-xs text-muted-foreground">アイテムなし</td></tr>
              ) : (
                filtered.map((item) => {
                  const stage = STAGE_MAP[item.stage];
                  return (
                    <tr
                      key={item.id}
                      onClick={() => setSelectedId(item.id)}
                      className="cursor-pointer border-b border-border last:border-0 transition-colors hover:bg-accent/50"
                    >
                      <td className="px-4 py-2.5 text-sm font-medium text-foreground">{item.title}</td>
                      <td className="px-4 py-2.5">
                        <Badge variant="outline" className={cn("text-[10px] border-0", stage.badgeClass)}>
                          {stage.label}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge variant="secondary" className="text-[10px]">article</Badge>
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="flex items-center gap-1 text-xs text-muted-foreground">
                          <Bot className="h-3 w-3" />
                          {item.agent}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-xs text-muted-foreground">{formatDateTime(item.updatedAt)}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}

      {selectedItem && (
        <DetailPanel
          item={selectedItem}
          onClose={() => setSelectedId(null)}
          onUpdate={(patch) => handleUpdateItem(selectedItem.id, patch)}
          onMove={(stage) => moveItem(selectedItem.id, stage)}
          onDelete={() => handleDeleteItem(selectedItem.id)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ContentCard
// ---------------------------------------------------------------------------

function ContentCard({
  item,
  isDragging,
  onDragStart,
  onDragEnd,
  onClick,
}: {
  item: ContentItem;
  isDragging: boolean;
  onDragStart: (e: React.DragEvent, id: string) => void;
  onDragEnd: () => void;
  onClick: () => void;
}) {
  const stage = STAGE_MAP[item.stage];

  return (
    <Card
      draggable
      onDragStart={(e) => onDragStart(e, item.id)}
      onDragEnd={onDragEnd}
      className={cn(
        "cursor-grab select-none p-3 transition-opacity active:cursor-grabbing",
        isDragging && "opacity-40",
      )}
    >
      <div className="flex items-start gap-2">
        <GripVertical className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground/50" />
        <div className="min-w-0 flex-1 space-y-1.5">
          <p className="text-sm font-medium leading-snug">{item.title}</p>
          {item.description && (
            <p className="line-clamp-2 text-xs text-muted-foreground">{item.description}</p>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="outline" className={cn("text-[10px] border-0", stage.badgeClass)}>
              {stage.label}
            </Badge>
            <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
              <Bot className="h-3 w-3" />
              {item.agent}
            </span>
          </div>
          <p className="flex items-center gap-1 text-[10px] text-muted-foreground/70">
            <Clock className="h-3 w-3" />
            {formatDateTime(item.updatedAt)}
          </p>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onClick(); }}
          className="shrink-0 text-muted-foreground hover:text-foreground"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// DetailPanel
// ---------------------------------------------------------------------------

function DetailPanel({
  item,
  onClose,
  onUpdate,
  onMove,
  onDelete,
}: {
  item: ContentItem;
  onClose: () => void;
  onUpdate: (patch: Partial<ContentItem>) => void;
  onMove: (stage: Stage) => void;
  onDelete: () => void;
}) {
  const [title, setTitle] = useState(item.title);
  const [description, setDescription] = useState(item.description);
  const [agent, setAgent] = useState(item.agent);

  useEffect(() => {
    setTitle(item.title);
    setDescription(item.description);
    setAgent(item.agent);
  }, [item.id, item.title, item.description, item.agent]);

  const commitField = (field: string, value: string) => {
    const trimmed = value.trim();
    if (field === "title" && trimmed && trimmed !== item.title) onUpdate({ title: trimmed });
    if (field === "description" && trimmed !== item.description) onUpdate({ description: trimmed });
    if (field === "agent" && trimmed && trimmed !== item.agent) onUpdate({ agent: trimmed });
  };

  const stage = STAGE_MAP[item.stage];

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative w-full max-w-md overflow-y-auto border-l border-border bg-background p-6 shadow-xl">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-bold">コンテンツ詳細</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-5">
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">タイトル</label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} onBlur={() => commitField("title", title)} />
          </div>

          <div>
            <label className="mb-1 block text-xs text-muted-foreground">ステージ</label>
            <select
              value={item.stage}
              onChange={(e) => onMove(e.target.value as Stage)}
              className="flex h-9 w-full rounded-md border border-border bg-transparent px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {STAGES.map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
            <Badge variant="outline" className={cn("mt-2 text-xs border-0", stage.badgeClass)}>
              {stage.label}
            </Badge>
          </div>

          <div>
            <label className="mb-1 block text-xs text-muted-foreground">説明 / スクリプト</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onBlur={() => commitField("description", description)}
              rows={6}
              className="flex w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring font-mono"
              placeholder="Markdownで記述..."
            />
          </div>

          <div>
            <label className="mb-1 block text-xs text-muted-foreground">担当エージェント</label>
            <div className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-muted-foreground" />
              <Input value={agent} onChange={(e) => setAgent(e.target.value)} onBlur={() => commitField("agent", agent)} className="flex-1" />
            </div>
          </div>

          {item.activity.length > 0 && (
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">アクティビティログ</label>
              <div className="space-y-1.5">
                {item.activity.map((entry, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Clock className="h-3 w-3 shrink-0" />
                    <span>{STAGE_MAP[entry.from].label} → {STAGE_MAP[entry.to].label}</span>
                    <span className="ml-auto text-[10px]">{formatDateTime(entry.at)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-1 text-xs text-muted-foreground">
            <p>作成: {formatDateTime(item.createdAt)}</p>
            <p>更新: {formatDateTime(item.updatedAt)}</p>
          </div>

          <Button
            variant="destructive"
            size="sm"
            className="w-full"
            onClick={() => { if (window.confirm("このコンテンツを削除しますか？")) onDelete(); }}
          >
            <Trash2 className="h-4 w-4" />
            削除
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// NewContentForm
// ---------------------------------------------------------------------------

function NewContentForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (data: { title: string; description: string; stage: Stage; agent: string }) => void;
  onCancel: () => void;
}) {
  const titleRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [stage, setStage] = useState<Stage>("idea");
  const [agent, setAgent] = useState("");

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    onSubmit({
      title: title.trim(),
      description: description.trim(),
      stage,
      agent: agent.trim() || "writer",
    });
  };

  return (
    <Card className="p-4">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">新規コンテンツ</h2>
          <button type="button" onClick={onCancel} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="mb-1 block text-xs text-muted-foreground">タイトル</label>
            <Input ref={titleRef} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="コンテンツタイトル" required />
          </div>
          <div className="sm:col-span-2">
            <label className="mb-1 block text-xs text-muted-foreground">説明</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="コンテンツの概要（任意）"
              rows={2}
              className="flex w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">ステージ</label>
            <select
              value={stage}
              onChange={(e) => setStage(e.target.value as Stage)}
              className="flex h-9 w-full rounded-md border border-border bg-transparent px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {STAGES.map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">担当エージェント</label>
            <Input value={agent} onChange={(e) => setAgent(e.target.value)} placeholder="writer" />
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>キャンセル</Button>
          <Button type="submit" size="sm">
            <Plus className="h-4 w-4" />
            追加
          </Button>
        </div>
      </form>
    </Card>
  );
}
