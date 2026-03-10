import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Wand2,
  Search,
  X,
  Tag,
  Play,
  Info,
  Loader2,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Shield,
  AlertTriangle,
  ShieldAlert,
  Minus,
  Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { PageSkeleton } from "@/components/PageSkeleton";
import { queryKeys } from "@/lib/queryKeys";
import { skillsApi, type SkillInfo, type SkillExecuteResponse } from "@/api/skills";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const RISK_CONFIG: Record<SkillInfo["risk"], { label: string; color: string; icon: React.ElementType }> = {
  safe: { label: "安全", color: "bg-green-500/10 text-green-500 border-green-500/20", icon: Shield },
  unknown: { label: "不明", color: "bg-amber-500/10 text-amber-500 border-amber-500/20", icon: AlertTriangle },
  critical: { label: "危険", color: "bg-red-500/10 text-red-500 border-red-500/20", icon: ShieldAlert },
};

const SOURCE_CONFIG: Record<SkillInfo["source"], { label: string; color: string }> = {
  builtin: { label: "ビルトイン", color: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
  local: { label: "ローカル", color: "bg-purple-500/10 text-purple-400 border-purple-500/20" },
  community: { label: "コミュニティ", color: "bg-teal-500/10 text-teal-400 border-teal-500/20" },
};

const CATEGORY_COLORS: Record<string, string> = {
  development: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  security: "bg-red-500/10 text-red-400 border-red-500/20",
  devops: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  documentation: "bg-green-500/10 text-green-400 border-green-500/20",
};

function getCategoryColor(category: string): string {
  return CATEGORY_COLORS[category] ?? "bg-muted text-muted-foreground border-border";
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function RiskBadge({ risk }: { risk: SkillInfo["risk"] }) {
  const config = RISK_CONFIG[risk];
  const Icon = config.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium", config.color)}>
      <Icon className="h-3 w-3" />
      {config.label}
    </span>
  );
}

function SourceBadge({ source }: { source: SkillInfo["source"] }) {
  const config = SOURCE_CONFIG[source];
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium", config.color)}>
      {config.label}
    </span>
  );
}

function CategoryBadge({ category }: { category: string }) {
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium", getCategoryColor(category))}>
      {category}
    </span>
  );
}

