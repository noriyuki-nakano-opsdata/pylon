import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  Search,
  Plus,
  Tag,
  Clock,
  Bot,
  X,
  BookOpen,
  Lightbulb,
  Database,
  FileText,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDateTime } from "@/lib/time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import {
  listMemories,
  createMemory,
  deleteMemory as apiDeleteMemory,
  type MemoryRecord,
} from "@/api/mission-control";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type MemoryCategory = "sessions" | "patterns" | "learnings" | "decisions";

interface MemoryEntry {
  id: number;
  title: string;
  content: string;
  category: MemoryCategory;
  tags: string[];
  sourceAgent: string;
  createdAt: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CATEGORY_TABS = [
  { key: "all", label: "すべて", icon: Database },
  { key: "sessions", label: "セッション", icon: FileText },
  { key: "patterns", label: "パターン", icon: BookOpen },
  { key: "learnings", label: "学習", icon: Lightbulb },
  { key: "decisions", label: "意思決定", icon: Brain },
] as const;

const CATEGORY_VARIANT: Record<MemoryCategory, "default" | "secondary" | "success" | "warning"> = {
  sessions: "secondary",
  patterns: "default",
  learnings: "success",
  decisions: "warning",
};

const CATEGORY_LABEL: Record<MemoryCategory, string> = {
  sessions: "セッション",
  patterns: "パターン",
  learnings: "学習",
  decisions: "意思決定",
};

function apiToEntry(record: MemoryRecord): MemoryEntry {
  const details = record.details || {};
  return {
    id: record.id,
    title: record.title || (details as Record<string, string>).title || "",
    content: record.content || (details as Record<string, string>).content || "",
    category: (record.category || (details as Record<string, string>).category || "patterns") as MemoryCategory,
    tags: ((details as Record<string, string[]>).tags || []),
    sourceAgent: record.actor || "system",
    createdAt: record.timestamp,
  };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MemoryCard({
  memory,
  onClick,
}: {
  memory: MemoryEntry;
  onClick: () => void;
}) {
  const formatted = formatDateTime(memory.createdAt);

  return (
    <Card
      className="cursor-pointer break-inside-avoid p-4 transition-colors hover:bg-accent/50"
      onClick={onClick}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold leading-snug text-foreground">
          {memory.title}
        </h3>
        <Badge variant={CATEGORY_VARIANT[memory.category]} className="shrink-0">
          {CATEGORY_LABEL[memory.category]}
        </Badge>
      </div>

      <p className="mb-3 line-clamp-3 text-xs leading-relaxed text-muted-foreground">
        {memory.content}
      </p>

      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <Bot className="h-3 w-3" />
          {memory.sourceAgent}
        </span>
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {formatted}
        </span>
      </div>

      {memory.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {memory.tags.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-0.5 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
            >
              <Tag className="h-2.5 w-2.5" />
              {tag}
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}

function MemoryDetailOverlay({
  memory,
  onClose,
  onDelete,
}: {
  memory: MemoryEntry;
  onClose: () => void;
  onDelete: () => void;
}) {
  const formatted = formatDateTime(memory.createdAt);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />
      <aside className="fixed inset-y-0 right-0 z-50 flex w-[400px] flex-col border-l border-border bg-background shadow-2xl animate-in slide-in-from-right duration-200">
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-lg font-semibold text-foreground">メモリー詳細</h2>
          <button onClick={onClose} className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          <div className="flex items-start gap-2">
            <Badge variant={CATEGORY_VARIANT[memory.category]}>
              {CATEGORY_LABEL[memory.category]}
            </Badge>
          </div>

          <h3 className="text-base font-bold text-foreground">{memory.title}</h3>

          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <Bot className="h-3.5 w-3.5" />
              {memory.sourceAgent}
            </span>
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              {formatted}
            </span>
          </div>

          <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
            {memory.content}
          </p>

          {memory.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {memory.tags.map((tag) => (
                <span key={tag} className="inline-flex items-center gap-0.5 rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                  <Tag className="h-3 w-3" />
                  {tag}
                </span>
              ))}
            </div>
          )}

          <div className="flex justify-end border-t border-border pt-4">
            <Button variant="destructive" size="sm" onClick={onDelete}>
              削除
            </Button>
          </div>
        </div>
      </aside>
    </>
  );
}

function AddMemoryOverlay({
  onClose,
  onAdd,
}: {
  onClose: () => void;
  onAdd: (entry: { title: string; content: string; category: MemoryCategory; tags: string[]; sourceAgent: string }) => void;
}) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [category, setCategory] = useState<MemoryCategory>("patterns");
  const [tagsInput, setTagsInput] = useState("");
  const [sourceAgent, setSourceAgent] = useState("");

  const handleSubmit = () => {
    if (!title.trim() || !content.trim()) return;
    const tags = tagsInput.split(",").map((t) => t.trim()).filter(Boolean);
    onAdd({
      title: title.trim(),
      content: content.trim(),
      category,
      tags,
      sourceAgent: sourceAgent.trim() || "user",
    });
    onClose();
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />
      <aside className="fixed inset-y-0 right-0 z-50 flex w-[400px] flex-col border-l border-border bg-background shadow-2xl animate-in slide-in-from-right duration-200">
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-lg font-semibold text-foreground">メモリーを追加</h2>
          <button onClick={onClose} className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">タイトル</label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="メモリーのタイトル" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">内容</label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="メモリーの詳細内容"
              rows={5}
              className="flex w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">カテゴリ</label>
            <div className="flex flex-wrap gap-2">
              {(["sessions", "patterns", "learnings", "decisions"] as const).map((cat) => (
                <button
                  key={cat}
                  type="button"
                  onClick={() => setCategory(cat)}
                  className={cn(
                    "rounded-md border px-3 py-1 text-xs font-medium transition-colors",
                    category === cat
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:text-foreground",
                  )}
                >
                  {CATEGORY_LABEL[cat]}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">タグ（カンマ区切り）</label>
            <Input value={tagsInput} onChange={(e) => setTagsInput(e.target.value)} placeholder="例: 認証, JWT, セキュリティ" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">ソースエージェント</label>
            <Input value={sourceAgent} onChange={(e) => setSourceAgent(e.target.value)} placeholder="例: coder, planner" />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" size="sm" onClick={onClose}>キャンセル</Button>
            <Button size="sm" onClick={handleSubmit} disabled={!title.trim() || !content.trim()}>
              <Plus className="mr-1 h-3.5 w-3.5" />
              追加
            </Button>
          </div>
        </div>
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export function Memory() {
  const queryClient = useQueryClient();
  const { data: memoriesData, isLoading: loading, error: queryError } = useQuery({
    queryKey: ["memories"],
    queryFn: async () => {
      const records = await listMemories();
      return records.map(apiToEntry);
    },
  });
  const memories = useMemo(() => memoriesData ?? [], [memoriesData]);
  const error = queryError ? (queryError instanceof Error ? queryError.message : "メモリーの取得に失敗しました") : null;

  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<string>("all");
  const [selectedMemory, setSelectedMemory] = useState<MemoryEntry | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);

  const createMutation = useMutation({
    mutationFn: (entry: { title: string; content: string; category: MemoryCategory; tags: string[]; sourceAgent: string }) =>
      createMemory({
        title: entry.title,
        content: entry.content,
        category: entry.category,
        actor: entry.sourceAgent,
        tags: entry.tags,
        details: { tags: entry.tags },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["memories"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: apiDeleteMemory,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["memories"] }),
  });

  const handleAdd = (entry: { title: string; content: string; category: MemoryCategory; tags: string[]; sourceAgent: string }) => {
    createMutation.mutate(entry);
  };

  const handleDelete = (id: number) => {
    deleteMutation.mutate(id);
  };

  const filtered = useMemo(() => {
    let result = memories;
    if (activeTab !== "all") {
      result = result.filter((m) => m.category === activeTab);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (m) =>
          m.title.toLowerCase().includes(q) ||
          m.content.toLowerCase().includes(q) ||
          m.tags.some((t) => t.toLowerCase().includes(q)),
      );
    }
    return result;
  }, [memories, activeTab, searchQuery]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">メモリー</h1>
          <p className="text-sm text-muted-foreground">
            AIエージェントの記憶・知識ベース（{memories.length}件）
          </p>
        </div>
        <Button size="sm" onClick={() => setShowAddForm(true)}>
          <Plus className="mr-1 h-4 w-4" />
          追加
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="タイトル・内容・タグで検索..."
          className="pl-9"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery("")}
            className="absolute right-3 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      <div className="flex gap-1 border-b border-border">
        {CATEGORY_TABS.map((tab) => {
          const isActive = activeTab === tab.key;
          const Icon = tab.icon;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                "inline-flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Brain className="mb-3 h-10 w-10 text-muted-foreground/50" />
          <p className="text-sm font-medium text-muted-foreground">
            {searchQuery ? "一致するメモリーが見つかりません" : "メモリーがありません"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground/70">
            {searchQuery ? "検索条件を変更してください" : "「追加」ボタンからメモリーを作成できます"}
          </p>
        </div>
      ) : (
        <div className="columns-1 gap-4 sm:columns-2 lg:columns-3">
          {filtered.map((memory) => (
            <div key={memory.id} className="mb-4">
              <MemoryCard memory={memory} onClick={() => setSelectedMemory(memory)} />
            </div>
          ))}
        </div>
      )}

      {selectedMemory && (
        <MemoryDetailOverlay
          memory={selectedMemory}
          onClose={() => setSelectedMemory(null)}
          onDelete={() => {
            handleDelete(selectedMemory.id);
            setSelectedMemory(null);
          }}
        />
      )}

      {showAddForm && (
        <AddMemoryOverlay onClose={() => setShowAddForm(false)} onAdd={handleAdd} />
      )}
    </div>
  );
}
