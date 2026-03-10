import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Map, Loader2, DollarSign, Target, Clock } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageSkeleton } from "@/components/PageSkeleton";
import { adsApi } from "@/api/ads";
import { cn } from "@/lib/utils";
import type { IndustryType, AdPlan, IndustryTemplate, AdsPlatform } from "@/types/ads";

const PLATFORM_LABELS: Record<AdsPlatform, string> = {
  google: "Google", meta: "Meta", linkedin: "LinkedIn",
  tiktok: "TikTok", microsoft: "Microsoft",
};

export function AdPlanGenerator() {
  const [selected, setSelected] = useState<IndustryType | null>(null);
  const [budget, setBudget] = useState<string>("");

  const { data: templates, isLoading: loadingTemplates } = useQuery({
    queryKey: ["ads", "templates"],
    queryFn: () => adsApi.getTemplates(),
  });

  const planMutation = useMutation({
    mutationFn: () => adsApi.generatePlan(selected!, Number(budget) || 0),
  });

  if (loadingTemplates) return <PageSkeleton />;

  const plan = planMutation.data;

  return (
    <div className="space-y-6 p-6">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-bold text-foreground">
          <Map className="h-5 w-5 text-primary" /> 広告プラン生成
        </h2>
        <p className="text-sm text-muted-foreground">
          業種テンプレートを選択して、最適な広告プランを生成します
        </p>
      </div>

      {/* Template Grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {(templates ?? FALLBACK_TEMPLATES).map((t) => (
          <button
            key={t.id}
            onClick={() => setSelected(t.id)}
            className="text-left"
          >
            <Card
              className={cn(
                "h-full transition-all",
                selected === t.id
                  ? "border-primary shadow-md shadow-primary/10"
                  : "hover:border-primary/30",
              )}
            >
              <CardContent className="p-4 space-y-2">
                <p className="text-sm font-bold text-foreground">{t.name}</p>
                <p className="text-xs text-muted-foreground line-clamp-2">{t.description}</p>
                <div className="flex flex-wrap gap-1">
                  {Object.keys(t.platforms).map((p) => (
                    <Badge key={p} variant="secondary" className="text-[10px]">
                      {PLATFORM_LABELS[p as AdsPlatform] ?? p}
                    </Badge>
                  ))}
                </div>
                <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
                  <DollarSign className="h-3 w-3" />
                  最低 ${t.min_monthly.toLocaleString()}/月
                </div>
              </CardContent>
            </Card>
          </button>
        ))}
      </div>

      {/* Budget input + Generate */}
      {selected && (
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <div className="flex items-center gap-2 flex-1">
              <span className="text-sm text-muted-foreground">月間予算</span>
              <span className="text-sm text-muted-foreground">$</span>
              <input
                type="number"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
                placeholder="10000"
                className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
              />
            </div>
            <Button
              onClick={() => planMutation.mutate()}
              disabled={planMutation.isPending}
              className="gap-2"
            >
              {planMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              プランを生成
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Plan Result */}
      {plan && <PlanResult plan={plan} />}
    </div>
  );
}

function PlanResult({ plan }: { plan: AdPlan }) {
  return (
    <div className="space-y-4">
      {/* Summary */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">プラン概要</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <p className="text-xs text-muted-foreground">推奨プラットフォーム</p>
              <div className="flex flex-wrap gap-1 mt-1">
                {plan.recommended_platforms.map((p) => (
                  <Badge key={p} variant="secondary" className="text-xs">
                    {PLATFORM_LABELS[p]}
                  </Badge>
                ))}
              </div>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">最低月間予算</p>
              <p className="text-sm font-bold text-foreground">${plan.monthly_budget_min.toLocaleString()}</p>
            </div>
            <div className="flex items-start gap-1">
              <Target className="h-3.5 w-3.5 text-muted-foreground mt-0.5" />
              <div>
                <p className="text-xs text-muted-foreground">主要KPI</p>
                <p className="text-sm font-medium text-foreground">{plan.primary_kpi}</p>
              </div>
            </div>
            <div className="flex items-start gap-1">
              <Clock className="h-3.5 w-3.5 text-muted-foreground mt-0.5" />
              <div>
                <p className="text-xs text-muted-foreground">収益化目安</p>
                <p className="text-sm font-medium text-foreground">{plan.time_to_profit}</p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Campaign Architecture */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">キャンペーン構成</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">プラットフォーム</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">キャンペーン名</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">目的</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">予算配分</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">ターゲティング</th>
                </tr>
              </thead>
              <tbody>
                {plan.campaign_architecture.map((c, i) => (
                  <tr key={i} className="border-b border-border last:border-0">
                    <td className="px-3 py-2">
                      <Badge variant="secondary" className="text-xs">{PLATFORM_LABELS[c.platform]}</Badge>
                    </td>
                    <td className="px-3 py-2 text-xs text-foreground">{c.campaign_name}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">{c.objective}</td>
                    <td className="px-3 py-2 text-right text-xs font-mono text-foreground">{(c.budget_share * 100).toFixed(0)}%</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground max-w-xs truncate">{c.targeting_summary}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

const FALLBACK_TEMPLATES: IndustryTemplate[] = [
  { id: "saas", name: "SaaS", description: "B2B SaaSプロダクト向け。リード獲得とデモ予約を最適化", platforms: { google: 40, linkedin: 35, meta: 25 }, min_monthly: 5000, primary_kpi: "CAC", time_to_profit: "3-6ヶ月" },
  { id: "ecommerce", name: "E-commerce", description: "オンラインストア向け。ROAS最大化と新規顧客獲得", platforms: { google: 35, meta: 40, tiktok: 25 }, min_monthly: 3000, primary_kpi: "ROAS", time_to_profit: "1-3ヶ月" },
  { id: "local-service", name: "ローカルサービス", description: "地域密着型ビジネス向け。来店と問合せを最適化", platforms: { google: 60, meta: 30, microsoft: 10 }, min_monthly: 1000, primary_kpi: "CPL", time_to_profit: "1-2ヶ月" },
  { id: "b2b-enterprise", name: "B2B Enterprise", description: "大企業向けソリューション。ABMとリードナーチャリング", platforms: { linkedin: 45, google: 35, meta: 20 }, min_monthly: 10000, primary_kpi: "SQL", time_to_profit: "6-12ヶ月" },
  { id: "info-products", name: "情報商材", description: "オンラインコース、電子書籍等。ファネル最適化", platforms: { meta: 45, google: 30, tiktok: 25 }, min_monthly: 2000, primary_kpi: "CPA", time_to_profit: "1-3ヶ月" },
  { id: "mobile-app", name: "モバイルアプリ", description: "アプリインストールとエンゲージメント最適化", platforms: { google: 35, meta: 35, tiktok: 30 }, min_monthly: 5000, primary_kpi: "CPI", time_to_profit: "3-6ヶ月" },
  { id: "real-estate", name: "不動産", description: "物件問合せとリード獲得を最適化", platforms: { google: 50, meta: 35, microsoft: 15 }, min_monthly: 3000, primary_kpi: "CPL", time_to_profit: "2-4ヶ月" },
  { id: "healthcare", name: "ヘルスケア", description: "医療・健康サービス向け。予約とコンプライアンス対応", platforms: { google: 55, meta: 30, microsoft: 15 }, min_monthly: 3000, primary_kpi: "CPA", time_to_profit: "2-4ヶ月" },
  { id: "finance", name: "金融", description: "金融サービス向け。リード獲得と規制対応", platforms: { google: 45, linkedin: 30, meta: 25 }, min_monthly: 8000, primary_kpi: "CAC", time_to_profit: "3-6ヶ月" },
  { id: "agency", name: "代理店", description: "マーケティング代理店向け。クライアント獲得", platforms: { google: 35, linkedin: 35, meta: 30 }, min_monthly: 5000, primary_kpi: "CAC", time_to_profit: "2-4ヶ月" },
  { id: "generic", name: "汎用", description: "業種を問わない標準テンプレート", platforms: { google: 40, meta: 35, microsoft: 25 }, min_monthly: 2000, primary_kpi: "CPA", time_to_profit: "2-4ヶ月" },
];
