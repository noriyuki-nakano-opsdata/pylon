# Pylon vNext Type Design

## Purpose

This document proposes the first-pass type model for the new autonomy and
governance features planned for Pylon vNext.

The design goal is to add goal-conditioned autonomy without weakening the
existing deterministic workflow kernel.

## Package Layout

Recommended new package:

- `src/pylon/autonomy`

Recommended initial modules:

- `goals.py`
- `termination.py`
- `routing.py`
- `evaluation.py`
- `context.py`
- `planner.py`
- `replan.py`

This package should depend on:

- `pylon.workflow`
- `pylon.safety`
- `pylon.approval`
- `pylon.providers`

It should not own persistence or safety rules directly.

## Goal Types

### `GoalSpec`

Represents the declared target of an autonomous run.

Suggested shape:

```python
@dataclass(frozen=True)
class GoalSpec:
    objective: str
    success_criteria: tuple["SuccessCriterion", ...] = ()
    constraints: "GoalConstraints" = GoalConstraints()
    failure_policy: "FailurePolicy" = FailurePolicy.ESCALATE
    allowed_effect_scopes: frozenset[str] = frozenset()
    allowed_secret_scopes: frozenset[str] = frozenset()
```

### `GoalConstraints`

```python
@dataclass(frozen=True)
class GoalConstraints:
    max_iterations: int | None = None
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    timeout_seconds: int | None = None
    max_replans: int | None = None
```

### `FailurePolicy`

```python
class FailurePolicy(enum.Enum):
    FAIL = "fail"
    ESCALATE = "escalate"
    REQUEST_APPROVAL = "request_approval"
```

### `SuccessCriterion`

Use a tagged union rather than a single free-form object.

Recommended criterion types:

- `RubricCriterion`
- `ToolTrajectoryCriterion`
- `HallucinationCriterion`
- `SafetyCriterion`
- `DeterministicCheckCriterion`

This keeps evaluation logic inspectable and versionable.

## Runtime Autonomy Context

### `AutonomyContext`

This should sit above `SafetyContext`.

Suggested fields:

```python
@dataclass
class AutonomyContext:
    run_id: str
    workflow_id: str
    goal: GoalSpec
    safety_context: SafetyContext
    current_iteration: int = 0
    replan_count: int = 0
    token_usage: TokenUsage = TokenUsage()
    estimated_cost_usd: float = 0.0
    model_tier: "ModelTier" = ModelTier.STANDARD
    cache_state: "CacheState" | None = None
```

This allows the autonomy layer to remain bounded by the same run identity and
safety envelope as the workflow kernel.

## Termination Types

### `TerminationCondition`

Use a protocol or abstract base with boolean composition.

```python
class TerminationCondition(Protocol):
    def evaluate(self, state: "TerminationState") -> "TerminationDecision": ...
```

### `TerminationDecision`

```python
@dataclass(frozen=True)
class TerminationDecision:
    matched: bool
    reason: str = ""
    terminal_status: str = ""
```

### `TerminationState`

```python
@dataclass(frozen=True)
class TerminationState:
    iterations: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    elapsed_seconds: int = 0
    last_quality_score: float | None = None
    external_stop_requested: bool = False
    stuck_detected: bool = False
```

### Composition

Support explicit composition objects:

- `AnyTermination`
- `AllTermination`

Avoid operator overloading in the first pass if it hurts readability or
serialization.

## Routing Types

### `ModelTier`

```python
class ModelTier(enum.Enum):
    LIGHTWEIGHT = "lightweight"
    STANDARD = "standard"
    PREMIUM = "premium"
```

### `ModelRouteRequest`

```python
@dataclass(frozen=True)
class ModelRouteRequest:
    purpose: str
    input_tokens_estimate: int
    requires_tools: bool = False
    latency_sensitive: bool = False
    quality_sensitive: bool = False
    cacheable_prefix: bool = False
```

### `ModelRouteDecision`

```python
@dataclass(frozen=True)
class ModelRouteDecision:
    provider_name: str
    model_id: str
    tier: ModelTier
    reasoning: str
    cache_strategy: "CacheStrategy" = CacheStrategy.NONE
    batch_eligible: bool = False
```

