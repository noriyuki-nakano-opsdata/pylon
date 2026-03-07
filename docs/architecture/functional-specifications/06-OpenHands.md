# 📘 OpenHands 機能仕様書

## プロジェクト概要
**OpenHands** は、AI エージェントが自律的にコーディングタスクを実行するプラットフォームです。GitHub リポジトリや Web ブラウザから直接コードを生成・修正・テスト実行し、完全な開発ワークフローを自動化します。

### 基本情報
- **GitHub**: `https://github.com/All-Hands-AI/OpenHands`
- **GitHub Stars**: ~67,300
- **ライセンス**: MIT
- **Python バージョン**: >=3.10
- **主要依存**: pyodide, jinja2, litellm など
- **言語モデル**: OpenAI、Anthropic、Gemini、Llama など全 16 のプロバイダー対応

---

## 主な機能・特徴

### 1. アーキテクチャコンセプト

#### Autonomous Coding Agents（自律的コーディングエージェント）
OpenHands は以下のサイクルを実行：
- **Plan**：タスク理解と計画
- **Execute**：コード生成と修正
- **Test**：テスト実行と検証
- **Refine**：フィードバックからの改善

### 2. コアコンポーネント

#### Agent クラス（AgentEngine）
```python
from openhands.agent_engine import AgentEngine

agent_engine = AgentEngine(
    config=Config(
        max_budget_per_task=5,
        sandbox="docker",
        max_iterations=100
    )
)
```

#### Action Space（行動空間）
- **File Operations**：作成、修正、削除、リネーム
- **Code Editing**：インテリセンス補助、フォーマット
- **Terminal**：コマンド実行、ログ表示
- **Browser**：Web ブラウザ操作
- **Git**：コミット、ブランチ管理

#### Memory System（メモリシステム）
- **短期記憶**：現在のタスク状態
- **長期記憶**：学習済みコードパターン、ベストプラクティス
- **コンテキスト管理**：最大 32k トークンの保持

### 3. プロダクトタイプ

#### 1. GitHub Integration（GitHub 連携）
```python
# GitHub のレポジトリから自動タスク抽出
from openhands.github_api import GitHubAPI

gh = GitHubAPI(token="...")
tasks = gh.get_issues(owner="langchain-ai", repo="langgraph")
```

#### 2. CLI Mode（コマンドラインモード）
```bash
# コマンドラインから動作
openhands --model "gpt-4o" --repo "langchain/langgraph"
```

#### 3. API Mode（API モード）
```python
from openhands.api import create_app, get_agent_response

app = create_app()
agent_response = get_agent_response("...")
```

---

## 使用例（簡易）

```python
from openhands.agent_engine import AgentEngine
from litellm import completion

# エージェント設定
config = Config(
    max_budget_per_task=5,
    sandbox="docker",
    max_iterations=100
)
agent = AgentEngine(config=config)

# タスク実行
task = "Create a Python script that prints Hello World"
response = agent.run(task=task)
print(response.output_text)
# Output: # print('Hello World')
```

---

## メリット・デメリット

### メリット✅
1. **自律的コーディング**：完全な開発ワークフロー自動化
2. **GitHub 連携**：既存プロジェクトへの自動適用
3. **マルチプラットフォーム対応**：Linux、macOS、Windows の全てに対応
4. **大規模コミュニティ**：67,000+ Stars、企業から個人まで幅広く利用
5. **テスト実行機能**：自動テスト生成と実行
6. **レビュー対応**：PR の作成・承認フローの自動化
7. **16+ のモデルプロバイダー対応**：OpenAI、Anthropic、Gemini など全 16 のモデル対応

### デメリット❌
1. **大規模コードベース**：30GB+ の依存関係、インストールに時間がかかる
2. **学習曲線**：自律的エージェントの設計・運用ノウハウが必要
3. **リソース要求高**：Docker コンテナ、メモリ大量消費
4. **プライバシー配慮**：クラウド API へのデフォルト接続
5. **設定複雑度**：環境構築に専門知識が必要

---

## エコシステム

### 関連プロジェクト
- [OpenAgents](https://github.com/All-Hands-AI/OpenAgents)
- [AutoEval](https://github.com/All-Hands-AI/AutoEval)
- [CodeT5-Eval](https://github.com/codeparrot/Codellama)

### ドキュメント
- **[Official Documentation](https://docs.all-hands.dev)**
- **[Quick Start Guide](https://docs.all-hands.dev/getting-started)**
- **[API Reference](https://docs.all-hands.dev/api)**
- **[Examples Gallery](https://github.com/All-Hands-AI/OpenHands/tree/main/examples)**

### コミュニティ
- [GitHub Discussions](https://github.com/All-Hands-AI/OpenHands/discussions)
- [Slack チャンネル](https://all-hands-io.slack.com)
- [Twitter/X](https://twitter.com/openhandsai)

---

## まとめ
OpenHands は「自律的コーディングエージェントプラットフォーム」で、完全な開発ワークフローの自動化を提供します。GitHub 連携と 16+ のモデルプロバイダー対応が強みですが、大規模コードベースとリソース要求が高デメリットです。企業レベルの開発効率化に最適です。
