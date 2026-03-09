# Autonomous Research Report Pipeline

A fully autonomous (A4) multi-agent example that researches a topic from
academic and industry sources, synthesizes findings, and produces a
publication-ready report.

## Architecture

Six specialised agents collaborate in a DAG workflow with parallel fan-out
at the research stage and a sequential editorial pipeline.

```mermaid
graph TD
    START((Start)) --> research_academic
    START --> research_industry

    research_academic["researcher_a<br/><i>Academic sources</i>"]
    research_industry["researcher_b<br/><i>Industry sources</i>"]

    research_academic --> synthesize
    research_industry --> synthesize

    synthesize["synthesizer<br/><i>join_policy: ALL_RESOLVED</i>"]
    synthesize --> write_report

    write_report["writer<br/><i>Draft report</i>"]
    write_report --> verify_facts

    verify_facts["fact_checker<br/><i>Verify claims</i>"]
    verify_facts --> final_edit

    final_edit["editor<br/><i>Final polish</i>"]
    final_edit --> END((End))

    style research_academic fill:#e8f4fd,stroke:#1e88e5
    style research_industry fill:#e8f4fd,stroke:#1e88e5
    style synthesize fill:#fff3e0,stroke:#fb8c00
    style write_report fill:#e8f5e9,stroke:#43a047
    style verify_facts fill:#fce4ec,stroke:#e53935
    style final_edit fill:#f3e5f5,stroke:#8e24aa
```

## Agents

| Agent | Autonomy | Role |
|-------|----------|------|
| `researcher_a` | A4 | Searches academic databases and journals |
| `researcher_b` | A4 | Searches industry reports and whitepapers |
| `synthesizer` | A4 | Merges and reconciles findings from both researchers |
| `writer` | A4 | Writes the structured research report |
| `fact_checker` | A4 | Verifies every claim and citation |
| `editor` | A4 | Final grammar, style, and formatting pass |

## Guardrails

- **Cost cap**: $3.00 USD
- **Timeout**: 20 minutes
- **Max iterations**: 15
- **Factual accuracy threshold**: 95%
- **Coverage threshold**: 80%
- **Effect scope**: agents may only write under `report/`
- **Audit log**: required

## Usage

```bash
pylon run --file pylon.yaml --input "topic: Large Language Model Alignment"
```
