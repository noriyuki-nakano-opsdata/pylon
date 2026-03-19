import { useState, useEffect, useMemo, useRef, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Loader2, Check, ArrowRight, Rocket,
  Flag, RefreshCw, Bot, CircleCheck, CircleX, Eye,
  ExternalLink, Zap, BarChart3, AlertCircle,
  Maximize2, Minimize2, FileCode2, Search, FolderTree, Route, X,
  ChevronRight, Folder, FolderOpen, FileJson2, FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MonacoCodeSurface } from "@/components/lifecycle/MonacoCodeSurface";
import type { DevelopmentWorkspaceFile, DevelopmentWorkspacePackage } from "@/types/lifecycle";
import { useLifecycleActions, useLifecycleState } from "./LifecycleContext";
import { useWorkflowRun } from "@/hooks/useWorkflowRun";
import { lifecycleApi } from "@/api/lifecycle";
import { MultiAgentCollaborationPulse, type CollaborationTimelineStep } from "@/components/lifecycle/MultiAgentCollaborationPulse";
import { buildPhasePulseSnapshot } from "@/components/lifecycle/pulseUtils";
import { buildDevelopmentWorkflowInput } from "@/lifecycle/inputs";
import {
  downstreamWorkspaceClassName,
} from "@/lifecycle/downstreamTheme";
import {
  presentDeliverySlices,
  presentFeatureLabel,
  presentNamedItem,
  presentVariantApprovalPacket,
  presentVariantModelLabel,
  presentVariantSelectionSummary,
  presentVariantTitle,
} from "@/lifecycle/designDecisionPresentation";
import { persistCompletedPhase } from "@/lifecycle/phasePersistence";
import { hasRestorablePhaseRun } from "@/lifecycle/phaseStatus";
import {
  selectPhaseStatus,
  selectDevelopmentViewModel,
} from "@/lifecycle/selectors";

/* ── Utility: extract CSS / JS / body sections from a single HTML string ── */
interface HtmlSections {
  css: string;
  js: string;
  body: string;
  full: string;
}

function extractSections(html: string): HtmlSections {
  const cssMatch = html.match(/<style[^>]*>([\s\S]*?)<\/style>/gi);
  const jsMatch = html.match(/<script(?![^>]*src)[^>]*>([\s\S]*?)<\/script>/gi);
  const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);

  const css = cssMatch ? cssMatch.map(s => s.replace(/<\/?style[^>]*>/gi, "")).join("\n\n") : "";
  const js = jsMatch ? jsMatch.map(s => s.replace(/<\/?script[^>]*>/gi, "")).join("\n\n") : "";
  const body = bodyMatch ? bodyMatch[1] : "";

  return { css, js, body, full: html };
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  return kb < 1024 ? `${kb.toFixed(1)} KB` : `${(kb / 1024).toFixed(2)} MB`;
}

function estimateQuality(sections: HtmlSections): { label: string; score: number; details: string[] } {
  const details: string[] = [];
  let score = 50;

  if (sections.css.length > 0) { score += 15; details.push("CSS 分離済み"); }
  if (sections.js.length > 0) { score += 10; details.push("JS あり"); }
  if (sections.body.includes("aria-")) { score += 10; details.push("ARIA 属性あり"); }
  if (sections.full.includes("<meta name=\"viewport\"")) { score += 10; details.push("レスポンシブ対応"); }
  if (sections.full.includes("lang=")) { score += 5; details.push("言語属性あり"); }

  const label = score >= 80 ? "良好" : score >= 60 ? "普通" : "基本";
  return { label, score: Math.min(score, 100), details };
}

type CodeTab = "full" | "css" | "js" | "body";
type DevelopmentPrepPanel = "handoff" | "graph" | "workspace";

type WorkspaceTreeNode = WorkspaceTreeFolderNode | WorkspaceTreeFileNode;

interface WorkspaceTreeFolderNode {
  id: string;
  kind: "folder";
  name: string;
  path: string;
  children: WorkspaceTreeNode[];
  fileCount: number;
  routeCount: number;
  entrypointCount: number;
  packageMeta?: DevelopmentWorkspacePackage | null;
}

interface WorkspaceTreeFileNode {
  id: string;
  kind: "file";
  name: string;
  path: string;
  file: DevelopmentWorkspaceFile;
}

interface MutableWorkspaceTreeFolderNode {
  id: string;
  kind: "folder";
  name: string;
  path: string;
  children: Map<string, MutableWorkspaceTreeFolderNode | WorkspaceTreeFileNode>;
  fileCount: number;
  routeCount: number;
  entrypointCount: number;
  packageMeta?: DevelopmentWorkspacePackage | null;
}

function createMutableWorkspaceFolderNode(
  name: string,
  path: string,
  packageMeta?: DevelopmentWorkspacePackage | null,
): MutableWorkspaceTreeFolderNode {
  return {
    id: `folder:${path}`,
    kind: "folder",
    name,
    path,
    children: new Map(),
    fileCount: 0,
    routeCount: 0,
    entrypointCount: 0,
    packageMeta,
  };
}

function sortWorkspaceTreeNodes(nodes: WorkspaceTreeNode[]): WorkspaceTreeNode[] {
  return [...nodes]
    .sort((left, right) => {
      if (left.kind !== right.kind) return left.kind === "folder" ? -1 : 1;
      if (left.kind === "file" && right.kind === "file" && left.file.entrypoint !== right.file.entrypoint) {
        return left.file.entrypoint ? -1 : 1;
      }
      return left.name.localeCompare(right.name, "ja");
    })
    .map((node) => (
      node.kind === "folder"
        ? { ...node, children: sortWorkspaceTreeNodes(node.children) }
        : node
    ));
}

function buildWorkspaceTree(
  files: DevelopmentWorkspaceFile[],
  packages: DevelopmentWorkspacePackage[],
): WorkspaceTreeNode[] {
  const rootNodes = new Map<string, MutableWorkspaceTreeFolderNode | WorkspaceTreeFileNode>();
  const folders = new Map<string, MutableWorkspaceTreeFolderNode>();
  const packagePathMap = new Map(packages.map((pkg) => [pkg.path, pkg]));

  const ensureFolder = (segments: string[]) => {
    let parentFolder: MutableWorkspaceTreeFolderNode | null = null;
    let currentPath = "";

    for (const segment of segments) {
      currentPath = currentPath ? `${currentPath}/${segment}` : segment;
      let folder = folders.get(currentPath);
      if (!folder) {
        folder = createMutableWorkspaceFolderNode(segment, currentPath, packagePathMap.get(currentPath) ?? null);
        folders.set(currentPath, folder);
        if (parentFolder) {
          parentFolder.children.set(folder.path, folder);
        } else {
          rootNodes.set(folder.path, folder);
        }
      }
      parentFolder = folder;
    }

    return parentFolder;
  };

  for (const file of files) {
    const segments = file.path.split("/").filter(Boolean);
    const folderSegments = segments.slice(0, -1);
    const fileName = segments.at(-1) ?? file.path;
    const parentFolder = ensureFolder(folderSegments);
    const fileNode: WorkspaceTreeFileNode = {
      id: `file:${file.path}`,
      kind: "file",
      name: fileName,
      path: file.path,
      file,
    };

    if (parentFolder) {
      parentFolder.children.set(file.path, fileNode);
    } else {
      rootNodes.set(file.path, fileNode);
    }

    let folderPath = "";
    for (const segment of folderSegments) {
      folderPath = folderPath ? `${folderPath}/${segment}` : segment;
      const folder = folders.get(folderPath);
      if (!folder) continue;
      folder.fileCount += 1;
      folder.routeCount += file.route_paths.length;
      if (file.entrypoint) folder.entrypointCount += 1;
    }
  }

  const finalize = (
    nodes: Array<MutableWorkspaceTreeFolderNode | WorkspaceTreeFileNode>,
  ): WorkspaceTreeNode[] => sortWorkspaceTreeNodes(
    nodes.map((node) => (
      node.kind === "folder"
        ? {
            id: node.id,
            kind: "folder",
            name: node.name,
            path: node.path,
            fileCount: node.fileCount,
            routeCount: node.routeCount,
            entrypointCount: node.entrypointCount,
            packageMeta: node.packageMeta,
            children: finalize([...node.children.values()]),
          }
        : node
    )),
  );

  return finalize([...rootNodes.values()]);
}

function collectWorkspaceFolderPaths(nodes: WorkspaceTreeNode[], acc = new Set<string>()) {
  for (const node of nodes) {
    if (node.kind !== "folder") continue;
    acc.add(node.path);
    collectWorkspaceFolderPaths(node.children, acc);
  }
  return acc;
}

function workspaceFileAccent(file: DevelopmentWorkspaceFile) {
  if (file.entrypoint) return "text-emerald-300";
  if (file.kind === "json" || file.path.endsWith(".json")) return "text-amber-200";
  if (file.kind === "md" || file.path.endsWith(".md")) return "text-violet-200";
  return "text-sky-300";
}

function workspaceFileIcon(file: DevelopmentWorkspaceFile) {
  if (file.kind === "json" || file.path.endsWith(".json")) return FileJson2;
  if (file.kind === "md" || file.path.endsWith(".md")) return FileText;
  return FileCode2;
}

function monacoLanguageForCodeTab(tab: CodeTab): string {
  switch (tab) {
    case "css":
      return "css";
    case "js":
      return "javascript";
    case "body":
    case "full":
      return "html";
    default:
      return "plaintext";
  }
}

function monacoLanguageForWorkspaceFile(path: string, kind?: string): string {
  const normalizedKind = (kind ?? "").toLowerCase();
  const normalizedPath = path.toLowerCase();

  if (normalizedKind === "tsx" || normalizedPath.endsWith(".tsx") || normalizedPath.endsWith(".ts")) {
    return "typescript";
  }
  if (normalizedKind === "jsx" || normalizedPath.endsWith(".jsx") || normalizedPath.endsWith(".js") || normalizedPath.endsWith(".mjs")) {
    return "javascript";
  }
  if (normalizedKind === "css" || normalizedPath.endsWith(".css") || normalizedPath.endsWith(".scss") || normalizedPath.endsWith(".less")) {
    return "css";
  }
  if (normalizedKind === "html" || normalizedPath.endsWith(".html")) {
    return "html";
  }
  if (normalizedKind === "json" || normalizedPath.endsWith(".json")) {
    return "json";
  }
  if (normalizedKind === "md" || normalizedPath.endsWith(".md")) {
    return "markdown";
  }

  return "plaintext";
}

function buildDevelopmentTimeline(
  agents: ReturnType<typeof buildPhasePulseSnapshot>["agents"],
  milestoneCount: number,
): CollaborationTimelineStep[] {
  const runningCount = agents.filter((agent) => agent.status === "running").length;
  const completedCount = agents.filter((agent) => agent.status === "completed").length;
  const integrator = agents.find((agent) => agent.id === "integrator");
  const reviewer = agents.find((agent) => agent.id === "reviewer");
  const lead = agents.find((agent) => agent.status === "running") ?? agents[0];

  return [
    {
      id: "parallel-build",
      label: "並列ビルド",
      detail: runningCount > 0
        ? `${runningCount} 本の実装レーンで、仕様分解・UI 実装・ドメイン実装を同時に進めています。`
        : "ビルドチームに担当レーンを割り振っています。",
      status: runningCount > 0 || completedCount > 0 ? "completed" : "pending",
      owner: lead?.label,
      artifact: "実装差分",
    },
    {
      id: "integration-pass",
      label: "統合パス",
      detail: integrator?.status === "running"
        ? integrator.currentTask ?? "統合担当が成果物を一本の実装へまとめています。"
        : "分散した実装を統合し、衝突を吸収します。",
      status: integrator?.status === "completed" ? "completed" : integrator?.status === "running" ? "running" : completedCount >= 2 ? "running" : "pending",
      owner: integrator?.label,
      artifact: "統合ビルド",
    },
    {
      id: "quality-review",
      label: milestoneCount > 0 ? "マイルストーン検証" : "品質レビュー",
      detail: reviewer?.status === "running"
        ? reviewer.currentTask ?? "レビュアーが品質ゲートとマイルストーンを検証しています。"
        : milestoneCount > 0
          ? "レビュアーが実装結果をマイルストーン基準で検証し、必要なら再ループします。"
          : "レビュアーが実装品質とリリース準備を確認します。",
      status: reviewer?.status === "completed" ? "completed" : reviewer?.status === "running" ? "running" : "pending",
      owner: reviewer?.label,
      artifact: milestoneCount > 0 ? "マイルストーン結果" : "レビュー結果",
    },
    {
      id: "deploy-handoff",
      label: "デプロイへの引き継ぎ",
      detail: "承認済みの実装結果を deploy phase に渡せる形で固定します。",
      status: agents.every((agent) => agent.status === "completed") ? "completed" : "pending",
      owner: reviewer?.label,
      artifact: "リリース候補",
    },
  ];
}

