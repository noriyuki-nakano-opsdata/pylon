# ADR-010: 調査→企画→承認→開発→更新 一気通貫ワークフローアーキテクチャ

- **Status**: Proposed
- **Date**: 2026-03-09
- **Authors**: System Architecture Team

## コンテキスト

現在のPylonは以下の3ワークフローを提供している:

1. `ux-analysis` (単一ノード: analyze → END)
2. `product-builder` (2ノード: plan → build → END)
3. `autonomous-builder` (ループ: plan → build → review(loop) → END)

これらは独立しており、調査から開発・更新までの一気通貫フローが存在しない。
また、単一モデルでの実行に限定されており、複数モデルの並行比較や、
デザイン案の比較・マージ、ドラフト→承認→確定のステート管理が不足している。

## 決定事項

以下5つの設計領域について、Pylonの既存アーキテクチャ(GraphExecutor, PylonProject DSL,
StateMachine, ApprovalManager)を拡張する形で一気通貫ワークフローを実現する。

---

## 1. マルチモデル並行実行アーキテクチャ

### 設計方針

GraphExecutorの既存の並行実行セマンティクス(fan-out/fan-in)を活用し、
同一プロンプトを複数モデルに同時投入する`parallel-model`ノードタイプを導入する。

### バックエンド設計

```
新規ノードタイプ: "parallel-model"
─────────────────────────────────────
WorkflowNodeDef に以下を追加:
  models: list[str]           # ["anthropic/claude-sonnet-4", "openai/gpt-4o", "google/gemini-2.0-flash"]
  evaluation_strategy: str    # "auto" | "manual" | "hybrid"
  cost_limit_per_model: float # 各モデルの上限コスト
```

#### ProviderRegistry 拡張

```python
# src/pylon/runtime/llm.py (既存)
class ProviderRegistry:
    # 現在: register("anthropic", factory) のみ
    # 拡張: 複数プロバイダを統一的に扱う

    async def fan_out(
        self,
        prompt: str,
        models: list[str],
        max_tokens: int = 4096,
    ) -> list[ModelResponse]:
        """同一プロンプトを複数モデルに並行送信"""
        tasks = []
        for model_id in models:
            provider_name = model_id.split("/")[0]
            provider = self._providers[provider_name](model_id)
            tasks.append(provider.generate(prompt, max_tokens))
        return await asyncio.gather(*tasks, return_exceptions=True)
```

#### 評価・比較エンジン

```python
# src/pylon/evaluation/comparator.py (新規)
@dataclass
class ModelComparison:
    model_id: str
    output: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float
    quality_score: float | None  # auto評価時のみ

@dataclass
class ComparisonResult:
    comparisons: list[ModelComparison]
    recommended_index: int | None  # auto評価時の推奨
    evaluation_rationale: str

class ResponseComparator:
    async def evaluate(
        self,
        prompt: str,
        responses: list[ModelComparison],
        criteria: list[str],  # ["accuracy", "code_quality", "completeness"]
    ) -> ComparisonResult:
        """メタモデル(固定: Claude)で複数レスポンスを評価"""
```

#### DAGノード定義

```
                    ┌──────────────────────┐
                    │    fan-out-models     │
                    │  (parallel-model)     │
                    └───┬──────┬──────┬────┘
                        │      │      │
                   ┌────▼─┐ ┌─▼────┐ ┌▼────┐
                   │Claude│ │GPT-4o│ │Gemini│
                   └──┬───┘ └──┬───┘ └──┬──┘
                      │        │        │
                    ┌─▼────────▼────────▼─┐
                    │    fan-in-compare     │
                    │  (join: ALL_RESOLVED) │
                    │  evaluation_strategy  │
                    └──────────┬───────────┘
                               │
              ┌────────────────▼───────────────┐
              │ evaluation_strategy == "manual" │
              │ → waiting_selection (承認待ち)   │
              │ evaluation_strategy == "auto"   │
              │ → 自動で最高スコアを選択          │
              └────────────────┬───────────────┘
                               │
                        ┌──────▼──────┐
                        │ 次ノードへ    │
                        └─────────────┘
```

