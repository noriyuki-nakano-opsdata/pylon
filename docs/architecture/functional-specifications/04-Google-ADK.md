# 📘 Google Agent Development Kit (ADK) 機能仕様書

## プロジェクト概要
**Agent Development Kit (ADK)** は、Google が開発したオープンソースの Python トリキットで、ソフトウェア開発の原則を AI エージェントの構築に適用します。複雑なシステムから単純なタスクまで、エージェントワークフローの構築、デプロイ、オーケストレーションを簡略化します。

### 基本情報
- **GitHub**: `https://github.com/google/adk-python`
- **PyPI**: [google-adk](https://pypi.org/project/google-adk/)
- **ライセンス**: Apache 2.0
- **Python バージョン**: >=3.10
- **リリースサイクル**: 約 2 週間に 1 回（ビジュアルな更新）
- **主要機能**: Flexibility and Control（柔軟性と制御）

---

## 主な機能・特徴

### 1. アーキテクチャコンセプト

#### Flexible & Modular（柔軟でモジュール化）
ADK は、以下のような柔軟性を提供：
- **モデル非依存**：Gemini に最適化しつつ、他社モデルとの互換性
- **デプロイ非依存**：Cloud Run、Vertex AI Agent Engine などどこでも展開可能
- **コード第一開発**：Python で直接定義、高いテスタビリティとバージョン管理
- **エージェント設定**：コードなしでエージェントを構築（Agent Config）

### 2. コアコンポーネント

#### Agent クラス
```python
from google.adk.agents import Agent, LlmAgent

# シンプルなエージェント
root_agent = Agent(
 name="search_assistant",
 model="gemini-2.5-flash",
 instruction="You are a helpful assistant. Answer user questions using Google Search when needed.",
 description="An assistant that can search the web.",
 tools=[google_search]
)

# マルチエージェントシステム
greeter = LlmAgent(name="greeter", model="gemini-2.5-flash", ...)
task_executor = LlmAgent(name="task_executor", model="gemini-2.5-flash", ...)

coordinator = LlmAgent(
 name="Coordinator",
 model="gemini-2.5-flash",
 description="I coordinate greetings and tasks.",
 sub_agents=[greeter, task_executor]
)
```

#### Tool Ecosystem（リッチなツール）
- **pre-built tools**：既製の Google 検索など
- **custom functions**：独自関数との連携
- **OpenAPI specs**：API デファインの自動連携
- **MCP tools**：Model Context Protocol の統合

### 3. 主要機能セット

#### Service Registration（サービス登録）
```python
# Custom service registration
class MyService(ADKService):
    async def run(self, context: Context) -> Any:
        return await self.task.run()
```

#### Rewind Functionality（巻き戻し機能）
セッションを以前の呼び出しに巻き戻す機能：
```python
# Rewind a session to before a previous invocation
await agent_session.rewind(
    last_agent_response_id="...",
    context_window_limitation_policy=None
)
```

#### Code Executor（コード実行）
```python
from google.adk.agent_engine import AgentEngineSandboxCodeExecutor

sandbox_code_executor = AgentEngineSandboxCodeExecutor(...)
```

#### Tool Confirmation Flow（ツール確認フロー：HITL）
ツール実行を明示的な確認でガード：
- 人間によるインタビューの導入
- カスタム入力オプション
- セキュリティ強化

---

## 開発者体験（DX）

### Development UI（開発者向け UI）
- **test, evaluate, debug**：エージェントのテスト、評価、デバッグ支援
- **visualize**：対話フローの視覚化
- **showcase**：デモ用プレゼンテーション機能

```bash
adk eval samples_for_testing/hello_world samples_for_testing/hello_world/hello_world_eval_set_001.evalset.json
```

### lms.txt と lms-full.txt
LLM にコンテキストを提供するファイル：
- `llms.txt` — 要約版（短縮）
- `llms-full.txt` — 完全情報版

---

## デプロイメント

### Cloud Run でコンテナ化
```bash
# Containerize agent docker build -f Dockerfile -t adk-app .
docker push gcr.io/PROJECT_ID/adk-app
gcloud run deploy --image=gcr.io/PROJECT_ID/adk-app
```

### Vertex AI Agent Engine
スケール対応：
- **auto-scaling**：需要に応じてスケーリング
- **high availability**：高可用性
- **low latency**：低遅延設計

---

## エコシステム

### Community Contributions
ADK のコミュニティコントリビューション：
- [adk-python-community](https://github.com/google/adk-python-community)
- サードパーティツール
- 統合スクリプト
- デプロイメントコード

### ドキュメント
- **[Official Documentation](https://google.github.io/adk-docs)**
- **[Contributing Guide](https://google.github.io/adk-docs/contributing-guide/)**
- **[Examples](https://github.com/google/adk-python/tree/main/samples_for_testing)**

### コミュニティ
- [Google Group](https://groups.google.com/g/adk-community)
- [Slack/Discord（将来的に）]

---

## メリット・デメリット

### メリット✅
1. **Google エコシステムとの統合**：Vertex AI、Cloud Run、BigQuery などのシームレス連携
2. **Model-Agnostic**：Gemini に最適化しつつ、他社モデルとの互換性
3. **Code-First Approach**：Python で直接定義、高いテスタビリティ
4. **Flexible Deployment**：どこでもデプロイ可能（Cloud Run、オンプレミスなど）
5. **Tool Ecosystem**：Google 検索、BigQuery、Firebase などとの連携
6. **Rewind Functionality**：セッションの巻き戻しによる柔軟な制御
7. **Bi-weekly Releases**：約 2 週間に 1 回の頻繁なリリースで最新機能の迅速な提供

### デメリット❌
1. **Google に依存**：一部機能は Google インフラ（Vertex AI、Cloud Run）に依存
2. **初期学習曲線**：モジュール化された設計のため、複雑な概念を理解する必要あり
3. **ツール確認フロー**：HITL が必要な場合、追加の手間が必要
4. **コミュニティの規模**：まだ新しいため、CrewAI や AutoGen に比べてコミュニティ小さい

---

## まとめ
Google ADK は「柔軟性と制御」を重視した、コード第一でモデル非依存のエージェント開発フレームワークです。Google エコシステムとの統合が強みですが、一部機能は Google インフラに依存しています。2 週間に 1 回の頻繁なリリースサイクルにより、最新機能の提供速度が速いです。
