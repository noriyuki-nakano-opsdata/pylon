"""Tests for lifecycle state invalidation helpers."""

from pylon.lifecycle.contracts import (
    _check_status,
    _is_valid_source_url,
    _looks_like_prototype_html,
)
from pylon.lifecycle.orchestrator import default_lifecycle_project_record
from pylon.lifecycle.state import (
    build_lifecycle_invalidation_patch,
    prune_lifecycle_records_from_phase,
    rebuild_lifecycle_phase_statuses,
)


def _project() -> dict[str, object]:
    project = default_lifecycle_project_record("orbit", tenant_id="default")
    project.update(
        {
            "researchOperatorDecision": {"mode": "conditional_handoff"},
            "research": {"summary": "evidence"},
            "analysis": {"personas": [{"name": "Operator"}]},
            "features": [{"feature": "Artifact lineage", "selected": True}],
            "milestones": [{"id": "ms-1", "name": "Alpha"}],
            "designVariants": [{"id": "design-1"}],
            "selectedDesignId": "design-1",
            "approvalStatus": "approved",
            "approvalComments": [{"id": "approval-1"}],
            "approvalRequestId": "apr_demo",
            "buildCode": "<html>preview</html>",
            "deployChecks": [{"id": "dq-1", "status": "pass"}],
            "releases": [{"id": "rel-1"}],
            "feedbackItems": [{"id": "fb-1"}],
            "artifacts": [
                {"id": "a-research", "phase": "research"},
                {"id": "a-planning", "phase": "planning"},
                {"id": "a-design", "phase": "design"},
                {"id": "a-development", "phase": "development"},
                {"id": "a-deploy", "phase": "deploy"},
            ],
            "decisionLog": [
                {"id": "d-research", "phase": "research"},
                {"id": "d-approval", "phase": "approval"},
                {"id": "d-deploy", "phase": "deploy"},
            ],
            "skillInvocations": [
                {"id": "s-research", "phase": "research"},
                {"id": "s-development", "phase": "development"},
            ],
            "delegations": [
                {"id": "g-planning", "phase": "planning"},
                {"id": "g-deploy", "phase": "deploy"},
            ],
            "phaseRuns": [
                {"id": "run-research", "phase": "research"},
                {"id": "run-design", "phase": "design"},
                {"id": "run-deploy", "phase": "deploy"},
            ],
        }
    )
    return project


def test_rebuild_phase_statuses_unlocks_only_next_phase():
    project = _project()

    statuses = rebuild_lifecycle_phase_statuses(project, completed_until="planning")
    lookup = {item["phase"]: item["status"] for item in statuses}

    assert lookup["research"] == "completed"
    assert lookup["planning"] == "completed"
    assert lookup["design"] == "available"
    assert lookup["development"] == "locked"
    assert lookup["approval"] == "locked"


def test_prune_records_from_phase_keeps_only_upstream_trace():
    project = _project()

    pruned = prune_lifecycle_records_from_phase(project, phase="design")

    assert [item["id"] for item in pruned["artifacts"]] == ["a-research", "a-planning"]
    assert [item["id"] for item in pruned["decisionLog"]] == ["d-research"]
    assert [item["id"] for item in pruned["skillInvocations"]] == ["s-research"]
    assert [item["id"] for item in pruned["delegations"]] == ["g-planning"]
    assert [item["id"] for item in pruned["phaseRuns"]] == ["run-research"]


def test_spec_change_invalidates_all_downstream_state_and_trace():
    project = _project()

    invalidation = build_lifecycle_invalidation_patch(project, changed_fields={"spec"})
    patch = invalidation["patch"]
    phase_lookup = {item["phase"]: item["status"] for item in patch["phaseStatuses"]}

    assert invalidation["reset_from"] == "research"
    assert patch["researchOperatorDecision"] is None
    assert patch["research"] is None
    assert patch["analysis"] is None
    assert patch["designVariants"] == []
    assert patch["buildCode"] is None
    assert patch["releases"] == []
    assert patch["feedbackItems"] == []
    assert patch["approvalRequestId"] is None
    assert patch["artifacts"] == []
    assert patch["decisionLog"] == []
    assert patch["skillInvocations"] == []
    assert patch["delegations"] == []
    assert patch["phaseRuns"] == []
    assert phase_lookup["research"] == "available"
    assert phase_lookup["planning"] == "locked"


