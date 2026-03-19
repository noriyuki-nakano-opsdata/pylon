import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Rocket, ArrowRight, ArrowLeft, Monitor, Tablet, Smartphone,
  ExternalLink, Download, ShieldCheck, CheckCircle2, Loader2,
  AlertTriangle, XCircle, FileWarning, BarChart3,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { lifecycleApi } from "@/api/lifecycle";
import { persistCompletedPhase } from "@/lifecycle/phasePersistence";
import { useLifecycleActions, useLifecycleState } from "./LifecycleContext";
import {
  downstreamTopbarClassName,
  downstreamWorkspaceClassName,
} from "@/lifecycle/downstreamTheme";
import {
  presentDeployCheckStatusLabel,
  presentNamedItem,
  presentVariantModelLabel,
  presentVariantTitle,
} from "@/lifecycle/designDecisionPresentation";
import { selectDeploySummary, selectSelectedDesign } from "@/lifecycle/selectors";

export function DeployPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycleState();
  const actions = useLifecycleActions();
  const [device, setDevice] = useState<"desktop" | "tablet" | "mobile">("desktop");
  const [isChecking, setIsChecking] = useState(false);
  const [isDeploying, setIsDeploying] = useState(false);
  const [deployError, setDeployError] = useState<string | null>(null);
  const [releaseNote, setReleaseNote] = useState("");
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!lc.buildCode) {
      setBlobUrl(null);
      return undefined;
    }
    const blob = new Blob([lc.buildCode], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    setBlobUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [lc.buildCode]);

  const runChecks = async () => {
    if (!projectSlug) return;
    setIsChecking(true);
    try {
      const response = await lifecycleApi.runDeployChecks(projectSlug, lc.buildCode ?? undefined);
      actions.applyProject(response.project);
    } finally {
      setIsChecking(false);
    }
  };

  const deploy = async () => {
    if (!projectSlug) return;
    setIsDeploying(true);
    setDeployError(null);
    try {
      const response = await lifecycleApi.createRelease(projectSlug, releaseNote);
      const completed = await persistCompletedPhase(
        projectSlug,
        "deploy",
        response.project.phaseStatuses ?? lc.phaseStatuses,
      );
      actions.applyProject(completed.project);
      setReleaseNote("");
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : "リリースの確定に失敗しました");
    } finally {
      setIsDeploying(false);
    }
  };

  const downloadHtml = () => {
    if (!lc.buildCode) return;
    const blob = new Blob([lc.buildCode], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${projectSlug ?? "product"}.html`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const goNext = () => navigate(`/p/${projectSlug}/lifecycle/iterate`);
  const goBack = () => navigate(`/p/${projectSlug}/lifecycle/development`);

  const {
    checks,
    allPassed,
    blockingChecks,
    cautionChecks,
    deployed,
    latestRelease,
    passedCount,
    releaseSummary,
    warningCount,
    failedCount,
  } = selectDeploySummary(lc);
  const selectedDesign = selectSelectedDesign(lc);
  const selectedDesignTitle = selectedDesign ? presentVariantTitle(selectedDesign, -1) : "未選択";
  const selectedDesignModel = selectedDesign ? presentVariantModelLabel(selectedDesign) : "未選択";
  const valueContract = lc.valueContract ?? lc.deliveryPlan?.value_contract ?? null;
  const outcomeTelemetryContract = lc.outcomeTelemetryContract ?? lc.deliveryPlan?.outcome_telemetry_contract ?? null;
  const deviceWidth = device === "desktop" ? "100%" : device === "tablet" ? "768px" : "375px";
  const releaseGatePending = lc.nextAction?.phase === "deploy" && lc.nextAction?.type === "request_release_decision";
  const releaseGateReason = releaseGatePending ? lc.nextAction?.reason ?? "" : "";
  const releaseGateDecisions = releaseGatePending && Array.isArray(lc.nextAction?.payload?.availableDecisions)
    ? (lc.nextAction?.payload?.availableDecisions as string[])
    : [];

  return (
    <div className={cn(downstreamWorkspaceClassName, "flex h-full flex-col")}>
      <div className={cn(downstreamTopbarClassName, "flex flex-wrap items-center gap-2 px-6 py-3")}>
        <button onClick={goBack} className="text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" /></button>
        <h1 className="flex items-center gap-2 text-sm font-bold text-foreground">
          <Rocket className="h-4 w-4 text-primary" /> デプロイ
        </h1>
        <div className="flex-1" />
        <div className="flex gap-0.5 rounded-md border border-border p-0.5">
          {([["desktop", Monitor], ["tablet", Tablet], ["mobile", Smartphone]] as const).map(([kind, Icon]) => (
            <button key={kind} onClick={() => setDevice(kind)} className={cn("rounded p-1.5", device === kind ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground")}>
              <Icon className="h-3.5 w-3.5" />
            </button>
          ))}
        </div>
        {deployed && (
          <button onClick={goNext} className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90">
            改善フェーズへ <ArrowRight className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      <div className="flex flex-1 flex-col overflow-hidden xl:flex-row">
        <div className="relative flex min-h-[24rem] flex-1 justify-center bg-background p-4 xl:min-h-0">
          {deployError && (
            <div className="absolute left-4 right-4 top-4 z-10 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive shadow-sm">
              {deployError}
            </div>
          )}
          {lc.buildCode ? (
            <iframe
              srcDoc={lc.buildCode}
              className="h-full border border-border rounded-lg bg-white transition-all"
              style={{ width: deviceWidth, maxWidth: "100%" }}
              sandbox="allow-scripts allow-same-origin"
              title="デプロイプレビュー"
            />
          ) : (
            <div className="flex w-full max-w-2xl items-center justify-center">
              <div className="w-full rounded-2xl border border-dashed border-border bg-card p-8 text-center">
                <Rocket className="mx-auto h-10 w-10 text-primary" />
                <h2 className="mt-4 text-lg font-semibold text-foreground">まだデプロイできるビルドがありません</h2>
                <p className="mt-2 text-sm text-muted-foreground">
                  開発フェーズでビルドを完了すると、ここにプレビュー、品質チェック、リリースゲートが表示されます。
                </p>
                <div className="mt-5 grid gap-3 text-left sm:grid-cols-3">
                  <div className="rounded-lg border border-border bg-background p-3">
                    <p className="text-xs text-muted-foreground">ビルドコード</p>
                    <p className="mt-1 text-sm font-medium text-foreground">{lc.buildCode ? "準備完了" : "未完了"}</p>
                  </div>
                  <div className="rounded-lg border border-border bg-background p-3">
                    <p className="text-xs text-muted-foreground">デプロイチェック</p>
                    <p className="mt-1 text-sm font-medium text-foreground">{checks.length > 0 ? `${checks.length}件` : "未実行"}</p>
                  </div>
                  <div className="rounded-lg border border-border bg-background p-3">
                    <p className="text-xs text-muted-foreground">リリース</p>
                    <p className="mt-1 text-sm font-medium text-foreground">{deployed ? latestRelease?.version : "未作成"}</p>
                  </div>
                </div>
                <button
                  onClick={goBack}
                  className="mt-5 inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-accent"
                >
                  <ArrowLeft className="h-4 w-4" /> 開発フェーズへ戻る
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="w-full overflow-y-auto border-t border-border bg-card/50 p-4 space-y-4 xl:w-96 xl:border-l xl:border-t-0">
          <div className="rounded-[1.6rem] border border-border/70 bg-card p-4 shadow-[0_16px_44px_rgba(15,23,42,0.08)]">
            <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">RELEASE SNAPSHOT</p>
            <div className="mt-3 rounded-[1.2rem] border border-border/60 bg-background/82 p-4">
              <p className="text-sm font-semibold text-foreground">{selectedDesignTitle}</p>
              <p className="mt-1 text-xs font-medium text-primary">{selectedDesignModel}</p>
              <p className="mt-3 text-xs leading-6 text-muted-foreground">{releaseSummary}</p>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-2">
                  <p className="text-[11px] text-muted-foreground">ビルドサイズ</p>
                  <p className="mt-1 font-semibold text-foreground">{((lc.buildCode?.length ?? 0) / 1024).toFixed(1)} KB</p>
                </div>
                <div className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-2">
                  <p className="text-[11px] text-muted-foreground">反復回数</p>
                  <p className="mt-1 font-semibold text-foreground">{lc.buildIteration || 1}</p>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-[1.6rem] border border-border/70 bg-card p-4 shadow-[0_16px_44px_rgba(15,23,42,0.08)]">
            <h3 className="flex items-center gap-2 text-sm font-bold text-foreground">
              <BarChart3 className="h-4 w-4 text-primary" />
              VALUE READINESS
            </h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
              <div className="rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">VALUE CONTRACT</p>
                <p className="mt-2 text-sm font-semibold text-foreground">{valueContract?.summary ?? "未生成"}</p>
                <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-muted-foreground">
                  <span className="rounded-full border border-border/60 bg-muted/10 px-2 py-1">persona {valueContract?.primary_personas?.length ?? 0}</span>
                  <span className="rounded-full border border-border/60 bg-muted/10 px-2 py-1">paths {valueContract?.information_architecture?.key_paths?.length ?? 0}</span>
                  <span className="rounded-full border border-border/60 bg-muted/10 px-2 py-1">metrics {valueContract?.success_metrics?.length ?? 0}</span>
                </div>
              </div>
              <div className="rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">OUTCOME TELEMETRY</p>
                <p className="mt-2 text-sm font-semibold text-foreground">{outcomeTelemetryContract?.summary ?? "未生成"}</p>
                <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-muted-foreground">
                  <span className="rounded-full border border-border/60 bg-muted/10 px-2 py-1">events {outcomeTelemetryContract?.telemetry_events?.length ?? 0}</span>
                  <span className="rounded-full border border-border/60 bg-muted/10 px-2 py-1">kill {outcomeTelemetryContract?.kill_criteria?.length ?? 0}</span>
                  <span className="rounded-full border border-border/60 bg-muted/10 px-2 py-1">checks {outcomeTelemetryContract?.release_checks?.length ?? 0}</span>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-[1.6rem] border border-border/70 bg-card p-4 shadow-[0_16px_44px_rgba(15,23,42,0.08)]">
            <h3 className="flex items-center gap-2 text-sm font-bold text-foreground">
              <ShieldCheck className="h-4 w-4 text-primary" />
              リリースゲート
            </h3>
            <div className="mt-3 grid grid-cols-3 gap-2 text-[10px]">
              <StatChip label="合格" value={passedCount} tone="success" />
              <StatChip label="注意" value={warningCount} tone="warning" />
              <StatChip label="不合格" value={failedCount} tone="danger" />
            </div>
            <div className="mt-3 rounded-[1.2rem] border border-border/60 bg-background/82 px-3 py-3 text-xs leading-6 text-muted-foreground">
              {releaseSummary}
            </div>
            {checks.length === 0 ? (
              <div className="mt-3 rounded-lg border border-dashed border-border px-3 py-4 text-xs text-muted-foreground">
                デプロイ前に品質チェックを実行してください。
              </div>
            ) : (
              <div className="mt-3 space-y-2">
                {checks.map((check) => (
                  <div key={check.id} className="rounded-[1.1rem] border border-border/60 bg-background/82 px-3 py-3">
                    <div className="flex items-start gap-2">
                      {check.status === "pass" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" /> :
                       check.status === "warning" ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" /> :
                       <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium text-foreground">{presentNamedItem(check.label)}</span>
                          <Badge variant="outline" className={cn(
                            "ml-auto rounded-full px-3 py-1 text-[10px]",
                            check.status === "pass" ? "border-success/30 text-success" :
                            check.status === "warning" ? "border-warning/30 text-warning" :
                            "border-destructive/30 text-destructive",
                          )}>
                            {presentDeployCheckStatusLabel(check.status)}
                          </Badge>
                        </div>
                        <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{presentNamedItem(check.detail)}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {(blockingChecks.length > 0 || cautionChecks.length > 0) && (
              <div className="mt-3 space-y-2">
                {blockingChecks.slice(0, 2).map((check) => (
                  <div key={`block-${check.id}`} className="rounded-2xl border border-rose-200 bg-rose-50/70 px-3 py-2 text-[11px] leading-5 text-rose-900">
                    不合格: {presentNamedItem(check.label)}
                  </div>
                ))}
                {blockingChecks.length === 0 && cautionChecks.slice(0, 2).map((check) => (
                  <div key={`warn-${check.id}`} className="rounded-2xl border border-amber-200 bg-amber-50/70 px-3 py-2 text-[11px] leading-5 text-amber-950">
                    注意: {presentNamedItem(check.label)}
                  </div>
                ))}
              </div>
            )}
            <button
              onClick={() => void runChecks()}
              disabled={!lc.buildCode || isChecking || isDeploying}
              className="mt-3 w-full rounded-2xl border border-border py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
            >
              {isChecking ? <span className="inline-flex items-center gap-1"><Loader2 className="h-3.5 w-3.5 animate-spin" />チェック実行中</span> : "チェックを再実行"}
            </button>
          </div>

          <div className="rounded-[1.6rem] border border-border/70 bg-card p-4 shadow-[0_16px_44px_rgba(15,23,42,0.08)] space-y-3">
            <h3 className="text-sm font-bold text-foreground">リリース記録</h3>
            {deployed && latestRelease ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-xs text-success">
                  <CheckCircle2 className="h-4 w-4" />
                  {latestRelease.version} を作成済み
                </div>
                <div className="rounded-[1.2rem] border border-success/20 bg-success/5 p-3 text-xs">
                  <p className="font-medium text-foreground">最新リリース</p>
                  <p className="mt-1 text-muted-foreground">{new Date(latestRelease.createdAt).toLocaleString("ja-JP")}</p>
                  <p className="mt-1 text-muted-foreground">品質スコア: {latestRelease.qualitySummary.overallScore}</p>
                  {latestRelease.note ? <p className="mt-2 text-foreground">{presentNamedItem(latestRelease.note)}</p> : null}
                </div>
                {blobUrl ? (
                  <a href={blobUrl} target="_blank" rel="noopener noreferrer" className="flex w-full items-center justify-center gap-1.5 rounded-2xl border border-primary/30 bg-primary/5 py-2 text-xs font-medium text-primary transition-colors hover:bg-primary/10">
                    <ExternalLink className="h-3.5 w-3.5" />
                    公開前プレビューを開く
                  </a>
                ) : null}
              </div>
            ) : (
              <>
                {releaseGatePending ? (
                  <div className="rounded-[1.2rem] border border-primary/20 bg-primary/5 p-3 text-xs">
                    <p className="font-semibold tracking-[0.14em] text-primary">HUMAN RELEASE GATE</p>
                    <p className="mt-2 leading-6 text-foreground">{presentNamedItem(releaseGateReason)}</p>
                    {releaseGateDecisions.length > 0 ? (
                      <p className="mt-2 text-muted-foreground">
                        判断候補: {releaseGateDecisions.join(" / ")}
                      </p>
                    ) : null}
                  </div>
                ) : null}
                <textarea
                  value={releaseNote}
                  onChange={(event) => setReleaseNote(event.target.value)}
                  rows={4}
                  placeholder={releaseGatePending
                    ? "承認理由、保留条件、運用メモを残す..."
                    : "リリースノート、判断理由、運用向けメモを残す..."}
                  className="w-full rounded-[1.2rem] border border-border bg-background p-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-none"
                />
                {releaseGatePending ? (
                  <div className="grid gap-2 sm:grid-cols-2">
                    <button
                      onClick={goBack}
                      className="flex w-full items-center justify-center gap-2 rounded-2xl border border-border py-2 text-xs font-medium text-foreground transition-colors hover:bg-accent"
                    >
                      <ArrowLeft className="h-3.5 w-3.5" />
                      修正のため development へ戻る
                    </button>
                    <button
                      onClick={() => void runChecks()}
                      disabled={!lc.buildCode || isChecking || isDeploying}
                      className="flex w-full items-center justify-center gap-2 rounded-2xl border border-border py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
                    >
                      {isChecking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                      再チェック
                    </button>
                  </div>
                ) : null}
                <button
                  onClick={() => void deploy()}
                  disabled={!allPassed || isDeploying || isChecking}
                  className={cn(
                    "flex w-full items-center justify-center gap-2 rounded-2xl py-2.5 text-xs font-semibold transition-colors",
                    allPassed && !isDeploying && !isChecking
                      ? "bg-primary text-primary-foreground hover:bg-primary/90"
                      : "cursor-not-allowed bg-muted text-muted-foreground",
                  )}
                >
                  {isDeploying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Rocket className="h-3.5 w-3.5" />}
                  {releaseGatePending ? "承認してリリース記録を作成" : "リリース記録を作成"}
                </button>
                {!allPassed ? (
                  <div className="flex items-start gap-2 rounded-[1.2rem] border border-warning/20 bg-warning/5 px-3 py-3 text-[11px] leading-5 text-warning">
                    <FileWarning className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    fail を含む場合はリリースできません。warning のみなら運用判断を添えて進められます。
                  </div>
                ) : null}
              </>
            )}

            <button onClick={downloadHtml} className="flex w-full items-center justify-center gap-1.5 rounded-2xl border border-border py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
              <Download className="h-3.5 w-3.5" />
              HTML をダウンロード
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "success" | "warning" | "danger";
}) {
  return (
    <div className={cn(
      "rounded-md px-2 py-1 text-center",
      tone === "success" ? "bg-success/10 text-success" :
      tone === "warning" ? "bg-warning/10 text-warning" :
      "bg-destructive/10 text-destructive",
    )}>
      <div className="font-medium">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}