### フロントエンド設計

```
src/components/comparison/
  ModelComparisonPanel.tsx    # side-by-side比較パネル
  ModelResponseCard.tsx       # 各モデルの出力カード
  CostQualityChart.tsx        # コスト×品質散布図
  ModelSelector.tsx           # ユーザー選択UI
```

#### ModelComparisonPanel 構造

```typescript
// src/components/comparison/ModelComparisonPanel.tsx
interface ModelComparisonPanelProps {
  comparisons: ModelComparison[];
  onSelect: (modelIndex: number) => void;
  onMerge: (selectedIndices: number[]) => void;
}

// レイアウト:
// ┌─────────────────────────────────────────────────────┐
// │ Model Comparison  [Cost Chart] [Quality Chart]      │
// ├──────────┬──────────┬──────────┤                    │
// │ Claude   │ GPT-4o   │ Gemini   │ ← カード横並び     │
// │ $0.012   │ $0.008   │ $0.003   │                    │
// │ 92/100   │ 88/100   │ 85/100   │                    │
// │ [Output] │ [Output] │ [Output] │                    │
// │ [Select] │ [Select] │ [Select] │                    │
// ├──────────┴──────────┴──────────┤                    │
// │ [Merge Selected]  [Auto Pick]  │                    │
// └────────────────────────────────┘                    │
```

### API エンドポイント

```
POST /api/v1/runs/{runId}/select-model
  Body: { "model_index": 0, "rationale": "..." }

GET  /api/v1/runs/{runId}/comparisons
  Response: { "comparisons": [...], "recommended_index": 0 }
```

---

## 2. デザインパターン比較機能

### 設計方針

マルチモデル並行実行と同じfan-out/fan-inメカニズムを再利用し、
単一モデルに対して異なるプロンプトバリエーション(テンプレート)を並行送信する。

### バックエンド設計

```python
# src/pylon/evaluation/design_variants.py (新規)
@dataclass
class DesignVariant:
    variant_id: str
    label: str          # "Minimal", "Dashboard-heavy", "Mobile-first"
    prompt_modifier: str # プロンプト修飾語
    constraints: dict    # { "style": "minimal", "nav": "bottom-tab" }

class DesignVariantGenerator:
    VARIANT_TEMPLATES = [
        DesignVariant("minimal", "Minimalist", "極限まで要素を削ぎ落とし...", {}),
        DesignVariant("dashboard", "Dashboard-centric", "データ密度の高い...", {}),
        DesignVariant("mobile", "Mobile-first", "モバイル体験を最優先に...", {}),
        DesignVariant("conversational", "Conversational UI", "チャット型...", {}),
    ]

    async def generate_variants(
        self,
        base_spec: str,
        variant_count: int = 3,
        model: str = "anthropic/claude-sonnet-4",
    ) -> list[DesignOutput]:
        """1つの要件から複数のデザイン案を生成"""
```

### マージ機能

```python
# src/pylon/evaluation/design_merger.py (新規)
class DesignMerger:
    async def merge(
        self,
        variants: list[DesignOutput],
        selected_aspects: dict[str, int],  # {"navigation": 0, "layout": 2, "color": 1}
        model: str = "anthropic/claude-sonnet-4",
    ) -> DesignOutput:
        """複数案の良い部分を組み合わせたハイブリッド案を生成"""
```

### DAGノード定義

```
                    ┌───────────────────────┐
                    │    generate-variants   │
                    │  (parallel-model)      │
                    │  同一モデル×3テンプレ    │
                    └───┬──────┬──────┬─────┘
                        │      │      │
                   ┌────▼──┐┌──▼───┐┌─▼─────┐
                   │Minimal││Dash  ││Mobile  │
                   └──┬────┘└──┬───┘└──┬─────┘
                      │        │       │
                    ┌─▼────────▼───────▼──┐
                    │   compare-designs    │
                    │ (waiting_selection)  │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ merge-or-select     │
                    │ (router)            │
                    ├──────────┬──────────┤
                    │ select   │ merge    │
                    └────┬─────┘────┬─────┘
                         │          │
                  ┌──────▼──┐  ┌───▼──────┐
                  │ use-as-is│  │merge-best│
                  └──────┬──┘  └───┬──────┘
                         │         │
                    ┌────▼─────────▼───┐
                    │   next-phase     │
                    └──────────────────┘
```

