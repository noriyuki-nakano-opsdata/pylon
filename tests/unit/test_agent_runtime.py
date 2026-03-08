"""Tests for agent runtime lifecycle."""

import pytest

from pylon.agents.runtime import Agent, HandoffData
from pylon.errors import AgentLifecycleError
from pylon.types import AgentConfig, AgentState


class TestAgentLifecycle:
    def test_full_lifecycle(self):
        agent = Agent(config=AgentConfig(name="test"))
        assert agent.state == AgentState.INIT

        agent.initialize()
        assert agent.state == AgentState.READY

        agent.start()
        assert agent.state == AgentState.RUNNING

        agent.complete()
        assert agent.state == AgentState.COMPLETED
        assert agent.is_terminal

    def test_pause_resume(self):
        agent = Agent(config=AgentConfig(name="test"))
        agent.initialize()
        agent.start()
        agent.pause()
        assert agent.state == AgentState.PAUSED
        agent.resume()
        assert agent.state == AgentState.RUNNING

    def test_kill_clears_memory(self):
        agent = Agent(config=AgentConfig(name="test"))
        agent.working_memory["key"] = "value"
        agent.initialize()
        agent.start()
        agent.kill()
        assert agent.state == AgentState.KILLED
        assert agent.working_memory == {}
        assert agent.last_handoff is not None
        assert agent.last_handoff.working_memory == {"key": "value"}

    def test_invalid_transition(self):
        agent = Agent(config=AgentConfig(name="test"))
        with pytest.raises(AgentLifecycleError):
            agent.start()  # Can't go from INIT to RUNNING directly

    def test_terminal_no_transition(self):
        agent = Agent(config=AgentConfig(name="test"))
        agent.initialize()
        agent.start()
        agent.complete()
        with pytest.raises(AgentLifecycleError):
            agent.start()

    def test_generate_and_restore_handoff(self):
        agent = Agent(config=AgentConfig(name="test"))
        agent.initialize()
        agent.start()
        agent.working_memory.update({"task": "refactor", "attempt": 2})

        handoff = agent.generate_handoff(restart_count=1, note="supervisor restart")
        assert isinstance(handoff, HandoffData)
        assert handoff.working_memory == {"task": "refactor", "attempt": 2}
        assert handoff.restart_count == 1

        restored = Agent(config=AgentConfig(name="test"))
        restored.restore_from_handoff(handoff)
        assert restored.working_memory == {"task": "refactor", "attempt": 2}
