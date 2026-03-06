"""StateMachine - generic finite state machine with guards and history."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class InvalidTransitionError(RuntimeError):
    def __init__(self, current: str, event: str) -> None:
        self.current_state = current
        self.event = event
        super().__init__(f"No transition from '{current}' on event '{event}'")


class StateNotFoundError(KeyError):
    pass


@dataclass
class TransitionRecord:
    from_state: str
    to_state: str
    event: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class StateDefinition:
    name: str
    on_enter: Callable[[str], None] | None = None
    on_exit: Callable[[str], None] | None = None


@dataclass
class Transition:
    from_state: str
    to_state: str
    event: str
    guard: Callable[[], bool] | None = None


@dataclass
class StateMachineConfig:
    initial_state: str = ""
    allow_self_transitions: bool = False


class StateMachine:
    def __init__(self, config: StateMachineConfig | None = None) -> None:
        self._config = config or StateMachineConfig()
        self._states: dict[str, StateDefinition] = {}
        self._transitions: list[Transition] = []
        self._current: str = ""
        self._history: list[TransitionRecord] = []
        self._started: bool = False

    @property
    def current_state(self) -> str:
        return self._current

    @property
    def history(self) -> list[TransitionRecord]:
        return list(self._history)

    def add_state(
        self,
        name: str,
        on_enter: Callable[[str], None] | None = None,
        on_exit: Callable[[str], None] | None = None,
    ) -> None:
        self._states[name] = StateDefinition(name=name, on_enter=on_enter, on_exit=on_exit)

    def add_transition(
        self,
        from_state: str,
        to_state: str,
        event: str,
        guard: Callable[[], bool] | None = None,
    ) -> None:
        self._transitions.append(Transition(
            from_state=from_state,
            to_state=to_state,
            event=event,
            guard=guard,
        ))

    def start(self) -> None:
        if not self._config.initial_state:
            raise ValueError("No initial state configured")
        if self._config.initial_state not in self._states:
            raise StateNotFoundError(self._config.initial_state)
        self._current = self._config.initial_state
        self._started = True
        state_def = self._states[self._current]
        if state_def.on_enter:
            state_def.on_enter(self._current)

    def trigger(self, event: str) -> str:
        if not self._started:
            raise RuntimeError("State machine not started")

        for t in self._transitions:
            if t.from_state != self._current or t.event != event:
                continue
            if not self._config.allow_self_transitions and t.to_state == self._current:
                continue
            if t.guard is not None and not t.guard():
                continue

            # Execute transition
            old_state = self._states.get(self._current)
            if old_state and old_state.on_exit:
                old_state.on_exit(self._current)

            prev = self._current
            self._current = t.to_state

            new_state = self._states.get(self._current)
            if new_state and new_state.on_enter:
                new_state.on_enter(self._current)

            self._history.append(TransitionRecord(
                from_state=prev,
                to_state=self._current,
                event=event,
            ))
            return self._current

        raise InvalidTransitionError(self._current, event)

    def get_available_events(self) -> list[str]:
        events = []
        for t in self._transitions:
            if t.from_state == self._current:
                if not self._config.allow_self_transitions and t.to_state == self._current:
                    continue
                events.append(t.event)
        return events