### フロントエンド設計

```
src/components/design/
  DesignComparisonView.tsx   # side-by-side比較(最大4案)
  DesignPreviewCard.tsx      # 各案のプレビュー+メタ情報
  AspectSelector.tsx         # 案ごとに「どの部分を採用するか」選択
  MergeConfigurator.tsx      # マージ設定UI
```

```typescript
// src/components/design/DesignComparisonView.tsx
// レイアウト:
// ┌──────────────────────────────────────────┐
// │ Design Variants (3 options)              │
// ├────────────┬────────────┬────────────────┤
// │ [Preview]  │ [Preview]  │ [Preview]      │
// │ Minimal    │ Dashboard  │ Mobile-first   │
// │            │            │                │
// │ Nav: ○     │ Nav: ●     │ Nav: ○         │
// │ Layout: ○  │ Layout: ○  │ Layout: ●      │
// │ Color: ●   │ Color: ○   │ Color: ○       │
// ├────────────┴────────────┴────────────────┤
// │ [Select #1]  [Merge Selected Aspects]    │
// └──────────────────────────────────────────┘
```

---

## 3. ドラフト→承認→確定のステート管理

### 設計方針

既存の `StateMachine` と `ApprovalManager` を拡張し、
成果物単位でドラフト/レビュー中/承認済み/確定のライフサイクルを管理する。

### ステートマシン定義

```
                ┌─────────┐
                │  draft   │ ← 初期状態
                └────┬─────┘
                     │ submit_for_review
                ┌────▼─────┐
                │ reviewing │ ← レビュアーに通知
                └────┬─────┘
                     │
            ┌────────┼────────┐
            │        │        │
     ┌──────▼──┐ ┌───▼────┐ ┌▼───────────┐
     │approved │ │rejected│ │revision_req│
     └────┬────┘ └───┬────┘ └─────┬──────┘
          │          │            │
     ┌────▼────┐     │       ┌───▼───┐
     │finalized│     │       │ draft │ ← 修正して再提出
     └────┬────┘     │       └───────┘
          │          │
     ┌────▼────┐ ┌───▼────┐
     │published│ │archived│
     └─────────┘ └────────┘
```

### バックエンド設計

```python
# src/pylon/artifacts/lifecycle.py (新規)
from enum import Enum
from pylon.state.machine import StateMachine, StateMachineConfig

class ArtifactStatus(str, Enum):
    DRAFT = "draft"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"
    FINALIZED = "finalized"
    PUBLISHED = "published"
    ARCHIVED = "archived"

@dataclass
class ArtifactVersion:
    version_id: str          # uuid
    artifact_id: str
    version_number: int      # 1, 2, 3...
    content: dict[str, Any]  # 成果物の実データ
    status: ArtifactStatus
    created_at: datetime
    created_by: str          # agent_id or user_id
    parent_version_id: str | None  # ロールバック元

@dataclass
class Artifact:
    artifact_id: str
    workflow_run_id: str
    phase: str               # "research", "planning", "development"
    artifact_type: str       # "ux_analysis", "build_plan", "code", "design"
    current_version: int
    versions: list[ArtifactVersion]
    status: ArtifactStatus

class ArtifactLifecycleManager:
    def __init__(self, approval_manager: ApprovalManager):
        self._approval_manager = approval_manager
        self._artifacts: dict[str, Artifact] = {}

    def create_draft(self, run_id: str, phase: str, content: dict) -> Artifact:
        """新規ドラフト作成"""

    def submit_for_review(self, artifact_id: str) -> None:
        """レビュー提出 → ApprovalManager経由で通知"""

    def approve(self, artifact_id: str, reviewer_id: str) -> None:
        """承認 → finalized可能に"""

    def reject(self, artifact_id: str, reviewer_id: str, reason: str) -> None:
        """却下 → archived"""

    def request_revision(self, artifact_id: str, feedback: str) -> None:
        """修正依頼 → draft状態に戻し、feedbackをstateに格納"""

    def finalize(self, artifact_id: str) -> None:
        """確定 → 以後の変更はnew version必須"""

    def rollback(self, artifact_id: str, target_version: int) -> None:
        """指定バージョンにロールバック"""
```