function PrepMetricCard({
  label,
  value,
  detail,
  tone = "default",
}: {
  label: string;
  value: string | number;
  detail?: string;
  tone?: "default" | "primary" | "warning" | "success";
}) {
  const toneClassName = {
    default: "border-border/55 bg-background/82 text-foreground",
    primary: "border-primary/20 bg-primary/5 text-foreground",
    warning: "border-amber-200 bg-amber-50/80 text-amber-950",
    success: "border-emerald-200 bg-emerald-50/80 text-emerald-950",
  }[tone];

  return (
    <div className={cn("rounded-[1.2rem] border px-3.5 py-3", toneClassName)}>
      <p className="text-[10px] font-semibold tracking-[0.18em] text-muted-foreground">{label}</p>
      <p className="mt-2 text-lg font-semibold tracking-tight">{value}</p>
      {detail ? (
        <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{detail}</p>
      ) : null}
    </div>
  );
}

function PrepDisclosure({
  title,
  summary,
  children,
  defaultOpen = false,
}: {
  title: string;
  summary: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details open={defaultOpen} className="group rounded-[1.25rem] border border-border/60 bg-background/82 px-4 py-4">
      <summary className="flex cursor-pointer list-none items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-foreground">{title}</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">{summary}</p>
        </div>
        <span className="rounded-full border border-border/60 bg-background/80 px-2.5 py-1 text-[10px] font-semibold tracking-[0.16em] text-muted-foreground">
          details
        </span>
      </summary>
      <div className="mt-4 space-y-3">
        {children}
      </div>
    </details>
  );
}

