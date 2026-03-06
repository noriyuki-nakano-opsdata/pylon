# 📘 AWS Strands Agents 機能仕様書

## プロジェクト概要
**Strands Agents** は、Amazon から提供されているシンプルな AI エージェント構築のための SDK です。モデル駆動アプローチで、わずか数行のコードだけで単純な会話アシスタントから複雑な自律的ワークフローまで実現します。

### 基本情報
- **GitHub**: `https://github.com/strands-agents/sdk-python`
- **ドキュメントサイト**: [strandsagents.com](https://strandsagents.com)
- **ライセンス**: Apache 2.0
- **Python バージョン**: >=3.10
- **主要パッケージ**: `strands-agents`, `strands-agents-tools`

---

## 主な機能・特徴

### 1. アーキテクチャコンセプト

#### Lightweight & Flexible（軽量で柔軟）
- シンプルなエージェントループ："just works"かつ完全にカスタマイズ可能
- **モデル非依存**：Amazon Bedrock、Anthropic、Gemini、LiteLLM、Llama、Ollama、OpenAI など全 11 のモデルプロバイダー対応
- **高機能**：マルチエージェントシステム、自律的エージェント、ストリーミングサポート

### 2. コアコンポーネント

#### Agent クラス
```python
from strands import Agent
from strands_tools import calculator

# シンプルなエージェント
tools = [calculator]
agent = Agent(tools=tools)
response = agent("What is the square root of 1764")
```

#### Tool Decorator（ツール装飾子）
```python
from strands import tool

@tool
def word_count(text: str) -> int:
    """Count words in text. This docstring is used by the LLM to understand the tool's purpose."""
    return len(text.split())

agent = Agent(tools=[word_count])
```

#### Hot Reloading（ホットリロード）
```python
from strands import Agent

# ./tools/ ディレクトリからの自動ツール読み込み
agent = Agent(load_tools_from_directory=True)
response = agent("Use any tools you find in the tools directory")
```

### 3. Model Providers（モデルプロバイダー）

#### Built-in Providers（11 つのプロバイダー対応）
- Amazon Bedrock
- Anthropic
- Gemini
- Cohere
- LiteLLM
- llama.cpp
- LlamaAPI
- MistralAI
- Ollama
- OpenAI
- SageMaker
- Writer

#### 使用例：Bedrock モデル
```python
from strands.models import BedrockModel
from strands import Agent

bedrock_model = BedrockModel(
    model_id="us.amazon.nova-pro-v1:0",
    temperature=0.3,
    streaming=True
)
agent = Agent(model=bedrock_model)
agent("Tell me about Agentic AI")
```

#### 使用例：Ollama モデル
```python
from strands.models.ollama import OllamaModel
from strands import Agent

ollama_model = OllamaModel(
    host="http://localhost:11434",
    model_id="llama3"
)
agent = Agent(model=ollama_model)
```

---

## 実験的機能：Bidirectional Streaming（双方向ストリーミング）

### 実装例：リアルタイム音声会話
```python
import asyncio
from strands.experimental.bidi import BidiAgent
from strands.experimental.bidi.models import BidiNovaSonicModel
from strands.experimental.bidi.io import BidiAudioIO, BidiTextIO
from strands.experimental.bidi.tools import stop_conversation
from strands_tools import calculator

async def main():
    model = BidiNovaSonicModel()
    agent = BidiAgent(model=model, tools=[calculator, stop_conversation])
    
    audio_io = BidiAudioIO()
    text_io = BidiTextIO()
    
    await agent.run(
        inputs=[audio_io.input()],
        outputs=[audio_io.output(), text_io.output()]
    )

asyncio.run(main())
```

#### 設定オプション
```python
model = BidiNovaSonicModel(
    provider_config={
        "audio": {
            "input_rate": 16000,
            "output_rate": 16000,
            "voice": "matthew"
        },
        "turn_detection": {
            "endpointingSensitivity": "MEDIUM"  # HIGH, MEDIUM, LOW
        }
    }
)
```

---

## メリット・デメリット

### メリット✅
1. **AWS エコシステム統合**：Bedrock、SageMaker、Lambda などのシームレス連携
2. **Lightweight Design**：シンプルで軽量な設計
3. **モデル非依存**：11 つの異なるプロバイダーに対応
4. **MCP ネイティブサポート**：Model Context Protocol との自動連携
5. **Hot Reloading**：ツールディレクトリからの自動読み込み
6. **Bi-directional Streaming**：リアルタイム音声会話の実験的サポート
7. **Production Ready**：デプロイメントガイドで本番環境対応

### デメリット❌
1. **限定的な機能セット**：LangGraph や AutoGen に比べて機能が少ない
2. **初期コミュニティ小**：比較的新しいプロジェクトのためドキュメントが不完全
3. **Amazon Bedrock 依存**：デフォルトでは AWS クレジットと設定が必要
4. **実験的機能**：双方向ストリーミングは実験的（API の変更あり）
5. **ツールエコシステム小**：strands-agents-tools は限定されたツールセット

---

## まとめ
AWS Strands Agents は「軽量で柔軟なモデル駆動アプローチ」を特徴とする AWS エコシステムのエージェントフレームワークです。11 つのモデルプロバイダーに対応し、MCP ネイティブサポートや双方向ストリーミングなどの革新的機能を備えます。ただし、LangChain や CrewAI のような大規模コミュニティに比べると機能セットが限定的です。