### バージョニング戦略

```
Artifact "ux-analysis-001"
  ├── v1 (draft)     → submitted → approved → finalized
  ├── v2 (draft)     → submitted → revision_requested → v3
  └── v3 (draft)     → submitted → approved → finalized → published
```

- 各バージョンはイミュータブル（上書きしない）
- ロールバックは「過去バージョンのcontentをコピーして新バージョン作成」
- finalized以降の変更は新バージョンの作成が必須

### API エンドポイント

```
POST   /api/v1/artifacts                          # ドラフト作成
GET    /api/v1/artifacts/{id}                      # 取得（全バージョン含む）
GET    /api/v1/artifacts/{id}/versions/{version}   # 特定バージョン取得
POST   /api/v1/artifacts/{id}/submit               # レビュー提出
POST   /api/v1/artifacts/{id}/approve              # 承認
POST   /api/v1/artifacts/{id}/reject               # 却下
POST   /api/v1/artifacts/{id}/request-revision     # 修正依頼
POST   /api/v1/artifacts/{id}/finalize             # 確定
POST   /api/v1/artifacts/{id}/rollback             # ロールバック
GET    /api/v1/artifacts/{id}/diff?from=1&to=3     # バージョン間diff
```

### フロントエンド設計

```
src/components/artifacts/
  ArtifactTimeline.tsx       # バージョン履歴タイムライン
  ArtifactStatusBadge.tsx    # ステータスバッジ(色分け)
  ReviewPanel.tsx            # レビュー・承認・却下UI
  VersionDiff.tsx            # バージョン間diff表示
  RollbackDialog.tsx         # ロールバック確認ダイアログ
```

```typescript
// src/components/artifacts/ArtifactTimeline.tsx
// レイアウト:
// ┌─────────────────────────────────────────┐
// │ UX Analysis  [FINALIZED]                │
// │                                          │
// │ v3 ● ── 2026-03-09 14:30  [Current]     │
// │    │    Approved by @reviewer            │
// │ v2 ○ ── 2026-03-09 13:00  [Superseded]  │
// │    │    Revision requested: "Add JTBD"   │
// │ v1 ○ ── 2026-03-09 11:00  [Superseded]  │
// │         Initial draft                    │
// │                                          │
// │ [View Diff v2→v3]  [Rollback to v2]     │
// └─────────────────────────────────────────┘
```

---

## 4. ワークフローDAG設計: 調査→企画→承認→開発→デプロイ→更新

### 完全DAGグラフ

