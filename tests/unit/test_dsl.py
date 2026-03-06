"""Tests for pylon.yaml DSL parser."""

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from pylon.dsl.parser import PylonProject, load_project


MINIMAL_YAML = """
version: "1"
name: test-project
agents:
  planner:
    model: anthropic/claude-sonnet-4-20250514
    role: Plan tasks
    autonomy: A2
    tools: [file-read]
workflow:
  type: graph
  nodes:
    plan:
      agent: planner
      next: END
"""

PR_REVIEW_YAML = """
version: "1"
name: pr-review-pipeline
description: Automated code review

agents:
  planner:
    model: anthropic/claude-sonnet-4-20250514
    role: Analyze PR diffs
    autonomy: A2
    tools: [github-pr-read, file-read]
  reviewer:
    model: anthropic/claude-sonnet-4-20250514
    role: Execute review plan
    autonomy: A2
    tools: [github-pr-comment, file-read]
  approver:
    model: anthropic/claude-sonnet-4-20250514
    role: Final review gate
    autonomy: A3
    tools: [github-pr-approve]

workflow:
  type: graph
  nodes:
    analyze:
      agent: planner
      next: review
    review:
      agent: reviewer
      next:
        - target: approve
          condition: "state.issues_found > 0"
        - target: END
          condition: "state.issues_found == 0"
    approve:
      agent: approver
      next: END

policy:
  max_cost_usd: 5.0
  max_duration: 30m
  require_approval_above: A3
"""


class TestPylonProject:
    def test_minimal_parse(self):
        project = PylonProject.model_validate(
            {"version": "1", "name": "test", "agents": {}, "workflow": {"type": "graph"}}
        )
        assert project.name == "test"
        assert project.version == "1"

    def test_default_policy(self):
        project = PylonProject.model_validate({"version": "1", "name": "test"})
        assert project.policy.max_cost_usd == 10.0
        assert project.policy.max_duration == "60m"
        assert project.policy.require_approval_above == "A3"


class TestLoadProject:
    def test_load_minimal_yaml(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write(MINIMAL_YAML)
            f.flush()
            project = load_project(f.name)
        assert project.name == "test-project"
        assert "planner" in project.agents
        assert project.agents["planner"].autonomy == "A2"

    def test_load_pr_review(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write(PR_REVIEW_YAML)
            f.flush()
            project = load_project(f.name)
        assert len(project.agents) == 3
        assert project.agents["approver"].autonomy == "A3"
        assert project.policy.max_cost_usd == 5.0

    def test_load_from_directory(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pylon.yaml"
            path.write_text(MINIMAL_YAML)
            project = load_project(d)
        assert project.name == "test-project"

    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_project("/nonexistent/path")

    def test_undefined_agent_in_workflow(self):
        bad_yaml = """
version: "1"
name: bad
agents:
  planner:
    role: test
workflow:
  type: graph
  nodes:
    step1:
      agent: nonexistent
      next: END
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write(bad_yaml)
            f.flush()
            with pytest.raises(ValidationError, match="nonexistent"):
                load_project(f.name)

    def test_undefined_target_in_workflow(self):
        bad_yaml = """
version: "1"
name: bad
agents:
  planner:
    role: test
workflow:
  type: graph
  nodes:
    step1:
      agent: planner
      next: nonexistent_node
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write(bad_yaml)
            f.flush()
            with pytest.raises(ValidationError, match="nonexistent_node"):
                load_project(f.name)

    def test_invalid_autonomy_level(self):
        bad_yaml = """
version: "1"
name: bad
agents:
  planner:
    autonomy: A5
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write(bad_yaml)
            f.flush()
            with pytest.raises(ValidationError, match="A5"):
                load_project(f.name)

    def test_duration_parsing(self):
        project = PylonProject.model_validate({
            "version": "1",
            "name": "test",
            "policy": {"max_duration": "30m"},
        })
        assert project.policy.max_duration_seconds() == 1800
