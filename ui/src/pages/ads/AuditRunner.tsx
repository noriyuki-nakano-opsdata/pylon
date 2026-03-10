import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Search, ChevronDown, ChevronUp, Play, AlertCircle,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AgentProgressView } from "@/components/lifecycle/AgentProgressView";
import { adsApi } from "@/api/ads";
import { cn } from "@/lib/utils";
import type { AdsPlatform, IndustryType, AuditRunConfig } from "@/types/ads";
import type { AgentProgress } from "@/hooks/useWorkflowRun";

const PLATFORMS: { id: AdsPlatform; label: string }[] = [
  { id: "google", label: "Google Ads" },
  { id: "meta", label: "Meta Ads" },
  { id: "linkedin", label: "LinkedIn Ads" },
  { id: "tiktok", label: "TikTok Ads" },
  { id: "microsoft", label: "Microsoft Ads" },
];

const INDUSTRIES: { value: IndustryType; label: string }[] = [
  { value: "saas", label: "SaaS" },
  { value: "ecommerce", label: "E-commerce" },
  { value: "local-service", label: "Local Service" },
  { value: "b2b-enterprise", label: "B2B Enterprise" },
  { value: "info-products", label: "Info Products" },
  { value: "mobile-app", label: "Mobile App" },
  { value: "real-estate", label: "Real Estate" },
  { value: "healthcare", label: "Healthcare" },
  { value: "finance", label: "Finance" },
  { value: "agency", label: "Agency" },
  { value: "generic", label: "Generic" },
];

const AUDIT_AGENTS = [
  { id: "audit-google", label: "Google Ads" },
  { id: "audit-meta", label: "Meta Ads" },
  { id: "audit-creative", label: "Creative" },
  { id: "audit-tracking", label: "Tracking" },
  { id: "audit-budget", label: "Budget" },
  { id: "audit-compliance", label: "Compliance" },
];

type Step = "config" | "running" | "complete";

export function AuditRunner() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("config");
  const [selectedPlatforms, setSelectedPlatforms] = useState<AdsPlatform[]>(["google", "meta"]);
  const [industryType, setIndustryType] = useState<IndustryType>("saas");
  const [monthlyBudget, setMonthlyBudget] = useState<string>("");
  const [accountDataOpen, setAccountDataOpen] = useState(false);
  const [accountData, setAccountData] = useState<Record<string, string>>({});
  const [runId, setRunId] = useState<string | null>(null);
  const [startTime] = useState(() => Date.now());

  const togglePlatform = (p: AdsPlatform) => {
    setSelectedPlatforms((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p],
    );
  };

  const startMutation = useMutation({
    mutationFn: (config: AuditRunConfig) => adsApi.runAudit(config),
    onSuccess: (data) => {
      setRunId(data.run_id);
      setStep("running");
    },
  });

  // Poll audit status when running
  const { data: statusData } = useQuery({
    queryKey: ["ads", "audit-status", runId],
    queryFn: () => adsApi.getAuditStatus(runId!),
    enabled: step === "running" && runId !== null,
    refetchInterval: 2000,
  });

  // Derive agent progress from status poll
  const agentProgress: AgentProgress[] = statusData?.progress
    ? Object.entries(statusData.progress).map(([nodeId, status]) => ({
        nodeId,
        agent: nodeId,
        status: status === "completed" ? "completed" as const
          : status === "running" ? "running" as const
          : status === "failed" ? "failed" as const
          : "pending" as const,
      }))
    : [];

  // Navigate to report when complete
  useEffect(() => {
    if (statusData?.status === "completed" && statusData.report) {
      navigate(`../reports/${statusData.report.id}`, { replace: true });
    }
  }, [statusData, navigate]);

  const handleStart = () => {
    const config: AuditRunConfig = {
      platforms: selectedPlatforms,
      industry_type: industryType,
      monthly_budget: monthlyBudget ? Number(monthlyBudget) : undefined,
      account_data: Object.keys(accountData).length > 0 ? accountData : undefined,
    };
    startMutation.mutate(config);
  };

  // Running state
  if (step === "running") {
    return (
      <AgentProgressView
        agents={AUDIT_AGENTS}
        progress={agentProgress}
        elapsedMs={Date.now() - startTime}
        title="広告監査を実行中..."
        subtitle="6つの専門エージェントがアカウントを分析しています"
      />
    );
  }

  // Config form
  return (
    <div className="mx-auto max-w-2xl space-y-6 p-6">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-bold text-foreground">
          <Search className="h-5 w-5 text-primary" /> 新規監査
        </h2>
        <p className="text-sm text-muted-foreground">
          監査対象のプラットフォームと業種を選択してください
        </p>
      </div>

      {/* Platform selection */}
      <Card>
        <CardContent className="p-4 space-y-3">
          <p className="text-sm font-medium text-foreground">プラットフォーム</p>
          <div className="flex flex-wrap gap-2">
            {PLATFORMS.map((p) => (
              <button
                key={p.id}
                onClick={() => togglePlatform(p.id)}
                className={cn(
                  "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors",
                  selectedPlatforms.includes(p.id)
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:border-primary/50",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Industry type */}
      <Card>
        <CardContent className="p-4 space-y-3">
          <p className="text-sm font-medium text-foreground">業種</p>
          <select
            value={industryType}
            onChange={(e) => setIndustryType(e.target.value as IndustryType)}
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground"
          >
            {INDUSTRIES.map((i) => (
              <option key={i.value} value={i.value}>{i.label}</option>
            ))}
          </select>
        </CardContent>
      </Card>

      {/* Monthly budget */}
      <Card>
        <CardContent className="p-4 space-y-3">
          <p className="text-sm font-medium text-foreground">月間予算 (任意)</p>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">$</span>
            <input
              type="number"
              value={monthlyBudget}
              onChange={(e) => setMonthlyBudget(e.target.value)}
              placeholder="10000"
              className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
            />
          </div>
        </CardContent>
      </Card>

      {/* Account data (collapsible) */}
      <Card>
        <CardContent className="p-4">
          <button
            onClick={() => setAccountDataOpen(!accountDataOpen)}
            className="flex w-full items-center justify-between text-sm font-medium text-foreground"
          >
            <span>アカウントデータ (任意)</span>
            {accountDataOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
          {accountDataOpen && (
            <div className="mt-3 space-y-3">
              {selectedPlatforms.map((p) => (
                <div key={p}>
                  <label className="text-xs text-muted-foreground">{PLATFORM_LABELS[p]}</label>
                  <textarea
                    value={accountData[p] ?? ""}
                    onChange={(e) => setAccountData((prev) => ({ ...prev, [p]: e.target.value }))}
                    rows={3}
                    placeholder="アカウントデータを貼り付け..."
                    className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
                  />
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Error */}
      {startMutation.isError && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          監査の開始に失敗しました。もう一度お試しください。
        </div>
      )}

      {/* Start button */}
      <Button
        onClick={handleStart}
        disabled={selectedPlatforms.length === 0 || startMutation.isPending}
        className="w-full gap-2"
        size="lg"
      >
        <Play className="h-4 w-4" />
        {startMutation.isPending ? "開始中..." : "監査を開始"}
      </Button>
    </div>
  );
}

const PLATFORM_LABELS: Record<AdsPlatform, string> = {
  google: "Google Ads",
  meta: "Meta Ads",
  linkedin: "LinkedIn Ads",
  tiktok: "TikTok Ads",
  microsoft: "Microsoft Ads",
};