```
START
  │
  ▼
┌────────────────────┐
│ 1. research        │  UX分析 + 競合調査
│    (agent)         │  agent: ux-analyst
│    parallel-model  │  出力: analysis, personas, kano
└────────┬───────────┘
         │ artifact: research-draft
         ▼
┌────────────────────┐
│ 2. research-review │  研究結果のレビュー
│    (approval-gate) │  人間が承認/修正依頼
└────┬─────────┬─────┘
     │approved  │revision
     ▼          ▼
     │   ┌──────────────┐
     │   │ 2b. research │ ← ループバック (max 3回)
     │   │    -revise   │
     │   └──────┬───────┘
     │          │
     ◄──────────┘
     │
     ▼
┌────────────────────────────┐
│ 3. ideation                │  要件から複数デザイン案生成
│    (parallel-model)        │  fan-out: 3バリアント
│    models: same×3 template │
└────────┬───────────────────┘
         │ artifacts: design-variant-{1,2,3}
         ▼
┌────────────────────┐
│ 4. design-select   │  人間がデザイン案を選択/マージ
│    (approval-gate) │
└────┬───────────────┘
     │selected / merged
     ▼
┌────────────────────┐
│ 5. planning        │  実装計画策定
│    (agent)         │  agent: architect
│    入力: selected   │  出力: build_plan, milestones
│    design + spec   │
└────────┬───────────┘
         │ artifact: plan-draft
         ▼
┌────────────────────┐
│ 6. plan-review     │  計画のレビュー
│    (approval-gate) │
└────┬─────────┬─────┘
     │approved  │revision
     ▼          ▼ (→ planning に戻る)
     │
     ▼
┌────────────────────┐
│ 7. development     │  コード生成
│    (agent)         │  agent: builder
│    optional:       │  入力: plan + design
│    parallel-model  │  出力: code
└────────┬───────────┘
         │
         ▼
┌────────────────────┐
│ 8. code-review     │  コードレビュー (ループ)
│    (loop)          │  agent: reviewer
│    max_iter: 5     │  criterion: all_milestones_met
│    threshold: 1.0  │
└────┬─────────┬─────┘
     │pass      │fail (→ development に戻る)
     ▼          │
     │◄─────────┘
     │
     ▼
┌────────────────────┐
│ 9. final-approval  │  最終承認
│    (approval-gate) │  人間が最終確認
└────┬─────────┬─────┘
     │approved  │rejected
     ▼          ▼
┌──────────┐  ┌─────────┐
│10. deploy│  │ archived │
│  (agent) │  └─────────┘
└────┬─────┘
     │
     ▼
┌────────────────────┐
│ 11. monitor        │  デプロイ後モニタリング
│    (loop)          │  定期的にメトリクス収集
│    criterion:      │  ユーザーフィードバック
│    update_required │
└────┬─────────┬─────┘
     │stable    │update_needed
     ▼          ▼
   END    ┌──────────────┐
          │ 12. update   │  改善サイクル
          │ (subgraph)   │  → planning に戻る
          └──────────────┘
```

### PylonProject YAML DSL定義

```yaml
version: "1"
name: "product-lifecycle"
description: "調査→企画→承認→開発→デプロイ→更新の一気通貫ワークフロー"

agents:
  ux-analyst:
    model: anthropic/claude-sonnet-4
    role: "UX/市場調査アナリスト"
    autonomy: A2
    tools: []
    sandbox: gvisor

  architect:
    model: anthropic/claude-sonnet-4
    role: "ソフトウェアアーキテクト"
    autonomy: A2
    tools: []
    sandbox: gvisor

  builder:
    model: anthropic/claude-sonnet-4
    role: "フルスタック開発者"
    autonomy: A3
    tools: [file-write, shell]
    sandbox: docker

  reviewer:
    model: anthropic/claude-sonnet-4
    role: "QAレビュアー"
    autonomy: A2
    tools: []
    sandbox: gvisor

  deployer:
    model: anthropic/claude-sonnet-4
    role: "デプロイメントエンジニア"
    autonomy: A3
    tools: [shell, file-write]
    sandbox: docker

workflow:
  type: graph
  nodes:
    # Phase 1: 調査
    research:
      agent: ux-analyst
      node_type: agent
      next:
        - target: research-review
    research-review:
      agent: ux-analyst
      node_type: agent  # ApprovalManager が介在
      next:
        - target: ideation
          condition: "state.research_approved == true"
        - target: research
          condition: "state.research_approved == false"

    # Phase 2: デザイン案生成・選択
    ideation:
      agent: ux-analyst
      node_type: agent  # parallel-model 拡張
      next:
        - target: design-select
    design-select:
      agent: ux-analyst
      node_type: agent  # 人間の選択待ち
      next:
        - target: planning

    # Phase 3: 計画
    planning:
      agent: architect
      node_type: agent
      next:
        - target: plan-review
    plan-review:
      agent: architect
      node_type: agent
      next:
        - target: development
          condition: "state.plan_approved == true"
        - target: planning
          condition: "state.plan_approved == false"

    # Phase 4: 開発
    development:
      agent: builder
      node_type: agent
      next:
        - target: code-review
    code-review:
      agent: reviewer
      node_type: loop
      loop_max_iterations: 5
      loop_criterion: state_value
      loop_threshold: 1.0
      loop_metadata:
        state_key: all_milestones_met
        true_value: true
      next: final-approval

    # Phase 5: 最終承認・デプロイ
    final-approval:
      agent: reviewer
      node_type: agent
      next:
        - target: deploy
          condition: "state.final_approved == true"
        - target: END
          condition: "state.final_approved == false"
    deploy:
      agent: deployer
      node_type: agent
      next: END

goal:
  objective: "ユーザー要件から完成プロダクトまでを自律的に推進する"
  success_criteria:
    - type: milestone_completion
      threshold: 1.0
      rubric: "全マイルストーンが達成されていること"
    - type: quality_gate
      threshold: 0.8
      rubric: "コードレビューの品質スコアが0.8以上"
  constraints:
    max_iterations: 20
    max_cost_usd: 50.0
    timeout: 4h
    max_replans: 3
  failure_policy: escalate

policy:
  max_cost_usd: 50.0
  max_duration: 4h
  require_approval_above: A3
```

