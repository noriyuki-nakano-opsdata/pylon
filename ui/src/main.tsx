import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FeatureFlagsProvider } from "@/contexts/FeatureFlagsContext";
import { I18nProvider } from "@/contexts/I18nContext";
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
        <I18nProvider>
          <FeatureFlagsProvider>
            <TenantProjectProvider>
              <App />
            </TenantProjectProvider>
          </FeatureFlagsProvider>
        </I18nProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
