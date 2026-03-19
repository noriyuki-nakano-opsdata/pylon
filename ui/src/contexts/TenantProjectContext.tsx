import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { setTenantId } from "@/api/client";
import { lifecycleApi } from "@/api/lifecycle";
import { generateProjectId } from "@/lib/projectId";
import { normalizeProductIdentity } from "@/lifecycle/productIdentity";
import type { LifecycleProductIdentity, LifecycleProject } from "@/types/lifecycle";

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

export interface CreateProjectInput {
  name: string;
  brief?: string;
  githubRepo?: string;
  productIdentity?: Partial<LifecycleProductIdentity>;
}

interface TenantProjectState {
  tenants: Tenant[];
  currentTenant: Tenant | null;
  projects: Project[];
  currentProject: Project | null;
  projectsLoading: boolean;
  setCurrentTenant: (tenant: Tenant) => void;
  setCurrentProject: (project: Project) => void;
  createProject: (input: CreateProjectInput) => Promise<Project>;
  deleteProject: (projectSlug: string) => Promise<void>;
  refreshProjects: () => Promise<void>;
}

const TenantProjectContext = createContext<TenantProjectState | null>(null);

const DEMO_TENANTS: Tenant[] = [
  { id: "default", name: "Default Org", slug: "default" },
  { id: "acme", name: "Acme Corp", slug: "acme" },
];

function mapLifecycleProject(project: LifecycleProject, tenantId: string): Project {
  return {
    id: project.projectId,
    name: project.name?.trim() || project.projectId,
    slug: project.projectId,
    tenantId: project.tenant_id ?? tenantId,
    description: project.description?.trim() || project.spec?.trim() || undefined,
    githubRepo: project.githubRepo?.trim() || undefined,
    createdAt: project.createdAt,
  };
}

function upsertProjects(projects: Project[], nextProject: Project): Project[] {
  const withoutCurrent = projects.filter((project) => project.slug !== nextProject.slug);
  return [nextProject, ...withoutCurrent].sort((left, right) => left.name.localeCompare(right.name, "en"));
}

export function TenantProjectProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [currentTenant, setCurrentTenantState] = useState<Tenant>(DEMO_TENANTS[0]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProject, setCurrentProjectState] = useState<Project | null>(null);
  const [projectsLoading, setProjectsLoading] = useState(true);

  const fetchProjects = useCallback(async (tenantId: string) => {
    setTenantId(tenantId);
    const response = await lifecycleApi.listProjects();
    return response.projects.map((project) => mapLifecycleProject(project, tenantId));
  }, []);

  const refreshProjects = useCallback(async () => {
    setProjectsLoading(true);
    try {
      const tenantProjects = await fetchProjects(currentTenant.id);
      setProjects(tenantProjects);
    } finally {
      setProjectsLoading(false);
    }
  }, [currentTenant.id, fetchProjects]);

  useEffect(() => {
    let cancelled = false;
    setProjectsLoading(true);
    void fetchProjects(currentTenant.id)
      .then((tenantProjects) => {
        if (cancelled) return;
        setProjects(tenantProjects);
      })
      .catch(() => {
        if (cancelled) return;
        setProjects([]);
      })
      .finally(() => {
        if (cancelled) return;
        setProjectsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentTenant.id, fetchProjects]);

  useEffect(() => {
    const match = location.pathname.match(/^\/p\/([^/]+)/);
    if (!match) {
      setCurrentProjectState((prev) => {
        if (prev && projects.some((project) => project.slug === prev.slug)) {
          return prev;
        }
        return projects[0] ?? null;
      });
      return;
    }
    const slug = decodeURIComponent(match[1]);
    const matchedProject = projects.find((project) => project.slug === slug);
    if (matchedProject) {
      if (matchedProject.slug !== currentProject?.slug) {
        setCurrentProjectState(matchedProject);
      }
      return;
    }

    let cancelled = false;
    void lifecycleApi.getProject(slug)
      .then((project) => {
        if (cancelled) return;
        const mapped = mapLifecycleProject(project, currentTenant.id);
        setProjects((prev) => upsertProjects(prev, mapped));
        setCurrentProjectState(mapped);
      })
      .catch(() => {
        if (cancelled) return;
        setCurrentProjectState(null);
      });

    return () => {
      cancelled = true;
    };
  }, [location.pathname, projects, currentProject?.slug, currentTenant.id]);

  const setCurrentTenant = useCallback((tenant: Tenant) => {
    setCurrentTenantState(tenant);
    setTenantId(tenant.id);
    setProjects([]);
    setCurrentProjectState(null);
    navigate("/dashboard");
  }, [navigate]);

  const setCurrentProject = useCallback((project: Project) => {
    setCurrentProjectState(project);
    const subPath = location.pathname.replace(/^\/p\/[^/]+/, "");
    navigate(`/p/${project.slug}${subPath || "/lifecycle"}`);
  }, [navigate, location.pathname]);

  const createProject = useCallback(async (input: CreateProjectInput) => {
    const name = input.name.trim();
    if (!name) {
      throw new Error("Project name is required");
    }
    const projectId = generateProjectId();

    const brief = input.brief?.trim() || "";
    const productIdentity = normalizeProductIdentity(input.productIdentity, {
      fallbackProductName: name,
    });

    const response = await lifecycleApi.saveProject(projectId, {
      name,
      description: brief,
      spec: brief,
      githubRepo: input.githubRepo?.trim() || null,
      productIdentity,
    });
    const initialLifecycleProject = {
      ...response.project,
      productIdentity: normalizeProductIdentity(response.project.productIdentity ?? productIdentity, {
        fallbackProductName: name,
      }),
      spec: response.project.spec?.trim() || brief,
    } satisfies LifecycleProject;
    const project = mapLifecycleProject(initialLifecycleProject, currentTenant.id);
    setProjects((prev) => upsertProjects(prev, project));
    setCurrentProjectState(project);
    navigate(`/p/${project.slug}/lifecycle/research`, {
      state: {
        initialLifecycleProject,
      },
    });
    return project;
  }, [currentTenant.id, navigate]);

  const deleteProject = useCallback(async (projectSlug: string) => {
    const deletedProject = projects.find((project) => project.slug === projectSlug);
    if (!deletedProject) {
      return;
    }

    await lifecycleApi.deleteProject(projectSlug);
    const tenantProjects = await fetchProjects(currentTenant.id);
    const remainingProjects = tenantProjects.filter((project) => project.slug !== projectSlug);
    setProjects(remainingProjects);

    if (currentProject?.slug !== projectSlug) {
      return;
    }

    const subPath = location.pathname.replace(/^\/p\/[^/]+/, "");
    const fallbackPath = subPath || "/lifecycle";
    const nextProject = remainingProjects[0] ?? null;
    setCurrentProjectState(nextProject);
    if (nextProject) {
      navigate(`/p/${nextProject.slug}${fallbackPath}`);
      return;
    }
    navigate("/dashboard");
  }, [currentProject?.slug, currentTenant.id, fetchProjects, location.pathname, navigate, projects]);

  return (
    <TenantProjectContext.Provider
      value={{
        tenants: DEMO_TENANTS,
        currentTenant,
        projects,
        currentProject,
        projectsLoading,
        setCurrentTenant,
        setCurrentProject,
        createProject,
        deleteProject,
        refreshProjects,
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