### 各ノードの入出力仕様

```
Node              | 入力                              | 出力
──────────────────┼───────────────────────────────────┼──────────────────────────────
research          | spec                              | analysis, personas, kano, user_stories
research-review   | analysis                          | research_approved, revision_feedback
ideation          | analysis, spec                    | design_variants[] (3案)
design-select     | design_variants                   | selected_design, merge_config?
planning          | selected_design, analysis, spec   | build_plan, milestones[]
plan-review       | build_plan                        | plan_approved, revision_feedback
development       | build_plan, selected_design, spec | code, generated_file
code-review       | code, milestones                  | all_milestones_met, quality_score, feedback
final-approval    | code, quality_score, cost         | final_approved
deploy            | code, build_plan                  | deploy_url, deploy_status
```

---

## 5. フロントエンドコンポーネント設計

### ディレクトリ構造

```
src/
├── pages/
│   ├── Studio.tsx                # 既存: チャットUI
│   ├── ProductLifecycle.tsx      # 新規: 一気通貫ビュー
│   └── UXAnalysis.tsx            # 既存: UX分析ビュー
│
├── components/
│   ├── lifecycle/                # フェーズ管理
│   │   ├── PhaseNavigator.tsx    # フェーズ間ナビゲーション
│   │   ├── PhaseCard.tsx         # 各フェーズの状態カード
│   │   └── WorkflowProgress.tsx  # 全体進捗バー
│   │
│   ├── comparison/               # 比較系 (Section 1, 2 共用)
│   │   ├── ModelComparisonPanel.tsx
│   │   ├── ModelResponseCard.tsx
│   │   ├── CostQualityChart.tsx
│   │   └── ModelSelector.tsx
│   │
│   ├── design/                   # デザイン比較 (Section 2)
│   │   ├── DesignComparisonView.tsx
│   │   ├── DesignPreviewCard.tsx
│   │   ├── AspectSelector.tsx
│   │   └── MergeConfigurator.tsx
│   │
│   ├── artifacts/                # 成果物管理 (Section 3)
│   │   ├── ArtifactTimeline.tsx
│   │   ├── ArtifactStatusBadge.tsx
│   │   ├── ReviewPanel.tsx
│   │   ├── VersionDiff.tsx
│   │   └── RollbackDialog.tsx
│   │
│   └── shared/                   # 共通
│       ├── DiffViewer.tsx        # 汎用diff表示
│       ├── CodeEditor.tsx        # コード編集(read-only可)
│       ├── PreviewFrame.tsx      # iframe sandboxプレビュー
│       └── CostIndicator.tsx     # コスト表示
│
├── hooks/
│   ├── useArtifact.ts            # 成果物CRUD
│   ├── useComparison.ts          # 比較結果の取得・選択
│   ├── usePhaseNavigation.ts     # フェーズ間遷移
│   └── useWorkflowProgress.ts    # 進捗ポーリング
│
├── api/
│   ├── artifacts.ts              # 成果物API
│   ├── comparisons.ts            # 比較API
│   └── lifecycle.ts              # ライフサイクルAPI
│
└── types/
    ├── artifact.ts               # 成果物型定義
    ├── comparison.ts             # 比較型定義
    └── lifecycle.ts              # ライフサイクル型定義
```