def test_planning_change_preserves_research_but_clears_design_and_later():
    project = _project()

    invalidation = build_lifecycle_invalidation_patch(project, changed_fields={"features"})
    patch = invalidation["patch"]

    assert invalidation["reset_from"] == "design"
    assert patch["buildCode"] is None
    assert patch["deployChecks"] == []
    assert patch["releases"] == []
    assert patch["feedbackItems"] == []
    assert [item["id"] for item in patch["artifacts"]] == ["a-research", "a-planning"]
    assert [item["id"] for item in patch["decisionLog"]] == ["d-research"]


# ---------------------------------------------------------------------------
# _check_status tests
# ---------------------------------------------------------------------------

def test_check_status_exact_match():
    assert _check_status("complete", "complete") is True


def test_check_status_case_insensitive():
    assert _check_status("Complete", "complete") is True
    assert _check_status("PASSED", "passed") is True


def test_check_status_strips_whitespace():
    assert _check_status("  complete  ", "complete") is True


def test_check_status_none_returns_false():
    assert _check_status(None, "complete") is False


def test_check_status_empty_string_returns_false():
    assert _check_status("", "complete") is False


def test_check_status_mismatch():
    assert _check_status("partial", "complete") is False


# ---------------------------------------------------------------------------
# _is_valid_source_url tests
# ---------------------------------------------------------------------------

def test_is_valid_source_url_accepts_https():
    assert _is_valid_source_url("https://example.com/page") is True


def test_is_valid_source_url_accepts_http():
    assert _is_valid_source_url("http://example.com") is True


def test_is_valid_source_url_rejects_ftp():
    assert _is_valid_source_url("ftp://example.com") is False


def test_is_valid_source_url_rejects_empty():
    assert _is_valid_source_url("") is False
    assert _is_valid_source_url(None) is False


def test_is_valid_source_url_rejects_bare_string():
    assert _is_valid_source_url("just some text") is False


def test_is_valid_source_url_rejects_scheme_only():
    assert _is_valid_source_url("https://") is False


# ---------------------------------------------------------------------------
# _looks_like_prototype_html (schema-based) tests
# ---------------------------------------------------------------------------

def test_looks_like_prototype_html_valid_english():
    html = """
    <html>
      <body data-prototype-kind="dashboard">
        <main>
          <nav aria-label="primary navigation"></nav>
          <section data-screen-id="home"></section>
        </main>
      </body>
    </html>
    """
    assert _looks_like_prototype_html(html) is True


def test_looks_like_prototype_html_valid_japanese_nav():
    html = """
    <html lang="ja">
      <body data-prototype-kind="control-center">
        <main>
          <nav aria-label="主要ナビゲーション"></nav>
          <section data-screen-id="workspace"></section>
        </main>
      </body>
    </html>
    """
    assert _looks_like_prototype_html(html) is True


def test_looks_like_prototype_html_tablist_role():
    html = """
    <html>
      <body data-prototype-kind="app">
        <main>
          <nav role="tablist"></nav>
          <div data-screen-id="s1"></div>
        </main>
      </body>
    </html>
    """
    assert _looks_like_prototype_html(html) is True


def test_looks_like_prototype_html_missing_nav():
    html = """
    <html>
      <body data-prototype-kind="app">
        <main>
          <div data-screen-id="s1"></div>
        </main>
      </body>
    </html>
    """
    assert _looks_like_prototype_html(html) is False


def test_looks_like_prototype_html_missing_screen():
    html = """
    <html>
      <body data-prototype-kind="app">
        <main>
          <nav aria-label="primary navigation"></nav>
        </main>
      </body>
    </html>
    """
    assert _looks_like_prototype_html(html) is False


def test_looks_like_prototype_html_missing_prototype_kind():
    html = """
    <html>
      <main>
        <nav aria-label="primary navigation"></nav>
        <div data-screen-id="s1"></div>
      </main>
    </html>
    """
    assert _looks_like_prototype_html(html) is False


def test_looks_like_prototype_html_empty_string():
    assert _looks_like_prototype_html("") is False
    assert _looks_like_prototype_html(None) is False
