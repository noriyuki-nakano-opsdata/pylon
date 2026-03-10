import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  RefreshCw,
  ArrowRight,
  CheckCircle,
  XCircle,
  Zap,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageSkeleton } from "@/components/PageSkeleton";
import { queryKeys } from "@/lib/queryKeys";
import { modelsApi } from "@/api/models";
import type { ModelsResponse, HealthResponse } from "@/api/models";
import { cn } from "@/lib/utils";

const POLICY_OPTIONS = [
  { value: "auto", label: "Auto" },
  { value: "stable", label: "Stable" },
  { value: "pinned", label: "Pinned" },
];

function PolicyBadge({ policy }: { policy: string }) {
  const colors: Record<string, string> = {
    auto: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    stable: "bg-green-500/10 text-green-400 border-green-500/20",
    pinned: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
        colors[policy] ?? "bg-muted text-muted-foreground border-border",
      )}
    >
      {policy}
    </span>
  );
}

/* ── Section 1: Provider Health Cards ── */
function HealthCards({ health }: { health: HealthResponse | undefined }) {
  if (!health) return null;
  const entries = Object.entries(health);
  if (entries.length === 0) return null;

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold tracking-tight">
        プロバイダーヘルス
      </h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {entries.map(([provider, info]) => (
          <Card key={provider}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "h-2.5 w-2.5 rounded-full",
                      info.status === "ok" ? "bg-green-500" : "bg-red-500",
                    )}
                  />
                  <span className="font-medium capitalize">{provider}</span>
                </div>
                {info.status === "ok" ? (
                  <CheckCircle className="h-4 w-4 text-green-500" />
                ) : (
                  <XCircle className="h-4 w-4 text-red-500" />
                )}
              </div>
              <p className="mt-2 text-sm text-muted-foreground truncate">
                {info.model}
              </p>
              <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                <Activity className="h-3 w-3" />
                <span>{info.latency_ms}ms</span>
              </div>
              {info.error && (
                <p className="mt-1 text-xs text-red-400 truncate">
                  {info.error}
                </p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}

/* ── Section 2: Model Policies ── */
function PolicyEditor({
  models,
}: {
  models: ModelsResponse | undefined;
}) {
  const queryClient = useQueryClient();
  const [edits, setEdits] = useState<
    Record<string, { policy: string; pin?: string }>
  >({});

  const mutation = useMutation({
    mutationFn: ({
      provider,
      policy,
      pin,
    }: {
      provider: string;
      policy: string;
      pin?: string;
    }) => modelsApi.updatePolicy(provider, policy, pin),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.models.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.models.health });
    },
  });

  if (!models) return null;
  const providers = Object.entries(models.providers);
  if (providers.length === 0) return null;

  const getEdit = (provider: string) =>
    edits[provider] ?? {
      policy: models.providers[provider].policy,
      pin: models.providers[provider].pin,
    };

  const setEdit = (
    provider: string,
    patch: Partial<{ policy: string; pin?: string }>,
  ) => {
    setEdits((prev) => ({
      ...prev,
      [provider]: { ...getEdit(provider), ...patch },
    }));
  };

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold tracking-tight">
        モデルポリシー
      </h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {providers.map(([provider, info]) => {
          const edit = getEdit(provider);
          return (
            <Card key={provider}>
              <CardContent className="space-y-3 p-4">
                <div className="flex items-center justify-between">
                  <span className="font-medium capitalize">{provider}</span>
                  <PolicyBadge policy={info.policy} />
                </div>

                <div>
                  <label className="mb-1 block text-xs text-muted-foreground">
                    ポリシー
                  </label>
                  <select
                    value={edit.policy}
                    onChange={(e) =>
                      setEdit(provider, { policy: e.target.value })
                    }
                    className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  >
                    {POLICY_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>

                {edit.policy === "pinned" && (
                  <div>
                    <label className="mb-1 block text-xs text-muted-foreground">
                      固定モデル
                    </label>
                    <select
                      value={edit.pin ?? ""}
                      onChange={(e) =>
                        setEdit(provider, { pin: e.target.value })
                      }
                      className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                    >
                      <option value="">選択してください</option>
                      {info.models.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <Button
                  size="sm"
                  className="w-full"
                  disabled={mutation.isPending}
                  onClick={() =>
                    mutation.mutate({
                      provider,
                      policy: edit.policy,
                      pin: edit.policy === "pinned" ? edit.pin : undefined,
                    })
                  }
                >
                  保存
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </section>
  );
}

/* ── Section 3: Fallback Chain ── */
function FallbackChain({ chain }: { chain: string[] | undefined }) {
  if (!chain || chain.length === 0) return null;

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold tracking-tight">
        フォールバックチェーン
      </h2>
      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 p-4">
          {chain.map((provider, i) => (
            <div key={provider} className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 rounded-lg border border-border bg-accent/50 px-3 py-2">
                <Zap className="h-4 w-4 text-primary" />
                <span className="text-sm font-medium capitalize">
                  {provider}
                </span>
              </div>
              {i < chain.length - 1 && (
                <ArrowRight className="h-4 w-4 text-muted-foreground" />
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </section>
  );
}

/* ── Section 4: Available Models Table ── */
function ModelsTable({
  models,
  onRefresh,
  isRefreshing,
}: {
  models: ModelsResponse | undefined;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  if (!models) return null;
  const providers = Object.entries(models.providers);
  if (providers.length === 0) return null;

  const toggle = (provider: string) =>
    setExpanded((prev) => ({ ...prev, [provider]: !prev[provider] }));

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold tracking-tight">
          利用可能なモデル
        </h2>
        <Button
          variant="outline"
          size="sm"
          onClick={onRefresh}
          disabled={isRefreshing}
        >
          <RefreshCw
            className={cn("mr-1.5 h-3.5 w-3.5", isRefreshing && "animate-spin")}
          />
          モデル一覧を更新
        </Button>
      </div>

      <div className="space-y-2">
        {providers.map(([provider, info]) => {
          const isOpen = expanded[provider] ?? false;
          return (
            <Card key={provider}>
              <button
                onClick={() => toggle(provider)}
                className="flex w-full items-center justify-between p-4 text-left"
              >
                <div className="flex items-center gap-2">
                  {isOpen ? (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="font-medium capitalize">{provider}</span>
                  <span className="text-xs text-muted-foreground">
                    ({info.models.length} モデル)
                  </span>
                </div>
                <PolicyBadge policy={info.policy} />
              </button>
              {isOpen && (
                <CardContent className="border-t border-border px-4 pb-4 pt-0">
                  <table className="mt-3 w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted-foreground">
                        <th className="pb-2 font-medium">モデルID</th>
                        <th className="pb-2 font-medium">表示名</th>
                        <th className="pb-2 font-medium">バージョン</th>
                        <th className="pb-2 font-medium">作成日</th>
                      </tr>
                    </thead>
                    <tbody>
                      {info.models.map((m) => (
                        <tr
                          key={m.id}
                          className="border-t border-border/50"
                        >
                          <td className="py-2 font-mono text-xs">
                            {m.id}
                          </td>
                          <td className="py-2">{m.name}</td>
                          <td className="py-2 text-muted-foreground">
                            {m.version ?? "-"}
                          </td>
                          <td className="py-2 text-muted-foreground">
                            {m.created ?? "-"}
                          </td>
                        </tr>
                      ))}
                      {info.models.length === 0 && (
                        <tr>
                          <td
                            colSpan={4}
                            className="py-4 text-center text-muted-foreground"
                          >
                            モデルが見つかりません
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </CardContent>
              )}
            </Card>
          );
        })}
      </div>
    </section>
  );
}

/* ── Main Page ── */
export function Models() {
  const queryClient = useQueryClient();

  const modelsQuery = useQuery({
    queryKey: queryKeys.models.all,
    queryFn: () => modelsApi.list(),
  });

  const healthQuery = useQuery({
    queryKey: queryKeys.models.health,
    queryFn: () => modelsApi.health(),
    refetchInterval: 30_000,
  });

  const refreshMutation = useMutation({
    mutationFn: () => modelsApi.refresh(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.models.all });
    },
  });

  if (modelsQuery.isLoading) return <PageSkeleton />;

  return (
    <div className="space-y-8 p-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">モデル管理</h1>
        <p className="text-sm text-muted-foreground">
          LLMプロバイダーとモデルの設定・監視
        </p>
      </div>

      <HealthCards health={healthQuery.data} />
      <PolicyEditor models={modelsQuery.data} />
      <FallbackChain chain={modelsQuery.data?.fallback_chain} />
      <ModelsTable
        models={modelsQuery.data}
        onRefresh={() => refreshMutation.mutate()}
        isRefreshing={refreshMutation.isPending}
      />
    </div>
  );
}
