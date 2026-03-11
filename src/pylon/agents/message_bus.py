"""Pub/Sub message bus for intra-workflow agent communication.

Implements MetaGPT-style topic-based messaging where agents subscribe
to action types (topics) and receive messages from other agents that
publish those actions.

Key design: agents never call each other directly. Communication flows
through the message bus, enabling loose coupling and observability.

The bus coexists with Pylon's state-based data passing (StatePatch) —
messages are transient coordination signals, not persistent state.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentMessage:
    """A message sent between agents through the message bus."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    sender: str = ""
    topic: str = ""  # Typically the action class name (MetaGPT pattern)
    content: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    reply_to: str | None = None  # ID of message this replies to


@dataclass
class Subscription:
    """A subscription binding an agent to a topic."""

    agent_id: str
    topic: str
    created_at: float = field(default_factory=time.time)


class AgentMessageBus:
    """Central message bus for agent-to-agent communication.

    Usage (MetaGPT-style):
        bus = AgentMessageBus()

        # Coder subscribes to "UserRequirement" messages
        bus.subscribe("coder", "UserRequirement")

        # Tester subscribes to "WriteCode" messages (Coder's output)
        bus.subscribe("tester", "WriteCode")

        # When Coder produces code, it publishes:
        bus.publish(AgentMessage(
            sender="coder",
            topic="WriteCode",
            content={"code": "def hello(): ..."},
        ))

        # Tester receives the message:
        messages = bus.poll("tester")
    """

    def __init__(self, *, max_buffer_per_agent: int = 100) -> None:
        self._subscriptions: dict[str, set[str]] = defaultdict(set)  # agent -> topics
        self._topic_subscribers: dict[str, set[str]] = defaultdict(set)  # topic -> agents
        self._mailboxes: dict[str, list[AgentMessage]] = defaultdict(list)
        self._max_buffer = max_buffer_per_agent
        self._history: list[AgentMessage] = []
        self._history_max = 1000

    def subscribe(self, agent_id: str, topic: str) -> Subscription:
        """Subscribe an agent to a topic."""
        self._subscriptions[agent_id].add(topic)
        self._topic_subscribers[topic].add(agent_id)
        return Subscription(agent_id=agent_id, topic=topic)

    def unsubscribe(self, agent_id: str, topic: str) -> None:
        """Unsubscribe an agent from a topic."""
        self._subscriptions[agent_id].discard(topic)
        self._topic_subscribers[topic].discard(agent_id)

    def watch(self, agent_id: str, topics: list[str]) -> list[Subscription]:
        """Subscribe an agent to multiple topics (MetaGPT _watch pattern)."""
        return [self.subscribe(agent_id, t) for t in topics]

    def publish(self, message: AgentMessage) -> int:
        """Publish a message to all subscribers of its topic.

        Returns the number of agents that received the message.
        """
        subscribers = self._topic_subscribers.get(message.topic, set())
        # Don't deliver to sender
        recipients = subscribers - {message.sender}

        for agent_id in recipients:
            mailbox = self._mailboxes[agent_id]
            mailbox.append(message)
            if len(mailbox) > self._max_buffer:
                self._mailboxes[agent_id] = mailbox[-self._max_buffer :]

        # Record history
        self._history.append(message)
        if len(self._history) > self._history_max:
            self._history = self._history[-self._history_max :]

        return len(recipients)

    def poll(
        self,
        agent_id: str,
        *,
        topic: str | None = None,
        clear: bool = True,
    ) -> list[AgentMessage]:
        """Retrieve pending messages for an agent.

        Args:
            agent_id: The receiving agent.
            topic: Filter by topic (None = all topics).
            clear: Remove messages after reading.

        Returns:
            List of pending messages.
        """
        mailbox = self._mailboxes.get(agent_id, [])

        if topic is not None:
            matching = [m for m in mailbox if m.topic == topic]
            if clear:
                self._mailboxes[agent_id] = [
                    m for m in mailbox if m.topic != topic
                ]
        else:
            matching = list(mailbox)
            if clear:
                self._mailboxes[agent_id] = []

        return matching

    def peek(self, agent_id: str) -> int:
        """Check how many pending messages an agent has."""
        return len(self._mailboxes.get(agent_id, []))

    def broadcast(self, message: AgentMessage) -> int:
        """Send a message to ALL registered agents (regardless of subscription).

        Note: the sender is excluded from recipients.
        """
        all_agents = set(self._subscriptions.keys()) - {message.sender}
        for agent_id in all_agents:
            self._mailboxes[agent_id].append(message)
        self._history.append(message)
        return len(all_agents)

    def get_subscriptions(self, agent_id: str) -> set[str]:
        """Get all topics an agent is subscribed to."""
        return set(self._subscriptions.get(agent_id, set()))

    def get_subscribers(self, topic: str) -> set[str]:
        """Get all agents subscribed to a topic."""
        return set(self._topic_subscribers.get(topic, set()))

    def get_recent_messages(
        self, *, limit: int = 50, topic: str | None = None
    ) -> list[AgentMessage]:
        """Get recent message history for observability."""
        messages = self._history
        if topic is not None:
            messages = [m for m in messages if m.topic == topic]
        return messages[-limit:]

    def clear_agent(self, agent_id: str) -> None:
        """Remove all subscriptions and pending messages for an agent."""
        topics = self._subscriptions.pop(agent_id, set())
        for topic in topics:
            self._topic_subscribers[topic].discard(agent_id)
        self._mailboxes.pop(agent_id, None)

    @property
    def agent_count(self) -> int:
        return len(self._subscriptions)

    @property
    def topic_count(self) -> int:
        return len(self._topic_subscribers)
