# Pylon — AIエージェント自律開発プラットフォーム

## 企画概要書 v1.0

---

## 1. コンセプト

### Pylon とは何か

Pylon は、**プロダクトのアイデアからリリースまでを AI エージェントが自律的に遂行する開発プラットフォーム**である。

従来の AI コーディングツールが「開発者の補助」に留まるのに対し、Pylon は市場調査・企画・設計・開発・品質保証・デプロイの全工程を **DAG ベースのワークフローグラフ**で定義し、複数の専門エージェントが並列に実行する。人間はゴールを設定し、承認判断を行い、最終的な品質を担保する**オーケストレーター**の立場をとる。

### 一言で表すと

> 「仕様を入力すれば、プロダクトが出てくる」

---

## 2. 解決する課題

| 課題 | 現状 | Pylon のアプローチ |
|------|------|-------------------|
| 開発リードタイム | アイデア→リリースに数週間〜数ヶ月 | 7フェーズを自律実行、数時間〜数日に短縮 |
| 専門人材の不足 | UXリサーチャー・セキュリティレビュアーなどの確保が困難 | 各専門領域を AI エージェントが担当 |
| 品質のばらつき | レビュー品質が担当者に依存 | GoalSpec → Critic → Verifier の3段階品質保証 |
| コスト予測の困難さ | LLM 利用コストが不透明 | ModelRouter による3段階ルーティング + コスト上限設定 |
| 意思決定の属人化 | 「なぜこの設計にしたか」が残らない | 全フェーズの決定ログ・成果物を自動記録 |

---

## 3. プロダクトライフサイクル — 7フェーズ自律実行

```
Research → Planning → Design → Approval → Development → Deploy → Iterate
```

各フェーズは **DAG (有向非巡回グラフ)** で構成され、並列実行可能なノードは `asyncio.gather()` で同時実行される。

### Research フェーズ — 4並列 + 統合

```
┌─ competitor-analyst ──┐
├─ market-researcher ───┤
├─ user-researcher ─────┤──→ research-synthesizer ──→ END
└─ tech-evaluator ──────┘
```

- 4つの専門エージェントが**異なる LLM プロバイダー**を使い、並列で市場調査を実行
- 調査深度を Quick / Standard / Deep で制御（トークン予算: 2K / 4K / 12K）
- Synthesizer が全結果を統合し、競合・市場規模・技術実現性・ユーザーセグメントの統合レポートを生成

### Planning フェーズ — 4並列 + 統合

```
┌─ persona-builder ─────┐
├─ story-architect ──────┤
├─ feature-analyst ──────┤──→ planning-synthesizer ──→ END
└─ solution-architect ───┘
```

- ペルソナ設計、ユーザージャーニーマップ、KANO分析、IA(情報アーキテクチャ)設計を並列実行
- 出力: ペルソナ、ユーザーストーリー、JTBD、サイトマップ、ユースケースカタログ、デザイントークン、WBS 付き3段階見積（Minimal / Standard / Full）

### Design フェーズ — 3並列 + 評価

```
┌─ claude-designer ─────┐
├─ openai-designer ──────┤──→ design-evaluator ──→ END
└─ gemini-designer ──────┘
```

- 3つの LLM がそれぞれ異なるデザインパターンで UI プロトタイプを生成
- Evaluator が UX品質・コード品質・パフォーマンス・アクセシビリティの4軸で採点

### Approval フェーズ — Human-in-the-Loop

- A3以上のオートノミーレベルでは**人間の承認が必須**
- 承認・却下・修正要求の3アクション
- A4（Full Autonomy）モードでは自動承認が可能

### Development フェーズ — 7ノード DAG

```
planner ──→ ┌─ frontend-builder ─┐──→ integrator ──→ ┌─ qa-engineer ──────┐──→ reviewer ──→ END
            └─ backend-builder ──┘                   └─ security-reviewer ─┘
```

- 計画→フロントエンド/バックエンド並列開発→統合→QA/セキュリティ並列レビュー→リリース判定
- セキュリティレビューは OWASP Top 10 ベース
- Reviewer が QA・セキュリティの結果を統合し、リリースブロッカーの有無を判定

---

## 4. 技術アーキテクチャ

### コアエンジン

| コンポーネント | 役割 |
|---------------|------|
| **GraphExecutor** | DAG のスーパーステップ実行。`asyncio.gather()` による true parallel |
| **CommitEngine** | 並列ノードの状態書き込み衝突を SHA256 ハッシュで検出・防止 |
| **WorkflowGraph** | 複数エントリポイント、join policy (ALL_RESOLVED / ANY / FIRST)、サイクル検出 |
| **LoopNode** | 成功基準 + 閾値 + 最大反復回数による反復改善ループ |

### 自律制御（Autonomy System）

5段階のオートノミーレベルで安全性を担保:

