import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "@/contexts/I18nContext";
import { Settings } from "../Settings";

const getReadinessMock = vi.fn();

vi.mock("@/api/health", () => ({
  healthApi: {
    getReadiness: () => getReadinessMock(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MemoryRouter>
          <Settings />
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("Settings", () => {
  beforeEach(() => {
    window.localStorage.setItem("pylon.ui.locale", "ja");
    getReadinessMock.mockReset();
    getReadinessMock.mockResolvedValue({
      status: "not_ready",
      ready: false,
      timestamp: 1,
      checks: [
        {
          name: "control_plane",
          status: "degraded",
          message: "in-memory control plane is reference-only",
          backend: "memory",
          readiness_tier: "reference",
          production_capable: false,
          workflow_count: 0,
        },
        {
          name: "auth",
          status: "degraded",
          message: "authentication is disabled",
          backend: "none",
          readiness_tier: "disabled",
          production_capable: false,
        },
        {
          name: "rate_limit",
          status: "degraded",
          message: "in-memory rate limiting is suitable for reference use only",
          backend: "memory",
          readiness_tier: "reference",
          production_capable: false,
        },
        { name: "system", status: "healthy", message: "operational" },
      ],
    });
  });

  it("surfaces readiness gaps and upgrade actions", async () => {
    renderPage();

    expect(await screen.findByText("Production Readiness")).toBeInTheDocument();
    expect(await screen.findByText("0 / 3")).toBeInTheDocument();
    expect(screen.getByText("本番化のための残作業")).toBeInTheDocument();
    expect(screen.getByText("control plane を sqlite 以上の durable backend に切り替える")).toBeInTheDocument();
    expect(screen.getByText("memory/none ではなく JWT または OIDC 認証を有効化する")).toBeInTheDocument();
    expect(screen.getByText("memory/disabled ではなく sqlite または redis rate limit を有効化する")).toBeInTheDocument();
  });

  it("shows a production-capable stack without upgrade actions", async () => {
    getReadinessMock.mockResolvedValueOnce({
      status: "ready",
      ready: true,
      timestamp: 1,
      checks: [
        {
          name: "control_plane",
          status: "healthy",
          message: "sqlite control plane is ready for single-node operation",
          backend: "sqlite",
          readiness_tier: "single-node",
          production_capable: true,
          workflow_count: 4,
        },
        {
          name: "auth",
          status: "healthy",
          message: "jwt_hs256 auth is ready for managed single-node deployments",
          backend: "jwt_hs256",
          readiness_tier: "single-node",
          production_capable: true,
        },
        {
          name: "rate_limit",
          status: "healthy",
          message: "sqlite rate limiting is ready for single-node operation",
          backend: "sqlite",
          readiness_tier: "single-node",
          production_capable: true,
        },
        { name: "system", status: "healthy", message: "operational" },
      ],
    });

    renderPage();

    expect(await screen.findByText("この構成は production-capable です。")).toBeInTheDocument();
    expect(screen.getByText("3 / 3")).toBeInTheDocument();
    expect(screen.queryByText("本番化のための残作業")).not.toBeInTheDocument();
  });
});
