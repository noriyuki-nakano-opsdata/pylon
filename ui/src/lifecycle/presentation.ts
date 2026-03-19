import type { LifecyclePhase } from "@/types/lifecycle";

const PHASE_LABELS: Record<LifecyclePhase, string> = {
  research: "調査",
  planning: "企画",
  design: "デザイン",
  approval: "承認",
  development: "開発",
  deploy: "デプロイ",
  iterate: "改善",
};

const RESEARCH_NODE_LABELS: Record<string, string> = {
  "competitor-analyst": "競合分析",
  "market-researcher": "市場調査",
  "user-researcher": "ユーザー調査",
  "tech-evaluator": "技術評価",
  "research-synthesizer": "統合分析",
  "evidence-librarian": "根拠整理",
  "devils-advocate-researcher": "反証レビュー",
  "cross-examiner": "相互検証",
  "research-judge": "最終判定",
};

const SOURCE_CLASS_LABELS: Record<string, string> = {
  vendor_page: "競合の製品ページ",
  pricing_page: "料金ページ",
  integration_doc: "導入 / 連携ドキュメント",
  market_report: "市場レポート",
  user_signal: "ユーザーシグナル",
  secondary_user_source: "補助的なユーザー情報",
  technical_source: "技術ソース",
};

const CLAIM_STATUS_LABELS: Record<string, string> = {
  accepted: "採択",
  blocked: "要再検討",
  contested: "反証あり",
  provisional: "仮置き",
};

const CLAIM_CATEGORY_LABELS: Record<string, string> = {
  competition: "競合",
  market: "市場",
  user: "ユーザー",
  technical: "技術",
  research: "調査",
};

const PARSE_STATUS_LABELS: Record<string, string> = {
  strict: "JSON厳密",
  repaired: "JSON修復",
  fallback: "フォールバック",
  failed: "解析失敗",
};

const NODE_STATUS_LABELS: Record<string, string> = {
  success: "正常",
  degraded: "要再確認",
  failed: "失敗",
};

const DISSENT_SEVERITY_LABELS: Record<string, string> = {
  critical: "重大",
  high: "高",
  medium: "中",
  low: "低",
};

const AUTONOMOUS_REMEDIATION_STATUS_LABELS: Record<string, string> = {
  not_needed: "不要",
  queued: "自動補完を継続予定",
  retrying: "自動補完中",
  resolved: "自動補完で解消",
  blocked: "自動補完の上限に到達",
};

const RESEARCH_RECOVERY_MODE_LABELS: Record<string, string> = {
  auto: "自動判断",
  deepen_evidence: "根拠を深掘り",
  reframe_research: "観点を切り替えて再調査",
};

const RESEARCH_OPERATOR_ACTION_LABELS: Record<string, string> = {
  wait_for_autonomous_recovery: "AI の自動回復を待つ",
  deepen_evidence: "根拠を深掘りして再実行",
  reframe_research: "観点を変えて再調査",
  conditional_handoff: "条件付きで企画へ進む",
  clarify_scope: "問いを絞ってから再調査",
  advance_to_planning: "企画へ進む",
};

const DEGRADATION_REASON_LABELS: Record<string, string> = {
  llm_json_parse_failed: "LLM 応答を構造化できませんでした",
  llm_response_repaired: "LLM 応答を JSON として修復しました",
  empty_llm_response: "LLM 応答が空でした",
  critical_dissent_unresolved: "重大な反証が未解決です",
};