export function DevelopmentPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycleState();
  const actions = useLifecycleActions();
  const [prepPanel, setPrepPanel] = useState<DevelopmentPrepPanel>("handoff");
  const [transitionError, setTransitionError] = useState<string | null>(null);
  const [isHandingOff, setIsHandingOff] = useState(false);
  const developmentPhaseStatus = selectPhaseStatus(lc.phaseStatuses, "development");
  const hasKnownDevelopmentRun = hasRestorablePhaseRun(
    lc.phaseStatuses,
    lc.phaseRuns,
    lc.runtimeActivePhase,
    "development",
  );
  const workflow = useWorkflowRun("development", projectSlug ?? "", { knownRunExists: hasKnownDevelopmentRun });
  const {
    buildTeam,
    canStartBuild,
    completedPreflightCount,
    conflictGuardCount,
    deliveryPlan,
    codeWorkspace,
    specAudit,
    dependencyEdgeCount,
    fileCount,
    packageCount,
    criticalPathCount,
    maxIterations,
    milestoneCount,
    preflightItems,
    readinessProgressPercent,
    routeCount,
    routeBindingCount,
    screenCount,
    selectedDesign,
    selectedFeatureCount,
    selectedPlanEstimate,
    unresolvedGapCount,
    workspaceFileCount,
    workPackageCount,
    workflowCount,
  } = selectDevelopmentViewModel(lc);
  const selectedDesignTitle = selectedDesign ? presentVariantTitle(selectedDesign, -1) : "未選択";
  const selectedDesignModel = selectedDesign ? presentVariantModelLabel(selectedDesign) : "未選択";
  const selectedDesignSummary = selectedDesign ? presentVariantSelectionSummary(selectedDesign) : "開発へ渡す基準案がまだ選ばれていません。";
  const selectedFeatures = lc.features.filter((feature) => feature.selected);
  const deliverySlices = presentDeliverySlices(selectedDesign?.implementation_brief?.delivery_slices);
  const approvalPacket = selectedDesign ? presentVariantApprovalPacket(selectedDesign) : null;
  const technicalChoices = selectedDesign?.implementation_brief?.technical_choices ?? [];
  const agentLanes = selectedDesign?.implementation_brief?.agent_lanes ?? [];
  const workPackages = deliveryPlan?.work_packages ?? [];
  const conflictPrevention = deliveryPlan?.merge_strategy.conflict_prevention ?? [];
  const reviewChecklist = approvalPacket?.reviewChecklist ?? [];
  const unresolvedGaps = specAudit?.unresolved_gaps ?? [];
  const valueContract = lc.valueContract ?? deliveryPlan?.value_contract ?? null;
  const outcomeTelemetryContract = lc.outcomeTelemetryContract ?? deliveryPlan?.outcome_telemetry_contract ?? null;
  const workspacePackages = codeWorkspace?.package_tree ?? [];
  const workspaceFiles = codeWorkspace?.files ?? [];
  const developmentPulse = buildPhasePulseSnapshot({
    lifecycle: lc,
    phase: "development",
    team: buildTeam,
    workflow,
    warmupTasks: [
      "ビルド設計が実装タスクを分解しています。",
      "フロントエンドが UI 実装を開始しています。",
      "バックエンドがドメインと state を構築しています。",
      "インテグレーターが結合ポイントを確認しています。",
      "Repo Executor が worktree を materialize して build を検証しています。",
      "リリースレビューが品質ゲートを準備しています。",
    ],
  });
  const syncedRunRef = useRef<string | null>(null);

  // Sync terminal workflow runs back into the lifecycle project.
  useEffect(() => {
    if ((workflow.status !== "completed" && workflow.status !== "failed") || !workflow.runId || !projectSlug) return;
    if (syncedRunRef.current === workflow.runId) return;
    syncedRunRef.current = workflow.runId;
    void lifecycleApi.syncPhaseRun(projectSlug, "development", workflow.runId).then(({ project }) => {
      actions.applyProject(project);
    });
  }, [actions, workflow.runId, workflow.status, projectSlug]);

  // Track build iteration from workflow state
  useEffect(() => {
    if (workflow.state._build_iteration != null) {
      const iteration = Number(workflow.state._build_iteration) || 1;
      actions.recordBuildIteration(iteration);
    }
    if (workflow.state.review) {
      const review = workflow.state.review as Record<string, unknown>;
      if (Array.isArray(review.milestone_results)) {
        actions.recordMilestoneResults(review.milestone_results as any);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow.state]);

  const isBuilding =
    workflow.status === "starting"
    || workflow.status === "running"
    || (developmentPhaseStatus === "in_progress" && !lc.buildCode);

  const startBuild = () => {
    actions.advancePhase("development");
    workflow.start(buildDevelopmentWorkflowInput(lc));
  };

  const goNext = async () => {
    if (!projectSlug) return;
    setTransitionError(null);
    setIsHandingOff(true);
    try {
      const response = await persistCompletedPhase(projectSlug, "development", lc.phaseStatuses);
      actions.applyProject(response.project);
      navigate(`/p/${projectSlug}/lifecycle/deploy`);
    } catch (err) {
      setTransitionError(err instanceof Error ? err.message : "デプロイへの引き継ぎに失敗しました");
    } finally {
      setIsHandingOff(false);
    }
  };

  // Error view
  if (workflow.status === "failed") {
    return (
      <div className={cn(downstreamWorkspaceClassName, "flex h-full items-center justify-center p-6")}>
        <div className="max-w-md w-full space-y-4 text-center">
          <AlertCircle className="h-12 w-12 text-destructive mx-auto" />
          <h2 className="text-lg font-bold text-foreground">開発エラー</h2>
          <p className="text-sm text-muted-foreground">{workflow.error ?? "ワークフローの実行に失敗しました"}</p>
          <button onClick={() => workflow.reset()} className="rounded-lg bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">やり直す</button>
        </div>
      </div>
    );
  }

  // Pre-build view
  if (!isBuilding && !lc.buildCode) {
    const prepPanelTitle = {
      handoff: "引き継ぎパケット",
      graph: "自律デリバリーグラフ",
      workspace: "SPEC とコードワークスペース",
    } satisfies Record<DevelopmentPrepPanel, string>;

    return (
      <div className={cn(downstreamWorkspaceClassName, "min-h-full p-6")}>
        <div className="mx-auto max-w-6xl space-y-6">
          <div className="rounded-[2rem] border border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(248,250,252,0.92))] p-6 shadow-[0_24px_70px_rgba(15,23,42,0.08)]">
            <div className="grid gap-6 xl:grid-cols-[minmax(0,1.18fr)_minmax(17rem,0.82fr)]">
              <div className="space-y-4">
                <div className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-background/80 px-3 py-1 text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">
                  <Rocket className="h-3.5 w-3.5 text-primary" />
                  PHASE 5 / 7
                </div>
                <div>
                  <h2 className="text-2xl font-semibold tracking-tight text-foreground">承認済みの判断を自律デリバリーへ変換する準備</h2>
                  <p className="mt-2 max-w-3xl text-sm leading-7 text-muted-foreground">
                    調査・企画・デザインで固定した判断を、dependency-aware な delivery graph に展開します。各レーンの ownership、依存順、merge 順、deploy handoff までを一つの mesh で閉じます。
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-4">
                  <div className="rounded-[1.35rem] border border-border/60 bg-background/82 p-4">
                    <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">機能数</p>
                    <p className="mt-3 text-lg font-semibold text-foreground">{selectedFeatureCount}</p>
                  </div>
                  <div className="rounded-[1.35rem] border border-border/60 bg-background/82 p-4">
                    <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">work package</p>
                    <p className="mt-3 text-lg font-semibold text-foreground">{workPackageCount || selectedPlanEstimate?.wbs.length || 0}</p>
                  </div>
                  <div className="rounded-[1.35rem] border border-border/60 bg-background/82 p-4">
                    <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">依存線</p>
                    <p className="mt-3 text-lg font-semibold text-foreground">{dependencyEdgeCount}</p>
                  </div>
                  <div className="rounded-[1.35rem] border border-border/60 bg-background/82 p-4">
                    <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">クリティカルパス</p>
                    <p className="mt-3 text-lg font-semibold text-foreground">{criticalPathCount || "未計測"}</p>
                  </div>
                </div>
              </div>

              <div className="rounded-[1.5rem] border border-border/60 bg-background/84 p-4">
                <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">自律デリバリーの基準案</p>
                <h3 className="mt-3 text-base font-semibold text-foreground">{selectedDesignTitle}</h3>
                <p className="mt-1 text-xs font-medium text-primary">{selectedDesignModel}</p>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{selectedDesignSummary}</p>
                <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-2">
                    <p className="text-[11px] text-muted-foreground">対象 plan</p>
                    <p className="mt-1 font-semibold text-foreground">{selectedPlanEstimate?.label ?? "未設定"}</p>
                  </div>
                  <div className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-2">
                    <p className="text-[11px] text-muted-foreground">期間</p>
                    <p className="mt-1 font-semibold text-foreground">{selectedPlanEstimate?.duration_weeks ? `${selectedPlanEstimate.duration_weeks} 週` : "未設定"}</p>
                  </div>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-2">
                    <p className="text-[11px] text-muted-foreground">主要画面</p>
                    <p className="mt-1 font-semibold text-foreground">{screenCount}</p>
                  </div>
                  <div className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-2">
                    <p className="text-[11px] text-muted-foreground">主要フロー</p>
                    <p className="mt-1 font-semibold text-foreground">{workflowCount}</p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.18fr)_minmax(19rem,0.82fr)]">
            <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_20px_56px_rgba(15,23,42,0.08)]">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                <div>
                  <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">compact prep clusters</p>
                  <h3 className="mt-1 text-lg font-semibold text-foreground">{prepPanelTitle[prepPanel]}</h3>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">
                    開発開始前に確認すべき情報だけを 3 つの面に整理しました。詳細は必要な面だけを開いて確認します。
                  </p>
                </div>
                <TabsList className="h-auto flex-wrap rounded-[1.25rem] bg-muted/60 p-1.5">
                  {([
                    { key: "handoff", label: "引き継ぎパケット", icon: Flag },
                    { key: "graph", label: "自律デリバリーグラフ", icon: BarChart3 },
                    { key: "workspace", label: "SPEC とコードワークスペース", icon: FileCode2 },
                  ] as const).map((tab) => {
                    const Icon = tab.icon;
                    return (
                      <TabsTrigger
                        key={tab.key}
                        value={tab.key}
                        active={prepPanel === tab.key}
                        onClick={() => setPrepPanel(tab.key)}
                        className="gap-2 rounded-[0.95rem] px-3 py-2 text-[11px] font-semibold"
                      >
                        <Icon className="h-3.5 w-3.5" />
                        {tab.label}
                      </TabsTrigger>
                    );
                  })}
                </TabsList>
              </div>

              <div className="mt-5 max-h-[46rem] space-y-4 overflow-auto pr-1">
                {prepPanel === "handoff" ? (
                  <>
                    <div className="grid gap-3 md:grid-cols-4">
                      <PrepMetricCard label="対象 plan" value={selectedPlanEstimate?.label ?? "未設定"} detail="承認済みの開発基準" tone="primary" />
                      <PrepMetricCard label="期間" value={selectedPlanEstimate?.duration_weeks ? `${selectedPlanEstimate.duration_weeks} 週` : "未設定"} />
                      <PrepMetricCard label="主要画面" value={screenCount} />
                      <PrepMetricCard label="主要フロー" value={workflowCount} />
                    </div>

                    <div className="rounded-[1.25rem] border border-border/60 bg-background/82 p-4">
                      <div className="flex flex-wrap items-center gap-2">
                        {selectedFeatures.length > 0 ? selectedFeatures.map((feature) => (
                          <Badge
                            key={feature.feature}
                            variant="outline"
                            className="rounded-full border-border/70 bg-muted/10 px-3 py-1 text-[11px] font-medium text-foreground"
                          >
                            {presentFeatureLabel(feature.feature)}
                          </Badge>
                        )) : (
                          <span className="text-sm text-muted-foreground">まだ機能が選択されていません。</span>
                        )}
                      </div>
                      <p className="mt-3 text-sm leading-6 text-muted-foreground">{selectedDesignSummary}</p>
                    </div>

                    <PrepDisclosure
                      title="承認パケット"
                      summary="handoff summary と must keep を compact に確認します。"
                      defaultOpen
                    >
                      <div className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                        <p className="text-sm leading-6 text-foreground/90">
                          {approvalPacket?.handoffSummary ?? "承認パケットはまだ準備中です。"}
                        </p>
                      </div>
                      {approvalPacket?.mustKeep?.length ? (
                        <div className="flex flex-wrap gap-2">
                          {approvalPacket.mustKeep.slice(0, 4).map((item) => (
                            <Badge key={item} variant="outline" className="rounded-full border-primary/30 bg-primary/5 px-3 py-1 text-[11px] text-primary">
                              {item}
                            </Badge>
                          ))}
                        </div>
                      ) : null}
                    </PrepDisclosure>

                    <PrepDisclosure
                      title="Value contract と telemetry contract"
                      summary="誰のどの仕事を伸ばし、何を観測するかを build 前に固定します。"
                      defaultOpen
                    >
                      <div className="grid gap-3 lg:grid-cols-2">
                        <div className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                          <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">VALUE CONTRACT</p>
                          <p className="mt-2 text-sm font-semibold text-foreground">{valueContract?.summary ?? "未生成"}</p>
                          <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
                            <div className="rounded-xl border border-border/50 bg-background/80 px-2 py-2">
                              <p className="text-muted-foreground">persona</p>
                              <p className="mt-1 font-semibold text-foreground">{valueContract?.primary_personas?.length ?? 0}</p>
                            </div>
                            <div className="rounded-xl border border-border/50 bg-background/80 px-2 py-2">
                              <p className="text-muted-foreground">key paths</p>
                              <p className="mt-1 font-semibold text-foreground">{valueContract?.information_architecture?.key_paths?.length ?? 0}</p>
                            </div>
                            <div className="rounded-xl border border-border/50 bg-background/80 px-2 py-2">
                              <p className="text-muted-foreground">metrics</p>
                              <p className="mt-1 font-semibold text-foreground">{valueContract?.success_metrics?.length ?? 0}</p>
                            </div>
                          </div>
                        </div>
                        <div className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                          <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">OUTCOME TELEMETRY</p>
                          <p className="mt-2 text-sm font-semibold text-foreground">{outcomeTelemetryContract?.summary ?? "未生成"}</p>
                          <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
                            <div className="rounded-xl border border-border/50 bg-background/80 px-2 py-2">
                              <p className="text-muted-foreground">events</p>
                              <p className="mt-1 font-semibold text-foreground">{outcomeTelemetryContract?.telemetry_events?.length ?? 0}</p>
                            </div>
                            <div className="rounded-xl border border-border/50 bg-background/80 px-2 py-2">
                              <p className="text-muted-foreground">kill</p>
                              <p className="mt-1 font-semibold text-foreground">{outcomeTelemetryContract?.kill_criteria?.length ?? 0}</p>
                            </div>
                            <div className="rounded-xl border border-border/50 bg-background/80 px-2 py-2">
                              <p className="text-muted-foreground">artifacts</p>
                              <p className="mt-1 font-semibold text-foreground">{outcomeTelemetryContract?.workspace_artifacts?.length ?? 0}</p>
                            </div>
                          </div>
                        </div>
                      </div>
                    </PrepDisclosure>

                    <PrepDisclosure
                      title="技術判断"
                      summary="設計上の固定判断だけを残し、ビルド開始前に読む量を絞ります。"
                      defaultOpen
                    >
                      <div className="grid gap-3 lg:grid-cols-2">
                        {technicalChoices.slice(0, 4).map((choice) => (
                          <div key={`${choice.area}-${choice.decision}`} className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                            <p className="text-sm font-semibold text-foreground">{presentNamedItem(choice.area)}</p>
                            <p className="mt-2 text-xs leading-5 text-foreground/90">{presentNamedItem(choice.decision)}</p>
                            <p className="mt-1 text-xs leading-5 text-muted-foreground">{presentNamedItem(choice.rationale)}</p>
                          </div>
                        ))}
                      </div>
                    </PrepDisclosure>

                    <PrepDisclosure
                      title="実装レーンと今回固定する実装スライス"
                      summary="build team の ownership と並列着手単位を同じ面で見ます。"
                      defaultOpen
                    >
                      <div className="grid gap-3 lg:grid-cols-2">
                        <div className="space-y-3">
                          {agentLanes.slice(0, 4).map((lane) => (
                            <div key={`${lane.role}-${lane.remit}`} className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                              <p className="text-sm font-semibold text-foreground">{presentNamedItem(lane.role)}</p>
                              <p className="mt-2 text-xs leading-5 text-foreground/90">{presentNamedItem(lane.remit)}</p>
                              {lane.skills.length > 0 ? (
                                <div className="mt-2 flex flex-wrap gap-2">
                                  {lane.skills.slice(0, 4).map((skill) => (
                                    <Badge key={skill} variant="outline" className="rounded-full border-border/70 bg-background/80 px-3 py-1 text-[11px] text-foreground">
                                      {presentNamedItem(skill)}
                                    </Badge>
                                  ))}
                                </div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                        <div className="space-y-3">
                          {deliverySlices.length > 0 ? deliverySlices.slice(0, 4).map((slice) => (
                            <div key={slice.key} className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                              <div className="flex flex-wrap items-center gap-2">
                                {slice.code ? (
                                  <Badge variant="outline" className="rounded-full border-primary/30 bg-primary/5 px-3 py-1 text-[11px] text-primary">
                                    {slice.code}
                                  </Badge>
                                ) : null}
                                {slice.milestone ? (
                                  <Badge variant="outline" className="rounded-full border-border/70 bg-background/80 px-3 py-1 text-[11px] text-foreground">
                                    {slice.milestone}
                                  </Badge>
                                ) : null}
                              </div>
                              <p className="mt-3 text-sm font-semibold leading-6 text-foreground">{slice.title}</p>
                              {slice.acceptance ? (
                                <p className="mt-2 text-xs leading-5 text-muted-foreground">{slice.acceptance}</p>
                              ) : null}
                            </div>
                          )) : (
                            <div className="rounded-2xl border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground">
                              実装スライスはまだ生成されていません。
                            </div>
                          )}
                        </div>
                      </div>
                    </PrepDisclosure>
                  </>
                ) : null}

                {prepPanel === "graph" ? (
                  <>
                    <div className="grid gap-3 md:grid-cols-4">
                      <PrepMetricCard label="work package" value={workPackageCount || selectedPlanEstimate?.wbs.length || 0} tone="primary" />
                      <PrepMetricCard label="依存線" value={dependencyEdgeCount} />
                      <PrepMetricCard label="conflict guard" value={conflictGuardCount} />
                      <PrepMetricCard label="クリティカルパス" value={criticalPathCount || "未計測"} />
                    </div>

                    <div className="grid gap-3">
                      {workPackages.length ? workPackages.slice(0, 6).map((pkg, index) => (
                        <div key={pkg.id} className="rounded-[1.25rem] border border-border/60 bg-background/82 px-4 py-4">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="outline" className="rounded-full border-primary/30 bg-primary/5 px-3 py-1 text-[11px] text-primary">
                              {`WP${index + 1}`}
                            </Badge>
                            <Badge variant="outline" className="rounded-full border-border/70 bg-muted/10 px-3 py-1 text-[11px] text-foreground">
                              {pkg.lane}
                            </Badge>
                            <Badge variant="outline" className="rounded-full border-border/70 bg-muted/10 px-3 py-1 text-[11px] text-foreground">
                              {`Day ${pkg.start_day}-${pkg.start_day + pkg.duration_days}`}
                            </Badge>
                            {pkg.is_critical ? (
                              <Badge variant="outline" className="rounded-full border-amber-300 bg-amber-50 px-3 py-1 text-[11px] text-amber-900">
                                クリティカル
                              </Badge>
                            ) : null}
                          </div>
                          <p className="mt-3 text-sm font-semibold leading-6 text-foreground">{pkg.title}</p>
                          <p className="mt-1 text-xs leading-5 text-muted-foreground">{pkg.summary}</p>
                          <div className="mt-3 grid gap-3 md:grid-cols-2">
                            <div className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                              <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">依存先</p>
                              <p className="mt-2 text-xs leading-5 text-foreground/90">
                                {pkg.depends_on.length > 0 ? pkg.depends_on.join(" → ") : "この package から着手できます"}
                              </p>
                            </div>
                            <div className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                              <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">受け入れ条件</p>
                              <p className="mt-2 text-xs leading-5 text-foreground/90">
                                {pkg.acceptance_criteria[0] ?? "build へ統合できること"}
                              </p>
                            </div>
                          </div>
                        </div>
                      )) : (
                        <div className="rounded-[1.35rem] border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground">
                          planning の WBS から work package を生成できていません。
                        </div>
                      )}
                    </div>

                    <PrepDisclosure
                      title="merge / conflict guard"
                      summary="衝突予防ルールをここに寄せ、ビルド前の確認先を 1 箇所に絞ります。"
                      defaultOpen
                    >
                      <div className="space-y-2">
                        {conflictPrevention.slice(0, 5).map((item) => (
                          <div key={item} className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-2 text-xs leading-5 text-foreground/90">
                            {item}
                          </div>
                        ))}
                        {!conflictPrevention.length ? (
                          <p className="text-xs text-muted-foreground">conflict guard はまだ定義されていません。</p>
                        ) : null}
                      </div>
                    </PrepDisclosure>

                    <PrepDisclosure
                      title="handoff で渡す観点"
                      summary="reviewer が deploy handoff 前に確認する論点です。"
                    >
                      <div className="space-y-2">
                        {reviewChecklist.slice(0, 4).map((item) => (
                          <div key={item} className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-2 text-xs leading-5 text-muted-foreground">
                            {item}
                          </div>
                        ))}
                      </div>
                    </PrepDisclosure>
                  </>
                ) : null}

                {prepPanel === "workspace" ? (
                  <>
                    <div className="grid gap-3 md:grid-cols-4">
                      <PrepMetricCard label="requirements" value={specAudit?.requirements_count ?? (lc.requirements?.requirements.length ?? 0)} />
                      <PrepMetricCard label="task DAG" value={specAudit?.task_count ?? (lc.taskDecomposition?.tasks.length ?? 0)} />
                      <PrepMetricCard label="API surfaces" value={specAudit?.api_surface_count ?? (lc.technicalDesign?.apiSpecification.length ?? 0)} />
                      <PrepMetricCard label="未解決 gap" value={unresolvedGapCount} tone={unresolvedGapCount > 0 ? "warning" : "success"} />
                    </div>

                    <PrepDisclosure
                      title="spec audit"
                      summary="requirements / design token / auth boundary / operability / technical design の欠落を 1 面で確認します。"
                      defaultOpen
                    >
                      <div className="flex items-center justify-between gap-3 rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                        <p className="text-sm font-semibold text-foreground">監査状態</p>
                        <Badge
                          variant="outline"
                          className={cn(
                            "rounded-full px-3 py-1 text-[11px]",
                            specAudit?.status === "ready_for_autonomous_build"
                              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                              : "border-amber-200 bg-amber-50 text-amber-900",
                          )}
                        >
                          {specAudit?.status === "ready_for_autonomous_build" ? "closed" : "needs closure"}
                        </Badge>
                      </div>
                      {unresolvedGaps.length > 0 ? (
                        <div className="space-y-2">
                          {unresolvedGaps.slice(0, 4).map((gap) => (
                            <div key={gap.id} className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                              <div className="flex items-center gap-2">
                                <Badge variant="outline" className="rounded-full border-border/70 bg-background/80 px-2.5 py-1 text-[10px] text-foreground">
                                  {gap.severity}
                                </Badge>
                                <p className="text-xs font-semibold text-foreground">{gap.title}</p>
                              </div>
                              <p className="mt-2 text-xs leading-5 text-muted-foreground">{gap.detail}</p>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="rounded-2xl border border-emerald-200 bg-emerald-50/70 px-3 py-3 text-xs leading-5 text-emerald-950">
                          requirements / design token / auth boundary / operability / technical design の主要 gap は閉じています。
                        </div>
                      )}
                    </PrepDisclosure>

                    <PrepDisclosure
                      title="code workspace"
                      summary="requirements から package / file / route binding まで閉じます。"
                      defaultOpen
                    >
                      <div className="grid gap-3 md:grid-cols-3">
                        <PrepMetricCard label="packages" value={packageCount} detail={codeWorkspace?.framework ?? "nextjs"} />
                        <PrepMetricCard label="files" value={workspaceFileCount || fileCount} detail={codeWorkspace?.router ?? "app"} />
                        <PrepMetricCard label="route bindings" value={routeBindingCount || routeCount} />
                      </div>
                      <div className="grid gap-3 lg:grid-cols-2">
                        <div className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                          <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">package tree</p>
                          <div className="mt-2 space-y-2">
                            {workspacePackages.slice(0, 5).map((pkg) => (
                              <div key={pkg.id} className="rounded-xl border border-border/50 bg-background/80 px-3 py-2">
                                <div className="flex items-center justify-between gap-2">
                                  <p className="text-xs font-semibold text-foreground">{pkg.label}</p>
                                  <span className="text-[10px] text-muted-foreground">{pkg.file_count} files</span>
                                </div>
                                <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{pkg.path}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                        <div className="rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                          <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">file slices</p>
                          <div className="mt-2 space-y-2">
                            {workspaceFiles.slice(0, 5).map((file) => (
                              <div key={file.path} className="rounded-xl border border-border/50 bg-background/80 px-3 py-2">
                                <p className="text-xs font-semibold text-foreground [overflow-wrap:anywhere]">{file.path}</p>
                                <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{file.lane} / {file.generated_from}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </PrepDisclosure>
                  </>
                ) : null}
              </div>
            </div>

            <div className="space-y-4">
              <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_20px_56px_rgba(15,23,42,0.08)]">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">開始前チェック</p>
                  <span className="text-xs font-medium text-muted-foreground">{completedPreflightCount}/{preflightItems.length}</span>
                </div>
                <div className="mt-3 h-2 rounded-full bg-muted/70">
                  <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${readinessProgressPercent}%` }} />
                </div>
                <div className="mt-4 space-y-2">
                  {preflightItems.map((item) => (
                    <div key={item.label} className="flex items-center gap-2 rounded-2xl border border-border/55 bg-muted/10 px-3 py-2 text-sm">
                      <span className={cn("h-2.5 w-2.5 rounded-full", item.done ? "bg-success" : "bg-warning")} />
                      <span className={item.done ? "text-foreground" : "text-muted-foreground"}>{item.label}</span>
                    </div>
                  ))}
                </div>
                {lc.approvalStatus !== "approved" ? (
                  <p className="mt-3 rounded-2xl border border-amber-200 bg-amber-50/70 px-3 py-3 text-xs leading-5 text-amber-950">
                    開発は承認後に開始します。まず approval phase で判断を確定してください。
                  </p>
                ) : null}
                <div className="mt-4 flex gap-2">
                  <button onClick={() => navigate(`/p/${projectSlug}/lifecycle/approval`)} className="flex-1 rounded-2xl border border-border px-4 py-3 text-sm font-medium text-foreground transition-colors hover:bg-accent">
                    承認に戻る
                  </button>
                  <button
                    onClick={startBuild}
                    disabled={!canStartBuild}
                    className={cn(
                      "flex-1 flex items-center justify-center gap-2 rounded-2xl py-3 text-sm font-medium transition-colors",
                      canStartBuild
                        ? "bg-primary text-primary-foreground hover:bg-primary/90"
                        : "cursor-not-allowed bg-muted text-muted-foreground",
                    )}
                  >
                    <Zap className="h-4 w-4" />
                    開発を開始
                  </button>
                </div>
              </div>

              <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_20px_56px_rgba(15,23,42,0.08)]">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">build team</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {buildTeam.map((agent) => (
                    <div key={agent.id} className="min-w-[10rem] flex-1 rounded-[1.15rem] border border-border/55 bg-muted/10 px-3 py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex h-8 w-8 items-center justify-center rounded-2xl bg-primary/10">
                          <Bot className="h-4 w-4 text-primary" />
                        </div>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-foreground">{agent.label}</p>
                          <p className="truncate text-xs text-muted-foreground">{agent.role}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-[1.8rem] border border-border/70 bg-card/92 p-5 shadow-[0_20px_56px_rgba(15,23,42,0.08)]">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-muted-foreground">launch focus</p>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <PrepMetricCard label="依存線" value={dependencyEdgeCount} />
                  <PrepMetricCard label="route bindings" value={routeBindingCount || routeCount} />
                  <PrepMetricCard label="packages" value={packageCount} />
                  <PrepMetricCard label="未解決 gap" value={unresolvedGapCount} tone={unresolvedGapCount > 0 ? "warning" : "success"} />
                </div>
                {prepPanel === "graph" && deliveryPlan?.critical_path.length ? (
                  <div className="mt-4 rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                    <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">クリティカルパス</p>
                    <p className="mt-2 text-xs leading-5 text-foreground/90">{deliveryPlan.critical_path.join(" → ")}</p>
                  </div>
                ) : null}
                {reviewChecklist.length > 0 ? (
                  <div className="mt-4 rounded-2xl border border-border/55 bg-muted/10 px-3 py-3">
                    <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">レビュアーに渡す条件</p>
                    <div className="mt-2 space-y-2">
                      {reviewChecklist.slice(0, 3).map((item) => (
                        <div key={item} className="rounded-2xl border border-border/55 bg-background/80 px-3 py-2 text-xs leading-5 text-muted-foreground">
                          {item}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Building view
  if (isBuilding) {
    return (
      <div className={cn(downstreamWorkspaceClassName, "flex h-full items-center justify-center p-6")}>
        <div className="w-full max-w-6xl space-y-5">
          <MultiAgentCollaborationPulse
            title="AIが自律開発中..."
            subtitle={milestoneCount > 0
              ? `マイルストーン達成まで build team が自律改善を繰り返しています。現在は ${lc.buildIteration + 1} 回目のループです。`
              : "build team が仕様をコードへ変換し、統合と品質確認まで閉じています。"}
            elapsedLabel={developmentPulse.elapsedLabel}
            agents={developmentPulse.agents}
            actions={developmentPulse.actions}
            events={developmentPulse.events}
            timeline={buildDevelopmentTimeline(developmentPulse.agents, milestoneCount)}
          />

          {milestoneCount > 0 && (
            <div className="grid gap-3 lg:grid-cols-2">
              <div className="rounded-3xl border border-border bg-card/80 p-5 backdrop-blur-sm">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                    <Flag className="mr-2 inline h-3.5 w-3.5" />
                    マイルストーン検証
                  </h3>
                  {lc.buildIteration > 0 && (
                    <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-[11px] text-primary">
                      <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                      反復 {lc.buildIteration + 1}
                    </div>
                  )}
                </div>
                <div className="mt-4 space-y-2">
                  {lc.milestones.map((ms) => {
                    const result = lc.milestoneResults.find((r) => r.id === ms.id);
                    const isSatisfied = result?.status === "satisfied";
                    const isChecked = result != null;
                    return (
                      <div key={ms.id} className={cn("flex items-start gap-3 rounded-2xl border px-4 py-3 text-sm",
                        isSatisfied ? "border-success/30 bg-success/5 text-success" :
                        isChecked ? "border-destructive/30 bg-destructive/5 text-destructive" :
                        "border-border bg-background/70 text-muted-foreground",
                      )}>
                        {isSatisfied ? <CircleCheck className="mt-0.5 h-4 w-4 shrink-0" /> :
                         isChecked ? <CircleX className="mt-0.5 h-4 w-4 shrink-0" /> :
                         <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />}
                        <div>
                          <p className="font-medium">{ms.name}</p>
                          {result?.reason && <p className="mt-0.5 text-xs opacity-75">{result.reason}</p>}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="rounded-3xl border border-border bg-card/80 p-5 backdrop-blur-sm">
                <h3 className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">ビルドループ</h3>
                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl border border-border bg-background/70 p-4">
                    <p className="text-xs text-muted-foreground">機能数</p>
                    <p className="mt-1 text-lg font-semibold text-foreground">{selectedFeatureCount}</p>
                  </div>
                  <div className="rounded-2xl border border-border bg-background/70 p-4">
                    <p className="text-xs text-muted-foreground">マイルストーン</p>
                    <p className="mt-1 text-lg font-semibold text-foreground">{milestoneCount}</p>
                  </div>
                  <div className="rounded-2xl border border-border bg-background/70 p-4">
                    <p className="text-xs text-muted-foreground">最大ループ</p>
                    <p className="mt-1 text-lg font-semibold text-foreground">{maxIterations}</p>
                  </div>
                </div>
                <p className="mt-4 text-sm text-muted-foreground">
                  build lane は並列で進み、統合後に reviewer が品質ゲートを判定します。未達なら次の iteration に戻ります。
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Complete view
  return (
    <BuildCompleteView
      onNext={() => void goNext()}
      transitionError={transitionError}
      isHandingOff={isHandingOff}
    />
  );
}

function BuildCompleteView({
  onNext,
  transitionError,
  isHandingOff,
}: {
  onNext: () => void;
  transitionError: string | null;
  isHandingOff: boolean;
}) {
  const lc = useLifecycleState();
  const [viewMode, setViewMode] = useState<"preview" | "code">("preview");
  const [codeTab, setCodeTab] = useState<CodeTab>("full");
  const [fullscreen, setFullscreen] = useState(false);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [selectedWorkspaceFile, setSelectedWorkspaceFile] = useState<string | null>(null);
  const [workspaceQuery, setWorkspaceQuery] = useState("");
  const [openWorkspaceFiles, setOpenWorkspaceFiles] = useState<string[]>([]);
  const [collapsedWorkspaceFolders, setCollapsedWorkspaceFolders] = useState<string[]>([]);
  const [showSummaryRail, setShowSummaryRail] = useState(false);
  const [showPreviewNotes, setShowPreviewNotes] = useState(false);
  const [showWorkspaceInspector, setShowWorkspaceInspector] = useState(false);
  const summaryPanelRef = useRef<HTMLDivElement | null>(null);

  const sections = lc.buildCode ? extractSections(lc.buildCode) : null;
  const quality = sections ? estimateQuality(sections) : null;
  const workspace = lc.deliveryPlan?.code_workspace ?? null;
  const repoExecution = lc.deliveryPlan?.repo_execution ?? null;
  const valueContract = lc.valueContract ?? lc.deliveryPlan?.value_contract ?? null;
  const outcomeTelemetryContract = lc.outcomeTelemetryContract ?? lc.deliveryPlan?.outcome_telemetry_contract ?? null;
  const workspaceFiles = useMemo(() => workspace?.files ?? [], [workspace?.files]);
  const activeWorkspaceFile = workspaceFiles.find((file) => file.path === selectedWorkspaceFile) ?? workspaceFiles[0] ?? null;
  const filteredWorkspaceFiles = useMemo(() => {
    const query = workspaceQuery.trim().toLowerCase();
    if (!query) return workspaceFiles;
    return workspaceFiles.filter((file) => {
      const haystack = [
        file.path,
        file.package_label,
        file.package_path,
        file.lane,
        file.generated_from,
        ...file.route_paths,
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [workspaceFiles, workspaceQuery]);
  const workspacePackageMap = useMemo(
    () => new Map((workspace?.package_tree ?? []).map((pkg) => [pkg.id, pkg])),
    [workspace?.package_tree],
  );
  const workspaceTree = useMemo(
    () => buildWorkspaceTree(filteredWorkspaceFiles, workspace?.package_tree ?? []),
    [filteredWorkspaceFiles, workspace?.package_tree],
  );
  const workspaceTreeFolderPaths = useMemo(
    () => collectWorkspaceFolderPaths(workspaceTree),
    [workspaceTree],
  );
  const collapsedWorkspaceFolderSet = useMemo(
    () => new Set(collapsedWorkspaceFolders),
    [collapsedWorkspaceFolders],
  );
  const openEditorFiles = useMemo(
    () => openWorkspaceFiles
      .map((path) => workspaceFiles.find((file) => file.path === path))
      .filter((file): file is DevelopmentWorkspaceFile => Boolean(file)),
    [openWorkspaceFiles, workspaceFiles],
  );
  const activePackage = activeWorkspaceFile ? workspacePackageMap.get(activeWorkspaceFile.package_id) ?? null : null;
  const relatedRouteBindings = useMemo(
    () => (workspace?.route_bindings ?? []).filter((binding) => activeWorkspaceFile?.path ? binding.file_paths.includes(activeWorkspaceFile.path) : false),
    [activeWorkspaceFile?.path, workspace?.route_bindings],
  );
  const relatedPackageGraph = useMemo(
    () => (workspace?.package_graph ?? []).filter((edge) => activePackage ? edge.source === activePackage.id || edge.target === activePackage.id : false),
    [activePackage, workspace?.package_graph],
  );
  const repoCommandStates = [
    { label: "install", payload: repoExecution?.install ?? null },
    { label: "build", payload: repoExecution?.build ?? null },
    { label: "test", payload: repoExecution?.test ?? null },
  ];
  const repoPassedCount = repoCommandStates.filter((command) => command.payload?.status === "passed").length;
  const handoff = lc.developmentHandoff;
  const activeCode = sections ? sections[codeTab] : "";
  const recentDevelopmentDecisions = useMemo(
    () => lc.decisionLog.filter((decision) => decision.phase === "development").slice(-3).reverse(),
    [lc.decisionLog],
  );
  const milestoneSummary = lc.milestoneResults.length > 0
    ? `${lc.milestoneResults.filter((result) => result.status === "satisfied").length}/${lc.milestoneResults.length} milestone satisfied`
    : "review results sealed into deploy handoff";
  const transcriptEntries = [
    {
      key: "system",
      speaker: "SYSTEM",
      badgeClass: "border-sky-400/25 bg-sky-400/10 text-sky-100",
      surfaceClass: "border-sky-400/16 bg-sky-400/[0.05]",
      title: handoff?.readiness_status === "ready_for_deploy" ? "Build orchestration completed" : "Build needs follow-up review",
      summary: handoff?.operator_summary || lc.deliveryPlan?.summary || "AI builder が design handoff を実装へ変換し、deploy へ渡す最終状態をまとめました。",
      chips: [
        lc.deliveryPlan?.execution_mode ?? null,
        workspace?.framework ? `${workspace.framework}/${workspace.router}` : null,
        workspace?.preview_entry ?? null,
      ].filter(Boolean) as string[],
      bullets: handoff?.evidence?.length
        ? handoff.evidence.slice(0, 3).map((item) => typeof item === "string" ? item : item.label)
        : (lc.deliveryPlan?.critical_path ?? []).slice(0, 3).map((item) => `critical path: ${item}`),
    },
    {
      key: "reviewer",
      speaker: "REVIEWER",
      badgeClass: "border-emerald-400/25 bg-emerald-400/10 text-emerald-100",
      surfaceClass: "border-emerald-400/16 bg-emerald-400/[0.05]",
      title: handoff?.readiness_status === "ready_for_deploy" ? "Quality gate passed" : "Quality gate produced issues",
      summary: milestoneSummary,
      chips: [
        `quality ${quality?.score ?? 0}`,
        handoff?.release_candidate ?? null,
        repoExecution?.ready ? "repo execution passed" : null,
      ].filter(Boolean) as string[],
      bullets: handoff?.review_focus?.length
        ? handoff.review_focus.slice(0, 3).map((item) => typeof item === "string" ? item : item.description)
        : quality?.details.slice(0, 3) ?? [],
    },
    {
      key: "executor",
      speaker: "REPO EXECUTOR",
      badgeClass: repoExecution?.ready
        ? "border-cyan-400/25 bg-cyan-400/10 text-cyan-100"
        : "border-rose-400/25 bg-rose-400/10 text-rose-100",
      surfaceClass: repoExecution?.ready
        ? "border-cyan-400/16 bg-cyan-400/[0.05]"
        : "border-rose-400/16 bg-rose-400/[0.05]",
      title: repoExecution?.ready ? "Workspace materialized successfully" : "Workspace materialization needs intervention",
      summary: repoExecution?.workspace_path
        ? `workspace: ${repoExecution.workspace_path}`
        : "repo execution metadata is not attached to this run.",
      chips: repoCommandStates.map((command) => `${command.label}:${command.payload?.status ?? "skipped"}`),
      bullets: repoExecution?.errors?.length
        ? repoExecution.errors.slice(0, 3)
        : repoCommandStates
          .filter((command) => command.payload?.command)
          .map((command) => command.payload?.command || "")
          .slice(0, 3),
    },
  ];

  useEffect(() => {
    if (lc.buildCode) {
      const blob = new Blob([lc.buildCode], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      setBlobUrl(url);
      return () => URL.revokeObjectURL(url);
    }
  }, [lc.buildCode]);

  useEffect(() => {
    if (!workspaceFiles.length) {
      setSelectedWorkspaceFile(null);
      setOpenWorkspaceFiles([]);
      return;
    }
    if (!selectedWorkspaceFile || !workspaceFiles.some((file) => file.path === selectedWorkspaceFile)) {
      setSelectedWorkspaceFile(workspaceFiles[0].path);
    }
  }, [selectedWorkspaceFile, workspaceFiles]);

  useEffect(() => {
    if (!workspaceFiles.length) return;
    setOpenWorkspaceFiles((current) => {
      const next = current.filter((path) => workspaceFiles.some((file) => file.path === path));
      const activePath = selectedWorkspaceFile ?? workspaceFiles[0].path;
      if (!next.includes(activePath)) next.push(activePath);
      return next.slice(-6);
    });
  }, [selectedWorkspaceFile, workspaceFiles]);

  useEffect(() => {
    setCollapsedWorkspaceFolders((current) => current.filter((path) => workspaceTreeFolderPaths.has(path)));
  }, [workspaceTreeFolderPaths]);

  if (!lc.buildCode || !sections || !quality) return null;

  const codeTabItems: { key: CodeTab; label: string; charCount: number }[] = [
    { key: "full", label: "HTML", charCount: sections.full.length },
    { key: "css", label: "CSS", charCount: sections.css.length },
    { key: "js", label: "JS", charCount: sections.js.length },
    { key: "body", label: "Body", charCount: sections.body.length },
  ];
  const selectWorkspaceFile = (path: string) => {
    setSelectedWorkspaceFile(path);
    setOpenWorkspaceFiles((current) => (current.includes(path) ? current : [...current, path].slice(-6)));
  };
  const closeWorkspaceTab = (path: string) => {
    setOpenWorkspaceFiles((current) => {
      const next = current.filter((item) => item !== path);
      if (selectedWorkspaceFile === path) {
        setSelectedWorkspaceFile(next[next.length - 1] ?? workspaceFiles[0]?.path ?? null);
      }
      return next;
    });
  };
  const toggleWorkspaceFolder = (path: string) => {
    setCollapsedWorkspaceFolders((current) => (
      current.includes(path)
        ? current.filter((item) => item !== path)
        : [...current, path]
    ));
  };
  const renderWorkspaceTreeNodes = (nodes: WorkspaceTreeNode[], depth = 0): ReactNode => (
    <div className="space-y-0.5">
      {nodes.map((node) => {
        if (node.kind === "folder") {
          const expanded = !collapsedWorkspaceFolderSet.has(node.path);
          return (
            <div key={node.id}>
              <button
                onClick={() => toggleWorkspaceFolder(node.path)}
                className={cn(
                  "flex w-full items-center justify-between rounded-xl py-1.5 pr-2 text-left text-xs transition-colors hover:bg-white/[0.04]",
                  expanded ? "text-slate-200" : "text-slate-400",
                )}
                style={{ paddingLeft: `${depth * 14 + 10}px` }}
              >
                <span className="flex min-w-0 items-center gap-1.5">
                  <ChevronRight className={cn("h-3.5 w-3.5 shrink-0 text-slate-600 transition-transform", expanded && "rotate-90 text-slate-400")} />
                  {expanded ? <FolderOpen className="h-3.5 w-3.5 shrink-0 text-sky-300" /> : <Folder className="h-3.5 w-3.5 shrink-0 text-slate-500" />}
                  <span className="truncate font-medium">{node.name}</span>
                </span>
                <span className="flex items-center gap-1.5 pl-2 text-[10px] text-slate-500">
                  {node.entrypointCount > 0 ? <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-1.5 py-0.5 text-[9px] text-emerald-200">entry</span> : null}
                  {node.packageMeta?.label ? <span className="truncate">{node.packageMeta.label}</span> : null}
                  <span>{node.fileCount}</span>
                </span>
              </button>
              {expanded ? (
                <div className="ml-3 border-l border-white/5 pl-1.5">
                  {renderWorkspaceTreeNodes(node.children, depth + 1)}
                </div>
              ) : null}
            </div>
          );
        }

        const Icon = workspaceFileIcon(node.file);
        const accentClassName = workspaceFileAccent(node.file);
        const active = activeWorkspaceFile?.path === node.path;

        return (
          <button
            key={node.id}
            onClick={() => selectWorkspaceFile(node.path)}
            className={cn(
              "flex w-full items-center justify-between rounded-xl py-1.5 pr-2 text-left text-xs transition-colors",
              active
                ? "bg-sky-400/[0.10] text-sky-50"
                : "text-slate-400 hover:bg-white/[0.04] hover:text-slate-200",
            )}
            style={{ paddingLeft: `${depth * 14 + 29}px` }}
            title={node.path}
          >
            <span className="flex min-w-0 items-center gap-2">
              <Icon className={cn("h-3.5 w-3.5 shrink-0", accentClassName)} />
              <span className="truncate">{node.name}</span>
            </span>
            <span className="flex items-center gap-1.5 pl-2 text-[10px] text-slate-500">
              {node.file.route_paths.length > 0 ? <span>{node.file.route_paths[0]}</span> : null}
              {node.file.entrypoint ? <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-1.5 py-0.5 text-[9px] text-emerald-200">entry</span> : null}
            </span>
          </button>
        );
      })}
    </div>
  );

  const renderWorkspaceShell = (showInspector: boolean) => (
    <div className={cn(
      "grid h-full min-h-0 grid-cols-1",
      showInspector ? "xl:grid-cols-[17rem_minmax(0,1fr)_18rem]" : "xl:grid-cols-[17rem_minmax(0,1fr)]",
    )}>
      <aside className="flex min-h-0 flex-col border-b border-white/8 bg-[#0b1017] xl:border-b-0 xl:border-r">
        <div className="border-b border-white/8 px-4 py-3">
          <div className="flex items-center justify-between gap-3 text-[11px] font-semibold tracking-[0.22em] text-slate-500">
            <span className="flex items-center gap-2">
              <FolderTree className="h-3.5 w-3.5 text-sky-300" />
              EXPLORER
            </span>
            <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[9px] text-slate-400">
              {workspace?.artifact_summary?.file_count ?? filteredWorkspaceFiles.length} files
            </span>
          </div>
          <div className="mt-3 rounded-[1rem] border border-white/10 bg-white/[0.03] px-3 py-3">
            <div className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.18em] text-slate-500">
            <FolderTree className="h-3.5 w-3.5 text-sky-300" />
              GENERATED WORKSPACE
            </div>
            <p className="mt-2 truncate font-mono text-[11px] text-slate-200">
              {repoExecution?.workspace_path ?? workspace?.preview_entry ?? "workspace://generated"}
            </p>
            <div className="mt-3 grid grid-cols-3 gap-2 text-[10px] text-slate-500">
              <div className="rounded-xl border border-white/8 bg-black/20 px-2 py-2">
                <p>pkg</p>
                <p className="mt-1 text-sm font-semibold text-slate-100">{workspace?.artifact_summary?.package_count ?? workspace?.package_tree.length ?? 0}</p>
              </div>
              <div className="rounded-xl border border-white/8 bg-black/20 px-2 py-2">
                <p>files</p>
                <p className="mt-1 text-sm font-semibold text-slate-100">{workspace?.artifact_summary?.file_count ?? workspaceFiles.length}</p>
              </div>
              <div className="rounded-xl border border-white/8 bg-black/20 px-2 py-2">
                <p>routes</p>
                <p className="mt-1 text-sm font-semibold text-slate-100">{workspace?.artifact_summary?.route_binding_count ?? workspace?.route_bindings.length ?? 0}</p>
              </div>
            </div>
          </div>
          <div className="mt-3 flex items-center gap-2 rounded-2xl border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-slate-300">
            <Search className="h-3.5 w-3.5 text-slate-500" />
            <input
              value={workspaceQuery}
              onChange={(event) => setWorkspaceQuery(event.target.value)}
              placeholder="path / route / lane を検索"
              className="w-full bg-transparent text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none"
            />
          </div>
          <p className="mt-2 text-[10px] font-medium tracking-[0.16em] text-slate-600">workspace explorer</p>
        </div>
        <div className="min-h-0 flex-1 overflow-auto px-3 py-3">
          <div className="space-y-4">
            {openEditorFiles.length > 0 ? (
              <section className="rounded-[1.15rem] border border-white/8 bg-white/[0.03] p-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[10px] font-semibold tracking-[0.18em] text-slate-500">OPEN EDITORS</p>
                  <span className="text-[10px] text-slate-500">{openEditorFiles.length}</span>
                </div>
                <div className="mt-2 space-y-1">
                  {openEditorFiles.map((file) => {
                    const Icon = workspaceFileIcon(file);
                    const active = activeWorkspaceFile?.path === file.path;
                    return (
                      <div
                        key={`open-editor-${file.path}`}
                        className={cn(
                          "flex items-center gap-2 rounded-xl px-2 py-1.5 text-xs",
                          active ? "bg-sky-400/[0.10] text-sky-50" : "text-slate-400 hover:bg-white/[0.04]",
                        )}
                      >
                        <button
                          onClick={() => selectWorkspaceFile(file.path)}
                          className="flex min-w-0 flex-1 items-center gap-2 text-left"
                        >
                          <Icon className={cn("h-3.5 w-3.5 shrink-0", workspaceFileAccent(file))} />
                          <span className="truncate">{file.path.split("/").pop()}</span>
                        </button>
                        {openEditorFiles.length > 1 ? (
                          <button
                            onClick={() => closeWorkspaceTab(file.path)}
                            className="rounded-full p-0.5 text-current/70 transition-colors hover:bg-white/10 hover:text-current"
                            aria-label={`${file.path} を閉じる`}
                          >
                            <X className="h-3 w-3" />
                          </button>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              </section>
            ) : null}

            <section className="rounded-[1.15rem] border border-white/8 bg-white/[0.03] p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-[10px] font-semibold tracking-[0.18em] text-slate-500">FILES</p>
                <div className="flex items-center gap-2 text-[10px] text-slate-500">
                  <span>{workspace?.framework ?? "html"}</span>
                  <span>{workspace?.router ?? "static"}</span>
                </div>
              </div>
              <div className="mt-3 rounded-[1rem] border border-white/8 bg-black/20 px-1.5 py-2">
                {workspaceTree.length > 0 ? (
                  renderWorkspaceTreeNodes(workspaceTree)
                ) : (
                  <div className="px-3 py-8 text-center text-xs text-slate-500">
                    一致する file はありません。
                  </div>
                )}
              </div>
            </section>

            <section className="rounded-[1.15rem] border border-white/8 bg-white/[0.03] p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-[10px] font-semibold tracking-[0.18em] text-slate-500">PACKAGE INDEX</p>
                <span className="text-[10px] text-slate-500">{workspace?.package_tree.length ?? 0}</span>
              </div>
              <div className="mt-2 space-y-1.5">
                {(workspace?.package_tree ?? []).map((pkg) => (
                  <button
                    key={`package-${pkg.id}`}
                    onClick={() => {
                      const match = filteredWorkspaceFiles.find((file) => file.package_id === pkg.id);
                      if (match) selectWorkspaceFile(match.path);
                    }}
                    className={cn(
                      "flex w-full items-center justify-between rounded-xl px-2 py-2 text-left text-xs transition-colors hover:bg-white/[0.04]",
                      activePackage?.id === pkg.id ? "bg-sky-400/[0.10] text-sky-50" : "text-slate-400",
                    )}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-slate-200">{pkg.label}</span>
                      <span className="mt-0.5 block truncate font-mono text-[10px] text-slate-500">{pkg.path}</span>
                    </span>
                    <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[9px] text-slate-400">
                      {pkg.file_count}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          </div>
        </div>
      </aside>

      <section className="flex min-h-0 flex-col bg-[#0c1118]">
        <div className="border-b border-white/8 bg-[#0f151e] px-4 py-3">
          {openWorkspaceFiles.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {openWorkspaceFiles.map((path) => {
                const file = workspaceFiles.find((item) => item.path === path);
                if (!file) return null;
                const active = activeWorkspaceFile?.path === path;
                return (
                  <div
                    key={path}
                    className={cn(
                      "inline-flex max-w-full items-center gap-2 rounded-2xl border px-3 py-1.5 text-xs",
                      active
                        ? "border-sky-400/25 bg-sky-400/[0.08] text-sky-50"
                        : "border-white/8 bg-black/20 text-slate-400",
                    )}
                  >
                    <button onClick={() => selectWorkspaceFile(path)} className="min-w-0 truncate text-left">
                      {path.split("/").pop()}
                    </button>
                    {openWorkspaceFiles.length > 1 ? (
                      <button
                        onClick={() => closeWorkspaceTab(path)}
                        className="rounded-full p-0.5 text-current/70 transition-colors hover:bg-white/10 hover:text-current"
                        aria-label={`${path} を閉じる`}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-sm text-slate-500">workspace file を選択してください。</p>
          )}
        </div>

        <div className="border-b border-white/8 bg-[#101722] px-4 py-3">
          {activeWorkspaceFile ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                {activeWorkspaceFile.path.split("/").map((segment, index, segments) => (
                  <span key={`${segment}-${index}`} className="inline-flex items-center gap-2">
                    {index > 0 ? <span className="text-slate-700">/</span> : null}
                    <span className={index === segments.length - 1 ? "font-semibold text-slate-100" : undefined}>{segment}</span>
                  </span>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-[10px] text-slate-300">{activeWorkspaceFile.kind}</Badge>
                <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-[10px] text-slate-300">{activeWorkspaceFile.line_count} lines</Badge>
                <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-[10px] text-slate-300">{activeWorkspaceFile.lane}</Badge>
                <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-[10px] text-slate-300">{activeWorkspaceFile.generated_from}</Badge>
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-500">workspace file を選択してください。</p>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-hidden bg-[#0a0f16]">
          {activeWorkspaceFile ? (
            <MonacoCodeSurface
              value={activeWorkspaceFile.content}
              language={monacoLanguageForWorkspaceFile(activeWorkspaceFile.path, activeWorkspaceFile.kind)}
              path={activeWorkspaceFile.path}
              label={`${activeWorkspaceFile.path} editor`}
              minimap={showInspector}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-500">
              workspace file を選択してください。
            </div>
          )}
        </div>

        <div className="border-t border-white/8 bg-[#101722] px-4 py-2">
          <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
            <span>{activePackage?.label ?? "package 未選択"}</span>
            {activeWorkspaceFile?.route_paths.length ? (
              <span>{`${activeWorkspaceFile.route_paths.length} route binding`}</span>
            ) : null}
            {activeWorkspaceFile?.content_preview ? (
              <span className="truncate">{activeWorkspaceFile.content_preview}</span>
            ) : null}
          </div>
        </div>
      </section>

      {showInspector ? (
        <aside className="hidden min-h-0 flex-col border-l border-white/8 bg-[#0b1017] xl:flex">
          <div className="border-b border-white/8 px-4 py-3">
            <div className="flex items-center gap-2 text-[11px] font-semibold tracking-[0.22em] text-slate-500">
              <Route className="h-3.5 w-3.5 text-sky-300" />
              INSPECTOR
            </div>
            <p className="mt-2 text-[10px] font-medium tracking-[0.16em] text-slate-600">inspector</p>
          </div>
          <div className="min-h-0 flex-1 space-y-4 overflow-auto px-4 py-4">
            <div className="rounded-[1.15rem] border border-white/8 bg-white/[0.03] p-4">
              <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-500">file summary</p>
              {activeWorkspaceFile ? (
                <div className="mt-3 space-y-2 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-slate-500">package</span>
                    <span className="text-right font-semibold text-slate-100">{activeWorkspaceFile.package_label}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-slate-500">lane</span>
                    <span className="font-semibold text-slate-100">{activeWorkspaceFile.lane}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-slate-500">source</span>
                    <span className="font-semibold text-slate-100">{activeWorkspaceFile.generated_from}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-slate-500">entrypoint</span>
                    <span className="font-semibold text-slate-100">{activeWorkspaceFile.entrypoint ? "yes" : "no"}</span>
                  </div>
                </div>
              ) : (
                <p className="mt-3 text-sm text-slate-500">workspace file を選択してください。</p>
              )}
            </div>

            <div className="rounded-[1.15rem] border border-white/8 bg-white/[0.03] p-4">
              <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-500">route bindings</p>
              <div className="mt-3 space-y-2">
                {relatedRouteBindings.length > 0 ? relatedRouteBindings.map((binding) => (
                  <div key={`${binding.route_path}-${binding.screen_id ?? "none"}`} className="rounded-2xl border border-white/8 bg-black/20 px-3 py-3">
                    <p className="text-sm font-semibold text-slate-100">{binding.route_path}</p>
                    <p className="mt-1 text-[11px] leading-5 text-slate-500">
                      {binding.screen_id ? `screen: ${binding.screen_id}` : "screen id なし"}
                    </p>
                  </div>
                )) : (
                  <div className="rounded-2xl border border-dashed border-white/10 px-3 py-4 text-xs text-slate-500">
                    この file に紐づく route binding はありません。
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-[1.15rem] border border-white/8 bg-white/[0.03] p-4">
              <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-500">package graph</p>
              <div className="mt-3 space-y-2">
                {relatedPackageGraph.length > 0 ? relatedPackageGraph.map((edge) => (
                  <div key={`${edge.source}-${edge.target}-${edge.reason}`} className="rounded-2xl border border-white/8 bg-black/20 px-3 py-3">
                    <p className="text-sm font-semibold text-slate-100">
                      {(workspacePackageMap.get(edge.source)?.label ?? edge.source)} → {(workspacePackageMap.get(edge.target)?.label ?? edge.target)}
                    </p>
                    <p className="mt-1 text-[11px] leading-5 text-slate-500">{edge.reason}</p>
                  </div>
                )) : (
                  <div className="rounded-2xl border border-dashed border-white/10 px-3 py-4 text-xs text-slate-500">
                    この package に隣接 dependency はありません。
                  </div>
                )}
              </div>
            </div>

            {repoExecution?.workspace_path ? (
              <div className="rounded-[1.15rem] border border-white/8 bg-white/[0.03] p-4">
                <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-500">materialization</p>
                <p className="mt-3 text-xs leading-5 text-slate-400 [overflow-wrap:anywhere]">
                  {repoExecution.workspace_path}
                </p>
                {repoExecution.repo_root ? (
                  <p className="mt-2 text-xs leading-5 text-slate-500 [overflow-wrap:anywhere]">
                    {repoExecution.repo_root}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        </aside>
      ) : null}
    </div>
  );

  // Fullscreen preview
  if (fullscreen) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col bg-[#04070d] text-slate-100">
        <div className="flex items-center gap-3 border-b border-white/10 bg-black/30 px-4 py-2 backdrop-blur">
          <span className="text-sm font-medium text-slate-100">フルスクリーンプレビュー</span>
          <div className="flex-1" />
          {blobUrl && (
            <a href={blobUrl} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-sky-300 hover:text-sky-200">
              <ExternalLink className="h-3.5 w-3.5" /> 新しいタブ
            </a>
          )}
          <button onClick={() => setFullscreen(false)} className="flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.05] px-3 py-1.5 text-xs font-medium text-slate-100 hover:bg-white/[0.08]">
            <Minimize2 className="h-3.5 w-3.5" /> 閉じる
          </button>
        </div>
        <iframe srcDoc={lc.buildCode} className="flex-1 border-0 bg-white" sandbox="allow-scripts allow-same-origin" title="フルスクリーンプレビュー" />
      </div>
    );
  }

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden bg-[#05070b] text-slate-100">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(56,189,248,0.14),transparent_32%),radial-gradient(circle_at_80%_0%,rgba(168,85,247,0.12),transparent_26%),linear-gradient(180deg,#05070b_0%,#0a0d12_48%,#06080d_100%)]" />
      <div className="pointer-events-none absolute inset-0 opacity-40 [background-image:linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)] [background-size:72px_72px]" />

      <div className="relative z-10 flex min-h-0 flex-1 flex-col">
        <div className="border-b border-white/8 bg-black/24 px-4 py-3 backdrop-blur xl:px-5">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-[11px] font-semibold tracking-[0.22em] text-emerald-100">
              <Check className="h-3.5 w-3.5" />
              BUILD COMPLETE
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline" className="border-white/10 bg-white/[0.03] text-[10px] text-slate-300">{formatBytes(new Blob([lc.buildCode]).size)}</Badge>
              {lc.buildCost > 0 ? (
                <Badge variant="outline" className="border-white/10 bg-white/[0.03] text-[10px] text-slate-300">
                  ${lc.buildCost.toFixed(4)}
                </Badge>
              ) : null}
              <Badge variant="outline" className="border-white/10 bg-white/[0.03] text-[10px] text-slate-300">
                {repoPassedCount}/{repoCommandStates.length} repo checks
              </Badge>
              <Badge variant="outline" className="border-white/10 bg-white/[0.03] text-[10px] text-slate-300">
                {quality.label} {quality.score}
              </Badge>
            </div>
            <div className="flex-1" />
            <div className="inline-flex rounded-full border border-white/10 bg-white/[0.04] p-1">
              {[
                { key: "preview" as const, label: "Preview", icon: Eye },
                { key: "code" as const, label: "Code", icon: FileCode2 },
              ].map((tab) => {
                const Icon = tab.icon;
                const active = viewMode === tab.key;
                return (
                  <button
                    key={tab.key}
                    onClick={() => setViewMode(tab.key)}
                    className={cn(
                      "inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                      active
                        ? "bg-slate-100 text-slate-950"
                        : "text-slate-400 hover:text-slate-100",
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {tab.label}
                  </button>
                );
              })}
            </div>
            {viewMode === "code" && workspaceFiles.length > 0 ? (
              <button
                onClick={() => setShowWorkspaceInspector((current) => !current)}
                className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-slate-300 transition-colors hover:bg-white/[0.08] hover:text-slate-100"
              >
                <Route className="h-3.5 w-3.5" />
                {showWorkspaceInspector ? "Inspector を隠す" : "Inspector を表示"}
              </button>
            ) : null}
            {viewMode === "preview" ? (
              <button
                onClick={() => setShowPreviewNotes((current) => !current)}
                className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-slate-300 transition-colors hover:bg-white/[0.08] hover:text-slate-100"
              >
                <BarChart3 className="h-3.5 w-3.5" />
                {showPreviewNotes ? "Notes を隠す" : "Notes を表示"}
              </button>
            ) : null}
            <button
              onClick={() => {
                if (showSummaryRail) {
                  setShowSummaryRail(false);
                  return;
                }
                setShowSummaryRail(true);
                requestAnimationFrame(() => {
                  summaryPanelRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
                });
              }}
              className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-slate-300 transition-colors hover:bg-white/[0.08] hover:text-slate-100"
            >
              {showSummaryRail ? "サマリーを隠す" : "サマリーを表示"}
            </button>
            {viewMode === "preview" ? (
              <button
                onClick={() => setFullscreen(true)}
                className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-slate-300 transition-colors hover:bg-white/[0.08] hover:text-slate-100"
                title="フルスクリーン"
              >
                <Maximize2 className="h-3.5 w-3.5" />
                Fullscreen
              </button>
            ) : null}
            {blobUrl ? (
              <a
                href={blobUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-slate-300 transition-colors hover:bg-white/[0.08] hover:text-slate-100"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                新しいタブ
              </a>
            ) : null}
            <button
              onClick={onNext}
              disabled={isHandingOff}
              className="inline-flex items-center gap-1.5 rounded-full bg-sky-400 px-4 py-1.5 text-xs font-semibold text-slate-950 transition-colors hover:bg-sky-300 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {isHandingOff ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              {isHandingOff ? "保存して移動中..." : "デプロイへ"}
              {!isHandingOff ? <ArrowRight className="h-3.5 w-3.5" /> : null}
            </button>
          </div>
        </div>

        <div className={cn(
          "grid min-h-0 flex-1 grid-cols-1",
          showSummaryRail && "xl:grid-cols-[20rem_minmax(0,1fr)]",
        )}>
          {showSummaryRail ? (
            <aside ref={summaryPanelRef} className="flex min-h-0 flex-col border-b border-white/8 bg-[linear-gradient(180deg,rgba(9,12,17,0.96),rgba(7,10,15,0.98))] xl:border-b-0 xl:border-r">
              <div className="border-b border-white/8 px-4 py-4">
                <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[10px] font-semibold tracking-[0.22em] text-slate-400">
                  pylon / development
                </div>
                <h2 className="mt-4 text-[1.55rem] font-semibold tracking-[-0.03em] text-slate-50">
                  v0 のように扱える build transcript と editor shell
                </h2>
                <p className="mt-2 text-sm leading-6 text-slate-400">
                  operator summary、repo execution、review focus を左に集約し、右は preview / code / workspace を行き来できる dark IDE に再構成しました。
                </p>
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <div className="rounded-[1.15rem] border border-white/8 bg-white/[0.03] p-3">
                    <p className="text-[10px] font-semibold tracking-[0.18em] text-slate-500">work package</p>
                    <p className="mt-2 text-lg font-semibold text-slate-100">{lc.deliveryPlan?.work_packages.length ?? 0}</p>
                  </div>
                  <div className="rounded-[1.15rem] border border-white/8 bg-white/[0.03] p-3">
                    <p className="text-[10px] font-semibold tracking-[0.18em] text-slate-500">packages</p>
                    <p className="mt-2 text-lg font-semibold text-slate-100">{workspace?.artifact_summary?.package_count ?? 0}</p>
                  </div>
                </div>
                {transitionError ? (
                  <div className="mt-4 rounded-[1.15rem] border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
                    {transitionError}
                  </div>
                ) : null}
              </div>

              <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
                <div className="space-y-4">
                  {transcriptEntries.map((entry) => (
                    <section key={entry.key} className={cn("rounded-[1.35rem] border p-4 shadow-[0_14px_38px_rgba(0,0,0,0.22)]", entry.surfaceClass)}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <span className={cn("inline-flex rounded-full border px-2.5 py-1 text-[10px] font-semibold tracking-[0.22em]", entry.badgeClass)}>
                            {entry.speaker}
                          </span>
                          <h3 className="mt-3 text-sm font-semibold text-slate-100">{entry.title}</h3>
                        </div>
                        <BarChart3 className="mt-0.5 h-4 w-4 text-slate-500" />
                      </div>
                      <p className="mt-3 text-sm leading-6 text-slate-300">{entry.summary}</p>
                      {entry.chips.length > 0 ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {entry.chips.map((chip) => (
                            <span key={chip} className="rounded-full border border-white/10 bg-black/20 px-2.5 py-1 text-[10px] text-slate-400">
                              {chip}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      {entry.bullets.length > 0 ? (
                        <div className="mt-4 space-y-2">
                          {entry.bullets.map((bullet) => (
                            <div key={bullet} className="rounded-2xl border border-white/8 bg-black/18 px-3 py-2 text-xs leading-5 text-slate-400">
                              {bullet}
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </section>
                  ))}

                  {recentDevelopmentDecisions.length > 0 ? (
                    <section className="rounded-[1.35rem] border border-white/8 bg-white/[0.03] p-4">
                      <p className="text-[11px] font-semibold tracking-[0.22em] text-slate-500">LATEST DECISIONS</p>
                      <div className="mt-3 space-y-2">
                        {recentDevelopmentDecisions.map((decision) => (
                          <div key={decision.id} className="rounded-2xl border border-white/8 bg-black/18 px-3 py-3">
                            <p className="text-sm font-semibold text-slate-100">{decision.title}</p>
                            <p className="mt-1 text-xs leading-5 text-slate-500">{decision.rationale}</p>
                          </div>
                        ))}
                      </div>
                    </section>
                  ) : null}

                  <section className="rounded-[1.35rem] border border-white/8 bg-white/[0.03] p-4">
                    <p className="text-[11px] font-semibold tracking-[0.22em] text-slate-500">VALUE / TELEMETRY</p>
                    <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                      <div className="rounded-2xl border border-white/8 bg-black/18 px-3 py-3">
                        <p className="text-[10px] font-semibold tracking-[0.18em] text-slate-500">value contract</p>
                        <p className="mt-2 text-sm font-semibold text-slate-100">{valueContract?.summary ?? "未生成"}</p>
                        <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-slate-400">
                          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">
                            persona {valueContract?.primary_personas?.length ?? 0}
                          </span>
                          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">
                            paths {valueContract?.information_architecture?.key_paths?.length ?? 0}
                          </span>
                          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">
                            metrics {valueContract?.success_metrics?.length ?? 0}
                          </span>
                        </div>
                      </div>
                      <div className="rounded-2xl border border-white/8 bg-black/18 px-3 py-3">
                        <p className="text-[10px] font-semibold tracking-[0.18em] text-slate-500">outcome telemetry</p>
                        <p className="mt-2 text-sm font-semibold text-slate-100">{outcomeTelemetryContract?.summary ?? "未生成"}</p>
                        <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-slate-400">
                          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">
                            events {outcomeTelemetryContract?.telemetry_events?.length ?? 0}
                          </span>
                          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">
                            kill {outcomeTelemetryContract?.kill_criteria?.length ?? 0}
                          </span>
                          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">
                            artifacts {outcomeTelemetryContract?.workspace_artifacts?.length ?? 0}
                          </span>
                        </div>
                      </div>
                    </div>
                  </section>

                  <section className="rounded-[1.35rem] border border-white/8 bg-white/[0.03] p-4">
                    <p className="text-[11px] font-semibold tracking-[0.22em] text-slate-500">READY TO HANDOFF</p>
                    <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                      <div className="rounded-2xl border border-white/8 bg-black/18 px-3 py-3">
                        <p className="text-[10px] font-semibold tracking-[0.18em] text-slate-500">deploy checklist</p>
                        <div className="mt-2 space-y-2">
                          {(handoff?.deploy_checklist ?? []).slice(0, 3).map((item) => (
                            <p key={typeof item === "string" ? item : item.id} className="text-xs leading-5 text-slate-300">{typeof item === "string" ? item : item.label}</p>
                          ))}
                          {!handoff?.deploy_checklist?.length ? (
                            <p className="text-xs leading-5 text-slate-500">deploy checklist は handoff packet にありません。</p>
                          ) : null}
                        </div>
                      </div>
                      <div className="rounded-2xl border border-white/8 bg-black/18 px-3 py-3">
                        <p className="text-[10px] font-semibold tracking-[0.18em] text-slate-500">workspace</p>
                        <p className="mt-2 text-xs leading-5 text-slate-300">{workspace?.preview_entry ?? "preview entry not resolved"}</p>
                        <p className="mt-1 text-xs leading-5 text-slate-500">{workspace?.dev_command ?? "dev command unavailable"}</p>
                      </div>
                    </div>
                  </section>
                </div>
              </div>

              <div className="border-t border-white/8 px-4 py-4">
                <div className="rounded-[1.35rem] border border-white/8 bg-white/[0.03] p-4">
                  <p className="text-[10px] font-semibold tracking-[0.22em] text-slate-500">NEXT ACTION</p>
                  <p className="mt-2 text-sm leading-6 text-slate-300">
                    {handoff?.readiness_status === "ready_for_deploy"
                      ? "deploy phase に進める状態です。preview を確認して、そのまま handoff を確定できます。"
                      : "rework が必要です。code / workspace で差分と route binding を確認してから次に進めてください。"}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {blobUrl ? (
                      <a
                        href={blobUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-slate-300 transition-colors hover:bg-white/[0.08] hover:text-slate-100"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        Preview を開く
                      </a>
                    ) : null}
                    <button
                      onClick={onNext}
                      disabled={isHandingOff}
                      className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-950 transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-70"
                    >
                      {isHandingOff ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                      {isHandingOff ? "保存中..." : "Deploy handoff"}
                    </button>
                  </div>
                </div>
              </div>
            </aside>
          ) : null}

          <section className="flex min-h-0 flex-col bg-transparent">
            <div className="border-b border-white/8 bg-black/18 px-4 py-3 backdrop-blur xl:px-5">
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-rose-400" />
                  <span className="h-2.5 w-2.5 rounded-full bg-amber-300" />
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
                </div>
                <p className="text-sm font-medium text-slate-100">
                  {viewMode === "preview"
                    ? workspace?.preview_entry ?? "preview"
                    : activeWorkspaceFile?.path ?? codeTabItems.find((item) => item.key === codeTab)?.label ?? "code"}
                </p>
                <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] text-slate-400">
                  {viewMode === "preview"
                    ? "preview canvas"
                    : workspaceFiles.length > 0
                      ? showWorkspaceInspector ? "explorer + inspector" : "explorer + editor"
                      : "build output"}
                </span>
                {viewMode !== "preview" ? (
                  <span className="rounded-full border border-sky-400/20 bg-sky-400/10 px-2.5 py-1 text-[10px] text-sky-100">
                    Monaco runtime
                  </span>
                ) : null}
                <div className="flex-1" />
                <div className="flex flex-wrap gap-2 text-[10px] text-slate-500">
                  <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1">
                    {workspace?.framework ?? "html"} / {workspace?.router ?? "static"}
                  </span>
                  <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1">
                    {repoExecution?.mode ?? "sandbox"}
                  </span>
                </div>
              </div>
            </div>

            <div className="min-h-0 flex-1 p-3 md:p-4 xl:p-5">
              <div className="h-full overflow-hidden rounded-[2rem] border border-white/10 bg-[#0c1017] shadow-[0_32px_90px_rgba(0,0,0,0.45)]">
                {viewMode === "preview" ? (
                  <div className={cn(
                    "grid h-full min-h-0 grid-cols-1",
                    showPreviewNotes && "xl:grid-cols-[minmax(0,1fr)_16rem]",
                  )}>
                    <div className="flex min-h-0 flex-col">
                      <div className="border-b border-white/8 bg-[#111722] px-4 py-3">
                        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                          <Eye className="h-3.5 w-3.5 text-sky-300" />
                          <span>{workspace?.preview_entry ?? "preview entry not resolved"}</span>
                          {workspace?.entrypoints[0] ? (
                            <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] text-slate-500">
                              {workspace.entrypoints[0]}
                            </span>
                          ) : null}
                        </div>
                      </div>
                      <div className="min-h-0 flex-1 bg-[#151b24] p-4 md:p-6">
                        <div className="h-full overflow-hidden rounded-[1.75rem] border border-black/20 bg-white shadow-[0_22px_64px_rgba(15,23,42,0.26)]">
                          <iframe srcDoc={lc.buildCode} className="h-full w-full border-0 bg-white" sandbox="allow-scripts allow-same-origin" title="プレビュー" />
                        </div>
                      </div>
                    </div>

                    {showPreviewNotes ? (
                    <aside className="hidden min-h-0 flex-col border-l border-white/8 bg-[#0d121b] xl:flex">
                      <div className="border-b border-white/8 px-4 py-3">
                        <p className="text-[11px] font-semibold tracking-[0.22em] text-slate-500">PREVIEW NOTES</p>
                      </div>
                      <div className="min-h-0 flex-1 space-y-4 overflow-auto px-4 py-4">
                        <div className="rounded-[1.15rem] border border-white/8 bg-white/[0.03] p-4">
                          <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-500">quality</p>
                          <p className="mt-2 text-lg font-semibold text-slate-100">{quality.score}</p>
                          <div className="mt-3 space-y-2">
                            {quality.details.map((detail) => (
                              <div key={detail} className="rounded-2xl border border-white/8 bg-black/18 px-3 py-2 text-xs text-slate-400">
                                {detail}
                              </div>
                            ))}
                          </div>
                        </div>
                        <div className="rounded-[1.15rem] border border-white/8 bg-white/[0.03] p-4">
                          <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-500">repo execution</p>
                          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                            {repoCommandStates.map((command) => (
                              <div key={command.label} className="rounded-2xl border border-white/8 bg-black/18 px-2 py-3">
                                <p className="text-[10px] tracking-[0.16em] text-slate-500">{command.label}</p>
                                <p className="mt-2 text-xs font-semibold text-slate-100">{command.payload?.status ?? "skipped"}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                        <div className="rounded-[1.15rem] border border-white/8 bg-white/[0.03] p-4">
                          <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-500">handoff</p>
                          <div className="mt-3 space-y-2">
                            {(handoff?.deploy_checklist ?? []).slice(0, 4).map((item) => (
                              <div key={typeof item === "string" ? item : item.id} className="rounded-2xl border border-white/8 bg-black/18 px-3 py-2 text-xs text-slate-400">
                                {typeof item === "string" ? item : item.label}
                              </div>
                            ))}
                            {!handoff?.deploy_checklist?.length ? (
                              <p className="text-xs leading-5 text-slate-500">deploy checklist はありません。</p>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    </aside>
                    ) : null}
                  </div>
                ) : workspaceFiles.length > 0 ? (
                  renderWorkspaceShell(showWorkspaceInspector)
                ) : (
                  <div className="flex h-full min-h-0 flex-col bg-[#0b1017]">
                    <div className="border-b border-white/8 px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        {codeTabItems.map((tab) => (
                          <button
                            key={tab.key}
                            onClick={() => setCodeTab(tab.key)}
                            className={cn(
                              "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                              codeTab === tab.key
                                ? "border-sky-300/30 bg-sky-300/12 text-sky-50"
                                : "border-white/8 bg-white/[0.03] text-slate-400 hover:text-slate-100",
                            )}
                          >
                            {tab.label}
                            <span className="ml-1.5 text-[10px] opacity-70">
                              {tab.charCount.toLocaleString()}
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="min-h-0 flex-1 overflow-hidden bg-[#0a0f16]">
                      <MonacoCodeSurface
                        value={activeCode || "(empty)"}
                        language={monacoLanguageForCodeTab(codeTab)}
                        path={`build-output/${codeTab === "full" ? "index.html" : codeTab === "css" ? "styles.css" : codeTab === "js" ? "app.js" : "body.html"}`}
                        label={`${codeTab} code editor`}
                        minimap
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
