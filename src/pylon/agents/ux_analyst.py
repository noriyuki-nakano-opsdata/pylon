"""UX Analysis Agent — comprehensive product/service analysis.

Performs multi-framework analysis:
  - User Journey Mapping
  - User Stories (Connextra format)
  - Job Stories (JTBD-based)
  - Jobs To Be Done (JTBD)
  - KANO Model Classification
  - Business Model Canvas
  - Business Process Analysis
  - Persona Analysis
  - Use Case Analysis

Each analysis is a node in a Pylon workflow DAG.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

# ── Domain Models ──


class KanoCategory(enum.StrEnum):
    MUST_BE = "must-be"
    ONE_DIMENSIONAL = "one-dimensional"
    ATTRACTIVE = "attractive"
    INDIFFERENT = "indifferent"
    REVERSE = "reverse"


@dataclass
class Persona:
    name: str
    role: str
    age_range: str
    goals: list[str]
    frustrations: list[str]
    tech_proficiency: str
    context: str


@dataclass
class UserJourneyStep:
    phase: str
    action: str
    touchpoint: str
    emotion: str  # positive / neutral / negative
    pain_points: list[str]
    opportunities: list[str]


@dataclass
class UserStory:
    role: str
    action: str
    benefit: str
    acceptance_criteria: list[str]
    priority: str  # must / should / could / wont

    @property
    def text(self) -> str:
        return f"As a {self.role}, I want to {self.action}, so that {self.benefit}"


@dataclass
class JobStory:
    situation: str
    motivation: str
    outcome: str
    forces: list[str]

    @property
    def text(self) -> str:
        return f"When {self.situation}, I want to {self.motivation}, so I can {self.outcome}"


@dataclass
class JTBDJob:
    job_performer: str
    core_job: str
    job_steps: list[str]
    desired_outcomes: list[str]
    constraints: list[str]
    emotional_jobs: list[str]
    social_jobs: list[str]


@dataclass
class KanoFeature:
    feature: str
    category: KanoCategory
    user_delight: float  # -1.0 to 1.0
    implementation_cost: str  # low / medium / high
    rationale: str


@dataclass
class BusinessModelElement:
    key_partners: list[str]
    key_activities: list[str]
    key_resources: list[str]
    value_propositions: list[str]
    customer_relationships: list[str]
    channels: list[str]
    customer_segments: list[str]
    cost_structure: list[str]
    revenue_streams: list[str]


@dataclass
class BusinessProcess:
    process_name: str
    trigger: str
    steps: list[dict[str, str]]  # {actor, action, system, output}
    exceptions: list[str]
    kpis: list[str]


@dataclass
class UseCase:
    name: str
    actor: str
    preconditions: list[str]
    main_flow: list[str]
    alternative_flows: list[dict[str, Any]]
    postconditions: list[str]
    business_rules: list[str]


@dataclass
class UXAnalysisResult:
    """Aggregated output of the full UX analysis pipeline."""
    product_name: str
    product_description: str
    personas: list[Persona] = field(default_factory=list)
    user_journeys: list[list[UserJourneyStep]] = field(default_factory=list)
    user_stories: list[UserStory] = field(default_factory=list)
    job_stories: list[JobStory] = field(default_factory=list)
    jtbd_jobs: list[JTBDJob] = field(default_factory=list)
    kano_features: list[KanoFeature] = field(default_factory=list)
    business_model: BusinessModelElement | None = None
    business_processes: list[BusinessProcess] = field(default_factory=list)
    use_cases: list[UseCase] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


# ── Prompt Templates ──

SYSTEM_PROMPT = (
    "You are a world-class UX strategist and product analyst. "
    "You combine expertise in user research, business analysis, and product strategy. "
    "Your analyses are thorough, actionable, and grounded in established frameworks. "
    "Always output valid JSON matching the requested schema."
)

ANALYSIS_PROMPTS: dict[str, str] = {
    "persona": (
        "Analyze the following product/service and create 3-5 detailed personas.\n\n"
        "For each persona provide:\n"
        "- name: A representative name\n"
        "- role: Their job title or role\n"
        "- age_range: e.g. '25-35'\n"
        "- goals: List of 3-5 goals\n"
        "- frustrations: List of 3-5 pain points\n"
        "- tech_proficiency: low / medium / high\n"
        "- context: Usage context description\n\n"
        "Output as JSON array of persona objects.\n\n"
        "Product: {spec}"
    ),
    "user_journey": (
        "Create detailed user journey maps for each persona.\n\n"
        "For each journey, create 5-8 steps with:\n"
        "- phase: Discovery / Onboarding / Usage / Retention / Advocacy\n"
        "- action: What the user does\n"
        "- touchpoint: Where the interaction happens\n"
        "- emotion: positive / neutral / negative\n"
        "- pain_points: List of friction points\n"
        "- opportunities: List of improvement opportunities\n\n"
        "Output as JSON array of journey arrays.\n\n"
        "Product: {spec}\n\nPersonas: {personas}"
    ),
    "user_story": (
        "Generate comprehensive user stories in Connextra format.\n\n"
        "For each story provide:\n"
        "- role: The user role\n"
        "- action: What they want to do\n"
        "- benefit: Why they want it\n"
        "- acceptance_criteria: List of specific criteria\n"
        "- priority: must / should / could / wont (MoSCoW)\n\n"
        "Generate 15-25 stories covering all major features.\n"
        "Output as JSON array.\n\n"
        "Product: {spec}\n\nPersonas: {personas}"
    ),
    "job_story": (
        "Create job stories based on JTBD methodology.\n\n"
        "For each story provide:\n"
        "- situation: The triggering context\n"
        "- motivation: What the user wants to achieve\n"
        "- outcome: The desired end state\n"
        "- forces: Push/pull forces and anxieties\n\n"
        "Generate 10-15 job stories.\n"
        "Output as JSON array.\n\n"
        "Product: {spec}\n\nPersonas: {personas}"
    ),
    "jtbd": (
        "Perform a thorough Jobs To Be Done analysis.\n\n"
        "For each job provide:\n"
        "- job_performer: Who performs the job\n"
        "- core_job: The main job to be done\n"
        "- job_steps: Ordered steps in the job\n"
        "- desired_outcomes: Measurable outcomes\n"
        "- constraints: Limitations and constraints\n"
        "- emotional_jobs: Emotional aspects\n"
        "- social_jobs: Social aspects\n\n"
        "Identify 5-8 core jobs.\n"
        "Output as JSON array.\n\n"
        "Product: {spec}\n\nPersonas: {personas}"
    ),
    "kano": (
        "Classify product features using the KANO model.\n\n"
        "For each feature provide:\n"
        "- feature: Feature name\n"
        "- category: must-be / one-dimensional / attractive / indifferent / reverse\n"
        "- user_delight: -1.0 to 1.0\n"
        "- implementation_cost: low / medium / high\n"
        "- rationale: Why this classification\n\n"
        "Analyze 15-20 features.\n"
        "Output as JSON array.\n\n"
        "Product: {spec}\n\nUser Stories: {user_stories}"
    ),
    "business_model": (
        "Create a Business Model Canvas analysis.\n\n"
        "Provide:\n"
        "- key_partners: List\n"
        "- key_activities: List\n"
        "- key_resources: List\n"
        "- value_propositions: List\n"
        "- customer_relationships: List\n"
        "- channels: List\n"
        "- customer_segments: List\n"
        "- cost_structure: List\n"
        "- revenue_streams: List\n\n"
        "Output as JSON object.\n\n"
        "Product: {spec}"
    ),
    "business_process": (
        "Analyze key business processes.\n\n"
        "For each process provide:\n"
        "- process_name: Name\n"
        "- trigger: What starts the process\n"
        "- steps: Array of {{actor, action, system, output}}\n"
        "- exceptions: Error/edge cases\n"
        "- kpis: Key performance indicators\n\n"
        "Identify 5-8 core processes.\n"
        "Output as JSON array.\n\n"
        "Product: {spec}\n\nBusiness Model: {business_model}"
    ),
    "use_case": (
        "Create detailed use case specifications.\n\n"
        "For each use case provide:\n"
        "- name: Use case name\n"
        "- actor: Primary actor\n"
        "- preconditions: List\n"
        "- main_flow: Ordered list of steps\n"
        "- alternative_flows: List of {{condition, steps}} objects\n"
        "- postconditions: List\n"
        "- business_rules: List\n\n"
        "Create 8-12 use cases.\n"
        "Output as JSON array.\n\n"
        "Product: {spec}\n\nUser Stories: {user_stories}"
    ),
    "recommendations": (
        "Based on all the analysis performed, provide strategic recommendations.\n\n"
        "Cover:\n"
        "1. Quick wins (high impact, low effort)\n"
        "2. Strategic investments (high impact, high effort)\n"
        "3. UX improvements based on journey pain points\n"
        "4. Feature prioritization based on KANO analysis\n"
        "5. Business model optimization opportunities\n"
        "6. Risk mitigation strategies\n\n"
        "Output as JSON array of recommendation strings.\n\n"
        "Product: {spec}\n\n"
        "KANO Analysis: {kano}\n\n"
        "User Journeys: {user_journeys}\n\n"
        "Business Model: {business_model}"
    ),
}


def build_ux_analysis_workflow() -> dict[str, Any]:
    """Return a Pylon workflow definition for the full UX analysis pipeline.

    DAG structure:
        spec_input
            ├── persona_analysis
            │       ├── user_journey_mapping
            │       ├── user_story_generation
            │       │       ├── kano_classification
            │       │       └── use_case_analysis
            │       ├── job_story_generation
            │       └── jtbd_analysis
            └── business_model_analysis
                    └── business_process_analysis
                                └── recommendations (joins all)
    """
    return {
        "version": "1",
        "name": "ux-analysis",
        "description": "Comprehensive UX & Business Analysis Pipeline",
        "agents": {
            "ux-analyst": {
                "model": "anthropic/claude-sonnet-4-20250514",
                "role": "UX strategist and product analyst",
                "autonomy": "A2",
                "tools": [],
                "sandbox": "gvisor",
            },
        },
        "workflow": {
            "type": "graph",
            "nodes": {
                "persona_analysis": {
                    "agent": "ux-analyst",
                    "node_type": "agent",
                    "next": [
                        "user_journey_mapping",
                        "user_story_generation",
                        "job_story_generation",
                        "jtbd_analysis",
                    ],
                },
                "user_journey_mapping": {
                    "agent": "ux-analyst",
                    "node_type": "agent",
                    "next": "recommendations",
                },
                "user_story_generation": {
                    "agent": "ux-analyst",
                    "node_type": "agent",
                    "next": ["kano_classification", "use_case_analysis"],
                },
                "job_story_generation": {
                    "agent": "ux-analyst",
                    "node_type": "agent",
                    "next": "recommendations",
                },
                "jtbd_analysis": {
                    "agent": "ux-analyst",
                    "node_type": "agent",
                    "next": "recommendations",
                },
                "kano_classification": {
                    "agent": "ux-analyst",
                    "node_type": "agent",
                    "next": "recommendations",
                },
                "use_case_analysis": {
                    "agent": "ux-analyst",
                    "node_type": "agent",
                    "next": "recommendations",
                },
                "business_model_analysis": {
                    "agent": "ux-analyst",
                    "node_type": "agent",
                    "next": "business_process_analysis",
                },
                "business_process_analysis": {
                    "agent": "ux-analyst",
                    "node_type": "agent",
                    "next": "recommendations",
                },
                "recommendations": {
                    "agent": "ux-analyst",
                    "node_type": "agent",
                    "next": "END",
                },
            },
        },
        "policy": {
            "max_cost_usd": 10.0,
            "require_approval_above": "A4",
        },
    }
