# 📘 Microsoft Agent Framework (AutoGen) 機能仕様書

## プロジェクト概要
**Microsoft Agent Framework**（正式名称：AutoGen）は、マイクロソフトが開発したマルチエージェントオーケストレーションフレームワークです。対話型で自律的な AI エージェントの作成に特化しています。

### 基本情報
- **GitHub**: `https://github.com/microsoft/autogen`
- **GitHub Stars**: ~54,500
- **ライセンス**: MIT
- **Python バージョン**: >=3.10
- **依存関係**: numpy, openai, langchain など

---

## 主な機能・特徴

### 1. アーキテクチャコンセプト

#### Multi-Agent Chat Systems
AutoGen の核となるのは、複数の AI エージェントが対話しながらタスクを完了するシステムです。

#### エージェントタイプ
- **AssistantAgent**：タスク実行を支援
- **UserProxyAgent**：ユーザー代理として人間と相互作用
- **GroupChatAgent**：グループチャットでの議論管理
- **CodeExecutionAgent**：コード実行機能付き

### 2. コアコンポーネント

#### ConversableAgent クラス
```python
from autogen import ConversableAgent

assistant = ConversableAgent(
    name="assistant",
    llm_config={"config_list": config_list},
    is_termination_msg=lambda x: "terminal" in x["content"],
    human_input_mode="TERMINATE"
)
```

#### GroupChat クラス
```python
from autogen import GroupChat, RoundRobinGroupChat

chat = GroupChat(
    agents=[assistant, user_proxy, ...],
    messages=[...],
    max_round=3,
    allow_adaptive_timeouts=False
)
```

### 3. プロダクトタイプ
- **Chat-Based**：対話ベースの多エージェントシステム
- **Code-Generation**：コード生成特化型
- **Task-Specific**：特定タスク向けカスタマイズ

---

## 使用例（簡易）

```python
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatAgent

# アシスタントエージェント
code_assistant = AssistantAgent(
    name="code_reviewer",
    system_message="You are an expert Python programmer."
)

# ユーザー代理
user_proxy = UserProxyAgent(
    name="user_proxy",
    code_execution_config={"last_n_messages": 3, "work_dir": "paper_code"}
)

# グループチャット
groupchat = GroupChat(
    agents=[code_assistant, user_proxy],
    messages=[],
    max_round=3
)

# グループチャットエージェント
groupchat_agent = GroupChatAgent(
    name="groupchat",
    llm_config={...},
    groupchat=groupchat
)
```

---

## メリット・デメリット

### メリット✅
- **マイクロソフトエコシステム統合**：Azure、GitHub、Visual Studio Code との連携
- **対話型アプローチ**：自然なエージェント間コミュニケーション
- **コード生成能力**：自律的なコードレビューと最適化
- **企業向け機能**：エンタープライズ環境での展開に対応
- **カスタマイズ性**：高度な設定オプション

### デメリット❌
- **リポジトリの頻繁変更**：開発が活発でドキュメント追従が必要
- **複雑な構成**：大型プロジェクトでは設定管理が困難
- **LLM API 依存**：オンプレミス展開が難しい場合がある

---

## エコシステム

### 関連リポジトリ
- [autogen-magentic-one](https://github.com/microsoft/autogen-magentic-one)
- [autogen-bench](https://github.com/microsoft/autogen-bench)：ベンチマークスイート
- [auto-gpts](https://github.com/microsoft/auto-gpts)

### ドキュメント
- [Official Documentation](https://microsoft.github.io/autogen/)
- [Getting Started Guide](https://microsoft.github.io/autogen/docs/)
- [Examples Gallery](https://microsoft.github.io/autogen/docs/getting-started/agent-concepts/)

---

## まとめ
AutoGen は対話型マルチエージェントシステムの構築に特化したフレームワークで、マイクロソフトエコシステムとの統合が強みです。コード生成タスクや複雑な分析タスクに適していますが、設定の頻繁な変更には注意が必要です。
