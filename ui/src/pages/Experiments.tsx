import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { Beaker, Play, Pause, RefreshCw, Square, GitBranch, Trophy, Activity, ShieldCheck, ShieldAlert } from "lucide-react";
import { experimentsApi, type CreateExperimentCampaignRequest, type ExperimentCampaign, type ExperimentIteration } from "@/api/experiments";
import { approvalsApi } from "@/api/approvals";
import { EmptyState } from "@/components/EmptyState";
import { PageSkeleton } from "@/components/PageSkeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { queryKeys } from "@/lib/queryKeys";

const DEFAULT_FORM: CreateExperimentCampaignRequest = {
  objective: "",
  repo_path: "",
  benchmark_command: "",
  planner_command: "",
  checks_command: "",
  metric_name: "latency",
  metric_direction: "minimize",
  metric_unit: "ms",
  metric_parser: "metric-line",
  metric_regex: "",
  max_iterations: 3,
  base_ref: "HEAD",
  promotion_branch: "",
  sandbox: {
    tier: "docker",
    allow_internet: false,
  },
  cleanup: {
    runtime_ttl_seconds: 21600,
    preserve_failed_worktrees: false,
  },
};

export function Experiments() {
  const { projectSlug } = useParams<{ projectSlug: string }>();
  const queryClient = useQueryClient();
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null);
  const [promotionBranch, setPromotionBranch] = useState("");
  const [form, setForm] = useState<CreateExperimentCampaignRequest>({
    ...DEFAULT_FORM,
    project_slug: projectSlug,
  });

  const campaignsQuery = useQuery({
    queryKey: queryKeys.experiments.list(projectSlug),
    queryFn: () => experimentsApi.list(projectSlug),
    refetchInterval: (query) => {
      const campaigns = query.state.data ?? [];
      return campaigns.some(isCampaignLive) ? 1200 : false;
    },
  });

  useEffect(() => {
    setForm((current) => ({ ...current, project_slug: projectSlug }));
  }, [projectSlug]);

  useEffect(() => {
    if (!campaignsQuery.data?.length) {
      setSelectedCampaignId(null);
      return;
    }
    if (!selectedCampaignId || !campaignsQuery.data.some((item) => item.id === selectedCampaignId)) {
      setSelectedCampaignId(campaignsQuery.data[0].id);
    }
  }, [campaignsQuery.data, selectedCampaignId]);

  const detailQuery = useQuery({
    queryKey: selectedCampaignId ? queryKeys.experiments.detail(selectedCampaignId) : ["experiments", "none"],
    queryFn: () => experimentsApi.get(selectedCampaignId!),
    enabled: Boolean(selectedCampaignId),
    refetchInterval: (query) => {
      const campaign = query.state.data?.campaign;
      return campaign && isCampaignLive(campaign) ? 1000 : false;
    },
  });

  useEffect(() => {
    const branch = detailQuery.data?.campaign.promotion.branch ?? "";
    setPromotionBranch(branch);
  }, [detailQuery.data?.campaign.promotion.branch, detailQuery.data?.campaign.id]);

  const invalidateExperiments = async (campaignId?: string) => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.experiments.list(projectSlug) });
    if (campaignId) {
      await queryClient.invalidateQueries({ queryKey: queryKeys.experiments.detail(campaignId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.experiments.iterations(campaignId) });
    }
  };

  const createMutation = useMutation({
    mutationFn: experimentsApi.create,
    onSuccess: async (detail) => {
      setSelectedCampaignId(detail.campaign.id);
      setForm((current) => ({
        ...DEFAULT_FORM,
        repo_path: current.repo_path,
        benchmark_command: current.benchmark_command,
        planner_command: current.planner_command,
        checks_command: current.checks_command,
        metric_name: current.metric_name,
        metric_direction: current.metric_direction,
        metric_unit: current.metric_unit,
        sandbox: { ...current.sandbox },
        cleanup: { ...current.cleanup },
        project_slug: projectSlug,
      }));
      await invalidateExperiments(detail.campaign.id);
    },
  });

  const startMutation = useMutation({
    mutationFn: (campaignId: string) => experimentsApi.start(campaignId),
    onSuccess: async (detail) => invalidateExperiments(detail.campaign.id),
  });
  const pauseMutation = useMutation({
    mutationFn: (campaignId: string) => experimentsApi.pause(campaignId),
    onSuccess: async (detail) => invalidateExperiments(detail.campaign.id),
  });
  const resumeMutation = useMutation({
    mutationFn: (campaignId: string) => experimentsApi.resume(campaignId),
    onSuccess: async (detail) => invalidateExperiments(detail.campaign.id),
  });
  const cancelMutation = useMutation({
    mutationFn: (campaignId: string) => experimentsApi.cancel(campaignId),
    onSuccess: async (detail) => invalidateExperiments(detail.campaign.id),
  });
  const promoteMutation = useMutation({
    mutationFn: ({ campaignId, branchName }: { campaignId: string; branchName: string }) =>
      experimentsApi.promote(campaignId, branchName),
    onSuccess: async (detail) => invalidateExperiments(detail.campaign.id),
  });
  const approveMutation = useMutation({
    mutationFn: (approvalId: string) => approvalsApi.approve(approvalId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["approvals"] });
      await invalidateExperiments(selectedCampaignId ?? undefined);
    },
  });
  const rejectMutation = useMutation({
    mutationFn: ({ approvalId, reason }: { approvalId: string; reason?: string }) =>
      approvalsApi.reject(approvalId, reason),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["approvals"] });
      await invalidateExperiments(selectedCampaignId ?? undefined);
    },
  });

  const selectedCampaign = detailQuery.data?.campaign ?? null;
  const selectedIterations = detailQuery.data?.iterations ?? [];
  const activeApproval = selectedCampaign?.approval ?? null;
  const latestEvents = useMemo(
    () => [...(selectedCampaign?.events ?? [])].reverse().slice(0, 8),
    [selectedCampaign?.events],
  );

  if (campaignsQuery.isLoading) return <PageSkeleton />;

  const campaigns = campaignsQuery.data ?? [];

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Experiment Campaigns</h1>
          <p className="text-sm text-muted-foreground">
            Git worktree-isolated optimization loops for benchmark-driven improvement.
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
          {projectSlug ? `Project: ${projectSlug}` : "No project route context"}
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Beaker className="h-4 w-4" />
                New Campaign
              </CardTitle>
              <CardDescription>
                Command planner is the primary path. Benchmark output should emit `METRIC name=value`.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Input
                placeholder="Objective"
                value={form.objective}
                onChange={(event) => setForm((current) => ({ ...current, objective: event.target.value }))}
              />
              <Input
                placeholder="Repository path"
                value={form.repo_path}
                onChange={(event) => setForm((current) => ({ ...current, repo_path: event.target.value }))}
              />
              <textarea
                className="min-h-[84px] w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder="Planner command"
                value={form.planner_command}
                onChange={(event) => setForm((current) => ({ ...current, planner_command: event.target.value }))}
              />
              <textarea
                className="min-h-[84px] w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder="Benchmark command"
                value={form.benchmark_command}
                onChange={(event) => setForm((current) => ({ ...current, benchmark_command: event.target.value }))}
              />
              <textarea
                className="min-h-[68px] w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder="Checks command (optional)"
                value={form.checks_command}
                onChange={(event) => setForm((current) => ({ ...current, checks_command: event.target.value }))}
              />
              <div className="grid grid-cols-2 gap-3">
                <Input
                  placeholder="Metric name"
                  value={form.metric_name}
                  onChange={(event) => setForm((current) => ({ ...current, metric_name: event.target.value }))}
                />
                <select
                  className="flex h-9 w-full rounded-md border border-border bg-transparent px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  value={form.metric_direction}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      metric_direction: event.target.value as "minimize" | "maximize",
                    }))
                  }
                >
                  <option value="minimize">Minimize</option>
                  <option value="maximize">Maximize</option>
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Input
                  placeholder="Metric unit"
                  value={form.metric_unit}
                  onChange={(event) => setForm((current) => ({ ...current, metric_unit: event.target.value }))}
                />
                <Input
                  type="number"
                  min={1}
                  placeholder="Iterations"
                  value={String(form.max_iterations)}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      max_iterations: Number.parseInt(event.target.value || "1", 10),
                    }))
                  }
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Input
                  placeholder="Base ref"
                  value={form.base_ref}
                  onChange={(event) => setForm((current) => ({ ...current, base_ref: event.target.value }))}
                />
                <Input
                  placeholder="Promotion branch"
                  value={form.promotion_branch}
                  onChange={(event) => setForm((current) => ({ ...current, promotion_branch: event.target.value }))}
                />
              </div>
              <div className="rounded-lg border border-border/60 bg-accent/10 p-3">
                <p className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
                  Sandbox Policy
                </p>
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <select
                    className="flex h-9 w-full rounded-md border border-border bg-transparent px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    value={form.sandbox?.tier ?? "docker"}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        sandbox: {
                          ...current.sandbox,
                          tier: event.target.value,
                        },
                      }))
                    }
                  >
                    <option value="docker">Docker</option>
                    <option value="gvisor">gVisor</option>
                    <option value="firecracker">Firecracker</option>
                    <option value="none">Host</option>
                  </select>
                  <Input
                    type="number"
                    min={60}
                    placeholder="Cleanup TTL (sec)"
                    value={String(form.cleanup?.runtime_ttl_seconds ?? 21600)}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        cleanup: {
                          ...current.cleanup,
                          runtime_ttl_seconds: Number.parseInt(event.target.value || "21600", 10),
                        },
                      }))
                    }
                  />
                </div>
                <div className="mt-3 flex flex-wrap gap-4 text-sm">
                  <label className="flex items-center gap-2 text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={Boolean(form.sandbox?.allow_internet)}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          sandbox: {
                            ...current.sandbox,
                            allow_internet: event.target.checked,
                          },
                        }))
                      }
                    />
                    Allow internet egress
                  </label>
                  <label className="flex items-center gap-2 text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={Boolean(form.cleanup?.preserve_failed_worktrees)}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          cleanup: {
                            ...current.cleanup,
                            preserve_failed_worktrees: event.target.checked,
                          },
                        }))
                      }
                    />
                    Preserve failed worktrees
                  </label>
                </div>
              </div>
              {createMutation.error instanceof Error && (
                <p className="text-sm text-destructive">{createMutation.error.message}</p>
              )}
              <Button
                className="w-full"
                onClick={() => createMutation.mutate({ ...form, project_slug: projectSlug })}
                disabled={createMutation.isPending}
              >
                {createMutation.isPending ? "Creating..." : "Create Campaign"}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Campaigns</CardTitle>
              <CardDescription>{campaigns.length} registered campaign(s)</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {campaigns.length === 0 ? (
                <EmptyState
                  icon={Beaker}
                  title="No experiment campaigns"
                  description="Create a benchmark-driven campaign to begin iterative optimization."
                />
              ) : (
                campaigns.map((campaign) => (
                  <button
                    key={campaign.id}
                    onClick={() => setSelectedCampaignId(campaign.id)}
                    className={`w-full rounded-lg border p-4 text-left transition-colors ${
                      selectedCampaignId === campaign.id
                        ? "border-primary bg-primary/5"
                        : "border-border hover:border-primary/40"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium">{campaign.name}</p>
                        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{campaign.objective}</p>
                      </div>
                      <StatusBadge status={campaign.status} className="shrink-0" />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                      <span>{campaign.progress.completed_iterations}/{campaign.progress.max_iterations} iters</span>
                      {campaign.baseline && <span>baseline {formatMetric(campaign.baseline.value, campaign.metric.unit)}</span>}
                      {campaign.best && <span>best {formatMetric(campaign.best.value, campaign.metric.unit)}</span>}
                    </div>
                  </button>
                ))
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          {!selectedCampaign ? (
            <EmptyState
              icon={Activity}
              title="Select a campaign"
              description="The right-hand panel shows live campaign detail, iteration history, and promotion state."
            />
          ) : detailQuery.isLoading ? (
            <PageSkeleton />
          ) : (
            <>
              <Card>
                <CardHeader>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <CardTitle className="text-xl">{selectedCampaign.name}</CardTitle>
                      <CardDescription>{selectedCampaign.objective}</CardDescription>
                    </div>
                    <StatusBadge status={selectedCampaign.status} />
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-3">
                    <MetricCard
                      icon={Activity}
                      label="Baseline"
                      value={selectedCampaign.baseline ? formatMetric(selectedCampaign.baseline.value, selectedCampaign.metric.unit) : "Pending"}
                    />
                    <MetricCard
                      icon={Trophy}
                      label="Best"
                      value={selectedCampaign.best ? formatMetric(selectedCampaign.best.value, selectedCampaign.metric.unit) : "None"}
                    />
                    <MetricCard
                      icon={GitBranch}
                      label="Promotion"
                      value={selectedCampaign.promotion.branch}
                    />
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {selectedCampaign.status === "draft" && (
                      <Button onClick={() => startMutation.mutate(selectedCampaign.id)} disabled={startMutation.isPending}>
                        <Play className="mr-2 h-4 w-4" />
                        Start
                      </Button>
                    )}
                    {selectedCampaign.status === "running" && (
                      <>
                        <Button variant="outline" onClick={() => pauseMutation.mutate(selectedCampaign.id)} disabled={pauseMutation.isPending}>
                          <Pause className="mr-2 h-4 w-4" />
                          Pause
                        </Button>
                        <Button variant="outline" onClick={() => cancelMutation.mutate(selectedCampaign.id)} disabled={cancelMutation.isPending}>
                          <Square className="mr-2 h-4 w-4" />
                          Cancel
                        </Button>
                      </>
                    )}
                    {selectedCampaign.status === "paused" && (
                      <>
                        <Button onClick={() => resumeMutation.mutate(selectedCampaign.id)} disabled={resumeMutation.isPending}>
                          <RefreshCw className="mr-2 h-4 w-4" />
                          Resume
                        </Button>
                        <Button variant="outline" onClick={() => cancelMutation.mutate(selectedCampaign.id)} disabled={cancelMutation.isPending}>
                          <Square className="mr-2 h-4 w-4" />
                          Cancel
                        </Button>
                      </>
                    )}
                    {selectedCampaign.status === "waiting_approval" && (
                      <Button variant="outline" onClick={() => cancelMutation.mutate(selectedCampaign.id)} disabled={cancelMutation.isPending}>
                        <Square className="mr-2 h-4 w-4" />
                        Cancel
                      </Button>
                    )}
                  </div>

                  {activeApproval?.required && activeApproval.status === "pending" && activeApproval.request_id && (
                    <div className="rounded-lg border border-warning/30 bg-warning/5 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <ShieldAlert className="h-4 w-4 text-warning" />
                            <p className="font-medium">Approval Required</p>
                          </div>
                          <p className="text-sm text-muted-foreground">
                            {activeApproval.message ?? "This experiment action is waiting for operator approval."}
                          </p>
                          <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                            <span>Request: <span className="font-mono">{activeApproval.request_id.slice(0, 12)}</span></span>
                            {activeApproval.expires_at && <span>Expires: {activeApproval.expires_at}</span>}
                            {activeApproval.target_branch && <span>Branch: <span className="font-mono">{activeApproval.target_branch}</span></span>}
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Button
                            variant="outline"
                            disabled={rejectMutation.isPending}
                            onClick={() =>
                              rejectMutation.mutate({
                                approvalId: activeApproval.request_id!,
                                reason: "Rejected from experiments surface",
                              })
                            }
                          >
                            Reject
                          </Button>
                          <Button
                            disabled={approveMutation.isPending}
                            onClick={() => approveMutation.mutate(activeApproval.request_id!)}
                          >
                            <ShieldCheck className="mr-2 h-4 w-4" />
                            Approve
                          </Button>
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
                    <div className="space-y-3 rounded-lg border border-border p-4">
                      <h3 className="font-medium">Execution</h3>
                      <dl className="space-y-2 text-sm">
                        <InfoRow label="Repo path" value={selectedCampaign.repo_path} mono />
                        <InfoRow label="Base ref" value={selectedCampaign.base_ref} mono />
                        <InfoRow label="Metric" value={`${selectedCampaign.metric.name} (${selectedCampaign.metric.direction})`} />
                        <InfoRow label="Iterations" value={`${selectedCampaign.progress.completed_iterations} / ${selectedCampaign.progress.max_iterations}`} />
                        <InfoRow label="Planner" value={selectedCampaign.planner.type === "command" ? "command planner" : `${selectedCampaign.planner.type} planner`} />
                        <InfoRow label="Sandbox tier" value={selectedCampaign.sandbox.tier} />
                        <InfoRow label="Internet" value={selectedCampaign.sandbox.allow_internet ? "allowed" : "blocked"} />
                        <InfoRow label="Cleanup TTL" value={`${selectedCampaign.cleanup.runtime_ttl_seconds}s`} />
                        <InfoRow label="Preserve failed" value={selectedCampaign.cleanup.preserve_failed_worktrees ? "yes" : "no"} />
                        <InfoRow label="Promotion status" value={selectedCampaign.promotion.status} />
                      </dl>
                    </div>

                    <div className="space-y-3 rounded-lg border border-border p-4">
                      <h3 className="font-medium">Promote</h3>
                      <Input
                        value={promotionBranch}
                        onChange={(event) => setPromotionBranch(event.target.value)}
                        placeholder="Promotion branch"
                      />
                      <Button
                        className="w-full"
                        variant="outline"
                        disabled={!selectedCampaign.best || promoteMutation.isPending}
                        onClick={() => promoteMutation.mutate({ campaignId: selectedCampaign.id, branchName: promotionBranch })}
                      >
                        {selectedCampaign.promotion.status === "approval_pending"
                          ? "Promotion Awaiting Approval"
                          : "Promote Best Candidate"}
                      </Button>
                      {selectedCampaign.best && (
                        <p className="text-xs text-muted-foreground">
                          Best ref: <span className="font-mono">{selectedCampaign.best.ref.slice(0, 12)}</span>
                        </p>
                      )}
                    </div>
                  </div>

                  {selectedCampaign.context_bundle && (
                    <div className="rounded-lg border border-border p-4">
                      <h3 className="font-medium">Agent Context</h3>
                      <dl className="mt-3 space-y-2 text-sm">
                        <InfoRow label="Workspace root" value={selectedCampaign.context_bundle.workspace_root} mono />
                        <InfoRow label="Runtime root" value={selectedCampaign.context_bundle.runtime_root} mono />
                        <InfoRow label="Brief" value={selectedCampaign.context_bundle.files.brief ?? "n/a"} mono />
                        <InfoRow label="History" value={selectedCampaign.context_bundle.files.history_markdown ?? "n/a"} mono />
                        <InfoRow label="Ideas" value={selectedCampaign.context_bundle.files.ideas ?? "n/a"} mono />
                      </dl>
                    </div>
                  )}

                  {selectedCampaign.last_error && (
                    <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                      {selectedCampaign.last_error}
                    </div>
                  )}
                </CardContent>
              </Card>

              <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Iterations</CardTitle>
                    <CardDescription>Baseline plus candidate attempts with diff and benchmark evidence.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {selectedIterations.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No iterations yet.</p>
                    ) : (
                      selectedIterations.map((iteration) => (
                        <IterationCard key={iteration.id} iteration={iteration} metricUnit={selectedCampaign.metric.unit} />
                      ))
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Recent Events</CardTitle>
                    <CardDescription>Most recent campaign state changes.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {latestEvents.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No events recorded.</p>
                    ) : (
                      latestEvents.map((event) => (
                        <div key={`${event.timestamp}-${event.kind}`} className="rounded-lg border border-border p-3">
                          <div className="flex items-center justify-between gap-3">
                            <Badge variant={event.level === "error" ? "destructive" : "secondary"}>
                              {event.kind}
                            </Badge>
                            <span className="text-[11px] text-muted-foreground">{event.timestamp}</span>
                          </div>
                          <p className="mt-2 text-sm">{event.message}</p>
                        </div>
                      ))
                    )}
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-accent/20 p-4">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <div className="mt-2 text-lg font-semibold">{value}</div>
    </div>
  );
}

function IterationCard({
  iteration,
  metricUnit,
}: {
  iteration: ExperimentIteration;
  metricUnit?: string;
}) {
  return (
    <div className="rounded-lg border border-border p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <p className="font-medium">
              {iteration.kind === "baseline" ? "Baseline" : `Iteration ${iteration.sequence}`}
            </p>
            {iteration.outcome && <Badge variant="secondary">{iteration.outcome}</Badge>}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{iteration.id}</p>
        </div>
        <StatusBadge status={iteration.status} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <InfoRow
          label="Metric"
          value={
            iteration.metric?.value != null
              ? formatMetric(iteration.metric.value, metricUnit)
              : "Not captured"
          }
        />
        <InfoRow
          label="Decision"
          value={iteration.decision?.reason ?? "Pending"}
        />
        <InfoRow label="Commit" value={iteration.commit_ref ?? "Uncommitted"} mono />
        <InfoRow label="Files" value={String(iteration.changed_files?.length ?? 0)} />
        <InfoRow
          label="Sandbox"
          value={String(iteration.benchmark?.sandbox?.tier ?? iteration.planner?.sandbox?.tier ?? "n/a")}
        />
        <InfoRow
          label="CPU"
          value={
            iteration.benchmark?.resource_usage
              ? `${iteration.benchmark.resource_usage.cpu_ms} ms`
              : "n/a"
          }
        />
      </div>
      {iteration.diff_stat && (
        <pre className="mt-3 overflow-x-auto rounded-md bg-muted/50 p-3 text-xs">{iteration.diff_stat}</pre>
      )}
      {iteration.benchmark?.stdout && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-muted-foreground">Benchmark output</summary>
          <pre className="mt-2 overflow-x-auto rounded-md bg-muted/50 p-3 text-xs">{iteration.benchmark.stdout}</pre>
        </details>
      )}
      {iteration.planner?.stderr && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-muted-foreground">Planner stderr</summary>
          <pre className="mt-2 overflow-x-auto rounded-md bg-muted/50 p-3 text-xs">{iteration.planner.stderr}</pre>
        </details>
      )}
      {iteration.benchmark?.policy_blocked && (
        <p className="mt-3 text-xs text-destructive">Sandbox policy blocked this command.</p>
      )}
    </div>
  );
}

function InfoRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={mono ? "max-w-[70%] truncate font-mono text-xs" : "text-right"}>{value}</span>
    </div>
  );
}

function formatMetric(value: number, unit?: string) {
  const rounded = Number.isInteger(value) ? String(value) : value.toFixed(3);
  return unit ? `${rounded} ${unit}` : rounded;
}

function isCampaignLive(campaign: ExperimentCampaign) {
  return campaign.status === "running" || campaign.control.pause_requested || campaign.control.cancel_requested;
}
