import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { agentsApi } from "@/api/agents";
import { modelsApi } from "@/api/models";
import { queryKeys } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";

const AUTONOMY_LEVELS = [
  { value: "A0", label: "A0 — 完全手動", description: "完全手動（承認なしでは何もしない）" },
  { value: "A1", label: "A1 — 提案のみ", description: "提案のみ（実行は人間が判断）" },
  { value: "A2", label: "A2 — 半自律", description: "半自律（低リスク操作は自動、高リスクは承認要求）" },
  { value: "A3", label: "A3 — 高自律", description: "高自律（ほぼ全て自動、重大変更のみ承認）" },
  { value: "A4", label: "A4 — 完全自律", description: "完全自律（全操作を自動実行）" },
];

const SANDBOX_OPTIONS = [
  { value: "gvisor", label: "gVisor", description: "軽量サンドボックス（ファイルシステム分離）" },
  { value: "docker", label: "Docker", description: "コンテナ分離（ネットワーク+ファイル分離）" },
  { value: "kata", label: "Kata", description: "マイクロVM（完全仮想化、最高セキュリティ）" },
  { value: "none", label: "None", description: "サンドボックスなし（開発環境のみ）" },
];

const AVAILABLE_TOOLS = [
  "file-read", "file-write", "shell", "http", "browser",
  "code-search", "code-edit", "git", "database",
];

const FALLBACK_MODELS = [
  { provider: "anthropic", id: "anthropic/claude-sonnet-4-6", name: "claude-sonnet-4-6" },
  { provider: "anthropic", id: "anthropic/claude-haiku-4-5-20251001", name: "claude-haiku-4-5-20251001" },
  { provider: "openai", id: "openai/gpt-5-mini", name: "gpt-5-mini" },
  { provider: "moonshot", id: "moonshot/kimi-k2.5", name: "kimi-k2.5" },
  { provider: "zhipu", id: "zhipu/glm-4-plus", name: "glm-4-plus" },
  { provider: "gemini", id: "gemini/gemini-3-pro-preview", name: "gemini-3-pro-preview" },
];

export function AgentNew() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [name, setName] = useState("");
  const [model, setModel] = useState("anthropic/claude-sonnet-4-6");
  const [role, setRole] = useState("");
  const [autonomy, setAutonomy] = useState("A2");
  const [sandbox, setSandbox] = useState("gvisor");
  const [selectedTools, setSelectedTools] = useState<string[]>([]);

  const modelsQuery = useQuery({
    queryKey: queryKeys.models.all,
    queryFn: () => modelsApi.list(),
  });

  const mutation = useMutation({
    mutationFn: () =>
      agentsApi.create({
        name,
        model,
        role,
        autonomy,
        sandbox,
        tools: selectedTools,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.agents.list() });
      navigate("/agents");
    },
  });

  const toggleTool = (tool: string) => {
    setSelectedTools((prev) =>
      prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool],
    );
  };

  const isValid = name.trim() && model.trim() && role.trim();

  // Build model options grouped by provider
  const modelOptions = (() => {
    if (modelsQuery.data) {
      const groups: { provider: string; models: { id: string; name: string }[] }[] = [];
      for (const [provider, info] of Object.entries(modelsQuery.data.providers)) {
        groups.push({
          provider,
          models: info.models.map((m) => ({
            id: `${provider}/${m.id}`,
            name: m.name,
          })),
        });
      }
      return groups;
    }
    // Fallback: group hardcoded list by provider
    const grouped = new Map<string, { id: string; name: string }[]>();
    for (const m of FALLBACK_MODELS) {
      const list = grouped.get(m.provider) ?? [];
      list.push({ id: m.id, name: m.name });
      grouped.set(m.provider, list);
    }
    return Array.from(grouped.entries()).map(([provider, models]) => ({
      provider,
      models,
    }));
  })();

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link to="/agents" className="rounded-md p-1 hover:bg-accent">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <Bot className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-2xl font-bold tracking-tight">New Agent</h1>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Basic info */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Basic Configuration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <FieldGroup label="Name" description="Unique identifier for this agent">
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. planner, coder, reviewer"
              />
            </FieldGroup>

            <FieldGroup label="Model" description="LLMプロバイダーとモデルID">
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                {modelOptions.map((group) => (
                  <optgroup key={group.provider} label={group.provider}>
                    {group.models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.id}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </FieldGroup>

            <FieldGroup label="Role" description="What this agent does">
              <Input
                value={role}
                onChange={(e) => setRole(e.target.value)}
                placeholder="e.g. Analyze requirements and create implementation plans"
              />
            </FieldGroup>
          </CardContent>
        </Card>

        {/* Autonomy */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Autonomy Level</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {AUTONOMY_LEVELS.map((level) => (
                <button
                  key={level.value}
                  onClick={() => setAutonomy(level.value)}
                  className={cn(
                    "flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors",
                    autonomy === level.value
                      ? "border-primary bg-primary/5"
                      : "border-border hover:bg-accent/50",
                  )}
                >
                  <div
                    className={cn(
                      "mt-0.5 h-4 w-4 shrink-0 rounded-full border-2",
                      autonomy === level.value
                        ? "border-primary bg-primary"
                        : "border-muted-foreground",
                    )}
                  />
                  <div>
                    <p className="text-sm font-medium text-foreground">{level.label}</p>
                    <p className="text-xs text-muted-foreground">{level.description}</p>
                  </div>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Sandbox */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Sandbox</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-2">
              {SANDBOX_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setSandbox(opt.value)}
                  className={cn(
                    "rounded-lg border p-3 text-left transition-colors",
                    sandbox === opt.value
                      ? "border-primary bg-primary/5"
                      : "border-border hover:bg-accent/50",
                  )}
                >
                  <p className="text-sm font-medium text-foreground">{opt.label}</p>
                  <p className="text-xs text-muted-foreground">{opt.description}</p>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Tools */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tools</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {AVAILABLE_TOOLS.map((tool) => (
                <button
                  key={tool}
                  onClick={() => toggleTool(tool)}
                  className={cn(
                    "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                    selectedTools.includes(tool)
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30",
                  )}
                >
                  {tool}
                </button>
              ))}
            </div>
            {selectedTools.length > 0 && (
              <p className="mt-3 text-xs text-muted-foreground">
                {selectedTools.length} tool{selectedTools.length !== 1 ? "s" : ""} selected
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3 border-t border-border pt-6">
        <Button
          onClick={() => mutation.mutate()}
          disabled={!isValid || mutation.isPending}
        >
          {mutation.isPending ? "Creating..." : "Create Agent"}
        </Button>
        <Button variant="ghost" onClick={() => navigate("/agents")}>
          Cancel
        </Button>
        {mutation.isError && (
          <p className="text-sm text-destructive">
            {(mutation.error as Error).message}
          </p>
        )}
      </div>
    </div>
  );
}

function FieldGroup({
  label,
  description,
  children,
}: {
  label: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-foreground">{label}</label>
      <p className="mb-1.5 text-xs text-muted-foreground">{description}</p>
      {children}
    </div>
  );
}
