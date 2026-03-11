"""ReAct cognitive engine for multi-turn agent reasoning.

Implements a graph-based ReAct (Reasoning + Acting) loop where the LLM
calls tools iteratively until a final answer is produced or termination
conditions are met.

The engine is designed to be used as a node handler within Pylon's
workflow execution runtime, replacing the single-shot LLM call with
an iterative reasoning loop.

Inspired by LangGraph's StateGraph/ToolNode pattern and OpenHands'
Controller-Agent architecture, adapted to Pylon's existing
TerminationCondition and StuckDetector infrastructure.
"""

from __future__ import annotations

import enum
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pylon.autonomy.termination import (
    TerminationCondition,
    TerminationState,
)
from pylon.providers.base import Message, Response, TokenUsage


class StepOutcome(enum.Enum):
    """Outcome of a single ReAct step."""

    CONTINUE = "continue"  # tool calls present → execute tools → loop
    FINAL_ANSWER = "final_answer"  # no tool calls → done
    TERMINATED = "terminated"  # termination condition met
    ERROR = "error"  # unrecoverable error


# Type aliases for pluggable tool execution
ToolExecutor = Callable[
    [str, dict[str, Any]],  # (tool_name, tool_input)
    Awaitable[str],  # tool output as string
]

ChatFn = Callable[
    [list[Message], Any],  # (messages, **kwargs)
    Awaitable[Response],  # LLM response
]


@dataclass
class ReActStep:
    """Record of a single ReAct iteration."""

    iteration: int
    thought: str  # LLM response content (the "reasoning")
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    outcome: StepOutcome
    tokens_used: TokenUsage = field(default_factory=TokenUsage)
    duration_ms: float = 0.0


@dataclass
class ReActResult:
    """Result of a complete ReAct execution."""

    final_answer: str
    steps: list[ReActStep]
    total_iterations: int
    total_tokens: TokenUsage
    termination_reason: str | None = None
    outcome: StepOutcome = StepOutcome.FINAL_ANSWER

    @property
    def tool_call_count(self) -> int:
        return sum(len(s.tool_calls) for s in self.steps)


@dataclass
class ReActConfig:
    """Configuration for the ReAct engine."""

    max_iterations: int = 20
    include_scratchpad: bool = True
    system_prefix: str = ""
    termination_condition: TerminationCondition | None = None
    stuck_detection_window: int = 3