| Level | 名称 | 動作 |
|-------|------|------|
| **A0** | Manual | エージェントが提案、人間が実行 |
| **A1** | Supervised | 各ステップで人間が承認 |
| **A2** | Semi-autonomous | ポリシー範囲内で自律実行 |
| **A3** | Autonomous-guarded | 計画を人間が承認後、実行 |
| **A4** | Fully autonomous | 安全エンベロープ内で完全自律 |

### 品質保証パイプライン

```
GoalSpec（目標定義）
  → Critic（基準ごとの評価）
    → Verifier（統合判定: SUCCESS / REFINE / FAIL）
      → RefinementPolicy（再計画 or エスカレーション）
```

### マルチプロバイダー LLM ルーティング

| Tier | 用途 | 対応プロバイダー |
|------|------|-----------------|
| LIGHTWEIGHT | 簡易変換・分類 | Haiku, GPT-4.1 Nano, Gemini Flash |
| STANDARD | 分析・設計 | Sonnet, GPT-5 Mini, Kimi K2.5, GLM-4 Plus |
| PREMIUM | 複雑な推論 | Opus, GPT-5 |

- コスト上限設定 (`max_cost_usd`) で予算超過を防止
- 各並列ノードが異なるプロバイダーを使用し、API rate limit を分散

### 安全機構

| 機構 | 概要 |
|------|------|
| **Safety Engine** | 入力サニタイズ、出力バリデーション、プロンプトガード |
| **Kill Switch** | 緊急停止機構 |
| **Sandbox** | gvisor ベースのサンドボックス実行 |
| **Bulkhead** | 同時実行数制限（sync / async 両対応） |
| **Capability Control** | エージェントごとのツール・権限制御 |

---

## 5. 差別化ポイント

### vs. GitHub Copilot / Cursor
- Pylon は**コード補完ではなく、プロダクト開発全体**を自律実行する
- Research → Deploy の一気通貫ワークフロー
- 企画（ペルソナ、JTBD、IA）からの一貫した設計根拠

### vs. Devin / OpenHands
- **DAG ベースの並列実行**による高速化（逐次実行ではない）
- **CommitEngine** による並列状態管理の厳密な衝突検出
- **5段階オートノミー**による段階的な自律性制御
- **マルチプロバイダー**対応（5+ LLM プロバイダーを並列活用）

### vs. 従来のプロジェクト管理ツール
- 「管理」ではなく**実行**するプラットフォーム
- 決定ログ・成果物・コスト追跡が全フェーズで自動記録

---

## 6. ユースケース

### ユースケース 1: 新規プロダクト立ち上げ
1. プロダクト概要を入力（例: 「AI エージェント管理ダッシュボード」）
2. A4 モードで自律実行開始
3. Research: 競合5社分析 + 市場規模推定 + 技術実現性評価 → **約2分**
4. Planning: ペルソナ3名 + KANO分析 + WBS見積3プラン → **約3分**
5. Design: 3つのデザイン案を並列生成・評価 → **約5分**
6. 人間が承認判断（Approval）
7. Development: フロント/バック並列開発 + QA + セキュリティレビュー → **約8分**
8. **合計約20分**で調査からプロトタイプ完成

### ユースケース 2: 既存コードの PR レビュー
```yaml
# pylon.yaml — 30行で定義
agents:
  planner:
    model: anthropic/claude-sonnet-4-20250514
    autonomy: A2
    tools: [github-pr-read, file-search]
  reviewer:
    autonomy: A2
    tools: [github-pr-comment]
  approver:
    autonomy: A3  # 人間承認必須
workflow:
  type: graph
  nodes:
    analyze: { agent: planner, next: review }
    review: { agent: reviewer, next: approve }
    approve: { agent: approver, next: END }
```

---

## 7. 技術スタック

| レイヤー | 技術 |
|---------|------|
| Frontend | React 19, TypeScript, Tailwind CSS 4, shadcn/ui, React Query |
| Backend | Python (asyncio), Pylon Core Engine |
| LLM | Anthropic, OpenAI, Google Gemini, Moonshot, ZhipuAI |
| Workflow | GraphExecutor, CommitEngine, WorkflowGraph |
| 品質保証 | GoalSpec, Critic, Verifier, VerificationDisposition |
| 安全性 | Safety Engine, Sandbox (gvisor), Kill Switch, Bulkhead |
| 状態管理 | イベントソーシング, 全フェーズ決定ログ |

---

## 8. 今後の展開

| フェーズ | 内容 |
|---------|------|
| **現在** | 7フェーズ自律実行、マルチプロバイダー並列、DAG ワークフロー |
| **短期** | デザインフェーズの IA 分析統合強化、反復開発ループの自動リプラン |
| **中期** | マルチテナント対応、チーム間承認フロー、カスタムエージェント定義 |
| **長期** | 自己改善型エージェント学習、プロダクト運用データからの自動改善提案 |

---

*Pylon — アイデアをプロダクトにする、AI エージェントの開発工場*
