# Pylon Product Lifecycle Multi-Agent Flow

This document visualizes the current Pylon product cycle as a multi-agent operating model.
It is aligned with `PHASE_ORDER`, `build_lifecycle_phase_blueprints(...)`, and the lifecycle quality contracts in:

- `src/pylon/lifecycle/orchestrator.py`
- `src/pylon/lifecycle/contracts.py`

## 1. Lifecycle Overview

```mermaid
flowchart TD
    Start([Project intent<br/>Operator goal])

    subgraph Research["Research Swarm"]
        R1[Competitor Scout]
        R2[Market Researcher]
        R3[User Researcher]
        R4[Tech Evaluator]
        R5[Research Synthesizer]
        R6[Evidence Librarian]
        R7[Devil's Advocate]
        R8[Cross Examiner]
        R9[Research Judge]
        RA[(market-research<br/>competitor-map<br/>risk-register<br/>claim-ledger)]

        R1 --> R5
        R2 --> R5
        R3 --> R5
        R4 --> R5
        R5 --> R6
        R5 --> R7
        R6 --> R8
        R7 --> R8
        R8 --> R9
        R9 --> RA
    end

    subgraph Planning["Planning Council"]
        P1[Persona Builder]
        P2[Story Architect]
        P3[Feature Analyst]
        P4[Solution Architect]
        P5[Planning Synthesizer]
        P6[Scope Skeptic]
        P7[Assumption Auditor]
        P8[Negative Persona Challenger]
        P9[Milestone Falsifier]
        P10[Planning Judge]
        PA[(product-brief<br/>delivery-plan<br/>milestone-plan<br/>decision-table)]

        P1 --> P5
        P2 --> P5
        P3 --> P5
        P4 --> P5
        P5 --> P6
        P5 --> P7
        P5 --> P8
        P5 --> P9
        P6 --> P10
        P7 --> P10
        P8 --> P10
        P9 --> P10
        P10 --> PA
    end

    subgraph Design["Design Jury"]
        D1[Concept Designer A]
        D2[Concept Designer B]
        D3[Preview Validator A]
        D4[Preview Validator B]
        D5[Design Judge]
        DA[(design-candidates<br/>design-scorecard<br/>selected prototype)]

        D1 --> D3
        D2 --> D4
        D3 --> D5
        D4 --> D5
        D5 --> DA
    end

    subgraph Approval["Approval Gate"]
        A1[Approval Chair]
        A2{Approve or rework?}
        AA[(approval-thread<br/>decision history)]

        A1 --> A2
        A2 --> AA
    end

    subgraph Development["Autonomous Delivery Mesh"]
        V1[Build Planner]
        V2[Frontend Builder]
        V3[Backend Builder]
        V4[Integrator]
        V5[QA Engineer]
        V6[Security Reviewer]
        V7[Release Reviewer]
        VA[(implementation-plan<br/>delivery-plan<br/>build-artifact<br/>milestone-report<br/>deploy-handoff)]

        V1 --> V2
        V1 --> V3
        V2 --> V4
        V3 --> V4
        V4 --> V5
        V4 --> V6
        V5 --> V7
        V6 --> V7
        V7 --> VA
    end

    subgraph Deploy["Release Gate"]
        G1[Release Manager]
        G2{Release-ready?}
        GA[(deploy-checks<br/>release-record)]

        G1 --> G2
        G2 --> GA
    end

    subgraph Iterate["Iteration Engine"]
        I1[Feedback Triager]
        I2[Roadmap Optimizer]
        IA[(feedback-backlog<br/>iteration-recommendations)]

        I1 --> I2
        I2 --> IA
    end

    Start --> R1
    RA --> P1
    PA --> D1
    DA --> A1
    A2 -- Go --> V1
    A2 -- Rework --> P1
    VA --> G1
    G2 -- Yes --> I1
    G2 -- No --> V1
    IA -. next cycle .-> R1
```

## 2. Development Contract-Conformance Flow

```mermaid
flowchart LR
    Approved[(approved context<br/>research + planning + design)]
    Contracts[(design tokens<br/>access policy<br/>audit / operability<br/>development standards)]
    Planner[Build Planner]
    Frontend[Frontend Builder]
    Backend[Backend Builder]
    Integrator[Integrator]
    QA[QA Engineer]
    Security[Security Reviewer]
    Reviewer[Release Reviewer]
    Gate{Contract and quality gates satisfied?}
    Handoff[(build-artifact<br/>milestone-report<br/>deploy-handoff)]

    Approved --> Planner
    Contracts --> Planner
    Contracts --> Frontend
    Contracts --> Backend
    Contracts --> Integrator
    Planner --> Frontend
    Planner --> Backend
    Frontend --> Integrator
    Backend --> Integrator
    Integrator --> QA
    Integrator --> Security
    QA --> Reviewer
    Security --> Reviewer
    Reviewer --> Gate
    Gate -- Yes --> Handoff
    Gate -- No --> Planner
```

## 3. Operating Rules

- `research`, `planning`, `design`, and `development` are executable multi-agent phases with explicit team blueprints and artifact contracts.
- `approval`, `deploy`, and `iterate` are not decorative UI steps; they are governance, release, and feedback loops that must preserve auditability.
- Development should not start from a blank prompt. It should start from approved upstream context plus formal contracts such as `design tokens`, `access policy`, `audit / operability`, and `development standards`.
- Prototype implementation should re-enter the planner or reviewer loop when contract conformance, security posture, milestone readiness, or deploy handoff is incomplete.
- Human decision points remain visible at the approval and release gates even when most execution is autonomous.
