import type { DesignVariant, LifecycleDecisionFrame } from "@/types/lifecycle";

const FEATURE_LABELS: Record<string, string> = {
  "research workspace": "調査ワークスペース",
  "planning synthesis": "企画シンセシス",
  "artifact lineage": "成果物系譜",
  "approval gate": "承認ゲート",
  "operator console": "オペレーターコンソール",
};

const SHARED_COPY_REPLACEMENTS: Array<[RegExp, string]> = [
  [
    /Operator trust: every phase decision should remain explainable, reviewable, and recoverable\.?/gi,
    "各フェーズの判断が、説明できて、レビューできて、巻き戻せる状態を守る。",
  ],
  [
    /Turn grounded evidence into a governed plan, then carry the same decision context into design and build\.?/gi,
    "根拠ある調査結果を統治された企画へ変え、その判断文脈をデザインと開発まで持ち運ぶ。",
  ],
  [
    /The plan keeps only features that remain traceable to research claims and falsifiable milestones\.?/gi,
    "調査根拠にさかのぼれ、マイルストーンで検証できる機能だけを残しています。",
  ],
  [/Strengthen mobile density control with clearer section hierarchy\.?/gi, "モバイル時の密度制御と階層差をさらに明確にする。"],
  [/Raise contrast around primary operator actions and status labels\.?/gi, "主要操作と状態ラベルのコントラストをさらに上げる。"],
  [/Make approval and readiness signals visible above the fold\.?/gi, "承認状態と準備完了のシグナルをファーストビューで見えるようにする。"],
  [
    /Every surface is decision-focused: approval gates surface evidence inline, artifact lineage reads as a lit timeline, and degraded states use amber signal pulses rather than modal interruptions\.?/gi,
    "すべての面を判断中心に置き、承認では根拠をその場で確認でき、リネージは時系列で追え、劣化状態もモーダルに逃がさず画面内で回復できます。",
  ],
  [
    /The operator always knows where they are, what is blocked, and what decision is next\.?/gi,
    "オペレーターが、いまどこにいて、何が詰まっていて、次に何を決めるべきかを常に把握できます。",
  ],
  [/Run discovery-to-build workflow/gi, "調査から実装準備までを一気通貫で進める"],
  [/Operator-led multi-agent/gi, "オペレーター主導のマルチエージェント"],
  [/Direction A/gi, "方向A"],
  [/Direction B/gi, "方向B"],
  [/product workflow/gi, "プロダクト導線"],
  [/control-room/gi, "制御室"],
  [/decision-studio/gi, "判断室"],
  [/precision operator shell/gi, "高精度オペレーターシェル"],
  [/control surface/gi, "操作盤"],
  [/four-zone/gi, "4ゾーン"],
  [/Sidebar nav/gi, "サイドバーナビ"],
  [/\bsidebar nav\b/gi, "サイドバーナビ"],
  [/control center shell/gi, "コントロールセンターシェル"],
  [/high density/gi, "高密度"],
  [/\bhigh density\b/gi, "高密度"],
  [/research workspace/gi, "調査ワークスペース"],
  [/planning synthesis/gi, "企画シンセシス"],
  [/Recover degraded research lane/gi, "劣化した調査レーンを立て直す"],
  [/Approve or rework a phase/gi, "承認するか差し戻すかを判断する"],
  [/Trace\s+artifact\s+lineage/gi, "成果物の系譜を追跡する"],
  [/追跡\s+成果物の系譜/gi, "成果物の系譜を追跡する"],
  [/追跡\s+成果物リネージ/gi, "成果物の系譜を追跡する"],
  [/Review runs and checkpoints/gi, "ランとチェックポイントを確認する"],
  [/Pending approvals and rework history/gi, "保留中の承認と差し戻し履歴を確認する"],
  [/Phase artifacts and lineage/gi, "フェーズ成果物と系譜を確認する"],
  [/Primary work area for each phase/gi, "各フェーズの主要作業面"],
  [/Open primary workspace/gi, "主要ワークスペースを開く"],
  [/Start research/gi, "調査を開始する"],
  [/Start 調査/gi, "調査を開始する"],
  [/Review planning/gi, "企画内容を確認する"],
  [/Select a design/gi, "デザイン案を選ぶ"],
  [/Run development/gi, "開発準備へ進める"],
  [/Idea to approval/gi, "構想から承認まで"],
  [/Lane recovery/gi, "レーン復旧"],
  [/Build artifacts and phase history are recorded/gi, "成果物とフェーズ履歴が記録される"],
  [/Build 成果物 and phase history are recorded/gi, "成果物とフェーズ履歴が記録される"],
  [/The recovery reason and delta are recorded/gi, "復旧理由と差分が記録される"],
  [/Selected design was generated from an older decision context/gi, "選択中の案は古い判断文脈で生成されています"],
  [/The operator can compare evidence, choose a resolution path, and re-run with confidence/gi, "根拠を比較し、復旧方針を選び、自信を持って再実行できる"],
  [/The next action and current state are obvious at a glance/gi, "次の操作と現在状態がひと目で分かる"],
  [/Review queue/gi, "レビューキュー"],
  [/Decision checklist/gi, "判断チェックリスト"],
  [/Governance context/gi, "統治コンテキスト"],
  [/Decision snapshot/gi, "判断サマリー"],
  [/Workflow lane/gi, "進行レーン"],
  [/Operator context/gi, "運用コンテキスト"],
  [/Run monitor/gi, "ラン監視"],
  [/Checkpoint lane/gi, "復旧レーン"],
  [/Operator notes/gi, "運用メモ"],
  [/Lineage explorer/gi, "リネージ探索"],
  [/Trace path/gi, "追跡経路"],
  [/Trace View/gi, "追跡ビュー"],
  [/\bTrace\b/gi, "追跡"],
  [/Product Platform Lead/gi, "プロダクト基盤責任者"],
  [/Reference rail/gi, "参照レール"],
  [/Primary tasks/gi, "主要タスク"],
  [/Task flow/gi, "作業フロー"],
  [/Support context/gi, "補助コンテキスト"],
  [/Evidence-to-build loop/gi, "根拠から実装への連鎖"],
  [/Governed delivery/gi, "統制されたデリバリー"],
  [/Operator-ready release/gi, "オペレーターが扱えるリリース"],
  [/Open the degraded lane/gi, "劣化したレーンを開く"],
  [/Open the approval gate/gi, "承認ゲートを開く"],
  [/the 承認ゲートを開く/gi, "承認ゲートを開く"],
  [/Review missing evidence and blockers/gi, "不足根拠とブロッカーを確認する"],
  [/Choose a recovery strategy/gi, "復旧方針を選ぶ"],
  [/Re-run only the affected lane/gi, "影響したレーンだけ再実行する"],
  [/Review the evidence/gi, "根拠を確認する"],
  [/Approve or request rework/gi, "承認するか差し戻しを依頼する"],
  [/Open an artifact/gi, "成果物を開く"],
  [/Inspect the linked decisions/gi, "紐づく判断を確認する"],
  [/Trace which agent produced it/gi, "どのエージェントが生成したか追跡する"],
  [/Approve/gi, "承認する"],
  [/Approve or rework/gi, "承認するか差し戻す"],
  [/Inspect evidence/gi, "根拠を確認する"],
  [/Review risks/gi, "リスクを確認する"],
  [/Active run/gi, "稼働中ラン"],
  [/Blocked node/gi, "停止ノード"],
  [/Next step/gi, "次の一手"],
  [/Queued/gi, "待機中"],
  [/Running/gi, "進行中"],
  [/Released/gi, "反映済み"],
  [/Escalations/gi, "要対応事項"],
  [/Retry budget/gi, "再試行余力"],
  [/handoff readiness/gi, "引き継ぎ準備度"],
  [/approval handoff/gi, "承認への引き継ぎ"],
  [/Handoff clarity/gi, "引き継ぎ明快さ"],
  [/Approval packet/gi, "承認パケット"],
  [/Rework request/gi, "差し戻し依頼"],
  [/Decision note/gi, "判断メモ"],
  [/Policy coverage/gi, "ポリシー充足"],
  [/Audit trail/gi, "監査証跡"],
  [/Decision owner/gi, "判断責任者"],
  [/Evidence source/gi, "根拠ソース"],
  [/Decision log/gi, "判断ログ"],
  [/Build artifact/gi, "ビルド成果物"],
  [/Policy update/gi, "ポリシー更新"],
  [/The decision history is recorded/gi, "判断履歴が記録される"],
  [/The evidence chain is explainable/gi, "根拠のつながりを説明できる"],
  [/Owner/gi, "担当者"],
  [/Timestamp/gi, "記録時刻"],
  [/Export/gi, "書き出し"],
  [/Risk register/gi, "リスク台帳"],
  [/Release signal/gi, "リリース判断シグナル"],
  [/Primary user/gi, "主要利用者"],
  [/Design lane/gi, "設計レーン"],
  [/Planning relies on a narrow trust assumption/gi, "企画が狭い信頼仮説に依存している"],
  [/The plan does not naturally protect against the hardest-to-serve user\.?/gi, "最も厳しい利用条件でも判断導線が破綻しないかを確認する必要がある。"],
  [/Aiko will trade setup breadth for stronger control and traceability\./gi, "初期セットアップの広さより、統制と追跡性を優先する前提です。"],
  [/The first milestone can be validated before full-scale automation breadth is delivered\./gi, "全面自動化の前に、最初のマイルストーンを先に検証する前提です。"],
  [/high-fidelity application shell with task flows/gi, "主要フローを含む高精度プロダクトワークスペース"],
  [/high-fidelity application shell with five primary screens and one degraded-state recovery flow/gi, "主要5画面と復旧フローを含む高精度プロダクトワークスペース"],
  [/three-column: 240px rail \| flex center \| 320px context panel/gi, "3カラム: 左レール / 主作業面 / 右コンテキスト"],
  [/two-panel: 55% run log \| 45% evidence accumulator, stacked on mobile/gi, "2パネル: 実行ログ / 根拠蓄積面。モバイルでは縦積み"],
  [/command-center/gi, "コマンドセンター"],
  [/decision-studio/gi, "判断スタジオ"],
  [/control-center/gi, "コントロールセンター"],
  [/split-review/gi, "比較レビュー"],
  [/two-column: 60% evidence brief \| 40% decision panel; single column on mobile/gi, "2カラム: 根拠ブリーフ / 判断パネル。モバイルでは1カラム"],
  [/single centered column \(max-width 800px\) with vertical timeline spine; full-width on mobile/gi, "中央1カラム: 縦タイムライン軸。モバイルでは全幅"],
  [/\bBuild to release\b/gi, "実装からリリースまで"],
  [/\bPlanning\b/gi, "企画"],
  [/\bApproval\b/gi, "承認"],
  [/\bApproval rules\b/gi, "承認ルール"],
  [/\bPolicies\b/gi, "ポリシー"],
  [/\bRecovery strategy\b/gi, "復旧方針"],
  [/\bthe approval gate\b/gi, "承認ゲート"],
  [/\bthe degraded lane\b/gi, "劣化レーン"],
  [/\ban artifact\b/gi, "成果物"],
  [/\bReview ラン and checkpoints\b/gi, "ランとチェックポイントを確認する"],
  [/\bPending 承認 and rework history\b/gi, "保留中の承認と差し戻し履歴を確認する"],
  [/\bPhase 成果物 and lineage\b/gi, "フェーズ成果物と系譜を確認する"],
  [/\bworkspace admin\b/gi, "ワークスペース管理者"],
  [/\bTeam routing\b/gi, "チームルーティング"],
  [/\bresearch から development まで\b/gi, "調査から開発まで"],
  [/\bapproval と rework\b/gi, "承認と差し戻し"],
  [/\bphase deep link\b/gi, "フェーズ直通リンク"],
  [/\brun telemetry\b/gi, "実行テレメトリ"],
  [/\bfeedback loop\b/gi, "フィードバックループ"],
  [/\brelease gate\b/gi, "リリースゲート"],
  [/\bhandoff\b/gi, "引き継ぎ"],
  [/\btemplate preview\b/gi, "テンプレートプレビュー"],
  [/\bllm preview\b/gi, "LLMプレビュー"],
  [/\brepaired preview\b/gi, "再構成プレビュー"],
  [/\bpreview html\b/gi, "プレビューHTML"],
  [/\bpreview\b/gi, "プレビュー"],
  [/\bprototype app\b/gi, "試作アプリ"],
  [/\bprototype spec\b/gi, "試作仕様"],
  [/\bms-alpha\b/gi, "初回検証マイルストーン"],
  [/\bms-beta\b/gi, "拡張検証マイルストーン"],
  [/\bms-release\b/gi, "リリース検証マイルストーン"],
  [/\bDAG\b/g, "実行グラフ"],
  [/\bactive run view\b/gi, "稼働中ランビュー"],
  [/\bcommand deck\b/gi, "コマンドデッキ"],
  [/\bcommand surface\b/gi, "操作盤"],
  [/\bcheckpoint recovery\b/gi, "チェックポイント復旧"],
  [/\bdecision ledger\b/gi, "判断台帳"],
  [/\bapp router\b/gi, "App Router"],
  [/\bapplication shell\b/gi, "アプリケーションシェル"],
  [/\bapp shell\b/gi, "アプリケーションシェル"],
  [/\bscreens\b/gi, "画面"],
  [/\bscreen\b/gi, "画面"],
  [/\bworkflows\b/gi, "フロー"],
  [/\bworkflow\b/gi, "フロー"],
  [/\broutes\b/gi, "ルート"],
  [/\broute\b/gi, "ルート"],
  [/\bfiles\b/gi, "ファイル"],
  [/\bfile\b/gi, "ファイル"],
  [/\blive event\b/gi, "ライブイベント"],
  [/\bView\b/gi, "ビュー"],
  [/\bresearch\b/gi, "調査"],
  [/\bdevelopment\b/gi, "開発"],
  [/\bphase\b/gi, "フェーズ"],
  [/\btelemetry\b/gi, "テレメトリ"],
  [/\bdeep link\b/gi, "直通リンク"],
  [/\bgate\b/gi, "ゲート"],
  [/\bloop\b/gi, "ループ"],
  [/\bOpen settings\b/gi, "設定を開く"],
  [/\bUpdate approval rules and quality gates\b/gi, "承認ルールと品質ゲートを更新する"],
  [/\bSave team routing\b/gi, "チームルーティングを保存する"],
  [/\bOpen the run monitor\b/gi, "ラン監視を開く"],
  [/\bInspect phase state and blockers\b/gi, "フェーズ状態とブロッカーを確認する"],
  [/\bChoose the required intervention\b/gi, "必要な介入を選ぶ"],
  [/\bThe blockage and response history are recorded\b/gi, "停止要因と対応履歴が記録される"],
  [/\bReview release readiness and publish outcome\b/gi, "リリース準備を確認して結果を記録する"],
  [/\bOpen release readiness\b/gi, "リリース準備を開く"],
  [/\bstateful\b/gi, "状態保持型"],
  [/\bshell\b/gi, "シェル"],
  [/\bworkspace\b/gi, "ワークスペース"],
  [/\bsynthesis\b/gi, "シンセシス"],
  [/\blayout\b/gi, "レイアウト"],
  [/\bdensity\b/gi, "密度"],
  [/\bnav\b/gi, "ナビ"],
  [/\brules\b/gi, "ルール"],
  [/\bdegraded\b/gi, "劣化"],
  [/\blane\b/gi, "レーン"],
  [/\brouting\b/gi, "ルーティング"],
  [/\brework\b/gi, "差し戻し"],
  [/Evidence\s+Review/gi, "根拠レビュー"],
  [/\bEvidence\b/gi, "根拠"],
  [/Primary Shell/gi, "主要シェル"],
  [/queue/gi, "キュー"],
  [/checklist/gi, "チェックリスト"],
  [/packet/gi, "パケット"],
  [/summary/gi, "サマリー"],
  [/timeline/gi, "タイムライン"],
  [/panel/gi, "パネル"],
  [/structure/gi, "構成"],
];