### `CacheStrategy`

```python
class CacheStrategy(enum.Enum):
    NONE = "none"
    PREFIX = "prefix"
    EXPLICIT = "explicit"
    BATCH = "batch"
```

## Evaluation Types

### `EvaluationKind`

```python
class EvaluationKind(enum.Enum):
    RESPONSE_QUALITY = "response_quality"
    TOOL_TRAJECTORY = "tool_trajectory"
    HALLUCINATION = "hallucination"
    SAFETY = "safety"
```

### `EvaluationRequest`

```python
@dataclass(frozen=True)
class EvaluationRequest:
    kind: EvaluationKind
    rubric: str = ""
    expected_tool_path: tuple[str, ...] = ()
    allowed_sources: tuple[str, ...] = ()
    threshold: float = 0.0
```

### `EvaluationResult`

```python
@dataclass(frozen=True)
class EvaluationResult:
    kind: EvaluationKind
    score: float
    passed: bool
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

### `VerificationDecision`

```python
class VerificationDisposition(enum.Enum):
    SUCCESS = "success"
    REFINE = "refine"
    ESCALATE = "escalate"
    FAIL = "fail"


@dataclass(frozen=True)
class VerificationDecision:
    disposition: VerificationDisposition
    reason: str
    results: tuple[EvaluationResult, ...] = ()
```

## Planner And Replan Types

### `PlanAction`

Planner output should not be free-form text only.

Use structured actions such as:

- `SelectBranchAction`
- `InvokeToolAction`
- `RequestApprovalAction`
- `EscalateAction`
- `RefineAction`

### `PlannerDecision`

```python
@dataclass(frozen=True)
class PlannerDecision:
    action: "PlanAction"
    rationale: str
    requested_effect_scopes: frozenset[str] = frozenset()
```

### `ReplanRequest`

```python
@dataclass(frozen=True)
class ReplanRequest:
    failed_node_id: str
    failure_reason: str
    available_branches: tuple[str, ...]
    prior_attempts: int
```

## Loop Types

General cyclic workflows should remain deferred.

Instead, add a bounded loop primitive.

### `LoopNodeConfig`

```python
@dataclass(frozen=True)
class LoopNodeConfig:
    max_iterations: int
    success_threshold: float
    on_exhaustion: FailurePolicy = FailurePolicy.ESCALATE
```

### `LoopIterationRecord`

```python
@dataclass(frozen=True)
class LoopIterationRecord:
    iteration: int
    writer_output_ref: str | None = None
    critic_results: tuple[EvaluationResult, ...] = ()
    verification: VerificationDecision | None = None
```

This should integrate into workflow event logs, not create a separate hidden
execution model.

## Public Status Types

To avoid another divergence between internal and public surfaces, add a shared
run status projection.

### `RunPhase`

```python
class RunPhase(enum.Enum):
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
```

### `RunStopReason`

```python
class RunStopReason(enum.Enum):
    NONE = "none"
    LIMIT_EXCEEDED = "limit_exceeded"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_DENIED = "approval_denied"
    QUALITY_REACHED = "quality_reached"
    QUALITY_FAILED = "quality_failed"
    EXTERNAL_STOP = "external_stop"
    STUCK_DETECTED = "stuck_detected"
    STATE_CONFLICT = "state_conflict"
```

## Observability Types

Metrics should be shaped around actual autonomy decisions.

Recommended event families:

- `autonomy.goal.started`
- `autonomy.model.routed`
- `autonomy.evaluation.completed`
- `autonomy.replan.requested`
- `autonomy.termination.matched`
- `autonomy.stuck.detected`

Recommended counters and histograms:

- model route count by tier/provider/model
- cache hit ratio
- evaluation pass/fail count by kind
- average refinement iterations per goal
- termination count by reason
- approval wait duration

## Compatibility Rules

- existing workflow handlers returning `dict` or `NodeResult` must continue to work
- existing `RunStatus` remains valid, but richer stop reasons should be added alongside it
- autonomy types must compose with `SafetyContext`, not replace it
- model routing must sit above provider selection, not inside individual providers
