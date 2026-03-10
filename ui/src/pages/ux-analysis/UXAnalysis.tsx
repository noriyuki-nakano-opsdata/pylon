import { useState, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  FileText, BarChart3,
  Loader2, Sparkles,
  Check, RotateCcw, Eye, CheckSquare, Rocket, Package, Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiFetch } from "@/api/client";
import type { AnalysisResult, WorkflowRun, WizardStep, FeatureSelection, Milestone, MilestoneResult } from "@/types/ux-analysis";
import { ReviewStep, SelectStep } from "./ResultsView";
import { BuildingStep, CompleteStep } from "./BuildView";

/* ── Mock Analysis (fallback) ── */
function generateMockResult(_spec: string): AnalysisResult {
  return {
    personas: [
      { name: "Tanaka Yuki", role: "Engineering Manager", age_range: "30-40", goals: ["チームの生産性向上", "AIエージェントの安全な運用", "コスト最適化"], frustrations: ["手動承認プロセスが遅い", "エージェントの動作が不透明"], tech_proficiency: "high", context: "10人規模の開発チームを管理" },
      { name: "Suzuki Mika", role: "Product Designer", age_range: "25-35", goals: ["プロトタイプの迅速な作成", "ユーザーフィードバックの反映"], frustrations: ["技術的な制約の理解が難しい", "AI生成物の品質管理"], tech_proficiency: "medium", context: "SaaS製品のUXデザイン担当" },
      { name: "Watanabe Ken", role: "DevOps Engineer", age_range: "28-38", goals: ["インフラ自動化", "セキュリティ強化"], frustrations: ["エージェントのリソース管理", "マルチテナントの複雑さ"], tech_proficiency: "high", context: "クラウドインフラの運用管理" },
    ],
    user_journeys: [[
      { phase: "Discovery", action: "製品を知る", touchpoint: "Web", emotion: "neutral", pain_points: ["情報が散在"], opportunities: ["LP改善"] },
      { phase: "Onboarding", action: "初期セットアップ", touchpoint: "CLI/UI", emotion: "negative", pain_points: ["設定が複雑"], opportunities: ["ウィザード導入"] },
      { phase: "Usage", action: "ワークフロー実行", touchpoint: "Studio", emotion: "positive", pain_points: [], opportunities: ["ビジュアルエディタ"] },
    ]],
    user_stories: [
      { role: "Developer", action: "ワークフローの実行状態をリアルタイムで確認する", benefit: "問題を早期に発見できる", acceptance_criteria: ["リアルタイム更新", "エラー通知"], priority: "must" },
      { role: "Developer", action: "自然言語でワークフローを定義する", benefit: "YAML不要", acceptance_criteria: ["チャットUI", "プレビュー"], priority: "must" },
      { role: "DevOps", action: "リソース使用量を監視する", benefit: "コスト最適化", acceptance_criteria: ["使用量グラフ", "アラート"], priority: "should" },
      { role: "Designer", action: "AIの出力をプレビューする", benefit: "品質確認", acceptance_criteria: ["リアルタイムプレビュー"], priority: "should" },
      { role: "Manager", action: "GitHub Issueから自動タスク生成", benefit: "手動作業削減", acceptance_criteria: ["Webhook連携"], priority: "could" },
    ],
    job_stories: [
      { situation: "新機能の要件がSlackで議論されている時", motivation: "議論をワークフロー定義に変換したい", outcome: "エージェントが自動で動き出す", forces: ["時間の圧力", "情報の散在"] },
      { situation: "本番でエージェントがエラーを起こした時", motivation: "状況を即座に把握して停止させたい", outcome: "影響を最小限に抑える", forces: ["緊急性", "影響範囲の不確実性"] },
    ],
    jtbd_jobs: [
      { job_performer: "Engineering Manager", core_job: "AIで開発プロセスを自動化する", job_steps: ["要件定義", "ワークフロー設計", "実行監視", "結果評価"], desired_outcomes: ["サイクル短縮", "品質向上"], constraints: ["予算", "セキュリティ"], emotional_jobs: ["チーム成長の実感"], social_jobs: ["先進的と認められたい"] },
    ],
    kano_features: [
      { feature: "ワークフロー実行エンジン", category: "must-be", user_delight: 0.0, implementation_cost: "high", rationale: "基本機能" },
      { feature: "リアルタイム実行ログ", category: "must-be", user_delight: 0.0, implementation_cost: "medium", rationale: "デバッグに不可欠" },
      { feature: "コスト追跡ダッシュボード", category: "one-dimensional", user_delight: 0.6, implementation_cost: "medium", rationale: "精度に比例" },
      { feature: "自然言語ワークフロー定義", category: "attractive", user_delight: 0.9, implementation_cost: "high", rationale: "差別化要素" },
      { feature: "ビジュアルDAGエディタ", category: "attractive", user_delight: 0.8, implementation_cost: "high", rationale: "視覚的理解向上" },
      { feature: "マルチテナント対応", category: "one-dimensional", user_delight: 0.5, implementation_cost: "high", rationale: "企業利用に必須" },
      { feature: "GitHub連携", category: "one-dimensional", user_delight: 0.7, implementation_cost: "medium", rationale: "開発フロー統合" },
      { feature: "承認フロー", category: "must-be", user_delight: 0.0, implementation_cost: "medium", rationale: "安全性に必須" },
      { feature: "Slack通知", category: "attractive", user_delight: 0.6, implementation_cost: "low", rationale: "便利だが必須ではない" },
      { feature: "AIエージェント会話可視化", category: "attractive", user_delight: 0.85, implementation_cost: "medium", rationale: "透明性を超える体験" },
      { feature: "テンプレートギャラリー", category: "attractive", user_delight: 0.7, implementation_cost: "high", rationale: "コミュニティ形成" },
    ],
    business_model: {
      key_partners: ["LLMプロバイダー", "クラウドインフラ"], key_activities: ["プラットフォーム開発"], key_resources: ["エンジニアリングチーム"],
      value_propositions: ["安全なAIエージェント運用", "ワークフロー自動化"], customer_relationships: ["セルフサービス"],
      channels: ["GitHub OSS"], customer_segments: ["開発チーム", "DevOps"], cost_structure: "API利用料、インフラ", revenue_streams: ["SaaS", "Enterprise"],
    },
    business_processes: [
      { process_name: "ワークフロー実行", trigger: "ユーザーが実行開始", steps: [{ actor: "User", action: "スペック入力", system: "Studio", output: "ワークフロー特定" }, { actor: "Agent", action: "ノード実行", system: "Runtime", output: "成果物" }], exceptions: ["APIタイムアウト"], kpis: ["成功率", "実行時間"] },
    ],
    use_cases: [
      { name: "ワークフロー実行", actor: "Developer", preconditions: ["ログイン済み"], main_flow: ["1. スペック入力", "2. 実行確認", "3. 結果表示"], alternative_flows: [{ condition: "承認必要", steps: ["承認待ち", "再開"] }], postconditions: ["履歴記録"], business_rules: ["コスト上限で停止"] },
    ],
    recommendations: [
      "【Quick Win】Slack通知 — 低コストで体験改善",
      "【Strategic】ビジュアルDAGエディタ — 差別化要素",
      "【Strategic】GitHub Issue→自動PR — 核心的価値",
      "【UX改善】オンボーディングウィザード — 最大ペインポイント",
      "【Feature Priority】自然言語ワークフロー定義 — KANO attractive + JTBD直結",
      "【Risk】サンドボックス強化 — セキュリティ必須",
    ],
  };
}