const MODEL_LABELS: Record<string, string> = {
  "claude-designer": "Claude Sonnet 4.6",
  "gemini-designer": "KIMI K2.5 / Direction B",
};

const MODEL_PRICING: Record<string, { input: number; output: number }> = {
  "anthropic/claude-sonnet-4-6": { input: 3.0, output: 15.0 },
  "google/gemini-3-pro-preview": { input: 1.25, output: 10.0 },
};

function normalizeText(value: string | null | undefined): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function dedupeStrings(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.map((value) => normalizeText(value)).filter(Boolean)));
}

function cleanupLocalizedText(value: string): string {
  return value
    .replace(/\.\s+(?=[\u3040-\u30ff\u3400-\u9fff])/g, "。")
    .replace(/split-レビュー/gi, "比較レビュー")
    .replace(/調査 ワークスペース/g, "調査ワークスペース")
    .replace(/調査 から 開発 まで/g, "調査から開発まで")
    .replace(/コントロールセンター シェル/g, "コントロールセンターシェル")
    .replace(/サイドバー ナビ/g, "サイドバーナビ")
    .replace(/高 密度/g, "高密度")
    .replace(/承認 ルール/g, "承認ルール")
    .replace(/承認 と 差し戻し/g, "承認と差し戻し")
    .replace(/劣化 レーン/g, "劣化レーン")
    .replace(/フェーズ直通リンク 付き/g, "フェーズ直通リンク付き")
    .replace(/切り替えながら 構想から承認まで/g, "切り替えながら、構想から承認まで")
    .replace(/成果物リネージ/g, "成果物系譜")
    .replace(/の 成果物系譜/g, "の成果物系譜")
    .replace(/成果物系譜 が/g, "成果物系譜が")
    .replace(/追跡 成果物の系譜/g, "成果物の系譜を追跡する")
    .replace(/追跡 成果物系譜/g, "成果物の系譜を追跡する")
    .replace(/再構成プレビュー を/g, "再構成プレビューを")
    .replace(/再構成プレビュー まで/g, "再構成プレビューまで")
    .replace(/修復済みプレビュー を/g, "再構成プレビューを")
    .replace(/主要判断 が/g, "主要判断が")
    .replace(/主要フロー が/g, "主要フローが")
    .replace(/差し戻し が/g, "差し戻しが")
    .replace(/ループ が/g, "ループが")
    .replace(/が フェーズ直通リンク付き/g, "がフェーズ直通リンク付き")
    .replace(/レーン に必要/g, "レーンに必要")
    .replace(/ゲート に必要/g, "ゲートに必要")
    .replace(/試作アプリ と/g, "試作アプリと")
    .replace(/引き継ぎ 準備度/g, "引き継ぎ準備度")
    .replace(/handoff 準備度/gi, "引き継ぎ準備度")
    .replace(/\s+\/\s+/g, " / ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function replaceKnownPhrases(value: string): string {
  return SHARED_COPY_REPLACEMENTS.reduce(
    (result, [pattern, replacement]) => result.replace(pattern, replacement),
    value,
  );
}

function replaceKnownLabels(value: string): string {
  let result = value;
  Object.entries(FEATURE_LABELS).forEach(([raw, localized]) => {
    result = result.replace(new RegExp(raw, "gi"), localized);
  });
  return result
    .replace(/Lifecycle Workspace/gi, "ライフサイクルワークスペース")
    .replace(/Research Workspace/gi, "調査ワークスペース")
    .replace(/Approval Gate/gi, "承認ゲート")
    .replace(/Artifact Lineage/gi, "成果物系譜")
    .replace(/Degraded Lane/gi, "劣化レーン")
    .replace(/Evidence Review/gi, "根拠レビュー")
    .replace(/Active Run View/gi, "稼働中ランビュー")
    .replace(/Provenance Drawer/gi, "系譜ドロワー")
    .replace(/Decision Review/gi, "判断レビュー")
    .replace(/Run Ledger/gi, "ラン台帳")
    .replace(/Release Readiness/gi, "リリース準備")
    .replace(/Phase Workspace/gi, "フェーズワークスペース")
    .replace(/Command Deck/gi, "コマンドデッキ")
    .replace(/Research Recovery/gi, "調査復旧")
    .replace(/Lineage Explorer/gi, "リネージ探索")
    .replace(/product-workspace/gi, "プロダクトワークスペース")
    .replace(/command-center/gi, "コマンドセンター")
    .replace(/split-review/gi, "比較レビュー")
    .replace(/high-fidelity application shell with task flows/gi, "主要フローまで含んだ高精度アプリケーション試作")
    .replace(/high-fidelity application shell with five primary screens and one degraded-state recovery flow/gi, "主要5画面と復旧フローを含む高精度アプリケーション試作");
}

function localizeText(value: string | null | undefined): string {
  const normalized = normalizeText(value);
  if (!normalized) return "";
  return cleanupLocalizedText(replaceKnownLabels(replaceKnownPhrases(normalized)));
}

function looksJapanese(value: string): boolean {
  return /[\u3040-\u30ff\u3400-\u9fff]/.test(value);
}

function looksLikeRiskStatement(value: string): boolean {
  return /状態です|依存して|圧力|課題|リスク|懸念|不安|論点/.test(value);
}

function looksLikeArtifactHeadline(value: string): boolean {
  return looksJapanese(value) && value.length <= 120 && !looksLikeRiskStatement(value);
}

function synthesizedDesignLeadThesis(frame: LifecycleDecisionFrame | null): string {
  const northStar = localizeText(frame?.north_star);
  const coreLoop = localizeText(frame?.core_loop);
  if (northStar || coreLoop) {
    return "成果物の系譜と承認根拠が同じ操作面でつながり、各判断を説明できる状態を守る。";
  }
  return "企画で見えた勝ち筋を、承認に耐えるプロダクト導線へ翻訳します。";
}

function isPresentationFriendlyHandoffNote(value: string): boolean {
  return (
    looksJapanese(value)
    && value.length <= 160
    && !/[`{}]/.test(value)
    && !/grid-template-columns|css custom properties|css grid|tailwind|router/i.test(value)
  );
}

function rewriteDecisionRisk(value: string): string {
  const localized = localizeText(value);
  if (!localized) return "";
  if (!looksJapanese(localized)) {
    return "確認事項: 最も厳しい利用条件でも判断導線が破綻しないかを承認前に確認する。";
  }
  if (/スコープ圧力|scope/i.test(localized)) {
    return "初回リリースでは運用コンソールの範囲を固定し、承認と差し戻しに必要な面を先に成立させる。";
  }
  if (/信頼仮説|導入判断時の不安|信頼形成/.test(localized)) {
    return "承認理由と根拠を同じ画面で読めるかを、今回の承認条件として確認する。";
  }
  if (/最も厳しい利用条件|hardest-to-serve/i.test(localized)) {
    return "最も厳しい利用条件でも判断導線が破綻しないかを、承認前の確認項目に含める。";
  }
  if (/情報密度/.test(localized)) {
    return "密度を上げる面と余白で読ませる面を分け、主要操作の視線導線を崩さない。";
  }
  return `確認事項: ${localized.replace(/状態です。?$/, "").replace(/。+$/, "")} を承認前に潰す。`;
}

function rewriteDecisionAssumption(value: string): string {
  const localized = localizeText(value);
  if (!localized) return "";
  if (!looksJapanese(localized)) {
    return "前提条件: 初回リリースで守るべき操作面を固定し、拡張は次段階で扱う。";
  }
  if (/統制と追跡性/.test(localized)) {
    return "広い設定幅より、判断根拠と成果物の系譜が一貫して見えることを優先する。";
  }
  if (/最初のマイルストーン|全面自動化/.test(localized)) {
    return "全面自動化より先に、初回検証で承認・差し戻し・追跡の最小運用を成立させる。";
  }
  if (/承認前に根拠/.test(localized)) {
    return "承認前に根拠をその場で読み返せることを、非交渉の条件として扱う。";
  }
  return `前提条件: ${localized.replace(/です。?$/, "").replace(/。+$/, "")} を崩さない。`;
}

function variantModeLabel(variant: Pick<DesignVariant, "id" | "pattern_name">): string {
  if (variant.id === "claude-designer") return "密度高めの制御室";
  if (variant.id === "gemini-designer") return "余白を効かせた判断室";
  return localizeText(variant.pattern_name) || "比較案";
}

function variantModelRef(variant: Pick<DesignVariant, "id" | "model">): string | null {
  const raw = normalizeText(variant.model).toLowerCase();
  if (raw.includes("claude sonnet 4.6")) return "anthropic/claude-sonnet-4-6";
  if (raw.includes("gemini 3 pro")) return "google/gemini-3-pro-preview";
  if (raw.includes("kimi") || raw.includes("k2.5")) return "moonshot/kimi-k2.5";
  if (variant.id === "claude-designer") return "anthropic/claude-sonnet-4-6";
  if (variant.id === "gemini-designer") return "moonshot/kimi-k2.5";
  return null;
}

function localizePreviewAttributeValue(value: string): string {
  return localizeText(value);
}

export function presentDirectionLabel(index: number): string {
  return `案 ${String.fromCharCode(65 + index)}`;
}

export function presentDecisionLeadThesis(frame: LifecycleDecisionFrame | null, fallback?: string | null): string {
  const lead = localizeText(frame?.lead_thesis);
  if (looksLikeArtifactHeadline(lead)) return lead;
  const fallbackText = localizeText(fallback);
  if (looksLikeArtifactHeadline(fallbackText)) return fallbackText;
  return synthesizedDesignLeadThesis(frame);
}

export function presentDecisionSummary(frame: LifecycleDecisionFrame | null): string {
  const summary = localizeText(frame?.summary);
  if (summary && summary !== localizeText(frame?.lead_thesis) && !looksLikeRiskStatement(summary)) return summary;
  return "この画面では、同じ分析結果から操作密度と判断リズムの異なる 2 案を作り、承認に渡す基準案を選びます。";
}

export function presentDecisionReviewItems(frame: LifecycleDecisionFrame | null): string[] {
  const risks = (frame?.key_risks ?? []).map((item) => rewriteDecisionRisk(item.title));
  const assumptions = (frame?.key_assumptions ?? []).map((item) => rewriteDecisionAssumption(item.title));
  const items = dedupeStrings([...risks, ...assumptions]).slice(0, 4);
  if (items.length > 0) return items;
  return ["承認理由、差し戻し理由、次の一手がファーストビューで説明できるかを確認する。"];
}

export function presentDecisionNorthStar(frame: LifecycleDecisionFrame | null): string {
  return localizeText(frame?.north_star) || "各フェーズの判断が、説明できて、レビューできて、巻き戻せる状態を守る。";
}

export function presentDecisionCoreLoop(frame: LifecycleDecisionFrame | null): string {
  return localizeText(frame?.core_loop) || "根拠ある調査結果を企画に変え、その判断文脈をデザインと開発まで持ち運ぶ。";
}

export function presentFeatureLabel(value: string): string {
  const normalized = normalizeText(value);
  if (!normalized) return "";
  return FEATURE_LABELS[normalized.toLowerCase()] ?? localizeText(normalized);
}

export function presentNamedItem(value: string): string {
  return localizeText(value);
}

export function presentVariantTitle(variant: Pick<DesignVariant, "pattern_name" | "id">, index: number): string {
  const localized = localizeText(variant.pattern_name);
  if (localized) return localized;
  return index >= 0 ? variantModeLabel(variant) : "比較案";
}

export function presentVariantSynopsis(
  variant: Pick<DesignVariant, "id" | "description" | "pattern_name">,
): string {
  if (variant.id === "claude-designer") {
    return "暗い制御室のような密度で、状態把握、承認、差し戻し、系譜確認を一枚の操作盤に集約する案です。";
  }
  if (variant.id === "gemini-designer") {
    return "明るい判断室のような余白で、根拠確認と承認判断を落ち着いて進められる案です。";
  }
  const localized = localizeText(variant.description);
  if (looksJapanese(localized)) return localized;
  return localized || "勝ち筋を別の操作体験として翻訳した比較案です。";
}

export function presentVariantModelLabel(variant: Pick<DesignVariant, "id" | "model">): string {
  return localizeText(variant.model) || MODEL_LABELS[variant.id] || "設計レーン";
}

export function presentVariantEstimatedCost(
  variant: Pick<DesignVariant, "id" | "model" | "tokens" | "cost_usd">,
): number {
  const modelRef = variantModelRef(variant);
  const pricing = modelRef ? MODEL_PRICING[modelRef] : null;
  const inputTokens = Number(variant.tokens?.in ?? 0);
  const outputTokens = Number(variant.tokens?.out ?? 0);
  if (pricing && inputTokens > 0 && outputTokens > 0) {
    return Math.round((((inputTokens * pricing.input) + (outputTokens * pricing.output)) / 1_000_000) * 1000) / 1000;
  }
  return Number(variant.cost_usd ?? 0);
}

export function presentVariantExperienceThesis(
  variant: Pick<DesignVariant, "id" | "description" | "narrative" | "decision_scope" | "provider_note" | "rationale" | "pattern_name">,
  frame: LifecycleDecisionFrame | null,
): string {
  const narrative = localizeText(variant.narrative?.experience_thesis);
  if (narrative) return narrative;
  const leadThesis = localizeText(variant.decision_scope?.lead_thesis) || presentDecisionLeadThesis(frame);
  if (variant.id === "claude-designer") {
    return `${leadThesis} そのため、情報を圧縮せずに並べ、判断材料と操作を同じ面に置く構成を採ります。`;
  }
  if (variant.id === "gemini-designer") {
    return `${leadThesis} そのため、余白と視線誘導で判断負荷を下げ、根拠確認を静かに進める構成を採ります。`;
  }
  return leadThesis;
}

export function presentVariantOperationalBet(
  variant: Pick<DesignVariant, "id" | "narrative" | "provider_note" | "rationale">,
): string {
  const narrative = localizeText(variant.narrative?.operational_bet);
  if (narrative) return narrative;
  const note = localizeText(variant.provider_note) || localizeText(variant.rationale);
  if (looksJapanese(note)) return note;
  if (variant.id === "claude-designer") {
    return "承認、差し戻し、リネージ確認を最短の視線移動で回せることに賭ける案です。";
  }
  if (variant.id === "gemini-designer") {
    return "重要な判断の前後で圧迫感を減らし、根拠を読みながら合意形成しやすくする案です。";
  }
  return note || "同じ勝ち筋を、別の運用リズムで成立させる案です。";
}

export function presentVariantHandoffNote(
  variant: Pick<DesignVariant, "id" | "narrative" | "provider_note" | "rationale">,
): string {
  const explicitNote = localizeText(variant.narrative?.handoff_note) || localizeText(variant.rationale);
  if (isPresentationFriendlyHandoffNote(explicitNote)) return explicitNote;
  const providerNote = localizeText(variant.provider_note);
  if (isPresentationFriendlyHandoffNote(providerNote)) {
    return providerNote;
  }
  if (variant.id === "claude-designer") {
    return "採用時は、高密度でも迷わない情報優先順位と、判断状態が一目で分かる表示ルールを承認パケットに固定します。";
  }
  if (variant.id === "gemini-designer") {
    return "採用時は、余白を保ちながら根拠と操作を行き来できるレイアウト規律を承認パケットに固定します。";
  }
  if (looksJapanese(explicitNote) && explicitNote.length > 0) {
    return explicitNote.length <= 160 ? explicitNote : `${explicitNote.slice(0, 157).trimEnd()}...`;
  }
  return "採用理由、主要画面、実装で守るべき体験を承認と開発へ引き継ぎます。";
}

export function presentVariantSelectionSummary(
  variant: Pick<DesignVariant, "selection_rationale" | "id" | "pattern_name" | "description">,
): string {
  const summary = localizeText(variant.selection_rationale?.summary);
  if (summary) return summary;
  return presentVariantSynopsis(variant);
}

export function presentVariantSelectionReasons(
  variant: Pick<DesignVariant, "selection_rationale" | "id" | "narrative" | "provider_note" | "rationale" | "pattern_name" | "description" | "decision_scope">,
): string[] {
  const reasons = (variant.selection_rationale?.reasons ?? []).map((item) => localizeText(item)).filter(Boolean);
  if (reasons.length > 0) return reasons;
  return [
    presentVariantExperienceThesis(variant, null),
    presentVariantOperationalBet(variant),
    presentVariantHandoffNote(variant),
  ]
    .map((item) => localizeText(item))
    .filter(Boolean)
    .slice(0, 3);
}

export function presentVariantTradeoffs(
  variant: Pick<DesignVariant, "selection_rationale" | "id">,
): string[] {
  const tradeoffs = (variant.selection_rationale?.tradeoffs ?? []).map((item) => localizeText(item)).filter(Boolean);
  if (tradeoffs.length > 0) return tradeoffs;
  if (variant.id === "claude-designer") {
    return ["情報密度が高いため、視線誘導と強弱設計を維持する必要がある。"];
  }
  if (variant.id === "gemini-designer") {
    return ["余白を優先しているため、同時監視量は制御室型より少ない。"];
  }
  return ["主要フローの強さと情報密度のバランスを監視する必要がある。"];
}

export function presentVariantApprovalFocus(
  variant: Pick<DesignVariant, "selection_rationale">,
): string[] {
  const focus = (variant.selection_rationale?.approval_focus ?? []).map((item) => localizeText(item)).filter(Boolean);
  return focus.slice(0, 4);
}

export function presentVariantApprovalPacket(
  variant: Pick<DesignVariant, "approval_packet" | "id" | "narrative" | "provider_note" | "rationale" | "description" | "pattern_name" | "decision_scope">,
): {
  operatorPromise: string;
  mustKeep: string[];
  guardrails: string[];
  reviewChecklist: string[];
  handoffSummary: string;
} {
  const packet = variant.approval_packet;
  const operatorPromise = localizeText(packet?.operator_promise) || presentVariantExperienceThesis(variant, null);
  const mustKeep = (packet?.must_keep ?? []).map((item) => localizeText(item)).filter(Boolean);
  const guardrails = (packet?.guardrails ?? []).map((item) => localizeText(item)).filter(Boolean);
  const reviewChecklist = (packet?.review_checklist ?? []).map((item) => localizeText(item)).filter(Boolean);
  const handoffSummary = localizeText(packet?.handoff_summary) || presentVariantHandoffNote(variant);
  return {
    operatorPromise,
    mustKeep: mustKeep.slice(0, 4),
    guardrails: guardrails.slice(0, 4),
    reviewChecklist: reviewChecklist.slice(0, 4),
    handoffSummary,
  };
}

export function presentSignatureMoment(value: string): string {
  return localizeText(value);
}

export function presentScreenText(value: string): string {
  return localizeText(value);
}

export type DeliverySliceView = {
  key: string;
  code?: string;
  title: string;
  milestone?: string;
  acceptance?: string;
};

function parseEmbeddedSliceField(source: string, field: string): string {
  const closedMatch = source.match(new RegExp(`['"]${field}['"]\\s*:\\s*['"]([^'"]+)['"]`));
  if (closedMatch?.[1]) return closedMatch[1].trim();
  const openMatch = source.match(new RegExp(`['"]${field}['"]\\s*:\\s*['"](.+)$`));
  return openMatch?.[1]?.replace(/['"}\],\s]+$/g, "").trim() ?? "";
}

function parseDeliverySlice(item: string, index: number): DeliverySliceView {
  const raw = String(item ?? "").trim();
  if (!raw) {
    return {
      key: `slice-${index}`,
      title: `実装スライス ${index + 1}`,
    };
  }
  if (raw.startsWith("{") && raw.includes("title")) {
    const code = parseEmbeddedSliceField(raw, "slice");
    const title = parseEmbeddedSliceField(raw, "title");
    const milestone = parseEmbeddedSliceField(raw, "milestone");
    const acceptance = parseEmbeddedSliceField(raw, "acceptance");
    if (title) {
      return {
        key: code || title || `slice-${index}`,
        code: code || undefined,
        title: presentNamedItem(title),
        milestone: milestone ? presentNamedItem(milestone) : undefined,
        acceptance: acceptance ? presentNamedItem(acceptance) : undefined,
      };
    }
  }
  return {
    key: raw,
    title: presentNamedItem(raw),
  };
}

export function presentDeliverySlices(items: string[] | undefined | null): DeliverySliceView[] {
  return (items ?? [])
    .map((item, index) => parseDeliverySlice(item, index))
    .filter((item, index, values) => values.findIndex((candidate) => candidate.key === item.key) === index);
}

export function presentDeployCheckStatusLabel(status: "pass" | "warning" | "fail"): string {
  if (status === "pass") return "合格";
  if (status === "warning") return "注意";
  return "不合格";
}

export function presentFeedbackTypeLabel(type: "bug" | "feature" | "improvement" | "praise"): string {
  if (type === "bug") return "不具合";
  if (type === "feature") return "機能要望";
  if (type === "improvement") return "改善案";
  return "好意的な声";
}

export function presentFeedbackImpactLabel(impact: "low" | "medium" | "high"): string {
  if (impact === "high") return "影響大";
  if (impact === "medium") return "影響中";
  return "影響小";
}

export function localizePreviewHtmlForDisplay(html: string): string {
  if (!html.trim() || typeof DOMParser === "undefined" || typeof NodeFilter === "undefined") {
    return html;
  }
  try {
    const document = new DOMParser().parseFromString(html, "text/html");
    if (!document.body) return html;
    if ((document.documentElement.getAttribute("lang") || "").toLowerCase() === "en") {
      document.documentElement.setAttribute("lang", "ja");
    }

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let current = walker.nextNode();
    while (current) {
      const textNode = current as Text;
      const parentTag = textNode.parentElement?.tagName;
      if (parentTag !== "SCRIPT" && parentTag !== "STYLE") {
        textNode.textContent = localizeText(textNode.textContent);
      }
      current = walker.nextNode();
    }

    ["aria-label", "title", "placeholder"].forEach((attribute) => {
      document.querySelectorAll<HTMLElement>(`[${attribute}]`).forEach((element) => {
        const value = element.getAttribute(attribute);
        if (!value) return;
        element.setAttribute(attribute, localizePreviewAttributeValue(value));
      });
    });

    return `<!doctype html>\n${document.documentElement.outerHTML}`;
  } catch {
    return html;
  }
}
