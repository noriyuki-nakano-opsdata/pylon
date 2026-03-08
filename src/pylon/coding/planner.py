from __future__ import annotations

import enum
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


class FileAction(enum.Enum):
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"


class CodingComplexity(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class PlanStep:
    description: str
    file_path: str
    action: FileAction


@dataclass(frozen=True)
class Plan:
    steps: list[PlanStep]
    estimated_files: list[str]
    estimated_complexity: CodingComplexity


@dataclass(frozen=True)
class HierarchyPolicy:
    """Limits on planning and decomposition breadth."""

    max_subtasks: int = 20
    max_plan_steps: int = 50


class TaskPlanner:
    """Generates plans and decomposes tasks into actionable steps."""

    def __init__(
        self,
        *,
        planner_fn: Callable[[str], Awaitable[Plan]] | None = None,
        decompose_fn: Callable[[str], Awaitable[list[str]]] | None = None,
        hierarchy_policy: HierarchyPolicy | None = None,
    ) -> None:
        self._planner_fn = planner_fn
        self._decompose_fn = decompose_fn
        self._policy = hierarchy_policy or HierarchyPolicy()

    async def plan(self, task_description: str) -> Plan:
        if not task_description or not task_description.strip():
            raise ValueError("task_description must be a non-empty string")

        if self._planner_fn is not None:
            result = await self._planner_fn(task_description)
        else:
            result = self._default_plan(task_description)

        if len(result.steps) > self._policy.max_plan_steps:
            raise ValueError(
                "Plan exceeds max steps: "
                f"{len(result.steps)} > {self._policy.max_plan_steps}"
            )
        return result

    async def decompose(self, task: str) -> list[str]:
        if not task or not task.strip():
            raise ValueError("task must be a non-empty string")

        if self._decompose_fn is not None:
            result = await self._decompose_fn(task)
        else:
            result = [task]

        if len(result) > self._policy.max_subtasks:
            raise ValueError(
                "Decomposition exceeds max subtasks: "
                f"{len(result)} > {self._policy.max_subtasks}"
            )
        return result

    def estimate_complexity(self, task: str) -> CodingComplexity:
        if not task or not task.strip():
            raise ValueError("task must be a non-empty string")

        word_count = len(task.split())
        file_refs = len(re.findall(r"\.\w{1,5}\b", task))

        score = word_count + file_refs * 3

        if score > 30:
            return CodingComplexity.HIGH
        if score >= 10:
            return CodingComplexity.MEDIUM
        return CodingComplexity.LOW

    # ------------------------------------------------------------------

    @staticmethod
    def _default_plan(task_description: str) -> Plan:
        step = PlanStep(
            description=task_description,
            file_path="",
            action=FileAction.MODIFY,
        )
        return Plan(
            steps=[step],
            estimated_files=[],
            estimated_complexity=CodingComplexity.LOW,
        )
