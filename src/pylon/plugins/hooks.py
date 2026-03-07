"""HookSystem - Plugin hook points and subscriptions."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class HookResult:
    """Result from a single hook handler invocation."""

    handler_name: str
    result: Any = None
    error: str | None = None
    duration: float = 0.0


@dataclass
class HookPoint:
    """A named hook point that handlers can subscribe to."""

    name: str
    description: str = ""


@dataclass
class _HookSubscription:
    id: str
    hook_name: str
    handler: Callable[[dict[str, Any]], Any]
    handler_name: str
    priority: int


class HookSystem:
    """Manages hook points and handler subscriptions."""

    def __init__(self) -> None:
        self._hooks: dict[str, HookPoint] = {}
        self._subscriptions: dict[str, list[_HookSubscription]] = {}

        for name, desc in _PREDEFINED_HOOKS:
            self.register_hook(name, desc)

    def register_hook(self, name: str, description: str = "") -> HookPoint:
        """Register a new hook point."""
        if name in self._hooks:
            raise ValueError(f"Hook already registered: {name}")
        hook = HookPoint(name=name, description=description)
        self._hooks[name] = hook
        self._subscriptions.setdefault(name, [])
        return hook

    def get_hook(self, name: str) -> HookPoint | None:
        return self._hooks.get(name)

    def list_hooks(self) -> list[HookPoint]:
        return list(self._hooks.values())

    def subscribe(
        self,
        hook_name: str,
        handler: Callable[[dict[str, Any]], Any],
        *,
        priority: int = 100,
        handler_name: str = "",
    ) -> str:
        """Subscribe a handler to a hook. Lower priority runs first."""
        if hook_name not in self._hooks:
            raise KeyError(f"Unknown hook: {hook_name}")
        sub_id = str(uuid.uuid4())
        sub = _HookSubscription(
            id=sub_id,
            hook_name=hook_name,
            handler=handler,
            handler_name=handler_name or f"handler-{sub_id[:8]}",
            priority=priority,
        )
        self._subscriptions[hook_name].append(sub)
        self._subscriptions[hook_name].sort(key=lambda s: s.priority)
        return sub_id

    def unsubscribe(self, hook_name: str, subscription_id: str) -> bool:
        """Remove a subscription. Returns True if found."""
        subs = self._subscriptions.get(hook_name, [])
        for i, sub in enumerate(subs):
            if sub.id == subscription_id:
                subs.pop(i)
                return True
        return False

    def trigger(self, hook_name: str, context: dict[str, Any] | None = None) -> list[HookResult]:
        """Trigger a hook, executing all subscribed handlers in priority order."""
        if hook_name not in self._hooks:
            raise KeyError(f"Unknown hook: {hook_name}")
        ctx = context or {}
        results: list[HookResult] = []
        for sub in self._subscriptions.get(hook_name, []):
            start = time.monotonic()
            try:
                result = sub.handler(ctx)
                duration = time.monotonic() - start
                results.append(
                    HookResult(
                        handler_name=sub.handler_name,
                        result=result,
                        duration=duration,
                    )
                )
            except Exception as e:
                duration = time.monotonic() - start
                results.append(
                    HookResult(
                        handler_name=sub.handler_name,
                        error=str(e),
                        duration=duration,
                    )
                )
        return results

    def subscriber_count(self, hook_name: str) -> int:
        return len(self._subscriptions.get(hook_name, []))


_PREDEFINED_HOOKS = [
    ("pre_agent_create", "Fired before an agent is created"),
    ("post_agent_create", "Fired after an agent is created"),
    ("pre_workflow_execute", "Fired before a workflow execution begins"),
    ("post_workflow_execute", "Fired after a workflow execution completes"),
    ("on_error", "Fired when an error occurs"),
]
