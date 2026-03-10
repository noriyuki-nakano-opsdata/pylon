import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Wallet, Loader2, TrendingUp, ArrowRight } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { adsApi } from "@/api/ads";
import { cn } from "@/lib/utils";
import type { AdsPlatform, BudgetAllocation } from "@/types/ads";

const PLATFORMS: { id: AdsPlatform; label: string }[] = [
  { id: "google", label: "Google Ads" },
  { id: "meta", label: "Meta Ads" },
  { id: "linkedin", label: "LinkedIn Ads" },
  { id: "tiktok", label: "TikTok Ads" },
  { id: "microsoft", label: "Microsoft Ads" },
];

const SPLIT_COLORS = {
  proven: "bg-emerald-500",
  growth: "bg-blue-500",
  experiment: "bg-purple-500",
};

const SPLIT_LABELS = {
  proven: "実績チャネル (70%)",
  growth: "成長チャネル (20%)",
  experiment: "実験チャネル (10%)",
};

export function BudgetOptimizer() {
  const [totalBudget, setTotalBudget] = useState<string>("");
  const [spend, setSpend] = useState<Record<AdsPlatform, string>>({
    google: "", meta: "", linkedin: "", tiktok: "", microsoft: "",
  });
  const [targetMer, setTargetMer] = useState<string>("3.0");

  const mutation = useMutation({
    mutationFn: () => {
      const currentSpend = Object.fromEntries(
        PLATFORMS.map((p) => [p.id, Number(spend[p.id]) || 0]),
      ) as Record<AdsPlatform, number>;
      return adsApi.optimizeBudget(
        currentSpend,
        Number(targetMer) || 3.0,
        Number(totalBudget) || undefined,
      );
    },
  });

  const result = mutation.data;

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-bold text-foreground">
          <Wallet className="h-5 w-5 text-primary" /> 予算最適化
        </h2>
        <p className="text-sm text-muted-foreground">
          現在の支出データから最適な予算配分を算出します
        </p>
      </div>

      {/* Input Section */}
      <Card>
        <CardContent className="p-4 space-y-4">
          {/* Total budget */}
          <div>
            <label className="text-sm font-medium text-foreground">月間総予算</label>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-sm text-muted-foreground">$</span>
              <input
                type="number"
                value={totalBudget}
                onChange={(e) => setTotalBudget(e.target.value)}
                placeholder="50000"
                className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
              />
            </div>
          </div>

          {/* Per-platform spend */}
          <div>
            <label className="text-sm font-medium text-foreground">プラットフォーム別現在支出</label>
            <div className="mt-2 space-y-2">
              {PLATFORMS.map((p) => (
                <div key={p.id} className="flex items-center gap-3">
                  <span className="w-28 text-sm text-muted-foreground">{p.label}</span>
                  <span className="text-sm text-muted-foreground">$</span>
                  <input
                    type="number"
                    value={spend[p.id]}
                    onChange={(e) => setSpend((prev) => ({ ...prev, [p.id]: e.target.value }))}
                    placeholder="0"
                    className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Target MER */}
          <div>
            <label className="text-sm font-medium text-foreground">目標MER (Marketing Efficiency Ratio)</label>
            <input
              type="number"
              step="0.1"
              value={targetMer}
              onChange={(e) => setTargetMer(e.target.value)}
              placeholder="3.0"
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
            />
          </div>

          <Button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="w-full gap-2"
            size="lg"
          >
            {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <TrendingUp className="h-4 w-4" />}
            最適化を実行
          </Button>
        </CardContent>
      </Card>

      {/* Result Section */}
      {result && <OptimizationResult result={result} currentSpend={spend} />}
    </div>
  );
}

function OptimizationResult({
  result,
  currentSpend,
}: {
  result: BudgetAllocation;
  currentSpend: Record<AdsPlatform, string>;
}) {
  return (
    <div className="space-y-4">
      {/* 70/20/10 Split */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">70/20/10 予算配分</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {(["proven", "growth", "experiment"] as const).map((key) => {
            const value = result[key];
            const pct = result.monthly_budget > 0 ? (value / result.monthly_budget) * 100 : 0;
            return (
              <div key={key} className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-foreground font-medium">{SPLIT_LABELS[key]}</span>
                  <span className="text-muted-foreground">${value.toLocaleString()}</span>
                </div>
                <div className="h-3 w-full rounded-full bg-muted">
                  <div
                    className={cn("h-full rounded-full transition-all", SPLIT_COLORS[key])}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* Platform Mix: Current vs Recommended */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">プラットフォーム別配分</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {PLATFORMS.map((p) => {
            const current = Number(currentSpend[p.id]) || 0;
            const recommended = result.platform_mix[p.id] ?? 0;
            const maxVal = Math.max(current, recommended, 1);

            return (
              <div key={p.id} className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-foreground font-medium w-28">{p.label}</span>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span>${current.toLocaleString()}</span>
                    <ArrowRight className="h-3 w-3" />
                    <span className="text-primary font-medium">${recommended.toLocaleString()}</span>
                    {recommended !== current && (
                      <Badge
                        variant="outline"
                        className={cn(
                          "text-[10px]",
                          recommended > current ? "text-emerald-500" : "text-red-500",
                        )}
                      >
                        {recommended > current ? "+" : ""}{current > 0 ? (((recommended - current) / current) * 100).toFixed(0) : "∞"}%
                      </Badge>
                    )}
                  </div>
                </div>
                <div className="flex gap-1">
                  <div className="h-2 flex-1 rounded-full bg-muted relative">
                    <div
                      className="absolute inset-y-0 left-0 rounded-full bg-muted-foreground/30"
                      style={{ width: `${(current / maxVal) * 100}%` }}
                    />
                  </div>
                  <div className="h-2 flex-1 rounded-full bg-muted relative">
                    <div
                      className="absolute inset-y-0 left-0 rounded-full bg-primary"
                      style={{ width: `${(recommended / maxVal) * 100}%` }}
                    />
                  </div>
                </div>
                <div className="flex gap-1 text-[10px] text-muted-foreground">
                  <span className="flex-1">現在</span>
                  <span className="flex-1">推奨</span>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* Summary */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-4 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">月間予算</p>
              <p className="font-bold text-foreground">${result.monthly_budget.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">目標MER</p>
              <p className="font-bold text-foreground">{result.mer_target}x</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
