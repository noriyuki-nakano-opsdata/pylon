import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DollarSign } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { PageSkeleton } from "@/components/PageSkeleton";
import { EmptyState } from "@/components/EmptyState";
import { queryKeys } from "@/lib/queryKeys";
import { costsApi } from "@/api/costs";
import { useI18n } from "@/contexts/I18nContext";
import { cn } from "@/lib/utils";

const PERIODS = [
  { value: "mtd", label: "MTD" },
  { value: "7d", label: "7 Days" },
  { value: "30d", label: "30 Days" },
  { value: "ytd", label: "YTD" },
  { value: "all", label: "All Time" },
] as const;

export function Costs() {
  const { t } = useI18n();
  const [period, setPeriod] = useState("mtd");

  const query = useQuery({
    queryKey: queryKeys.costs.summary(period),
    queryFn: () => costsApi.summary(period),
    retry: false,
  });

  if (query.isLoading) return <PageSkeleton />;

  const data = query.data;

  if (query.isError || !data) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold tracking-tight">{t("costs.title")}</h1>
        <EmptyState
          icon={DollarSign}
          title={t("costs.empty.title")}
          description={t("costs.empty.description")}
        />
      </div>
    );
  }

  const budgetPercent =
    data.budget_usd > 0
      ? Math.round((data.total_usd / data.budget_usd) * 100)
      : 0;

  const providerEntries = Object.entries(data.by_provider).sort(
    (a, b) => b[1] - a[1],
  );
  const modelEntries = Object.entries(data.by_model).sort(
    (a, b) => b[1] - a[1],
  );

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t("costs.title")}</h1>
        <p className="text-sm text-muted-foreground">
          {t("costs.description")}
        </p>
      </div>

      {/* Period selector */}
      <div className="flex gap-1">
        {PERIODS.map((p) => (
          <Button
            key={p.value}
            variant={period === p.value ? "default" : "ghost"}
            size="sm"
            onClick={() => setPeriod(p.value)}
          >
            {p.label}
          </Button>
        ))}
      </div>

      {/* Total + Budget */}
      <Card>
        <CardContent className="p-6">
          <div className="flex items-baseline justify-between">
            <div>
              <p className="text-sm text-muted-foreground">{t("costs.totalSpend")}</p>
              <p className="text-3xl font-bold">${data.total_usd.toFixed(2)}</p>
            </div>
            {data.budget_usd > 0 && (
              <div className="text-right">
                <p className="text-sm text-muted-foreground">{t("costs.budget")}</p>
                <p className="text-lg font-semibold">
                  ${data.budget_usd.toFixed(2)}
                </p>
              </div>
            )}
          </div>

          {data.budget_usd > 0 && (
            <div className="mt-4 space-y-1">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>{t("costs.usedPercent", { percent: budgetPercent })}</span>
                <span>
                  {t("costs.remaining", { amount: (data.budget_usd - data.total_usd).toFixed(2) })}
                </span>
              </div>
              <div className="h-2 w-full rounded-full bg-muted">
                <div
                  className={cn(
                    "h-full rounded-full transition-all",
                    budgetPercent >= 90
                      ? "bg-destructive"
                      : budgetPercent >= 70
                        ? "bg-warning"
                        : "bg-primary",
                  )}
                  style={{ width: `${Math.min(budgetPercent, 100)}%` }}
                />
              </div>
            </div>
          )}

          <div className="mt-4 flex gap-6 text-sm text-muted-foreground">
            <span>{t("costs.runs", { count: data.run_count })}</span>
            <span>{t("costs.tokensIn", { count: data.total_tokens_in.toLocaleString() })}</span>
            <span>{t("costs.tokensOut", { count: data.total_tokens_out.toLocaleString() })}</span>
          </div>
        </CardContent>
      </Card>

      {/* Breakdowns */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* By Provider */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("costs.byProvider")}</CardTitle>
          </CardHeader>
          <CardContent>
            {providerEntries.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("common.noData")}</p>
            ) : (
              <div className="space-y-3">
                {providerEntries.map(([provider, cost]) => (
                  <CostRow
                    key={provider}
                    label={provider}
                    value={cost}
                    total={data.total_usd}
                  />
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* By Model */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("costs.byModel")}</CardTitle>
          </CardHeader>
          <CardContent>
            {modelEntries.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("common.noData")}</p>
            ) : (
              <div className="space-y-3">
                {modelEntries.map(([model, cost]) => (
                  <CostRow
                    key={model}
                    label={model}
                    value={cost}
                    total={data.total_usd}
                  />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function CostRow({
  label,
  value,
  total,
}: {
  label: string;
  value: number;
  total: number;
}) {
  const percent = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="truncate font-medium">{label}</span>
        <span className="text-muted-foreground">
          ${value.toFixed(2)} ({percent}%)
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