/* ── Main Component ── */

export function UXAnalysis() {
  const [step, setStep] = useState<WizardStep>("input");
  const [spec, setSpec] = useState("");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [reviewTab, setReviewTab] = useState<string>("overview");
  const [features, setFeatures] = useState<FeatureSelection[]>([]);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [buildRunId, setBuildRunId] = useState<string | null>(null);
  const [buildCode, setBuildCode] = useState<string | null>(null);
  const [buildCost, setBuildCost] = useState<number>(0);
  const [buildIteration, setBuildIteration] = useState(0);
  const [milestoneResults, setMilestoneResults] = useState<MilestoneResult[]>([]);

  // Analysis via backend
  const analyzeMutation = useMutation({
    mutationFn: async (specText: string) => {
      const run = await apiFetch<WorkflowRun>("/v1/workflows/ux-analysis/runs", {
        method: "POST",
        body: JSON.stringify({ input: { spec: specText } }),
      });
      return run;
    },
    onSuccess: (run) => {
      // Poll for completion
      pollRun(run.id, (completed) => {
        const state = completed.state as Record<string, unknown> | undefined;
        const analysis = state?.analysis as AnalysisResult | undefined;
        if (analysis) {
          setResult(analysis);
        } else {
          // Fallback to mock
          setResult(generateMockResult(spec));
        }
        initFeatureSelection();
        setStep("review");
      });
    },
    onError: () => {
      // Fallback to mock on error
      setResult(generateMockResult(spec));
      setStep("review");
    },
  });

  // Build via backend (autonomous-builder with milestones)
  const buildMutation = useMutation({
    mutationFn: async () => {
      const selectedFeatures = features.filter((f) => f.selected).map((f) => ({
        feature: f.feature,
        priority: f.priority,
        category: f.category,
      }));
      // Use autonomous-builder if milestones defined, else fallback to product-builder
      const workflow = milestones.length > 0 ? "autonomous-builder" : "product-builder";
      const run = await apiFetch<WorkflowRun>(`/v1/workflows/${workflow}/runs`, {
        method: "POST",
        body: JSON.stringify({
          input: {
            spec,
            selected_features: selectedFeatures,
            analysis: result,
            milestones: milestones.map((m) => ({ id: m.id, name: m.name, criteria: m.criteria })),
          },
        }),
      });
      return run;
    },
    onSuccess: (run) => {
      setBuildRunId(run.id);
      setBuildIteration(0);
      pollRunWithProgress(run.id, (completed) => {
        const state = completed.state as Record<string, unknown> | undefined;
        setBuildCode((state?.code as string) ?? null);
        setBuildCost(Number(state?.estimated_cost_usd ?? 0));
        if (state?.review) {
          const review = state.review as Record<string, unknown>;
          setMilestoneResults((review.milestone_results as MilestoneResult[]) ?? []);
        }
        setStep("complete");
      });
    },
    onError: () => {
      setBuildCode("<!DOCTYPE html><html><head><title>Build Error</title></head><body><h1>Build failed - check backend logs</h1></body></html>");
      setStep("complete");
    },
  });

  function pollRun(runId: string, onComplete: (run: WorkflowRun) => void) {
    const interval = setInterval(async () => {
      try {
        const run = await apiFetch<WorkflowRun>(`/v1/runs/${runId}`);
        if (["completed", "failed", "rejected"].includes(run.status)) {
          clearInterval(interval);
          onComplete(run);
        }
      } catch {
        clearInterval(interval);
        onComplete({ id: runId, workflow_id: "", status: "failed", started_at: "", completed_at: null });
      }
    }, 2000);
  }

  function pollRunWithProgress(runId: string, onComplete: (run: WorkflowRun) => void) {
    const interval = setInterval(async () => {
      try {
        const run = await apiFetch<WorkflowRun>(`/v1/runs/${runId}`);
        const state = run.state as Record<string, unknown> | undefined;
        // Track iteration progress
        if (state?._build_iteration != null) {
          setBuildIteration(Number(state._build_iteration));
        }
        // Track milestone progress in real-time
        if (state?.review) {
          const review = state.review as Record<string, unknown>;
          if (review.milestone_results) {
            setMilestoneResults(review.milestone_results as MilestoneResult[]);
          }
        }
        if (["completed", "failed", "rejected"].includes(run.status)) {
          clearInterval(interval);
          onComplete(run);
        }
      } catch {
        clearInterval(interval);
        onComplete({ id: runId, workflow_id: "", status: "failed", started_at: "", completed_at: null });
      }
    }, 3000);
  }

  function initFeatureSelection() {
    if (!result) return;
    const feats: FeatureSelection[] = result.kano_features.map((k) => ({
      feature: k.feature,
      category: k.category,
      selected: k.category === "must-be" || k.category === "one-dimensional",
      priority: k.category === "must-be" ? "must" as const : k.category === "one-dimensional" ? "should" as const : "could" as const,
      user_delight: k.user_delight,
      implementation_cost: k.implementation_cost,
      rationale: k.rationale,
    }));
    setFeatures(feats);
  }

  useEffect(() => {
    if (result && features.length === 0) initFeatureSelection();
  }, [result]);

  const runAnalysis = () => {
    if (!spec.trim()) return;
    setStep("analyzing");
    analyzeMutation.mutate(spec);
  };

  const startBuild = () => {
    setStep("building");
    buildMutation.mutate();
  };

  const reset = () => {
    setStep("input");
    setSpec("");
    setResult(null);
    setFeatures([]);
    setMilestones([]);
    setBuildRunId(null);
    setBuildCode(null);
    setBuildCost(0);
    setBuildIteration(0);
    setMilestoneResults([]);
    setReviewTab("overview");
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header with stepper */}
      <div className="border-b border-border px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <h1 className="flex items-center gap-2 text-xl font-bold text-foreground">
            <Sparkles className="h-5 w-5 text-primary" />
            Product Builder
          </h1>
          {step !== "input" && (
            <button onClick={reset} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors">
              <RotateCcw className="h-3.5 w-3.5" /> 最初から
            </button>
          )}
        </div>
        <StepIndicator current={step} />
      </div>

      {/* Step content */}
      <div className="flex-1 overflow-hidden">
        {step === "input" && <InputStep spec={spec} setSpec={setSpec} onSubmit={runAnalysis} />}
        {step === "analyzing" && <AnalyzingStep />}
        {step === "review" && result && (
          <ReviewStep result={result} reviewTab={reviewTab} setReviewTab={setReviewTab} onNext={() => setStep("select")} />
        )}
        {step === "select" && (
          <SelectStep features={features} setFeatures={setFeatures} milestones={milestones} setMilestones={setMilestones} onBack={() => setStep("review")} onBuild={startBuild} />
        )}
        {step === "building" && <BuildingStep milestones={milestones} iteration={buildIteration} milestoneResults={milestoneResults} />}
        {step === "complete" && <CompleteStep code={buildCode} cost={buildCost} iteration={buildIteration} milestoneResults={milestoneResults} onReset={reset} />}
      </div>
    </div>
  );
}

