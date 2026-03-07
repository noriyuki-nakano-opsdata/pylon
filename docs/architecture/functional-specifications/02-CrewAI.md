# 📘 CrewAI 機能仕様書

## プロジェクト概要
**CrewAI** は、自律的な AI エージェントのオーケストレーションのための軽量で高速な Python フレームワークです。LangChain など他のフレームワークに依存せず、完全に独自に開発されています。

### 基本情報
- **GitHub**: `https://github.com/crewAIInc/crewai`
- **GitHub Stars**: ~44,700
- **ライセンス**: MIT
- **Python バージョン**: >=3.10 <3.14
- **依存管理**: UV (pip の代替)

---

## 主な機能・特徴

### 1. アーキテクチャコンセプト

#### Crews（チーム型）vs Flows（フロー型）
CrewAI は 2 つのアーキテクチャを提供：

**Crews**:
- 自律的な AI エージェントチーム
- タスクの委任と協力支援
- ロールベースの自己組織化
- 動的な意思決定能力

**Flows**:
- 企業向け・生産環境用アーキテクチャ
- イベント駆動型制御
- 詳細な実行パス管理
- クリーンな状態管理

### 2. コアコンポーネント

#### Agent（エージェント）
```python
from crewai import Agent

agent = Agent(
    role="Data Researcher",
    goal="Uncover cutting-edge developments",
    backstory="You're a seasoned researcher..."
)
```

#### Task（タスク）
```python
from crewai import Task

task = Task(
    description="Conduct thorough research about {topic}",
    expected_output="A list with 10 bullet points...",
    agent=agent
)
```

#### Crew（チーム）
```python
from crewai import Crew, Process

crew = Crew(
    agents=[analyst, researcher],
    tasks=[analysis_task, research_task],
    process=Process.sequential  # sequential | hierarchical
)
```

### 3. プロセスタイプ

#### Sequential（順次）
- タスクが順番に実行される
- シンプルなワークフロー対応
- リソース使用量少

#### Hierarchical（階層的）
- マネージャーエージェントによる管理
- プランニングと執行の分離
- デlegation と検証機能

---

## 使用例（簡易）

```python
from crewai import Agent, Task, Crew, Process

# エージェント定義
researcher = Agent(
    role="Senior Data Researcher",
    goal="Uncover cutting-edge developments in {topic}",
    backstory="You're a seasoned researcher..."
)

reporting_analyst = Agent(
    role="Reporting Analyst",
    goal="Create detailed reports based on {topic} data",
    backstory="You're a meticulous analyst..."
)

# タスク定義
research_task = Task(
    description="Conduct thorough research about {topic}",
    expected_output="A list with 10 bullet points...",
    agent=researcher
)

reporting_task = Task(
    description="Review context and expand each topic into full section",
    expected_output="Fully fledged reports with main topics...",
    agent=reporting_analyst,
    output_file='report.md'
)

# クルー（チーム）作成
crew = Crew(
    agents=[researcher, reporting_analyst],
    tasks=[research_task, reporting_task],
    process=Process.sequential,
    verbose=True
)

# 実行
result = crew.kickoff(inputs={'topic': 'AI Agents'})
```

---

## メリット・デメリット

### メリット✅
- **高速実行**：5.76 倍の性能向上（LangGraph vs）
- **独立性**：LangChain に依存しないため軽量
- **柔軟性**：高レベルから低レベルまで完全カスタマイズ可能
- **企業対応**：AMP スイートによる可観測性、セキュリティ機能
- **コミュニティ**：10 万人以上の認定開発者
- **フロー制御**：Crews と Flows の組み合わせで複雑な自動化

### デメリット❌
- **YAML 設定の複雑さ**：大規模プロジェクトでは設定が複雑になる
- **外部ツール依存**：SerperDevTool など一部の機能は API キーが必要
- **バージョン管理**：UV と pip の両方に対応（移行学習曲線）

---

## エコシステム

### CrewAI AMP スイート（企業向け）
- **Crew Control Plane**：リアルタイムモニタリング
- **可観測性**：メトリクス、ログ、トレース
- **統合機能**：既存システムとのシームレス接続
- **セキュリティ**：堅牢なセキュリティとコンプライアンス機能
- **サポート**：24/7 エンタープライズ支援

### 学習リソース
- [learn.crewai.com](https://learn.crewai.com) — コース提供
- [community.crewai.com](https://community.crewai.com) — フォーラム
- [blog.crewai.com](https://blog.crewai.com) — ブログ

---

## LLM 接続オプション

CrewAI は複数の言語モデルを支持：
- OpenAI API（デフォルト）
- Anthropic, Cohere など他社の API
- ローカルモデル：Ollama、LM Studio を使用可能
- カスタムトレーニング済みモデルの統合

---

## まとめ
CrewAI は自律性と制約の最適なバランスを提供するフレームワークです。特に企業の自動化プロセスに最適で、Crews と Flows の組み合わせにより、自律的かつ詳細な制御が可能です。