### ステート管理パターン

```typescript
// src/hooks/useWorkflowProgress.ts
// TanStack Query でサーバー状態をポーリング + ローカルUIステートは useState

interface WorkflowProgressState {
  currentPhase: Phase;
  phases: PhaseStatus[];
  artifacts: Record<string, Artifact>;
  pendingActions: PendingAction[];  // 人間の操作待ち
}

type Phase =
  | "research"
  | "ideation"
  | "planning"
  | "development"
  | "review"
  | "approval"
  | "deploy";

interface PhaseStatus {
  phase: Phase;
  status: "pending" | "active" | "waiting_input" | "completed" | "failed";
  artifactId: string | null;
  startedAt: string | null;
  completedAt: string | null;
  cost: number;
}

// 使用例:
function useWorkflowProgress(runId: string) {
  return useQuery({
    queryKey: ["workflow-progress", runId],
    queryFn: () => apiFetch<WorkflowProgressState>(
      `/api/v1/runs/${runId}/progress`
    ),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 2000;
      const active = data.phases.some(p =>
        p.status === "active" || p.status === "waiting_input"
      );
      return active ? 2000 : false;
    },
  });
}
```

### ProductLifecycle ページ構成

```typescript
// src/pages/ProductLifecycle.tsx
// レイアウト:
//
// ┌──────────────────────────────────────────────────────────┐
// │ Product Lifecycle                        [$2.34 total]   │
// ├──────────────────────────────────────────────────────────┤
// │ [Research]→[Ideation]→[Planning]→[Dev]→[Review]→[Deploy]│
// │     ●          ●         ◐         ○       ○       ○    │
// │  completed   completed  active   pending pending pending │
// ├──────────────────────────────────────────────────────────┤
// │                                                          │
// │  ┌─ Active Phase: Planning ──────────────────────────┐   │
// │  │                                                    │   │
// │  │  [Artifact: build-plan v2]  [REVIEWING]            │   │
// │  │                                                    │   │
// │  │  ┌─────────────────────────────────────────────┐   │   │
// │  │  │  (PhaseContent - 各フェーズ固有UI)            │   │   │
// │  │  │  Planning: 計画内容 + マイルストーン一覧      │   │   │
// │  │  │  Research: 分析結果 + ペルソナカード          │   │   │
// │  │  │  Ideation: デザイン比較パネル                 │   │   │
// │  │  │  Development: コードプレビュー               │   │   │
// │  │  └─────────────────────────────────────────────┘   │   │
// │  │                                                    │   │
// │  │  [Approve]  [Request Revision]  [Reject]           │   │
// │  └────────────────────────────────────────────────────┘   │
// │                                                          │
// │  ┌─ Version History ─────────────────────────────────┐   │
// │  │  (ArtifactTimeline)                                │   │
// │  └───────────────────────────────────────────────────┘   │
// └──────────────────────────────────────────────────────────┘

export function ProductLifecycle() {
  const { runId } = useParams();
  const progress = useWorkflowProgress(runId!);
  const [selectedPhase, setSelectedPhase] = useState<Phase | null>(null);

  const activePhase = selectedPhase
    ?? progress.data?.phases.find(p => p.status === "active" || p.status === "waiting_input")?.phase
    ?? progress.data?.currentPhase;

  return (
    <div className="flex h-full flex-col">
      <WorkflowProgress
        phases={progress.data?.phases ?? []}
        onPhaseClick={setSelectedPhase}
      />
      <div className="flex-1 overflow-auto p-6">
        <PhaseContent
          phase={activePhase}
          artifactId={...}
          runId={runId}
        />
      </div>
    </div>
  );
}
```

### 各フェーズ固有コンポーネント

