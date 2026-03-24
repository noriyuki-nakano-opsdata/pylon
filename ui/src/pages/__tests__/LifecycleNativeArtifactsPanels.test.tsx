import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BehaviorModelPanel } from "../lifecycle/BehaviorModelPanel";
import { RequirementsPanel } from "../lifecycle/RequirementsPanel";
import { ReverseEngineeringPanel } from "../lifecycle/ReverseEngineeringPanel";
import { TaskDecompositionPanel } from "../lifecycle/TaskDecompositionPanel";
import { TechnicalDesignPanel } from "../lifecycle/TechnicalDesignPanel";

describe("Lifecycle native artifact panels", () => {
  it("renders requirements, reverse engineering, task, behavior, and technical panels", () => {
    render(
      <div>
        <RequirementsPanel
          bundle={{
            requirements: [
              {
                id: "REQ-0001",
                pattern: "event-driven",
                statement: "When approval is requested, the system shall persist the decision.",
                confidence: 0.91,
                sourceClaimIds: ["claim-1"],
                userStoryIds: ["US-0001"],
                acceptanceCriteria: ["Given an approval request, when accepted, then the decision is stored."],
              },
            ],
            userStories: [{ id: "US-0001", title: "operator", description: "As operator, I want to record approvals." }],
            acceptanceCriteria: [{ id: "AC-0001", requirementId: "REQ-0001", criterion: "Given an approval request..." }],
            confidenceDistribution: { high: 1, medium: 0, low: 0 },
            completenessScore: 0.92,
            traceabilityIndex: { "claim-1": ["REQ-0001"] },
          }}
        />
        <ReverseEngineeringPanel
          result={{
            extractedRequirements: [{ id: "REQ-R-0001", statement: "The system shall expose approval endpoints.", sourceFile: "server/routes/approval.ts" }],
            architectureDoc: { endpoint_count: 2 },
            dataflowMermaid: "graph LR\nClient-->API",
            apiEndpoints: [{ method: "GET", path: "/api/approvals", handler: "listApprovals", filePath: "server/routes/approval.ts" }],
            databaseSchema: [],
            interfaces: [],
            taskStructure: [],
            testSpecs: [],
            coverageScore: 0.82,
            languagesDetected: ["typescript"],
            sourceType: "prototype_app",
          }}
        />
        <TaskDecompositionPanel
          decomposition={{
            tasks: [{ id: "TASK-0001", title: "Implement approval log", description: "", phase: "Phase 1", milestoneId: "ms-1", dependsOn: [], effortHours: 8, priority: "must", featureId: "feat-1", requirementId: "REQ-0001" }],
            dagEdges: [],
            phaseMilestones: [{ phase: "Phase 1", milestoneIds: ["ms-1"], taskCount: 1, totalHours: 8, durationDays: 20 }],
            totalEffortHours: 8,
            criticalPath: ["TASK-0001"],
            effortByPhase: { "Phase 1": 8 },
            hasCycles: false,
          }}
        />
        <BehaviorModelPanel
          analysis={{
            rubberDuckPrd: {
              problemStatement: "Approval latency blocks delivery.",
              targetUsers: ["operator"],
              successMetrics: [],
              scopeBoundaries: { inScope: ["approval"], outOfScope: ["billing"] },
              keyDecisions: [],
            },
            edgeCases: {
              edgeCases: [{ id: "EC-1", scenario: "Double submit", severity: "high", mitigation: "dedupe", featureId: "feat-1" }],
              riskMatrix: { high: 1 },
              coverageScore: 1,
            },
            impactAnalysis: {
              layers: [{ layer: "api", impacts: [{ component: "approval route", description: "changes request handling" }] }],
              blastRadius: 2,
              criticalPathsAffected: ["TASK-0001"],
            },
            sequenceDiagrams: {
              diagrams: [{ id: "seq-1", title: "Approval", mermaidCode: "sequenceDiagram\nUser->>API: approve", flowType: "success" }],
            },
            stateTransitions: {
              states: [{ id: "pending", name: "pending", description: "" }],
              transitions: [{ fromState: "pending", toState: "approved", trigger: "approve", guard: "", riskLevel: "low" }],
              riskStates: [],
              mermaidCode: "stateDiagram-v2\npending --> approved: approve",
            },
          }}
        />
        <TechnicalDesignPanel
          bundle={{
            architecture: { system_overview: "Approval service", architectural_pattern: "SPA + API" },
            dataflowMermaid: "flowchart LR\nUser-->API",
            apiSpecification: [{ method: "POST", path: "/api/v1/approvals", description: "Create approval", authRequired: true }],
            databaseSchema: [{ name: "approvals", columns: [{ name: "id", type: "uuid", primaryKey: true }], indexes: [] }],
            interfaceDefinitions: [{ name: "ApprovalRecord", properties: [{ name: "id", type: "string" }], extends: [] }],
            componentDependencyGraph: { UI: ["API"] },
          }}
        />
      </div>,
    );

    expect(screen.getByText("EARS 要件定義")).toBeInTheDocument();
    expect(screen.getByText("既存コードの逆分析")).toBeInTheDocument();
    expect(screen.getByText("タスク分解 (TASK-XXXX)")).toBeInTheDocument();
    expect(screen.getByText("ラバーダック PRD")).toBeInTheDocument();
    expect(screen.getByText("影響範囲分析")).toBeInTheDocument();
    expect(screen.getByText("技術設計書")).toBeInTheDocument();
  });
});
