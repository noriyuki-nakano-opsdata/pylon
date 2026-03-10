import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Megaphone, Search, Map, ArrowRight, TrendingUp } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageSkeleton } from "@/components/PageSkeleton";
import { EmptyState } from "@/components/EmptyState";
import { adsApi } from "@/api/ads";
import { cn } from "@/lib/utils";
import type { AuditGrade, AggregateReport, AdsPlatform } from "@/types/ads";

const GRADE_COLORS: Record<AuditGrade, string> = {
  A: "bg-emerald-500/10 text-emerald-500 border-emerald-500/30",
  B: "bg-blue-500/10 text-blue-500 border-blue-500/30",
  C: "bg-yellow-500/10 text-yellow-500 border-yellow-500/30",
  D: "bg-orange-500/10 text-orange-500 border-orange-500/30",
  F: "bg-red-500/10 text-red-500 border-red-500/30",
};

const PLATFORM_LABELS: Record<AdsPlatform, string> = {
  google: "Google Ads",
  meta: "Meta Ads",
  linkedin: "LinkedIn Ads",
  tiktok: "TikTok Ads",
  microsoft: "Microsoft Ads",
};

export function AdsDashboard() {
  const navigate = useNavigate();

  const { data: reports, isLoading, isError } = useQuery({
    queryKey: ["ads", "reports"],
    queryFn: () => adsApi.listReports(),
    retry: false,
  });

  if (isLoading) return <PageSkeleton />;

  if (isError || !reports || reports.length === 0) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Megaphone}
          title="監査データがありません"
          description="最初の監査を実行して、広告アカウントの健全性スコアを確認しましょう。"
          action={{ label: "監査を実行", onClick: () => navigate("audit") }}
        />
      </div>
    );
  }

  const latest = reports[0];

  return (
    <div className="space-y-6 p-6">
      {/* Aggregate Health Score */}
      <Card>
        <CardContent className="p-6">
          <div className="flex items-center gap-6">
            <div className="text-center">
              <p className="text-sm text-muted-foreground mb-1">総合ヘルススコア</p>
              <p className="text-5xl font-bold text-foreground">{latest.aggregate_score}</p>
            </div>
            <Badge
              variant="outline"
              className={cn("text-2xl px-4 py-2 font-bold", GRADE_COLORS[latest.aggregate_grade])}
            >
              {latest.aggregate_grade}
            </Badge>
            <div className="flex-1" />
            <div className="text-right text-sm text-muted-foreground">
              <p>{latest.total_checks} チェック</p>
              <p className="text-emerald-500">{latest.passed_checks} 合格</p>
              <p className="text-yellow-500">{latest.warning_checks} 警告</p>
              <p className="text-red-500">{latest.failed_checks} 不合格</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Platform Score Cards */}
      <div>
        <h2 className="text-sm font-semibold text-foreground mb-3">プラットフォーム別スコア</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {latest.platforms.map((p) => (
            <Card key={p.platform}>
              <CardContent className="p-4">
                <p className="text-xs font-medium text-muted-foreground">{PLATFORM_LABELS[p.platform]}</p>
                <div className="flex items-baseline gap-2 mt-1">
                  <span className="text-2xl font-bold text-foreground">{p.score}</span>
                  <Badge variant="outline" className={cn("text-xs", GRADE_COLORS[p.grade])}>
                    {p.grade}
                  </Badge>
                </div>
                <div className="mt-2 h-1.5 w-full rounded-full bg-muted">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      p.score >= 80 ? "bg-emerald-500" : p.score >= 60 ? "bg-yellow-500" : "bg-red-500",
                    )}
                    style={{ width: `${p.score}%` }}
                  />
                </div>
                <p className="text-[11px] text-muted-foreground mt-1">{p.checks.length} チェック</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      {/* Quick Actions + Recent Reports */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Quick Actions */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">クイックアクション</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button className="w-full justify-start gap-2" onClick={() => navigate("audit")}>
              <Search className="h-4 w-4" /> 新規監査を実行
            </Button>
            <Button variant="outline" className="w-full justify-start gap-2" onClick={() => navigate("plan")}>
              <Map className="h-4 w-4" /> プランを生成
            </Button>
            <Button variant="outline" className="w-full justify-start gap-2" onClick={() => navigate("budget")}>
              <TrendingUp className="h-4 w-4" /> 予算を最適化
            </Button>
          </CardContent>
        </Card>

        {/* Recent Reports */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">最近の監査レポート</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {reports.slice(0, 5).map((r) => (
                <ReportRow key={r.id} report={r} onClick={() => navigate(`reports/${r.id}`)} />
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function ReportRow({ report, onClick }: { report: AggregateReport; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-md border border-border p-3 text-left transition-colors hover:bg-accent"
    >
      <Badge variant="outline" className={cn("text-sm font-bold", GRADE_COLORS[report.aggregate_grade])}>
        {report.aggregate_grade}
      </Badge>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground truncate">
          スコア: {report.aggregate_score} / 100
        </p>
        <p className="text-xs text-muted-foreground">
          {new Date(report.created_at).toLocaleDateString("ja-JP")} ・ {report.platforms.length} プラットフォーム
        </p>
      </div>
      <ArrowRight className="h-4 w-4 text-muted-foreground shrink-0" />
    </button>
  );
}
