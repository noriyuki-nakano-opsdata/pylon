"""Compiled workflow condition predicates."""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from typing import Any

from pylon.errors import WorkflowError

_COMPARE_OPS: dict[type, Any] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_BOOL_OPS: dict[type, Any] = {
    ast.And: all,
    ast.Or: any,
}

_UNARY_OPS: dict[type, Any] = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
}


@dataclass(frozen=True)
class CompiledCondition:
    """Pre-validated workflow edge predicate."""

    source: str
    expression: ast.AST | None

    def evaluate(self, state: dict[str, Any]) -> bool:
        """Evaluate the compiled predicate against a state payload."""
        if self.expression is None:
            return False
        try:
            return bool(_eval_node(self.expression, state))
        except AttributeError as exc:
            raise WorkflowError(f"Condition references missing state field: {exc}") from exc


def compile_condition(condition: str | None) -> CompiledCondition | None:
    """Parse and validate a condition string for later execution."""
    if condition is None:
        return None

    source = condition.strip()
    if not source:
        return CompiledCondition(source=condition, expression=None)

    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise WorkflowError(f"Invalid condition syntax: {condition}") from exc

    _validate_node(tree.body)
    return CompiledCondition(source=condition, expression=tree.body)


def safe_eval_condition(condition: str, state: dict[str, Any]) -> bool:
    """Compile and evaluate a condition in one step."""
    compiled = compile_condition(condition)
    if compiled is None:
        return True
    return compiled.evaluate(state)


def _validate_node(node: ast.AST) -> None:  # noqa: PLR0911
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float, str, bool, type(None))):
            raise WorkflowError(f"Unsupported literal type: {type(node.value).__name__}")
        return

    if isinstance(node, ast.Attribute):
        if not isinstance(node.value, ast.Name) or node.value.id != "state":
            raise WorkflowError(
                f"Attribute access only allowed on 'state', got: {ast.dump(node.value)}"
            )
        return

    if isinstance(node, ast.Name):
        if node.id in {"state", "True", "False", "None"}:
            return
        raise WorkflowError(f"Unsupported name: '{node.id}'")

    if isinstance(node, ast.Compare):
        _validate_node(node.left)
        for op_node, comparator in zip(node.ops, node.comparators):
            if type(op_node) not in _COMPARE_OPS:
                raise WorkflowError(f"Unsupported comparison: {type(op_node).__name__}")
            _validate_node(comparator)
        return

    if isinstance(node, ast.BoolOp):
        if type(node.op) not in _BOOL_OPS:
            raise WorkflowError(f"Unsupported boolean op: {type(node.op).__name__}")
        for value in node.values:
            _validate_node(value)
        return

    if isinstance(node, ast.UnaryOp):
        if type(node.op) not in _UNARY_OPS:
            raise WorkflowError(f"Unsupported unary op: {type(node.op).__name__}")
        _validate_node(node.operand)
        return

    raise WorkflowError(f"Unsupported expression node: {type(node).__name__}")


def _eval_node(node: ast.AST, state: dict[str, Any]) -> Any:  # noqa: PLR0911
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Attribute):
        if not isinstance(node.value, ast.Name) or node.value.id != "state":
            raise WorkflowError(
                f"Attribute access only allowed on 'state', got: {ast.dump(node.value)}"
            )
        dot = _DotDict(state)
        return getattr(dot, node.attr)

    if isinstance(node, ast.Name):
        if node.id == "state":
            return _DotDict(state)
        if node.id in ("True", "False", "None"):
            return {"True": True, "False": False, "None": None}[node.id]
        raise WorkflowError(f"Unsupported name: '{node.id}'")

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, state)
        for op_node, comparator in zip(node.ops, node.comparators):
            op_func = _COMPARE_OPS.get(type(op_node))
            if op_func is None:
                raise WorkflowError(f"Unsupported comparison: {type(op_node).__name__}")
            right = _eval_node(comparator, state)
            if not op_func(left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.BoolOp):
        op_func = _BOOL_OPS.get(type(node.op))
        if op_func is None:
            raise WorkflowError(f"Unsupported boolean op: {type(node.op).__name__}")
        values = [_eval_node(v, state) for v in node.values]
        return op_func(values)

    if isinstance(node, ast.UnaryOp):
        op_func = _UNARY_OPS.get(type(node.op))
        if op_func is None:
            raise WorkflowError(f"Unsupported unary op: {type(node.op).__name__}")
        return op_func(_eval_node(node.operand, state))

    raise WorkflowError(f"Unsupported expression node: {type(node).__name__}")


class _DotDict:
    """Dict wrapper allowing dot notation access for condition evaluation."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, key: str) -> Any:
        try:
            return self._data[key]
        except KeyError:
            raise AttributeError(key) from None