function stripSourceLead(text: string): string {
  let next = text.replace(/\*\*/g, "").replace(/^#+\s*/, "").trim();
  if (next.includes(": #")) {
    next = next.split(": #").slice(-1)[0]?.trim() ?? next;
  }
  const parts = next.split(":");
  if (parts.length >= 3) {
    const head = parts[0]?.trim();
    const tail = parts.slice(1).join(":").trim();
    if (head && tail.toLowerCase().startsWith(head.toLowerCase())) {
      next = tail;
    }
  }
  if (next.includes("**")) {
    next = next.split("**").slice(-1)[0]?.trim() ?? next;
  }
  next = next.replace(/^[^。]{0,60}(記事|ブログ|ガイド|ドキュメント|レポート|資料|docs|guide)より[:：]?\s*/iu, "");
  const japaneseIndex = next.search(/[ぁ-んァ-ヶ一-龠]/u);
  if (japaneseIndex > 16) {
    const prefix = next.slice(0, japaneseIndex);
    if (/^[ -~\s:;,.#\-$()%/]+$/.test(prefix)) {
      next = next.slice(japaneseIndex).trim();
    }
  }
  return next;
}

export function polishResearchCopy(value: string): string {
  let next = stripSourceLead(value)
    .replace(/\s+/g, " ")
    .replace(
      "外部 URL に grounded された evidence が不足しています。",
      "外部 URL の根拠が不足しています。",
    )
    .replace(
      "主要仮説に対する反証が生成されています。",
      "主要仮説に対する反証は確保できています。",
    )
    .replace("external url evidence is missing", "外部 URL の根拠が不足しています")
    .replace("external url evidence is present", "外部 URL の根拠があります")
    .replace("Autonomous remediation budget is exhausted.", "自動補完の回数上限に達しました。")
    .replace("The current research blockers need operator guidance.", "現在の調査の詰まりはオペレーターの判断が必要です。")
    .replace("Proceed with planning under explicit research assumptions.", "未解決の前提を明示したうえで企画へ進みます。")
    .replace(
      /Planning outputs are not yet sufficient for design and approval\./gi,
      "企画の成果がまだ十分ではなく、デザインと承認へ進める状態ではありません。",
    )
    .replace(
      /Close the remaining research gaps so 企画 can continue without operator intervention\./gi,
      "残っている調査ギャップを埋め、オペレーターの介入なしで企画へ進める状態にします。",
    )
    .replace(
      /Can the team defend this thesis with enough grounded evidence to plan against it:/gi,
      "この仮説は、企画に進めるだけの公開根拠で支えられているか:",
    )
    .replace(
      /この仮説を、企画に使える grounded evidence で防御できるか:/gi,
      "この仮説は、企画に進めるだけの公開根拠で支えられているか:",
    )
    .replace(
      /Define the observable evidence that would falsify this claim in the first milestone\./gi,
      "最初のマイルストーンで、この主張を否定できる観測可能な根拠を定義してください。",
    )
    .replace(/grounded evidence/gi, "公開根拠")
    .replace(/kill criteria/gi, "除外条件")
    .replace(/\bopen question\b/gi, "未解決の論点")
    .replace(/\bassumption\b/gi, "前提条件")
    .replace(/\bprimary scope\b/gi, "主計画")
    .replace(/\balpha scope\b/gi, "アルファ範囲")
    .replace(/\bclaim\b/gi, "主張")
    .replace(/\bcritical node\b/gi, "重要ノード")
    .replace(/\bUX\b/g, "UX")
    .replace("低下したノード", "要再確認ノード")
    .replace(/Research needs rework/gi, "調査結果の見直しが必要です")
    .replace(/strict gate/gi, "品質ゲート")
    .replace(/guarded handoff/gi, "条件付き引き継ぎ")
    .replace(/confidence floor/gi, "信頼度下限")
    .replace(/winning theses?/gi, "有力仮説")
    .replace(/\bthesis\b/gi, "仮説")
    .replace(/critical dissent/gi, "重大な反証")
    .replace(/\bdissent\b/gi, "反証")
    .replace(/\bevidence\b/gi, "根拠")
    .replace(/\bgrounded\b/gi, "裏づいた")
    .replace(/公開根拠/g, "公開根拠")
    .replace(/\bplanning\b/gi, "企画")
    .replace(/\bdegraded\b/gi, "要再確認")
    .replace(/\bblocked\b/gi, "未達")
    .replace(/\bpass\b/gi, "通過")
    .replace(/winning\s*仮説\s*数/gi, "有力仮説数")
    .replace(/有力仮説 数/g, "有力仮説数")
    .replace(/接地した根拠/g, "公開根拠")
    .replace(/外部 URL に\s*紐づいた\s*された\s*根拠\s*が\s*あります。?/gi, "外部 URL の根拠があります。")
    .replace(/外部 URL に\s*紐づいた\s*された\s*根拠\s*が\s*不足しています。?/gi, "外部 URL の根拠が不足しています。")
    .replace(/外部 URL に\s*裏づいた\s*された\s*根拠\s*が\s*あります。?/gi, "外部 URL の根拠があります。")
    .replace(/外部 URL に\s*裏づいた\s*された\s*根拠\s*が\s*不足しています。?/gi, "外部 URL の根拠が不足しています。")
    .replace(/どの論文も/g, "どの仮説も")
    .replace(/論文/g, "仮説")
    .replace(/ゼロの解決が記録された/g, "解決がまだ記録されていない")
    .replace(/Not publicly listed/gi, "非公開")
    .replace(/feature breadth/gi, "機能の広さ")
    .replace(/traceability/gi, "追跡可能性")
    .replace(/(^|[。\s])は\s*企画\s*の閾値を満たしています。?/g, "$1信頼度下限は企画の閾値を満たしています。")
    .replace(/operator/gi, "オペレーター")
    .replace(/blocker/gi, "阻害要因")
    .replace(/brief/gi, "要約")
    .replace(/no unresolved 重大な反証/gi, "未解決の重大な反証はありません")
    .trim();
  for (const [nodeId, label] of Object.entries(RESEARCH_NODE_LABELS)) {
    next = next.replace(new RegExp(`\\b${nodeId.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\$&")}\\b`, "gi"), label);
  }
  return next;
}

export function polishConsoleCopy(value: string): string {
  return polishResearchCopy(value)
    .replace(
      /Development is approval-gated and must not auto-run until approval is granted\./gi,
      "開発は承認後にのみ開始されます。まず承認フェーズで判断を確定してください。",
    )
    .replace(
      /Deploy checks have passed and a release record can be created\./gi,
      "デプロイチェックは通過しています。リリース記録を作成できます。",
    )
    .replace(
      /The release exists, but no iteration feedback has been captured yet\./gi,
      "リリースは作成済みですが、改善に回すフィードバックがまだ記録されていません。",
    )
    .replace(
      /A release and feedback loop already exist; continue iterating within the backlog\./gi,
      "リリースと改善ループは揃っています。バックログを起点に次の改善を進めてください。",
    )
    .replace(
      "Phase outputs did not satisfy readiness checks.",
      "品質ゲートを満たせなかったため、見直しが必要です。",
    )
    .replace(/critical research dissent/gi, "重大な反証")
    .replace(/critical research nodes/gi, "重要ノード")
    .replace(/support handoff/gi, "後続フェーズへの引き継ぎ")
    .replace(/requires rework/gi, "見直しが必要")
    .replace(/project brief/gi, "プロジェクト要約")
    .replace(/public web evidence/gi, "公開 Web 根拠")
    .replace(
      /mix vendor pages with neutral analyst or practitioner sources before finalizing claims\./gi,
      "主張を確定する前に、ベンダーページだけでなく第三者ソースも混ぜて根拠を厚くしてください。",
    )
    .replace(
      /call out where the result is based on public web evidence versus the project brief\./gi,
      "公開 Web 根拠とプロジェクト要約由来の内容を明確に分けてください。",
    )
    .replace(
      /prefer source diversity over adding more snippets from the same domain\./gi,
      "同じドメインの断片を増やすより、異なるソースの多様性を優先してください。",
    )
    .replace(/reviewed (\d+) grounded sources for research\./gi, "調査のために接地済みソースを $1 件確認しました。")
    .replace(/research phase skill executed by /gi, "")
    .replace(/Delegate /g, "")
    .replace(/for lifecycle phase research on project [^.:]+\.?/gi, "")
    .replace(/for research\/[a-z-]+: /gi, "")
    .replace(/current cycle/gi, "現サイクル")
    .replace(/未解決の critical dissent が (\d+) 件残っています。/g, "未解決の重大な反証が $1 件残っています。")
    .replace(/confidence floor は ([0-9.]+)、winning thesis 数は (\d+) です。/g, "信頼度下限は $1、有力仮説数は $2 です。")
    .replace(/Research Judgement/g, "調査判定")
    .replace(/Research Cross Examination/g, "相互検証")
    .replace(/Claim Ledger/g, "主張台帳")
    .replace(/Research Dissent/g, "反証レビュー")
    .replace(/Research Report/g, "調査レポート")
    .replace(/Research Swarm requires rework/g, "調査結果の見直しが必要")
    .replace(/Downstream lifecycle outputs invalidated/g, "後続成果物を再生成")
    .replace(/Research execution inputs changed; regenerate research and all downstream artifacts\./g, "調査入力が変わったため、research と後続成果物を再生成します。")
    .replace(/lineage_reset/g, "系譜リセット")
    .replace(/phase_outcome/g, "フェーズ判定")
    .replace(/Completed/g, "完了")
    .replace(/Running/g, "実行中")
    .replace(/Failed/g, "失敗")
    .replace(/deterministic-reference/g, "内部参照")
    .replace(/competitive-intelligence/gi, "競争分析")
    .replace(/market-sizing/gi, "市場規模推定")
    .replace(/market-research/gi, "市場調査")
    .replace(/persona-research/gi, "ペルソナ分析")
    .replace(/local/gi, "ローカル")
    .replace(/task:/gi, "タスク:");
}

export function presentLifecycleGateReason(params: {
  currentPhase: LifecyclePhase;
  recommendedPhase: LifecyclePhase | null;
  reason: string | null | undefined;
}): string | null {
  const { currentPhase, recommendedPhase, reason } = params;
  if (typeof reason !== "string" || reason.trim().length === 0) {
    return null;
  }

  if (
    recommendedPhase === "approval"
    && currentPhase !== "approval"
    && /Development is approval-gated and must not auto-run until approval is granted\./i.test(reason)
  ) {
    if (currentPhase === "development") {
      return polishConsoleCopy(reason);
    }
    return `${formatPhaseLabel(currentPhase)} は承認の判断が完了するまで開けません。まず承認フェーズで判断を確定してください。`;
  }

  if (
    recommendedPhase === "development"
    && currentPhase !== "development"
    && (
      /phase workflow API/i.test(reason)
      || /ready for implementation/i.test(reason)
      || /Run development mesh/i.test(reason)
    )
  ) {
    return `${formatPhaseLabel(currentPhase)} は開発フェーズの実行が完了するまで開けません。まず開発フェーズを開始して build を生成してください。`;
  }

  if (
    recommendedPhase === "deploy"
    && currentPhase !== "deploy"
    && (
      /release record/i.test(reason)
      || /deploy checks/i.test(reason)
      || /release exists/i.test(reason)
    )
  ) {
    return `${formatPhaseLabel(currentPhase)} はデプロイ判断が完了するまで開けません。まずデプロイフェーズでチェックとリリース記録を確定してください。`;
  }

  return polishConsoleCopy(reason);
}

export function formatPhaseLabel(phase: LifecyclePhase): string {
  return PHASE_LABELS[phase] ?? phase;
}

export function formatResearchNodeLabel(nodeId: string): string {
  return RESEARCH_NODE_LABELS[nodeId] ?? nodeId;
}

export function formatSourceClassLabel(code: string): string {
  return SOURCE_CLASS_LABELS[code] ?? code;
}

export function formatClaimStatus(status: string): string {
  return CLAIM_STATUS_LABELS[status] ?? status;
}

export function formatClaimCategory(category: string): string {
  return CLAIM_CATEGORY_LABELS[category] ?? category;
}

export function formatParseStatus(status: string): string {
  return PARSE_STATUS_LABELS[status] ?? status;
}

export function formatNodeStatus(status: string): string {
  return NODE_STATUS_LABELS[status] ?? status;
}

export function formatDissentSeverity(severity: string): string {
  return DISSENT_SEVERITY_LABELS[severity] ?? severity;
}

export function formatAutonomousRemediationStatus(status: string): string {
  return AUTONOMOUS_REMEDIATION_STATUS_LABELS[status] ?? status;
}

export function formatResearchRecoveryMode(mode: string): string {
  return RESEARCH_RECOVERY_MODE_LABELS[mode] ?? polishResearchCopy(mode.replaceAll("_", " "));
}

export function formatResearchOperatorAction(action: string): string {
  return RESEARCH_OPERATOR_ACTION_LABELS[action] ?? polishResearchCopy(action.replaceAll("_", " "));
}

export function formatResearchDegradationReason(reason: string): string {
  if (DEGRADATION_REASON_LABELS[reason]) {
    return DEGRADATION_REASON_LABELS[reason];
  }
  if (reason.startsWith("missing_source_classes:")) {
    const values = reason
      .replace("missing_source_classes:", "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    return `不足ソース: ${values.map(formatSourceClassLabel).join(" / ")}`;
  }
  if (reason.startsWith("quality_gate_failed:")) {
    const gateId = reason.replace("quality_gate_failed:", "");
    const gateLabel: Record<string, string> = {
      "source-grounding": "外部根拠の接地不足",
      "critical-dissent-resolved": "重大な反証が未解決",
      "confidence-floor": "信頼度下限が未達",
      "critical-node-health": "主要ノードの健全性が未達",
      "counterclaim-coverage": "反証カバレッジが不足",
    };
    return gateLabel[gateId] ?? gateId;
  }
  return polishResearchCopy(reason.replaceAll("_", " "));
}

export function formatResearchGateTitle(gateId: string, title: string): string {
  const labels: Record<string, string> = {
    "source-grounding": "採択主張が外部根拠に紐づいている",
    "counterclaim-coverage": "主要仮説に対する反証が確保されている",
    "critical-dissent-resolved": "重大な反証が未解決のまま残っていない",
    "confidence-floor": "企画に渡せる信頼度を満たしている",
    "critical-node-health": "主要ノードが要再確認 / 失敗ではない",
  };
  return labels[gateId] ?? polishResearchCopy(title);
}

export function formatRunStatus(status: string): string {
  const labels: Record<string, string> = {
    completed: "完了",
    running: "実行中",
    failed: "失敗",
    pending: "待機",
  };
  return labels[status.toLowerCase()] ?? polishConsoleCopy(status);
}

export function formatPhaseStatus(status: string): string {
  const labels: Record<string, string> = {
    available: "開始可能",
    in_progress: "進行中",
    completed: "完了",
    locked: "未解放",
  };
  return labels[status] ?? polishConsoleCopy(status);
}

export function formatEARSPattern(pattern: string): string {
  const labels: Record<string, string> = {
    ubiquitous: "普遍的要件",
    "event-driven": "イベント駆動",
    unwanted: "例外処理",
    "state-driven": "状態駆動",
    optional: "オプション",
    complex: "複合要件",
  };
  return labels[pattern] ?? pattern;
}

export function formatConfidenceBadge(confidence: number): { label: string; level: string } {
  if (confidence >= 0.8) return { label: "高信頼度", level: "high" };
  if (confidence >= 0.5) return { label: "中信頼度", level: "medium" };
  return { label: "低信頼度", level: "low" };
}

export function formatTaskPriority(priority: string): string {
  const labels: Record<string, string> = { must: "必須", should: "推奨", could: "任意" };
  return labels[priority] ?? priority;
}

export function formatRiskSeverity(severity: string): string {
  const labels: Record<string, string> = { critical: "致命的", high: "高", medium: "中", low: "低" };
  return labels[severity] ?? severity;
}
