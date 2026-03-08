# CLEO パターン適用 実装計画書

> **作成日**: 2026-03-08
> **対象プロジェクト**: Pylon (`/Users/noriyuki.nakano/Documents/99_work/pylon`)
> **参照プロジェクト**: CLEO (`/Users/noriyuki.nakano/Documents/99_work/cleo`)
> **テスト状態**: 1387 tests all passing (計画策定時点)

---

## 目次

1. [概要](#概要)
2. [精査結果サマリー](#精査結果サマリー)
3. [Tier A: 即時実装（高価値・低工数）](#tier-a-即時実装高価値低工数)
4. [Tier B: 次期実装（高価値・中工数）](#tier-b-次期実装高価値中工数)
5. [Tier C: 後期検討（中価値 or 高工数）](#tier-c-後期検討中価値-or-高工数)
6. [Tier D: スキップ（不要 or 競合）](#tier-d-スキップ不要-or-競合)
7. [付録: 発見された既存バグ](#付録-発見された既存バグ)

---

## 概要

CLEOプロジェクト（TypeScript, 262 MCP operations, タスク/記憶/ライフサイクル管理）の優れたパターンを、Pylon（Python, 22,420行, 自律AIエージェントオーケストレーション）に適用するための実装計画書。

6チームによるCLEO調査 → クロス分析 → 4チームによる精査を経て、以下の優先度で分類。

### 重要な所見

1. **Pylonの最大のギャップはアーキテクチャではなく永続化**。全リポジトリがin-memory
2. **PylonはDAG実行と自律性モデリングでCLEOを上回っている**。A0-A4ラダー、Rule-of-Two+、composable termination conditionsは退行させない
3. **最もROIが高いのはTier Aの4件**（各200行以下、安全性/運用性のギャップを埋める）
4. **CLEOのBRAIN（記憶システム）の3層検索は思想として優れている**が、永続化基盤が先決

---

## 精査結果サマリー

4チームが実際のコードを読んで検証した結果:

| 提案 | 前提の正確性 | 修正 |
|------|------------|------|
| A1 Session Handoff | **正しい** | — |
| A2 Hierarchy Policy | **正しい** | — |
| A3 Structured Exit Codes | **正しい（補足あり）** | HTTP風status_codeは既存。exit_codeは別フィールドとして追加 |
| A4 Circular Validation | **正しい** | — |
| B1 Layered Validation | **部分的に正しい** | 3系統分散は事実だが、一部は意図的な分離 |
| B2 Dependency Waves | **正しい** | — |
| B3 Scoped Kill Switch | **間違い** | 既にscope-aware実装済み。Tier Aに格上げ（工数SS） |
| B4 CQRS分離 | **正しい** | — |
| D1 Dispatch-First | **概ね正しい** | スキップ妥当 |
| D2 WarpChain | **正しい** | スキップ妥当 |
| D3 contextvars | **正しいが留意点** | `run_in_tenant_context`にisolation設計上の注意点発見 |
| D4 Token管理 | **スキップ理由不適切** | Tier Cに格上げ。ContextManagerが既にruntime層にある |

---

## Tier A: 即時実装（高価値・低工数）

### A1: Session Handoff Protocol

**優先度**: P0-critical
**工数**: S（~30行追加）
**リスク**: 低（HandoffDataはOptional、既存テストに影響なし）

#### 問題

エージェント障害復旧時にコンテキストが消失する。

- `runtime.py:34-35`: COMPLETED/FAILED/KILLED遷移時に`working_memory.clear()`が無条件実行
- `supervisor.py:117-124`: `kill_agent()` → `create_agent()` で新Agentは空のworking_memoryで起動
- McpSessionとの紐付けも引き継がれない

```python
# runtime.py:34-35 — 現状
if target in (AgentState.COMPLETED, AgentState.FAILED, AgentState.KILLED):
    self.working_memory.clear()
```

#### CLEOの参照パターン

CLEOの`HandoffData`（`src/core/sessions/handoff.ts:30-49`）は8フィールド:
`lastTask`, `tasksCompleted`, `tasksCreated`, `decisionsRecorded`, `nextSuggested`, `openBlockers`, `openBugs`, `note`/`nextAction`

#### 変更内容

**ファイル1: `src/pylon/agents/runtime.py`**

Agent classの前（L15の後）にHandoffData追加:

```python
@dataclass(frozen=True)
class HandoffData:
    """Context preserved across agent restarts."""
    agent_id: str
    config_name: str
    working_memory: dict[str, Any]
    state_before_kill: str
    restart_count: int
    note: str = ""
```

Agent classにメソッド追加:

```python
def generate_handoff(self, *, restart_count: int = 0, note: str = "") -> HandoffData:
    """Capture current context before terminal transition."""
    return HandoffData(
        agent_id=self.id,
        config_name=self.config.name,
        working_memory=dict(self.working_memory),
        state_before_kill=self.state.value,
        restart_count=restart_count,
        note=note,
    )

def restore_from_handoff(self, handoff: HandoffData) -> None:
    """Restore working memory from a handoff."""
    self.working_memory.update(handoff.working_memory)
```

**ファイル2: `src/pylon/agents/supervisor.py`**

- L10: importに`HandoffData`追加
- L110-111の間: kill前にhandoff生成

```python
handoff = agent.generate_handoff(
    restart_count=supervised.restart_count + 1,
    note="auto-restart by supervisor",
)
```

- L123-124の後: 新Agentにhandoff復元

```python
new_agent.restore_from_handoff(handoff)
```

---

### A2: Hierarchy Policy Enforcement

**優先度**: P0-critical
**工数**: S（~25行追加、~5行変更）
**リスク**: 中（デフォルトPolicy使用時は既存テスト通過。decompose_fnが大量結果を返すテストがあれば調整必要）

#### 問題

`TaskPlanner.decompose()`に深さ/幅の上限がなく、再帰的なタスク分解が無制限に拡大する。

- `planner.py:56-63`: `decompose()`のデフォルト実装はタスクをそのまま返すだけ
- 外部注入の`decompose_fn`が無制限のリストを返してもサイズ検証なし
- `AgentPool.max_size`はPool単体の保護であり、サブタスク数を制限しない

```python
# planner.py:56-63 — 現状
async def decompose(self, task: str) -> list[str]:
    if not task or not task.strip():
        raise ValueError("task must be a non-empty string")
    if self._decompose_fn is not None:
        return await self._decompose_fn(task)
    return [task]
```

#### CLEOの参照パターン

CLEOの`HierarchyPolicy`（`src/core/tasks/hierarchy-policy.ts:17-23`）:
`maxDepth`, `maxSiblings`, `maxActiveSiblings` + 2プリセットプロファイル（`llm-agent-first`, `human-cognitive`）

#### 変更内容

**ファイル1: `src/pylon/coding/planner.py`**

L33の後にHierarchyPolicy追加:

```python
@dataclass(frozen=True)
class HierarchyPolicy:
    """Limits on task decomposition depth and breadth."""
    max_subtasks: int = 20
    max_plan_steps: int = 50
```

`__init__`にパラメータ追加（L38-45）:

```python
def __init__(
    self,
    *,
    planner_fn: ... = None,
    decompose_fn: ... = None,
    hierarchy_policy: HierarchyPolicy | None = None,
) -> None:
    ...
    self._policy = hierarchy_policy or HierarchyPolicy()
```

`plan()`と`decompose()`のreturn前にサイズ検証追加:

```python
# plan() — return前
if len(result.steps) > self._policy.max_plan_steps:
    raise ValueError(
        f"Plan exceeds max steps: {len(result.steps)} > {self._policy.max_plan_steps}"
    )

# decompose() — return前
if len(result) > self._policy.max_subtasks:
    raise ValueError(
        f"Decomposition exceeds max subtasks: {len(result)} > {self._policy.max_subtasks}"
    )
```

**ファイル2: `src/pylon/control_plane/scheduler/scheduler.py`**

`__init__`に`max_scheduled_tasks`追加（L102-106）:

```python
def __init__(self, *, max_scheduled_tasks: int = 200) -> None:
    ...
    self._max_scheduled_tasks = max_scheduled_tasks
```

`schedule()`, `schedule_recurring()`の先頭に登録数チェック追加。

---

### A3: Structured Exit Codes

**優先度**: P1-high
**工数**: S（~25行追加）
**リスク**: 低（exit_codeはクラス変数追加のみ、既存status_codeと並行）

#### 問題

PylonのエラーはHTTP風`status_code`（400/403/500等）を全クラスに持つが、CLI/K8s用のprocess exit codeが未定義。K8sの`restartPolicy`やSupervisorの自動再起動判断に使えない。

#### CLEOの参照パターン

CLEOは72コード/13カテゴリの範囲別exit code（`src/types/exit-codes.ts`）:
0 success, 10-19 hierarchy, 20-29 concurrency, 30-39 session, 40-47 verification, 50-54 context, 60-67 orchestration, 70-79 nexus, 80-84 lifecycle, 85-89 artifact, 90-94 provenance

#### 変更内容

**ファイル: `src/pylon/errors.py`**

L7の後にExitCode enum追加:

```python
import enum

class ExitCode(enum.IntEnum):
    """Process exit codes for Pylon."""
    SUCCESS = 0
    # Config (10-19)
    CONFIG_INVALID = 10
    # Agent (20-29)
    AGENT_LIFECYCLE_ERROR = 20
    AGENT_NOT_FOUND = 21
    # Policy / Security (30-39)
    POLICY_VIOLATION = 30
    PROMPT_INJECTION = 31
    APPROVAL_REQUIRED = 32
    # Workflow / Task (40-49)
    WORKFLOW_ERROR = 40
    TASK_QUEUE_ERROR = 41
    SCHEDULER_ERROR = 42
    # Infrastructure (50-59)
    SANDBOX_ERROR = 50
    PROVIDER_ERROR = 51
    # General (70-79)
    INTERNAL_ERROR = 70
    UNKNOWN_ERROR = 79
```

PylonErrorに`exit_code`追加:

```python
class PylonError(Exception):
    code: str = "PYLON_INTERNAL_ERROR"
    status_code: int = 500
    exit_code: ExitCode = ExitCode.INTERNAL_ERROR  # 追加
```

各サブクラスに対応するexit_codeを設定:

| クラス | exit_code |
|--------|-----------|
| ConfigError | `ExitCode.CONFIG_INVALID` |
| PolicyViolationError | `ExitCode.POLICY_VIOLATION` |
| AgentLifecycleError | `ExitCode.AGENT_LIFECYCLE_ERROR` |
| WorkflowError | `ExitCode.WORKFLOW_ERROR` |
| SandboxError | `ExitCode.SANDBOX_ERROR` |
| ProviderError | `ExitCode.PROVIDER_ERROR` |
| PromptInjectionError | `ExitCode.PROMPT_INJECTION` |
| ApprovalRequiredError | `ExitCode.APPROVAL_REQUIRED` |

`to_dict()`に`"exit_code": self.exit_code.value`を追加。

---

### A4: Circular Validation Prevention

**優先度**: P1-high
**工数**: S（~20行追加）
**リスク**: 低（authored_byはデフォルト空文字、reviewer_agent_idもデフォルト空文字でチェックはスキップされる）

#### 問題

`coding/reviewer.py`に自己レビュー防止がない。`CodeChange`に作成者情報がなく、`CodeReviewer.review()`はエージェントIDを受け取らない。A2+の自律ワークフローで整合性ギャップ。

```python
# reviewer.py:37-44 — 現状
@dataclass(frozen=True)
class CodeChange:
    file_path: str
    content: str
    line_count: int = 0
    has_tests: bool = False
    # authored_by なし
```

#### CLEOの参照パターン

CLEOの`checkCircularValidation()`（`src/core/validation/verification.ts:375-411`）:
3パターン防止（作成者→検証不可、検証者→再テスト不可、テスター→作成不可）+ 3バイパス例外（`user`, `legacy`, `system`）

#### 変更内容

**ファイル1: `src/pylon/coding/reviewer.py`**

CodeChangeに`authored_by`追加（L43の後）:

```python
authored_by: str = ""  # agent_id of the author
```

CodeReviewerに`reviewer_agent_id`追加:

```python
def __init__(
    self,
    *,
    quality_gates: QualityGateConfig | None = None,
    review_fn: ... = None,
    reviewer_agent_id: str = "",  # 追加
) -> None:
    ...
    self._reviewer_agent_id = reviewer_agent_id
```

`review()`の先頭に自己レビュー検出追加:

```python
async def review(self, changes: list[CodeChange]) -> ReviewResult:
    if self._reviewer_agent_id:
        for change in changes:
            if change.authored_by and change.authored_by == self._reviewer_agent_id:
                raise PolicyViolationError(
                    f"Circular validation: agent '{self._reviewer_agent_id}' "
                    f"cannot review its own change to '{change.file_path}'",
                    details={
                        "reviewer": self._reviewer_agent_id,
                        "author": change.authored_by,
                        "file": change.file_path,
                    },
                )
    ...
```

**ファイル2: `src/pylon/coding/committer.py`**

CommitPlanに`authored_by`追加（L26-31）:

```python
authored_by: str = ""  # agent_id for audit trail
```

---

### A5: KillSwitch 中間スコープ継承（B3から格上げ）

**優先度**: P1-high
**工数**: SS（~25行変更）
**リスク**: 低（keyword-only引数でデフォルト空文字、後方互換維持）

#### 問題

KillSwitchは既にscope-aware（`global`/`tenant:{id}`/`workflow:{id}`/`agent:{id}`）だが、中間スコープの継承が未実装。`tenant:acme`が有効でも、その配下の`workflow:wf-1`には伝播しない。現状は`global`のみが全スコープに継承。

```python
# kill_switch.py:47-57 — 現状
def is_active(self, scope: str) -> bool:
    if scope in self._active:
        return True
    if "global" in self._active and scope != "global":
        return True
    return False
```

#### 変更内容

**ファイル: `src/pylon/safety/kill_switch.py`**

`_ActiveSwitch`に`parent_scope`追加（L22）:

```python
parent_scope: str = ""
```

`activate()`にkeyword-only引数`parent_scope`追加（L35）:

```python
def activate(self, scope: str, reason: str, issued_by: str,
             *, parent_scope: str = "") -> KillSwitchEvent:
```

`is_active()`を階層チェインに書き換え（L47-57）:

```python
def is_active(self, scope: str) -> bool:
    if scope in self._active:
        return True
    if "global" in self._active:
        return True
    for active_scope, switch in self._active.items():
        if self._is_ancestor(active_scope, scope):
            return True
    return False

def _is_ancestor(self, ancestor: str, descendant: str) -> bool:
    """Check if ancestor scope covers descendant via parent_scope chain."""
    for s, switch in self._active.items():
        if s == descendant and switch.parent_scope:
            if switch.parent_scope == ancestor:
                return True
            return self._is_ancestor(ancestor, switch.parent_scope)
    return False
```

---

## Tier B: 次期実装（高価値・中工数）

### B1: Layered Validation Gates

**優先度**: P1-high
**工数**: M（新規ファイル ~120行）

#### 問題

バリデーションが3系統に分散:
1. `config/validator.py` — `FieldConstraint`ベースの型変換+範囲チェック
2. `api/schemas.py` — `FieldRule`ベースのAPI入力バリデーション
3. `dsl/parser.py` — Pydantic v2の`BaseModel` + `@field_validator`

`FieldConstraint`と`FieldRule`はほぼ同等の概念を二重実装。

#### CLEOの参照パターン

4層sequential fail-fast（`src/mcp/lib/verification-gates.ts:29-34`）:
`SCHEMA(1)` → `SEMANTIC(2)` → `REFERENTIAL(3)` → `PROTOCOL(4)`

#### 変更内容

**新規ファイル: `src/pylon/config/pipeline.py`**（~120行）

```python
@dataclass
class ValidationIssue:
    stage: str       # "schema" | "semantic" | "referential" | "protocol"
    field: str
    message: str
    severity: str    # "error" | "warning"

@dataclass
class ValidationContext:
    agents: dict[str, Any]
    workflow_nodes: dict[str, Any]
    policy: dict[str, Any]

@dataclass
class PipelineResult:
    valid: bool
    issues: list[ValidationIssue]
    stages_passed: list[str]

class ValidationPipeline:
    def __init__(self, stages: list[ValidationStage] | None = None): ...
    def run(self, config: dict[str, Any], context: ValidationContext | None = None) -> PipelineResult: ...
```

既存ファイルは変更なし（pipeline.pyが既存バリデータを内部で委譲）。

---

### B2: Dependency Wave Analysis

**優先度**: P1-high
**工数**: M（~60行追加）

#### 問題

`WorkflowScheduler`はheapqベースのフラット優先度キュー。`WorkflowTask`に依存関係フィールドがない。`GraphExecutor`のDAG依存解決とは未接続。

#### 変更内容

**ファイル: `src/pylon/control_plane/scheduler/scheduler.py`**

`WorkflowTask`にフィールド追加（L27）:

```python
dependencies: set[str] = field(default_factory=set)
```

`WorkflowScheduler`に3メソッド追加（L77以降）:

```python
def compute_waves(self) -> list[list[WorkflowTask]]:
    """Kahn's algorithmでDAGをwave分解。循環検出あり。"""
    ...

def dequeue_wave(self) -> list[WorkflowTask]:
    """現在のwave（依存が全てCOMPLETEDのタスク群）をまとめてdequeue。"""
    ...

def complete(self, task_id: str) -> bool:
    """タスクをCOMPLETEDに遷移。"""
    ...
```

---

### B4: CQRS Gateway分離

**優先度**: P2-medium
**工数**: M（~30行変更）

#### 問題

`Repository[T]`（`base.py:15-53`）が`get`/`list`/`create`/`update`/`delete`を混在。各具象実装はProtocolに準拠していないものもある。

#### 変更内容

**ファイル: `src/pylon/repository/base.py`**

`ReadRepository[T]`と`WriteRepository[T]`を新規定義。`Repository[T]`は両方を継承（後方互換）:

```python
@runtime_checkable
class ReadRepository(Protocol[T]):
    async def get(self, id: str) -> T | None: ...
    async def list(self, *, limit: int = 100, offset: int = 0, **filters: Any) -> list[T]: ...

@runtime_checkable
class WriteRepository(Protocol[T]):
    async def create(self, entity: T) -> T: ...
    async def update(self, id: str, **updates: Any) -> T | None: ...
    async def delete(self, id: str) -> bool: ...

@runtime_checkable
class Repository(ReadRepository[T], WriteRepository[T], Protocol[T]):
    """Full CRUD repository (backward compatible)."""
    pass
```

具象クラスへの適用は段階的。

---

## Tier C: 後期検討（中価値 or 高工数）

### C1: Atomic Write Pattern

永続化バックエンド決定後に実装。CLEOの`temp→validate→backup→rename`パターンを採用。

### C2: 6-Gate Verification

CI/CDパイプライン統合が前提。CLEOの6ゲート（implemented→testsPassed→qaPassed→cleanupDone→securityPassed→documented）は参考にするが、現在のPylonスコープではオーバーエンジニアリング。

### C3: Hybrid Memory Search

FTS+Vector+Graphの3信号検索。FTS+Vectorは SQLite拡張で実現可能だが、Graph neighborsに大きなインフラが必要。

### C4: Token管理改善（D4から格上げ）

**格上げ理由**: スキップ理由「Provider層の責務」が実装と矛盾。`ContextManager`は既にruntime層（`src/pylon/runtime/context.py`）に存在。

**変更内容:**

`_estimate_message_tokens()`のトークン推定精度改善:

```python
try:
    import tiktoken
    _ENCODER = tiktoken.get_encoding("cl100k_base")
    _HAS_TIKTOKEN = True
except ImportError:
    _HAS_TIKTOKEN = False

def _estimate_message_tokens(messages: list[Message]) -> int:
    text = "\n".join(message.content for message in messages)
    if not text:
        return 1
    if _HAS_TIKTOKEN:
        return max(1, len(_ENCODER.encode(text)))
    # Fallback: 日本語対応の簡易推定
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, ascii_chars // 4 + int(non_ascii_chars / 1.5))
```

`pyproject.toml`にoptional dependency追加:

```toml
[project.optional-dependencies]
tokenizer = ["tiktoken>=0.7.0"]
```

### C5: 3-Tier MVI Spawning

プロダクションワークロードデータなしにTier境界を決められない。

---

## Tier D: スキップ（不要 or 競合）

### D1: Dispatch-First + Registry-as-Truth — スキップ

**理由**: PylonのPython module system + Protocol型で部分的に達成済み。RegistryがAgent/Pluginの2系統に分裂しているが、TypeScript固有のイディオムを持ち込むメリットは低い。

**精査結果**: Protocol型によるインターフェース契約は存在するが「Registry-as-Truth」は未達成。ただしスキップは妥当。

### D2: WarpChain — スキップ

**理由**: PylonのDAG + Python AST条件（`conditions.py`のホワイトリスト制限付き評価器）はWarpChainの線形チェーン+固定ジャンプより表現力が高い。

**精査結果**: 正しい。join semantics, loop termination criterion, autonomy-aware terminationを持つPylonのグラフが上位互換。

### D3: Process-Scoped Session Context — スキップ

**理由**: Pythonの`contextvars`で既にper-coroutine分離が達成されている（`tenancy/context.py`）。CLEOのNode.js MCP固有の問題。

**精査結果**: スキップ妥当。ただし`run_in_tenant_context`に設計上の注意点あり（[付録参照](#付録-発見された既存バグ)）。

---

## 付録: 発見された既存バグ

精査中に発見された、本計画とは独立した問題。

### Bug-1: `run_in_tenant_context` の isolation 注意点

**ファイル**: `src/pylon/tenancy/context.py:72-77`
**Severity**: Warning

```python
async def run_in_tenant_context(ctx: TenantContext, coro: Any) -> Any:
    current_ctx = contextvars.copy_context()
    current_ctx.run(_current_tenant.set, ctx)
    task = current_ctx.run(asyncio.get_running_loop().create_task, coro)
    return await task
```

`copy_context()`は呼び出し元の全contextvarをコピーする。他のテナントのContextVarがリークする可能性がある。`contextvars.Context()`（空コンテキスト）を使うか、`create_task(coro, context=child_ctx)`（Python 3.12+）で明示的に渡す方が安全。

**推奨修正**: コメントで設計意図を明記 + テストで並行タスクからのtenant leakがないことを検証。

### Bug-2: トークン推定の精度（日本語）

**ファイル**: `src/pylon/runtime/context.py:10-12`
**Severity**: Warning

```python
def _estimate_message_tokens(messages: list[Message]) -> int:
    text = "\n".join(message.content for message in messages)
    return max(1, len(text) // 4)
```

`len(text) // 4`はASCII英語では近似として通るが、日本語など多バイト文字では大幅に過小推定される。Tier C4で対応予定。

---

## 実装スケジュール

### Phase 1: Tier A（並列実装可能）

全5件は依存関係なし。並列実装可能。

```
A3 (ExitCode enum) ─────────┐
A4 (Circular Validation) ───┤
A1 (Session Handoff) ───────┼─→ テスト実行 → マージ
A2 (Hierarchy Policy) ──────┤
A5 (KillSwitch継承) ────────┘
```

**推奨実装順序**: A3 → A4 → A1 → A5 → A2（A3がenumのみで最も簡単、A2はテスト調整の可能性あり）

### Phase 2: Tier B（Phase 1完了後）

```
B3 (KillSwitch改善) ──┐
B2 (Dependency Waves) ┼─→ テスト実行
B4 (CQRS分離) ────────┤
B1 (Validation Pipeline) ───→ テスト実行
```

### Phase 3: Tier C（Phase 2完了後、選択的）

バックエンド決定・プロダクション要件に応じて選択。

---

## 変更ファイル一覧

| Tier | ファイル | 操作 | 追加行数 |
|------|---------|------|---------|
| A1 | `src/pylon/agents/runtime.py` | 変更 | ~20 |
| A1 | `src/pylon/agents/supervisor.py` | 変更 | ~10 |
| A2 | `src/pylon/coding/planner.py` | 変更 | ~25 |
| A2 | `src/pylon/control_plane/scheduler/scheduler.py` | 変更 | ~10 |
| A3 | `src/pylon/errors.py` | 変更 | ~25 |
| A4 | `src/pylon/coding/reviewer.py` | 変更 | ~15 |
| A4 | `src/pylon/coding/committer.py` | 変更 | ~5 |
| A5 | `src/pylon/safety/kill_switch.py` | 変更 | ~25 |
| B1 | `src/pylon/config/pipeline.py` | **新規** | ~120 |
| B2 | `src/pylon/control_plane/scheduler/scheduler.py` | 変更 | ~60 |
| B4 | `src/pylon/repository/base.py` | 変更 | ~30 |
| C4 | `src/pylon/runtime/context.py` | 変更 | ~15 |
| C4 | `pyproject.toml` | 変更 | ~3 |
| Bug-1 | `src/pylon/tenancy/context.py` | 変更 | ~5 |

**合計**: 既存ファイル変更13、新規ファイル1、追加行数 ~370行
