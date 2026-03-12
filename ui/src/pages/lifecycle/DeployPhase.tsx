import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Rocket, ArrowRight, ArrowLeft, Monitor, Tablet, Smartphone,
  ExternalLink, Download, ShieldCheck, CheckCircle2, Loader2,
  AlertTriangle, XCircle, FileWarning,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { lifecycleApi } from "@/api/lifecycle";
import { useLifecycle } from "./LifecycleContext";

export function DeployPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycle();
  const [device, setDevice] = useState<"desktop" | "tablet" | "mobile">("desktop");
  const [isChecking, setIsChecking] = useState(false);
  const [isDeploying, setIsDeploying] = useState(false);
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
      lc.applyProject(response.project);
    } finally {
      setIsChecking(false);
    }
  };

  const deploy = async () => {
    if (!projectSlug) return;
    setIsDeploying(true);
    try {
      const response = await lifecycleApi.createRelease(projectSlug, releaseNote);
      lc.applyProject(response.project);
      lc.completePhase("deploy");
      setReleaseNote("");
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

  const checks = lc.deployChecks;
  const allPassed = checks.length > 0 && checks.every((item) => item.status !== "fail");
  const deployed = lc.releases.length > 0;
  const latestRelease = lc.releases[0];
  const deviceWidth = device === "desktop" ? "100%" : device === "tablet" ? "768px" : "375px";
  const passedCount = checks.filter((item) => item.status === "pass").length;
  const warningCount = checks.filter((item) => item.status === "warning").length;
  const failedCount = checks.filter((item) => item.status === "fail").length;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-6 py-3">
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
        <div className="flex min-h-[24rem] flex-1 justify-center bg-background p-4 xl:min-h-0">
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

        <div className="w-full border-t border-border bg-card/50 p-4 overflow-y-auto space-y-4 xl:w-80 xl:border-l xl:border-t-0">
          <div className="rounded-xl border border-border bg-card p-4">
            <h3 className="flex items-center gap-2 text-sm font-bold text-foreground mb-3">
              <ShieldCheck className="h-4 w-4 text-primary" /> リリースゲート
            </h3>
            {checks.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border px-3 py-4 text-xs text-muted-foreground">
                デプロイ前に品質チェックを実行してください。
              </div>
            ) : (
              <div className="space-y-2">
                {checks.map((check) => (
                  <div key={check.id} className="rounded-lg border border-border px-3 py-2">
                    <div className="flex items-center gap-2">
                      {check.status === "pass" ? <CheckCircle2 className="h-4 w-4 text-success shrink-0" /> :
                       check.status === "warning" ? <AlertTriangle className="h-4 w-4 text-warning shrink-0" /> :
                       <XCircle className="h-4 w-4 text-destructive shrink-0" />}
                      <span className="text-xs font-medium text-foreground">{check.label}</span>
                      <Badge variant="outline" className={cn(
                        "ml-auto text-[10px]",
                        check.status === "pass" ? "border-success/30 text-success" :
                        check.status === "warning" ? "border-warning/30 text-warning" :
                        "border-destructive/30 text-destructive",
                      )}>
                        {check.status}
                      </Badge>
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">{check.detail}</p>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-3 grid grid-cols-3 gap-2 text-[10px]">
              <StatChip label="合格" value={passedCount} tone="success" />
              <StatChip label="警告" value={warningCount} tone="warning" />
              <StatChip label="不合格" value={failedCount} tone="danger" />
            </div>
            <button
              onClick={() => void runChecks()}
              disabled={!lc.buildCode || isChecking || isDeploying}
              className="mt-3 w-full rounded-md border border-border py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors disabled:opacity-50"
            >
              {isChecking ? <span className="inline-flex items-center gap-1"><Loader2 className="h-3.5 w-3.5 animate-spin" />チェック実行中</span> : "チェックを実行"}
            </button>
          </div>

          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <h3 className="text-sm font-bold text-foreground">リリース</h3>
            {deployed && latestRelease ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs text-success">
                  <CheckCircle2 className="h-4 w-4" /> {latestRelease.version} を作成済み
                </div>
                <div className="rounded-lg border border-success/20 bg-success/5 p-3 text-xs">
                  <p className="font-medium text-foreground">最新リリース</p>
                  <p className="mt-1 text-muted-foreground">{new Date(latestRelease.createdAt).toLocaleString("ja-JP")}</p>
                  <p className="mt-1 text-muted-foreground">品質スコア: {latestRelease.qualitySummary.overallScore}</p>
                  {latestRelease.note && <p className="mt-1 text-foreground">{latestRelease.note}</p>}
                </div>
                {blobUrl && (
                  <a href={blobUrl} target="_blank" rel="noopener noreferrer" className="flex items-center justify-center gap-1.5 w-full rounded-md border border-primary/30 bg-primary/5 py-2 text-xs text-primary hover:bg-primary/10 transition-colors">
                    <ExternalLink className="h-3.5 w-3.5" /> プレビューを開く
                  </a>
                )}
              </div>
            ) : (
              <>
                <textarea
                  value={releaseNote}
                  onChange={(event) => setReleaseNote(event.target.value)}
                  rows={3}
                  placeholder="リリースノートや判断メモを残す..."
                  className="w-full rounded-lg border border-border bg-background p-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-none"
                />
                <button
                  onClick={() => void deploy()}
                  disabled={!allPassed || isDeploying || isChecking}
                  className={cn(
                    "w-full flex items-center justify-center gap-2 rounded-md py-2 text-xs font-medium transition-colors",
                    allPassed && !isDeploying && !isChecking
                      ? "bg-primary text-primary-foreground hover:bg-primary/90"
                      : "bg-muted text-muted-foreground cursor-not-allowed",
                  )}
                >
                  {isDeploying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Rocket className="h-3.5 w-3.5" />}
                  リリース作成
                </button>
                {!allPassed && (
                  <div className="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 px-3 py-2 text-[11px] text-warning">
                    <FileWarning className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                    fail を含む場合は release を作成できません。warning のみなら release は可能です。
                  </div>
                )}
              </>
            )}

            <button onClick={downloadHtml} className="w-full flex items-center justify-center gap-1.5 rounded-md border border-border py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
              <Download className="h-3.5 w-3.5" /> HTMLをダウンロード
            </button>
          </div>

          <div className="rounded-xl border border-border bg-card p-4">
            <h3 className="text-sm font-bold text-foreground mb-2">ビルド情報</h3>
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between"><span className="text-muted-foreground">コスト</span><span className="font-mono text-foreground">${lc.buildCost.toFixed(4)}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">イテレーション</span><span className="font-mono text-foreground">{lc.buildIteration || 1}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">コードサイズ</span><span className="font-mono text-foreground">{((lc.buildCode?.length ?? 0) / 1024).toFixed(1)} KB</span></div>
            </div>
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
