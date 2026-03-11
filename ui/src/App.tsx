import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { FeatureUnavailable } from "@/components/FeatureUnavailable";
import { Layout } from "@/components/Layout";
import { useFeatureFlags } from "@/contexts/FeatureFlagsContext";
import { LifecycleLayout } from "@/pages/lifecycle/LifecycleLayout";

const Dashboard = lazy(() => import("@/pages/Dashboard").then(m => ({ default: m.Dashboard })));
const Agents = lazy(() => import("@/pages/Agents").then(m => ({ default: m.Agents })));
const AgentDetail = lazy(() => import("@/pages/AgentDetail").then(m => ({ default: m.AgentDetail })));
const AgentNew = lazy(() => import("@/pages/AgentNew").then(m => ({ default: m.AgentNew })));
const Workflows = lazy(() => import("@/pages/Workflows").then(m => ({ default: m.Workflows })));
const Runs = lazy(() => import("@/pages/Runs").then(m => ({ default: m.Runs })));
const Approvals = lazy(() => import("@/pages/Approvals").then(m => ({ default: m.Approvals })));
const Costs = lazy(() => import("@/pages/Costs").then(m => ({ default: m.Costs })));
const Providers = lazy(() => import("@/pages/Providers").then(m => ({ default: m.Providers })));
const Studio = lazy(() => import("@/pages/Studio").then(m => ({ default: m.Studio })));
const TasksBoard = lazy(() => import("@/pages/TasksBoard").then(m => ({ default: m.TasksBoard })));
const TeamStructure = lazy(() => import("@/pages/TeamStructure").then(m => ({ default: m.TeamStructure })));
const Memory = lazy(() => import("@/pages/Memory").then(m => ({ default: m.Memory })));
const Calendar = lazy(() => import("@/pages/Calendar").then(m => ({ default: m.Calendar })));
const ContentPipeline = lazy(() => import("@/pages/ContentPipeline").then(m => ({ default: m.ContentPipeline })));
const Issues = lazy(() => import("@/pages/Issues").then(m => ({ default: m.Issues })));
const IssueDetail = lazy(() => import("@/pages/IssueDetail").then(m => ({ default: m.IssueDetail })));
const PullRequests = lazy(() => import("@/pages/PullRequests").then(m => ({ default: m.PullRequests })));
const PullRequestDetail = lazy(() => import("@/pages/PullRequestDetail").then(m => ({ default: m.PullRequestDetail })));
const Models = lazy(() => import("@/pages/Models").then(m => ({ default: m.Models })));
const Skills = lazy(() => import("@/pages/Skills").then(m => ({ default: m.Skills })));
const Settings = lazy(() => import("@/pages/Settings").then(m => ({ default: m.Settings })));
const AdsLayout = lazy(() => import("@/pages/ads/AdsLayout").then(m => ({ default: m.AdsLayout })));
const AdsDashboard = lazy(() => import("@/pages/ads/AdsDashboard").then(m => ({ default: m.AdsDashboard })));
const AuditRunner = lazy(() => import("@/pages/ads/AuditRunner").then(m => ({ default: m.AuditRunner })));
const AuditReport = lazy(() => import("@/pages/ads/AuditReport").then(m => ({ default: m.AuditReport })));
const AdPlanGenerator = lazy(() => import("@/pages/ads/AdPlanGenerator").then(m => ({ default: m.AdPlanGenerator })));
const BudgetOptimizer = lazy(() => import("@/pages/ads/BudgetOptimizer").then(m => ({ default: m.BudgetOptimizer })));
const ProjectNew = lazy(() => import("@/pages/ProjectNew").then(m => ({ default: m.ProjectNew })));
const ResearchPhase = lazy(() => import("@/pages/lifecycle/ResearchPhase").then(m => ({ default: m.ResearchPhase })));
const PlanningPhase = lazy(() => import("@/pages/lifecycle/PlanningPhase").then(m => ({ default: m.PlanningPhase })));
const DesignPhase = lazy(() => import("@/pages/lifecycle/DesignPhase").then(m => ({ default: m.DesignPhase })));
const ApprovalPhase = lazy(() => import("@/pages/lifecycle/ApprovalPhase").then(m => ({ default: m.ApprovalPhase })));
const DevelopmentPhase = lazy(() => import("@/pages/lifecycle/DevelopmentPhase").then(m => ({ default: m.DevelopmentPhase })));
const DeployPhase = lazy(() => import("@/pages/lifecycle/DeployPhase").then(m => ({ default: m.DeployPhase })));
const IteratePhase = lazy(() => import("@/pages/lifecycle/IteratePhase").then(m => ({ default: m.IteratePhase })));

