import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FeatureFlagsProvider } from "@/contexts/FeatureFlagsContext";
import { TenantProjectProvider } from "@/contexts/TenantProjectContext";
import { App } from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: 1,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <FeatureFlagsProvider>
          <TenantProjectProvider>
            <App />
          </TenantProjectProvider>
        </FeatureFlagsProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