function StatsBar({ total, sources }: { total: number; sources: Record<string, number> }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className="text-sm text-muted-foreground">
        合計 <span className="font-semibold text-foreground">{total}</span> 件
      </span>
      {Object.entries(sources).map(([source, count]) => {
        const config = SOURCE_CONFIG[source as SkillInfo["source"]];
        if (!config) return null;
        return (
          <span key={source} className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium", config.color)}>
            {config.label}: {count}
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skill Card
// ---------------------------------------------------------------------------

function SkillCard({
  skill,
  onExecute,
  onDetail,
}: {
  skill: SkillInfo;
  onExecute: () => void;
  onDetail: () => void;
}) {
  return (
    <Card className="flex flex-col p-4 transition-colors hover:bg-accent/50">
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="text-sm font-bold leading-snug text-foreground">{skill.name}</h3>
        <RiskBadge risk={skill.risk} />
      </div>

      <p className="mb-3 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
        {skill.description}
      </p>

      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <CategoryBadge category={skill.category} />
        <SourceBadge source={skill.source} />
      </div>

      {skill.tags.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {skill.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-0.5 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
            >
              <Tag className="h-2.5 w-2.5" />
              {tag}
            </span>
          ))}
          {skill.tags.length > 3 && (
            <span className="text-[10px] text-muted-foreground">+{skill.tags.length - 3}</span>
          )}
        </div>
      )}

      <div className="mt-auto flex items-center gap-2 pt-1">
        <Button size="sm" className="h-7 text-xs" onClick={onExecute}>
          <Play className="mr-1 h-3 w-3" />
          実行
        </Button>
        <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onDetail}>
          <Info className="mr-1 h-3 w-3" />
          詳細
        </Button>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Detail Panel
// ---------------------------------------------------------------------------

function SkillDetailPanel({
  skillId,
  onClose,
  onExecute,
}: {
  skillId: string;
  onClose: () => void;
  onExecute: () => void;
}) {
  const { data: skill, isLoading } = useQuery({
    queryKey: queryKeys.skills.detail(skillId),
    queryFn: () => skillsApi.get(skillId),
  });

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />
      <aside className="fixed inset-y-0 right-0 z-50 flex w-[420px] flex-col border-l border-border bg-background shadow-2xl animate-in slide-in-from-right duration-200">
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-lg font-semibold text-foreground">スキル詳細</h2>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {isLoading ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : skill ? (
          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
            <h3 className="text-base font-bold text-foreground">{skill.name}</h3>
            <p className="text-sm leading-relaxed text-muted-foreground">{skill.description}</p>

            <div className="flex flex-wrap items-center gap-2">
              <RiskBadge risk={skill.risk} />
              <CategoryBadge category={skill.category} />
              <SourceBadge source={skill.source} />
            </div>

            {skill.tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {skill.tags.map((tag) => (
                  <span key={tag} className="inline-flex items-center gap-0.5 rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    <Tag className="h-3 w-3" />
                    {tag}
                  </span>
                ))}
              </div>
            )}

            <div className="space-y-2 text-xs text-muted-foreground">
              {skill.path && (
                <div>
                  <span className="font-medium text-foreground">パス: </span>
                  <code className="rounded bg-muted px-1.5 py-0.5">{skill.path}</code>
                </div>
              )}
              {skill.installed_at && (
                <div>
                  <span className="font-medium text-foreground">インストール日: </span>
                  {skill.installed_at}
                </div>
              )}
              {skill.has_scripts != null && (
                <div>
                  <span className="font-medium text-foreground">スクリプト: </span>
                  {skill.has_scripts ? "あり" : "なし"}
                </div>
              )}
            </div>

            {skill.content && (
              <div>
                <h4 className="mb-1.5 text-xs font-medium text-foreground">コンテンツ</h4>
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted/50 p-3 text-xs leading-relaxed text-foreground">
                  {skill.content}
                </pre>
              </div>
            )}

            <div className="flex justify-end border-t border-border pt-4">
              <Button size="sm" onClick={onExecute}>
                <Play className="mr-1 h-3.5 w-3.5" />
                実行
              </Button>
            </div>
          </div>
        ) : null}
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// Execute Panel
// ---------------------------------------------------------------------------

function SkillExecutePanel({
  skill,
  onClose,
}: {
  skill: SkillInfo;
  onClose: () => void;
}) {
  const [input, setInput] = useState("");
  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState("");
  const [showContext, setShowContext] = useState(false);
  const [contextPairs, setContextPairs] = useState<{ key: string; value: string }[]>([]);
  const [result, setResult] = useState<SkillExecuteResponse | null>(null);

  const PROVIDERS = [
    { id: "anthropic", label: "Anthropic", models: ["claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-opus-4-6"] },
    { id: "openai", label: "OpenAI", models: ["gpt-5-mini", "gpt-4.1", "gpt-4.1-mini"] },
    { id: "gemini", label: "Google Gemini", models: ["gemini-3-flash-preview", "gemini-3.1-flash-lite-preview", "gemini-2.5-flash"] },
    { id: "moonshot", label: "Moonshot", models: ["kimi-k2.5"] },
    { id: "zhipu", label: "ZhipuAI", models: ["glm-4-plus"] },
  ];

  const currentProvider = PROVIDERS.find((p) => p.id === provider);

  const executeMutation = useMutation({
    mutationFn: () => {
      const ctx: Record<string, string> = {};
      for (const pair of contextPairs) {
        if (pair.key.trim()) ctx[pair.key.trim()] = pair.value;
      }
      return skillsApi.execute(
        skill.id,
        input,
        Object.keys(ctx).length > 0 ? ctx : undefined,
        provider,
        model || undefined,
      );
    },
    onSuccess: (data) => setResult(data),
  });

  const addContextPair = () => setContextPairs([...contextPairs, { key: "", value: "" }]);
  const removeContextPair = (index: number) => setContextPairs(contextPairs.filter((_, i) => i !== index));
  const updateContextPair = (index: number, field: "key" | "value", val: string) => {
    const next = [...contextPairs];
    next[index] = { ...next[index], [field]: val };
    setContextPairs(next);
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />
      <aside className="fixed inset-y-0 right-0 z-50 flex w-[480px] flex-col border-l border-border bg-background shadow-2xl animate-in slide-in-from-right duration-200">
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-foreground">スキル実行</h2>
            <p className="text-xs text-muted-foreground">{skill.name}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">入力</label>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="スキルに渡す入力を入力..."
              rows={5}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          {/* Provider / Model selection */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">プロバイダー</label>
              <select
                value={provider}
                onChange={(e) => { setProvider(e.target.value); setModel(""); }}
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>{p.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">モデル</label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="">自動選択（ポリシーに従う）</option>
                {currentProvider?.models.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <button
              type="button"
              onClick={() => setShowContext(!showContext)}
              className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              {showContext ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              コンテキスト（オプション）
            </button>

            {showContext && (
              <div className="mt-2 space-y-2">
                {contextPairs.map((pair, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Input
                      value={pair.key}
                      onChange={(e) => updateContextPair(i, "key", e.target.value)}
                      placeholder="キー"
                      className="h-8 text-xs"
                    />
                    <Input
                      value={pair.value}
                      onChange={(e) => updateContextPair(i, "value", e.target.value)}
                      placeholder="値"
                      className="h-8 text-xs"
                    />
                    <button
                      type="button"
                      onClick={() => removeContextPair(i)}
                      className="shrink-0 rounded p-1 text-muted-foreground hover:text-foreground"
                    >
                      <Minus className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
                <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={addContextPair}>
                  <Plus className="mr-1 h-3 w-3" />
                  追加
                </Button>
              </div>
            )}
          </div>

          <Button
            onClick={() => executeMutation.mutate()}
            disabled={!input.trim() || executeMutation.isPending}
            className="w-full"
          >
            {executeMutation.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                実行中...
              </>
            ) : (
              <>
                <Play className="mr-2 h-4 w-4" />
                実行開始
              </>
            )}
          </Button>

          {executeMutation.isError && (
            <div className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
              実行エラー: {(executeMutation.error as Error).message}
            </div>
          )}

          {result && (
            <div className="space-y-3">
              <h4 className="text-sm font-semibold text-foreground">実行結果</h4>
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted/50 p-4 text-xs leading-relaxed text-foreground">
                {result.result}
              </pre>
              <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
                <span>プロバイダー: {result.provider}</span>
                <span>モデル: {result.model}</span>
                <span>入力: {result.tokens_in.toLocaleString()} tokens</span>
                <span>出力: {result.tokens_out.toLocaleString()} tokens</span>
              </div>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export function Skills() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [selectedSkillId, setSelectedSkillId] = useState<string | null>(null);
  const [executeSkill, setExecuteSkill] = useState<SkillInfo | null>(null);
  const [scanMessage, setScanMessage] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: [...queryKeys.skills.all, categoryFilter, sourceFilter, search],
    queryFn: () =>
      skillsApi.list({
        category: categoryFilter || undefined,
        source: sourceFilter || undefined,
        search: search || undefined,
      }),
  });

  const scanMutation = useMutation({
    mutationFn: skillsApi.scan,
    onSuccess: (result) => {
      setScanMessage(`スキャン完了: 合計${result.total}件（新規${result.new}件、削除${result.removed}件）`);
      queryClient.invalidateQueries({ queryKey: queryKeys.skills.all });
      setTimeout(() => setScanMessage(null), 5000);
    },
    onError: (err: Error) => {
      setScanMessage(`スキャンエラー: ${err.message}`);
      setTimeout(() => setScanMessage(null), 5000);
    },
  });

  const skills = data?.skills ?? [];
  const categories = data?.categories ?? {};
  const sources = data?.sources ?? {};

  if (isLoading) return <PageSkeleton lines={8} />;

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">スキル管理</h1>
          <p className="text-sm text-muted-foreground">AIスキルの管理・テスト実行。エージェントへの割り当てはエージェント詳細で設定</p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => scanMutation.mutate()}
          disabled={scanMutation.isPending}
        >
          {scanMutation.isPending ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="mr-1 h-4 w-4" />
          )}
          スキルをスキャン
        </Button>
      </div>

      {/* Scan toast */}
      {scanMessage && (
        <div className={cn(
          "rounded-md border px-4 py-2 text-sm",
          scanMessage.includes("エラー")
            ? "border-red-500/30 bg-red-500/10 text-red-400"
            : "border-green-500/30 bg-green-500/10 text-green-400",
        )}>
          {scanMessage}
        </div>
      )}

      {/* Stats */}
      <StatsBar total={data?.total ?? 0} sources={sources} />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        >
          <option value="">すべてのカテゴリ</option>
          {Object.entries(categories).map(([cat, count]) => (
            <option key={cat} value={cat}>
              {cat} ({count})
            </option>
          ))}
        </select>

        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          className="h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        >
          <option value="">すべてのソース</option>
          {Object.entries(SOURCE_CONFIG).map(([key, config]) => (
            <option key={key} value={key}>
              {config.label}
            </option>
          ))}
        </select>

        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="スキルを検索..."
            className="pl-9"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Skills Grid */}
      {skills.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Wand2 className="mb-3 h-10 w-10 text-muted-foreground/50" />
          <p className="text-sm font-medium text-muted-foreground">
            {search || categoryFilter || sourceFilter ? "一致するスキルが見つかりません" : "スキルがありません"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground/70">
            {search || categoryFilter || sourceFilter
              ? "フィルター条件を変更してください"
              : "「スキルをスキャン」ボタンでスキルを読み込めます"}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {skills.map((skill) => (
            <SkillCard
              key={skill.id}
              skill={skill}
              onExecute={() => setExecuteSkill(skill)}
              onDetail={() => setSelectedSkillId(skill.id)}
            />
          ))}
        </div>
      )}

      {/* Detail Panel */}
      {selectedSkillId && (
        <SkillDetailPanel
          skillId={selectedSkillId}
          onClose={() => setSelectedSkillId(null)}
          onExecute={() => {
            const skill = skills.find((s) => s.id === selectedSkillId);
            if (skill) {
              setSelectedSkillId(null);
              setExecuteSkill(skill);
            }
          }}
        />
      )}

      {/* Execute Panel */}
      {executeSkill && (
        <SkillExecutePanel
          skill={executeSkill}
          onClose={() => setExecuteSkill(null)}
        />
      )}
    </div>
  );
}
