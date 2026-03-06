# 📘 LangGraph 機能仕様書

## プロジェクト概要
**LangGraph** は、長期実行、状態フルな AI エージェントおよびワークフローを構築・管理・デプロイするためのオーケストレーションフレームワークです。langchain-ai から開発されており、LangChain エコシステムと完全に統合されています。

### 基本情報
- **GitHub**: `https://github.com/langchain-ai/langgraph`
- **GitHub Stars**: ~24,700
- **ライセンス**: MIT
- **Python バージョン**: >=3.10 <3.14
- **依存リポジトリ**: [langgraphjs](https://github.com/langchain-ai/langgraphjs) (JavaScript/TypeScript 版)

---

## 主な機能・特徴

### 1. アーキテクチャコンセプト
- **状態フルエージェント**：短期メモリと長期記憶の両方を持つ真の状態フルエージェントを構築可能
- **永続化の実行**：失敗しても再開可能な長期実行ワークフロー対応
- **ヒューマンインザループ**：実行中いつでも人間による介入・編集が可能
- **詳細なデバッグ**：LangSmith と連携した深い可視化機能
- **プロダクション対応デプロイメント**：スケーラブルな実行環境での展開可能

### 2. コアコンポーネント

#### StateGraph クラス
```python
from langgraph.graph import START, StateGraph
```
- 状態フルグラフの構築に使用
- ノード（処理関数）とエッジを定義
- TypedDict で型付けされた状態管理

#### CompiledGraph
```python
graph.compile().invoke(state)
```
- グラフのコンパイルと実行
- チェックポイント保存/復元対応

### 3. 重要な利点（Benefits）
1. **Long-Running Workflows**：長期にわたるスレッド安全なワークフロー実行
2. **Human-in-the-Loop**：人間による介入を容易にサポート
3. **Comprehensive Memory**：短期・長期記憶の両方を含む完全なメモリ管理
4. **Debugging with LangSmith**：LangSmith と連携した詳細な可視化
5. **Production Deployment**：スケーラブルなプロダクション環境での展開

---

## 使用例（簡易）

```python
from langgraph.graph import START, StateGraph
from typing_extensions import TypedDict

class State(TypedDict):
    text: str


def node_a(state: State) -> dict:
    return {"text": state["text"] + "a"}


def node_b(state: State) -> dict:
    return {"text": state["text"] + "b"}


graph = StateGraph(State)
graph.add_node("node_a", node_a)
graph.add_node("node_b", node_b)
graph.add_edge(START, "node_a")
graph.add_edge("node_a", "node_b")

print(graph.compile().invoke({"text": ""}))
# {'text': 'ab'}
```

---

## エコシステム

### 関連製品
- **LangSmith**：エージェントの評価、可視化、デバッグ支援
- **LangSmith Deployment**：スケーラブルなデプロイメントプラットフォーム
- **LangChain Agents**：`create_agent` を使用したハイアレベルエージェント構築
- **LangGraph Studio**：ビジュアルプロトタイピングツール

### ドキュメントリソース
- [Guides](https://docs.langchain.com/oss/python/langgraph/overview)
- [Reference](https://reference.langchain.com/python/langgraph/)
- [Examples](https://docs.langchain.com/oss/python/langgraph/agentic-rag)
- [LangChain Forum](https://forum.langchain.com/)

---

## API 概要

### メイン関数とメソッド

#### StateGraph クラス
```python
graph = StateGraph(State)
graph.add_node("name", node)
graph.add_edge("from", "to")
graph.set_entry_point("entry")
graph.add_conditional_edges("condition", router, ...)
```

#### 主要メソッド
- `add_node(name: str, func)`：ノードの追加
- `add_edge(from_, to)`：エッジの定義
- `set_entry_point(entry_)`：エントリーポイントの設定
- `compile()`：グラフをコンパイル
- `invoke(state)`：グラフへの状態の適用と実行
- `get_state_schema()`：状態スキーマの取得

---

## 制限事項・制約

### 技術的制限
1. **LangChain 依存**：完全な LangGraph とは独立して使用可能だが、最大の強みは LangChain との統合
2. **高レベル抽象化なし**：プロンプトやアーキテクチャを自分で設計する必要あり
3. **状態管理複雑さ**：大規模グラフでは状態管理が複雑になる
4. **チェックポイントストレージ**：永続化には外部ストレージ（PostgreSQL、S3 など）が必要

### 運用制限
- 長期実行では LangSmith と連携する必要がある
- 詳細な可視化を必要とする場合は LangSmith のセットアップが必要

---

## まとめ
LangGraph は低レベルなオーケストレーションフレームワークであり、高レベル抽象化を提供しない代わりに、完全に制御可能な柔軟性を提供します。LangChain エコシステムとの統合が最大の強みであり、長期実行・状態フルエージェントの構築に最適です。