export function App() {
  const { isEnabled } = useFeatureFlags();

  return (
    <ErrorBoundary>
    <Suspense fallback={<div className="flex h-screen items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>}>
      <Routes>
        <Route element={<Layout />}>
          {/* Default redirect */}
          <Route index element={<Navigate to="/dashboard" replace />} />

          {/* Project-scoped routes */}
          <Route path="p/:projectSlug">
            <Route index element={<Navigate to={isEnabled("project", "studio") ? "studio" : "runs"} replace />} />
            <Route
              path="studio"
              element={isEnabled("project", "studio")
                ? <Studio />
                : <FeatureUnavailable title="Quick Build is disabled" description="This backend only exposes the stable orchestration surfaces." />}
            />
            <Route
              path="tasks"
              element={isEnabled("project", "tasks")
                ? <TasksBoard />
                : <FeatureUnavailable title="Task Board is disabled" description="Mission-control surfaces are not enabled in the current backend." />}
            />
            <Route
              path="team"
              element={isEnabled("project", "team")
                ? <TeamStructure />
                : <FeatureUnavailable title="Agent Monitoring is disabled" description="Mission-control surfaces are not enabled in the current backend." />}
            />
            <Route
              path="memory"
              element={isEnabled("project", "memory")
                ? <Memory />
                : <FeatureUnavailable title="Memory is disabled" description="Mission-control surfaces are not enabled in the current backend." />}
            />
            <Route
              path="calendar"
              element={isEnabled("project", "calendar")
                ? <Calendar />
                : <FeatureUnavailable title="Calendar is disabled" description="Mission-control surfaces are not enabled in the current backend." />}
            />
            <Route
              path="content"
              element={isEnabled("project", "content")
                ? <ContentPipeline />
                : <FeatureUnavailable title="Content Pipeline is disabled" description="Mission-control surfaces are not enabled in the current backend." />}
            />
            <Route
              path="issues"
              element={isEnabled("project", "issues")
                ? <Issues />
                : <FeatureUnavailable title="Issues are disabled" description="GitHub mock surfaces are hidden until a real integration is enabled." />}
            />
            <Route
              path="issues/:issueNumber"
              element={isEnabled("project", "issues")
                ? <IssueDetail />
                : <FeatureUnavailable title="Issues are disabled" description="GitHub mock surfaces are hidden until a real integration is enabled." />}
            />
            <Route
              path="pulls"
              element={isEnabled("project", "pulls")
                ? <PullRequests />
                : <FeatureUnavailable title="Pull Requests are disabled" description="GitHub mock surfaces are hidden until a real integration is enabled." />}
            />
            <Route
              path="pulls/:prNumber"
              element={isEnabled("project", "pulls")
                ? <PullRequestDetail />
                : <FeatureUnavailable title="Pull Requests are disabled" description="GitHub mock surfaces are hidden until a real integration is enabled." />}
            />
            <Route path="runs" element={<Runs />} />
            <Route path="approvals" element={<Approvals />} />

            {/* Ads Audit */}
            <Route
              path="ads"
              element={isEnabled("project", "ads")
                ? <AdsLayout />
                : <FeatureUnavailable title="Ads Audit is disabled" description="This backend does not expose the ads analysis contract yet." />}
            >
              <Route index element={<Navigate to="dashboard" replace />} />
              <Route path="dashboard" element={<AdsDashboard />} />
              <Route path="audit" element={<AuditRunner />} />
              <Route path="reports" element={<AuditReport />} />
              <Route path="reports/:reportId" element={<AuditReport />} />
              <Route path="plan" element={<AdPlanGenerator />} />
              <Route path="budget" element={<BudgetOptimizer />} />
            </Route>

            {/* Product Lifecycle */}
            <Route
              path="lifecycle"
              element={isEnabled("project", "lifecycle")
                ? <LifecycleLayout />
                : <FeatureUnavailable title="Lifecycle is disabled" description="The current backend is focused on the stable orchestration control plane." />}
            >
              <Route index element={<Navigate to="research" replace />} />
              <Route path="research" element={<ResearchPhase />} />
              <Route path="planning" element={<PlanningPhase />} />
              <Route path="design" element={<DesignPhase />} />
              <Route path="approval" element={<ApprovalPhase />} />
              <Route path="development" element={<DevelopmentPhase />} />
              <Route path="deploy" element={<DeployPhase />} />
              <Route path="iterate" element={<IteratePhase />} />
            </Route>
          </Route>

          {/* Admin routes (not project-scoped) */}
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="workflows" element={isEnabled("admin", "workflows") ? <Workflows /> : <FeatureUnavailable title="Workflows are disabled" description="This surface is not enabled in the current backend." />} />
          <Route path="agents" element={isEnabled("admin", "agents") ? <Agents /> : <FeatureUnavailable title="Agents are disabled" description="This surface is not enabled in the current backend." />} />
          <Route path="agents/new" element={isEnabled("admin", "agents") ? <AgentNew /> : <FeatureUnavailable title="Agents are disabled" description="This surface is not enabled in the current backend." />} />
          <Route path="agents/:agentId" element={isEnabled("admin", "agents") ? <AgentDetail /> : <FeatureUnavailable title="Agents are disabled" description="This surface is not enabled in the current backend." />} />
          <Route path="costs" element={isEnabled("admin", "costs") ? <Costs /> : <FeatureUnavailable title="Costs are disabled" description="This surface is not enabled in the current backend." />} />
          <Route path="providers" element={isEnabled("admin", "providers") ? <Providers /> : <FeatureUnavailable title="Providers are disabled" description="This surface is not enabled in the current backend." />} />
          <Route path="models" element={isEnabled("admin", "models") ? <Models /> : <FeatureUnavailable title="Models are disabled" description="This surface is not enabled in the current backend." />} />
          <Route path="skills" element={isEnabled("admin", "skills") ? <Skills /> : <FeatureUnavailable title="Skills are disabled" description="This surface is not enabled in the current backend." />} />
          <Route path="projects/new" element={<ProjectNew />} />
          <Route path="settings" element={isEnabled("admin", "settings") ? <Settings /> : <FeatureUnavailable title="Settings are disabled" description="This surface is not enabled in the current backend." />} />

          {/* Legacy redirects */}
          <Route path="studio" element={<Navigate to="/p/todo-app-builder/studio" replace />} />
          <Route path="runs" element={<Navigate to="/p/todo-app-builder/runs" replace />} />
          <Route path="approvals/*" element={<Navigate to="/p/todo-app-builder/approvals" replace />} />
        </Route>
      </Routes>
    </Suspense>
    </ErrorBoundary>
  );
}
