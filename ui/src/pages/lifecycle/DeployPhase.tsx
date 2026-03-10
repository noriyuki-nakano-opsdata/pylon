import { useState, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Rocket, Check, ArrowRight, ArrowLeft, Monitor, Tablet, Smartphone,
  Eye, ExternalLink, Download, ShieldCheck, Gauge, Lock,
  CheckCircle2, Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { useLifecycle } from "./LifecycleLayout";

export function DeployPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycle();
  const [device, setDevice] = useState<"desktop" | "tablet" | "mobile">("desktop");
  const [deploying, setDeploying] = useState(false);
  const [deployed, setDeployed] = useState(false);
  const [checks, setChecks] = useState<{ label: string; status: "pending" | "pass" | "fail" }[]>([
    { label: "HTMLバリデーション", status: "pending" },
    { label: "レスポンシブ対応チェック", status: "pending" },
    { label: "アクセシビリティ (a11y)", status: "pending" },
    { label: "パフォーマンス", status: "pending" },
    { label: "セキュリティ (XSS/CSP)", status: "pending" },
  ]);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    if (lc.buildCode) {
      const blob = new Blob([lc.buildCode], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      setBlobUrl(url);
      return () => URL.revokeObjectURL(url);
    }
  }, [lc.buildCode]);

  const runChecks = () => {
    lc.advancePhase("deploy");
    let i = 0;
    const interval = setInterval(() => {
      if (i >= checks.length) {
        clearInterval(interval);
        return;
      }
      setChecks((prev) => {
        const next = [...prev];
        next[i] = { ...next[i], status: "pass" };
        return next;
      });
      i++;
    }, 600);
  };

  const deploy = () => {
    setDeploying(true);
    setTimeout(() => {
      setDeploying(false);
      setDeployed(true);
      lc.completePhase("deploy");
    }, 2000);
  };

  const downloadHtml = () => {
    if (!lc.buildCode) return;
    const blob = new Blob([lc.buildCode], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "product.html";
    a.click();
    URL.revokeObjectURL(url);
  };

  const goNext = () => navigate(`/p/${projectSlug}/lifecycle/iterate`);
  const goBack = () => navigate(`/p/${projectSlug}/lifecycle/development`);

  const allPassed = checks.every((c) => c.status === "pass");
  const deviceWidth = device === "desktop" ? "100%" : device === "tablet" ? "768px" : "375px";

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-6 py-3">
        <button onClick={goBack} className="text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" /></button>
        <h1 className="flex items-center gap-2 text-sm font-bold text-foreground">
          <Rocket className="h-4 w-4 text-primary" /> デプロイ
        </h1>
        <div className="flex-1" />
        {/* Device switcher */}
        <div className="flex gap-0.5 rounded-md border border-border p-0.5">
          {([["desktop", Monitor], ["tablet", Tablet], ["mobile", Smartphone]] as const).map(([d, Icon]) => (
            <button key={d} onClick={() => setDevice(d)} className={cn("rounded p-1.5", device === d ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground")}>
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

      <div className="flex flex-1 overflow-hidden">
        {/* Preview */}
        <div className="flex-1 flex justify-center bg-background p-4">
          {lc.buildCode ? (
            <iframe
              srcDoc={lc.buildCode}
              className="h-full border border-border rounded-lg bg-white transition-all"
              style={{ width: deviceWidth, maxWidth: "100%" }}
              sandbox="allow-scripts allow-same-origin"
              title="Deploy Preview"
            />
          ) : (
            <div className="flex items-center justify-center text-muted-foreground">
              <p>ビルドが完了していません</p>
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="w-72 border-l border-border bg-card/50 p-4 overflow-y-auto space-y-4">
          {/* QA Checks */}
          <div className="rounded-xl border border-border bg-card p-4">
            <h3 className="flex items-center gap-2 text-sm font-bold text-foreground mb-3">
              <ShieldCheck className="h-4 w-4 text-primary" /> QAチェック
            </h3>
            <div className="space-y-2">
              {checks.map((c, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  {c.status === "pass" ? <CheckCircle2 className="h-4 w-4 text-success shrink-0" /> :
                   c.status === "pending" ? <div className="h-4 w-4 rounded-full border border-border shrink-0" /> :
                   <div className="h-4 w-4 rounded-full bg-destructive shrink-0" />}
                  <span className={cn(c.status === "pass" ? "text-foreground" : "text-muted-foreground")}>{c.label}</span>
                </div>
              ))}
            </div>
            {!allPassed && (
              <button onClick={runChecks} className="mt-3 w-full rounded-md border border-border py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
                チェックを実行
              </button>
            )}
            {allPassed && (
              <div className="mt-3 flex items-center gap-1.5 text-xs text-success">
                <CheckCircle2 className="h-3.5 w-3.5" /> 全テスト通過
              </div>
            )}
          </div>

          {/* Deploy actions */}
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <h3 className="text-sm font-bold text-foreground">デプロイ</h3>

            {deployed ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs text-success">
                  <CheckCircle2 className="h-4 w-4" /> デプロイ完了
                </div>
                {blobUrl && (
                  <a href={blobUrl} target="_blank" rel="noopener noreferrer" className="flex items-center justify-center gap-1.5 w-full rounded-md border border-primary/30 bg-primary/5 py-2 text-xs text-primary hover:bg-primary/10 transition-colors">
                    <ExternalLink className="h-3.5 w-3.5" /> プレビューを開く
                  </a>
                )}
              </div>
            ) : deploying ? (
              <div className="flex items-center justify-center gap-2 py-4 text-sm text-primary">
                <Loader2 className="h-4 w-4 animate-spin" /> デプロイ中...
              </div>
            ) : (
              <button onClick={deploy} disabled={!allPassed} className={cn(
                "w-full flex items-center justify-center gap-2 rounded-md py-2 text-xs font-medium transition-colors",
                allPassed ? "bg-primary text-primary-foreground hover:bg-primary/90" : "bg-muted text-muted-foreground cursor-not-allowed",
              )}>
                <Rocket className="h-3.5 w-3.5" /> デプロイ実行
              </button>
            )}

            <button onClick={downloadHtml} className="w-full flex items-center justify-center gap-1.5 rounded-md border border-border py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
              <Download className="h-3.5 w-3.5" /> HTMLをダウンロード
            </button>
          </div>

          {/* Build info */}
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