| フェーズ | コンポーネント | 主な機能 |
|----------|---------------|----------|
| Research | `ResearchPhaseContent` | ペルソナカード、KANO図、ジャーニーマップ (既存UXAnalysis.tsxを再利用) |
| Ideation | `IdeationPhaseContent` | `DesignComparisonView` + `MergeConfigurator` |
| Planning | `PlanningPhaseContent` | マイルストーン一覧、技術スタック表、コンポーネント図 |
| Development | `DevelopmentPhaseContent` | コードプレビュー、`ModelComparisonPanel`(マルチモデル時) |
| Review | `ReviewPhaseContent` | マイルストーン達成状況、品質スコア、フィードバック編集 |
| Approval | `ApprovalPhaseContent` | 全成果物サマリー、コスト合計、最終承認ボタン |
| Deploy | `DeployPhaseContent` | デプロイ状況、URL、モニタリングダッシュボード |

### ルーティング追加

```typescript
// src/App.tsx に追加
<Route path="p/:projectSlug">
  {/* 既存 */}
  <Route path="studio" element={<Studio />} />
  <Route path="ux-analysis" element={<UXAnalysis />} />
  {/* 新規 */}
  <Route path="lifecycle" element={<ProductLifecycle />} />
  <Route path="lifecycle/:runId" element={<ProductLifecycle />} />
  <Route path="lifecycle/:runId/compare" element={<ComparisonView />} />
  <Route path="artifacts/:artifactId" element={<ArtifactDetail />} />
</Route>
```

---

## 技術的トレードオフ

### 採用した選択

| 項目 | 選択 | 理由 |
|------|------|------|
| マルチモデル | fan-out/fan-in (既存DAG拡張) | 新規エンジン不要、既存のGraphExecutorのParallel実行を再利用 |
| ステート管理 | サーバー側StateMachine + クライアントTanStack Query | 信頼できるソース(server)を一元化、UIはポーリングで追従 |
| バージョニング | append-only (イミュータブル) | ロールバックが安全、監査ログとして機能 |
| 比較UI | side-by-side (最大4パネル) | UX調査で3-4案が認知負荷の限界と判明 |
| 承認フロー | 既存ApprovalManager拡張 | 新規の承認基盤不要、既にAgent承認の仕組みがある |

### 棄却した代替案

| 代替案 | 棄却理由 |
|--------|----------|
| 独立したオーケストレーションサービス | 複雑度増大、既存GraphExecutorで十分 |
| クライアント側ステート管理(Zustand等) | サーバーが真のソース、二重管理のリスク |
| リアルタイム(WebSocket) | ポーリング2秒で十分、WebSocket基盤追加のコスト不要 |
| 全フェーズ自動(人間介在なし) | 品質保証のため承認ゲートが必須 |

---

## 実装優先度

| 優先度 | 項目 | 依存関係 | 見積もり |
|--------|------|----------|----------|
| P0 | ドラフト→承認→確定ステート管理 | 既存StateMachine, ApprovalManager | 3-5日 |
| P0 | 一気通貫DAGワークフロー定義 | P0ステート管理 | 3-5日 |
| P1 | マルチモデル並行実行 | ProviderRegistry拡張 | 5-7日 |
| P1 | ProductLifecycleページ + PhaseNavigator | P0 DAG | 5-7日 |
| P2 | デザインパターン比較 | P1マルチモデル | 3-5日 |
| P2 | 比較・マージUI | P1, P2バックエンド | 3-5日 |
| P3 | モニタリング・更新ループ | P0全体 | 5-7日 |

---

## リスクと緩和策

| リスク | 影響 | 緩和策 |
|--------|------|--------|
| マルチモデルAPIコスト爆発 | 高 | cost_limit_per_model + policy.max_cost_usd で上限制御 |
| 承認ゲートでのブロッキング | 中 | タイムアウト + 自動承認オプション (autonomy A4) |
| 長時間ワークフローのステート喪失 | 高 | CheckpointRepository による定期チェックポイント (既存) |
| fan-out時の部分失敗 | 中 | return_exceptions=True + フォールバック戦略 |
| UIの認知負荷過多 | 中 | PhaseNavigator で1フェーズずつ表示、全体は進捗バーで俯瞰 |

## 関連ADR

- ADR-001: Graph Engine Self-Implementation
- ADR-004: Autonomy Ladder
- ADR-007: Deterministic DAG Execution Semantics
- ADR-009: Runtime-Centered Bounded Autonomy
