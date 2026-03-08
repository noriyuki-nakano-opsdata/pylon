from __future__ import annotations

from pylon.api.schemas import CREATE_AGENT_SCHEMA
from pylon.config.pipeline import (
    ValidationPipeline,
    build_validation_report,
    validate_project_definition,
)
from pylon.config.validator import AgentConfigSchema


class TestValidationPipeline:
    def test_project_definition_passes_all_stages(self) -> None:
        result = validate_project_definition(
            {
                "version": "1",
                "name": "demo",
                "agents": {"writer": {"autonomy": "A2"}},
                "workflow": {
                    "nodes": {
                        "start": {"agent": "writer", "next": "END"},
                    }
                },
            }
        )
        assert result.valid is True
        assert result.issues == []
        assert result.stages_passed == ["schema", "semantic", "referential", "protocol"]

    def test_project_definition_reports_semantic_issue(self) -> None:
        result = validate_project_definition(
            {
                "version": "1",
                "name": "demo",
                "agents": {"writer": {"autonomy": "A9"}},
                "workflow": {"nodes": {"start": {"agent": "writer", "next": "END"}}},
            }
        )
        assert result.valid is False
        assert result.issues[0].stage == "semantic"
        assert result.issues[0].field == "agents.writer.autonomy"

    def test_project_definition_reports_referential_issue(self) -> None:
        result = validate_project_definition(
            {
                "version": "1",
                "name": "demo",
                "agents": {"writer": {"role": "write"}},
                "workflow": {"nodes": {"start": {"agent": "missing", "next": "END"}}},
            }
        )
        assert result.valid is False
        assert result.issues[0].stage == "referential"
        assert result.issues[0].field == "workflow.nodes.start.agent"

    def test_project_definition_reports_protocol_warning_for_multiple_entries(self) -> None:
        result = validate_project_definition(
            {
                "version": "1",
                "name": "demo",
                "agents": {"writer": {"role": "write"}},
                "workflow": {
                    "nodes": {
                        "start": {"agent": "writer", "next": "END"},
                        "other": {"agent": "writer", "next": "END"},
                    }
                },
            }
        )
        assert result.valid is True
        assert len(result.warnings) == 1
        assert result.warnings[0].stage == "protocol"

    def test_build_validation_report_normalizes_counts(self) -> None:
        result = validate_project_definition(
            {
                "version": "1",
                "name": "demo",
                "agents": {"writer": {"role": "write"}},
                "workflow": {
                    "nodes": {
                        "start": {"agent": "writer", "next": "END"},
                        "other": {"agent": "writer", "next": "END"},
                    }
                },
            }
        )
        report = build_validation_report(result)
        assert report["source"] == "project_definition"
        assert report["valid"] is True
        assert report["summary"] == {"error_count": 0, "warning_count": 1}
        assert report["warnings"][0]["stage"] == "protocol"

    def test_config_schema_pipeline_delegates_to_config_validator(self) -> None:
        pipeline = ValidationPipeline.for_config_schema(AgentConfigSchema)
        result = pipeline.run({"autonomy": "A2"})
        assert result.valid is False
        assert result.issues[0].stage == "schema"
        assert result.issues[0].field == "name"

    def test_api_schema_pipeline_delegates_to_api_validator(self) -> None:
        pipeline = ValidationPipeline.for_api_schema(CREATE_AGENT_SCHEMA)
        result = pipeline.run({"name": 123})
        assert result.valid is False
        assert result.issues[0].stage == "schema"
        assert result.issues[0].field == "body"