/* ── Step Indicator ── */
const STEPS: { key: WizardStep; label: string; icon: React.ElementType }[] = [
  { key: "input", label: "入力", icon: FileText },
  { key: "analyzing", label: "分析", icon: BarChart3 },
  { key: "review", label: "レビュー", icon: Eye },
  { key: "select", label: "機能選択", icon: CheckSquare },
  { key: "building", label: "開発", icon: Rocket },
  { key: "complete", label: "完成", icon: Package },
];

function StepIndicator({ current }: { current: WizardStep }) {
  const currentIdx = STEPS.findIndex((s) => s.key === current);
  return (
    <div className="flex items-center gap-1">
      {STEPS.map((s, i) => {
        const done = i < currentIdx;
        const active = s.key === current;
        return (
          <div key={s.key} className="flex items-center gap-1">
            {i > 0 && <div className={cn("h-px w-6", done ? "bg-success" : "bg-border")} />}
            <div className={cn(
              "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
              done && "bg-success/10 text-success",
              active && "bg-primary/10 text-primary",
              !done && !active && "text-muted-foreground",
            )}>
              {done ? <Check className="h-3 w-3" /> : <s.icon className="h-3 w-3" />}
              {s.label}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Step 1: Input ── */
function InputStep({ spec, setSpec, onSubmit }: { spec: string; setSpec: (s: string) => void; onSubmit: () => void }) {
  return (
    <div className="flex items-center justify-center h-full p-6">
      <div className="w-full max-w-2xl space-y-6">
        <div className="text-center">
          <Sparkles className="h-12 w-12 text-primary mx-auto mb-4" />
          <h2 className="text-2xl font-bold text-foreground">何を作りますか？</h2>
          <p className="mt-2 text-muted-foreground">
            プロダクトの概要を入力すると、UX分析→機能選択→自律開発まで一気通貫で実行します
          </p>
        </div>
        <textarea
          value={spec}
          onChange={(e) => setSpec(e.target.value)}
          placeholder="例: タスク管理アプリ。チームメンバーがタスクを作成・割り当て・進捗管理できる。カンバンボードとリスト表示の切り替え、期限設定、ラベル分類、コメント機能..."
          className="w-full rounded-lg border border-border bg-background p-4 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
          rows={6}
          autoFocus
        />
        <button
          onClick={onSubmit}
          disabled={!spec.trim()}
          className={cn(
            "w-full flex items-center justify-center gap-2 rounded-lg py-3 text-sm font-medium transition-colors",
            spec.trim()
              ? "bg-primary text-primary-foreground hover:bg-primary/90"
              : "bg-muted text-muted-foreground cursor-not-allowed",
          )}
        >
          <Zap className="h-4 w-4" />
          UX分析を開始
        </button>
      </div>
    </div>
  );
}

/* ── Step 2: Analyzing ── */
function AnalyzingStep() {
  const phases = ["ペルソナ分析", "ユーザージャーニー", "ユーザーストーリー", "ジョブストーリー", "JTBD分析", "KANOモデル", "ビジネスモデル", "業務プロセス", "ユースケース", "レコメンデーション"];
  const [current, setCurrent] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setCurrent((c) => Math.min(c + 1, phases.length - 1)), 1200);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="flex items-center justify-center h-full p-6">
      <div className="w-full max-w-lg space-y-6 text-center">
        <Loader2 className="h-12 w-12 text-primary mx-auto animate-spin" />
        <h2 className="text-xl font-bold text-foreground">AIが徹底分析中...</h2>
        <div className="space-y-2">
          {phases.map((p, i) => (
            <div key={i} className={cn(
              "flex items-center gap-2 rounded-md px-4 py-2 text-sm transition-all",
              i < current && "text-success",
              i === current && "text-primary font-medium",
              i > current && "text-muted-foreground/50",
            )}>
              {i < current ? <Check className="h-4 w-4" /> : i === current ? <Loader2 className="h-4 w-4 animate-spin" /> : <div className="h-4 w-4" />}
              {p}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