class ReActEngine:
    """Graph-based ReAct loop engine.

    Execution flow:
    1. Send messages to LLM
    2. Check response for tool_calls
       - If tool_calls present → execute tools → append results → goto 1
       - If no tool_calls → return final answer
    3. Check termination conditions after each iteration
    4. Detect stuck loops (repeated identical tool calls)

    Usage:
        engine = ReActEngine(config=ReActConfig(max_iterations=10))
        result = await engine.run(
            messages=[Message(role="user", content="Find and fix the bug")],
            chat_fn=llm_runtime.chat,
            tool_executor=my_tool_executor,
            available_tools=tool_definitions,
        )
    """

    def __init__(self, config: ReActConfig | None = None) -> None:
        self._config = config or ReActConfig()
        self._recent_signatures: list[str] = []

    async def run(
        self,
        *,
        messages: list[Message],
        chat_fn: ChatFn,
        tool_executor: ToolExecutor,
        available_tools: list[dict[str, Any]] | None = None,
        chat_kwargs: dict[str, Any] | None = None,
    ) -> ReActResult:
        """Execute the full ReAct loop.

        Args:
            messages: Initial message history (system + user messages).
            chat_fn: Async callable that sends messages to the LLM.
            tool_executor: Async callable that executes a tool by name.
            available_tools: Tool definitions to pass to the LLM.
            chat_kwargs: Additional kwargs for chat_fn.

        Returns:
            ReActResult with the final answer and step history.
        """
        working_messages = list(messages)
        steps: list[ReActStep] = []
        total_tokens = TokenUsage()
        termination_state = TerminationState()
        kwargs = dict(chat_kwargs or {})
        if available_tools:
            kwargs["tools"] = available_tools

        for iteration in range(1, self._config.max_iterations + 1):
            step_start = time.monotonic()

            # 1. Call the LLM
            response = await chat_fn(working_messages, **kwargs)

            # Accumulate token usage
            if response.usage:
                total_tokens = TokenUsage(
                    input_tokens=total_tokens.input_tokens
                    + response.usage.input_tokens,
                    output_tokens=total_tokens.output_tokens
                    + response.usage.output_tokens,
                    cache_read_tokens=total_tokens.cache_read_tokens
                    + response.usage.cache_read_tokens,
                    cache_write_tokens=total_tokens.cache_write_tokens
                    + response.usage.cache_write_tokens,
                    reasoning_tokens=total_tokens.reasoning_tokens
                    + response.usage.reasoning_tokens,
                )

            # 2. Check for tool calls
            if not response.tool_calls:
                # Final answer — no more tools to call
                step = ReActStep(
                    iteration=iteration,
                    thought=response.content,
                    tool_calls=[],
                    tool_results=[],
                    outcome=StepOutcome.FINAL_ANSWER,
                    tokens_used=response.usage or TokenUsage(),
                    duration_ms=(time.monotonic() - step_start) * 1000,
                )
                steps.append(step)
                return ReActResult(
                    final_answer=response.content,
                    steps=steps,
                    total_iterations=iteration,
                    total_tokens=total_tokens,
                )

            # 3. Execute tool calls
            working_messages.append(
                Message(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )

            tool_results: list[dict[str, Any]] = []
            for tc in response.tool_calls:
                tool_name = tc.get("name", "")
                tool_input = tc.get("input", {})
                tc_id = tc.get("id", "")

                if isinstance(tool_input, str):
                    import json

                    try:
                        tool_input = json.loads(tool_input)
                    except (json.JSONDecodeError, TypeError):
                        tool_input = {"raw": tool_input}

                try:
                    result = await tool_executor(tool_name, tool_input)
                except Exception as exc:
                    result = f"Error executing {tool_name}: {exc}"

                tool_results.append(
                    {"tool_call_id": tc_id, "name": tool_name, "output": result}
                )

                working_messages.append(
                    Message(
                        role="tool",
                        content=str(result),
                        tool_call_id=tc_id,
                    )
                )

            step = ReActStep(
                iteration=iteration,
                thought=response.content,
                tool_calls=response.tool_calls,
                tool_results=tool_results,
                outcome=StepOutcome.CONTINUE,
                tokens_used=response.usage or TokenUsage(),
                duration_ms=(time.monotonic() - step_start) * 1000,
            )
            steps.append(step)

            # 4. Check termination conditions
            if self._config.termination_condition is not None:
                termination_state = TerminationState(
                    iterations=iteration,
                    total_tokens=total_tokens.total_tokens,
                    prompt_tokens=total_tokens.input_tokens,
                    completion_tokens=total_tokens.output_tokens,
                    elapsed_seconds=(time.monotonic() - step_start),
                )
                decision = self._config.termination_condition.evaluate(
                    termination_state
                )
                if decision.should_stop:
                    return ReActResult(
                        final_answer=response.content,
                        steps=steps,
                        total_iterations=iteration,
                        total_tokens=total_tokens,
                        termination_reason=decision.reason,
                        outcome=StepOutcome.TERMINATED,
                    )

            # 5. Stuck detection
            signature = _compute_step_signature(response.tool_calls)
            if self._is_stuck(signature):
                return ReActResult(
                    final_answer=response.content,
                    steps=steps,
                    total_iterations=iteration,
                    total_tokens=total_tokens,
                    termination_reason="stuck: repeated identical tool calls",
                    outcome=StepOutcome.TERMINATED,
                )
            self._recent_signatures.append(signature)

        # Max iterations exhausted
        return ReActResult(
            final_answer=steps[-1].thought if steps else "",
            steps=steps,
            total_iterations=self._config.max_iterations,
            total_tokens=total_tokens,
            termination_reason="max_iterations_exceeded",
            outcome=StepOutcome.TERMINATED,
        )

    def _is_stuck(self, signature: str) -> bool:
        """Check if the agent is stuck in a loop."""
        window = self._config.stuck_detection_window
        recent = self._recent_signatures[-window:]
        if len(recent) < window:
            return False
        return all(s == signature for s in recent)


def _compute_step_signature(tool_calls: list[dict[str, Any]]) -> str:
    """Compute a signature for stuck detection."""
    parts = []
    for tc in sorted(tool_calls, key=lambda x: x.get("name", "")):
        parts.append(f"{tc.get('name', '')}:{tc.get('input', '')}")
    return "|".join(parts)
