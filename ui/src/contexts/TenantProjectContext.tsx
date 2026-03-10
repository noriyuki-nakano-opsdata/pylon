import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { setTenantId } from "@/api/client";

export interface Tenant {
  id: string;
  name: string;
  slug: string;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  tenantId: string;
  description?: string;
  githubRepo?: string;
  createdAt: string;
}

interface TenantProjectState {
  tenants: Tenant[];
  currentTenant: Tenant | null;
  projects: Project[];
  currentProject: Project | null;
  setCurrentTenant: (tenant: Tenant) => void;
  setCurrentProject: (project: Project) => void;
}

const TenantProjectContext = createContext<TenantProjectState | null>(null);

const DEMO_TENANTS: Tenant[] = [
  { id: "default", name: "Default Org", slug: "default" },
  { id: "acme", name: "Acme Corp", slug: "acme" },
];

const DEMO_PROJECTS: Project[] = [
  {
    id: "proj-1",
    name: "todo-app-builder",
    slug: "todo-app-builder",
    tenantId: "default",
    description: "AI-powered todo app generator",
    githubRepo: "acme/todo-app",
    createdAt: "2026-03-01T00:00:00Z",
  },
  {
    id: "proj-2",
    name: "api-service",
    slug: "api-service",
    tenantId: "default",
    description: "Backend API microservice",
    githubRepo: "acme/api-service",
    createdAt: "2026-03-05T00:00:00Z",
  },
  {
    id: "proj-3",
    name: "landing-page",
    slug: "landing-page",
    tenantId: "acme",
    description: "Marketing landing page",
    githubRepo: "acme/landing-page",
    createdAt: "2026-03-08T00:00:00Z",
  },
];

export function TenantProjectProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [currentTenant, setCurrentTenantState] = useState<Tenant>(DEMO_TENANTS[0]);
  const [currentProject, setCurrentProjectState] = useState<Project>(DEMO_PROJECTS[0]);

  const tenantProjects = DEMO_PROJECTS.filter((p) => p.tenantId === currentTenant.id);

  // Sync context from URL: when URL has /p/:slug, update context to match
  useEffect(() => {
    const match = location.pathname.match(/^\/p\/([^/]+)/);
    if (!match) return;
    const slug = match[1];
    if (slug === currentProject?.slug) return;
    const project = DEMO_PROJECTS.find((p) => p.slug === slug);
    if (project) {
      setCurrentProjectState(project);
      const tenant = DEMO_TENANTS.find((t) => t.id === project.tenantId);
      if (tenant && tenant.id !== currentTenant.id) {
        setCurrentTenantState(tenant);
        setTenantId(tenant.id);
      }
    }
  }, [location.pathname, currentProject?.slug, currentTenant.id]);

  const setCurrentTenant = useCallback((tenant: Tenant) => {
    setCurrentTenantState(tenant);
    setTenantId(tenant.id);
    const firstProject = DEMO_PROJECTS.find((p) => p.tenantId === tenant.id);
    if (firstProject) {
      setCurrentProjectState(firstProject);
      // Navigate to the new project's lifecycle
      navigate(`/p/${firstProject.slug}/lifecycle`);
    }
  }, [navigate]);

  const setCurrentProject = useCallback((project: Project) => {
    setCurrentProjectState(project);
    // Preserve current sub-path under /p/:slug/
    const subPath = location.pathname.replace(/^\/p\/[^/]+/, "");
    navigate(`/p/${project.slug}${subPath || "/lifecycle"}`);
  }, [navigate, location.pathname]);

  return (
    <TenantProjectContext.Provider
      value={{
        tenants: DEMO_TENANTS,
        currentTenant,
        projects: tenantProjects,
        currentProject,
        setCurrentTenant,
        setCurrentProject,
      }}
    >
      {children}
    </TenantProjectContext.Provider>
  );
}

export function useTenantProject() {
  const ctx = useContext(TenantProjectContext);
  if (!ctx) throw new Error("useTenantProject must be used within TenantProjectProvider");
  return ctx;
}
