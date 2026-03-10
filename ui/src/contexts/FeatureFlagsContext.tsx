import { createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { featuresApi, fallbackFeatureManifest, type FeatureManifest } from "@/api/features";
import { queryKeys } from "@/lib/queryKeys";

interface FeatureFlagsContextValue {
  manifest: FeatureManifest;
  isLoading: boolean;
  isEnabled: (group: "admin" | "project", key: string) => boolean;
}

const FeatureFlagsContext = createContext<FeatureFlagsContextValue>({
  manifest: fallbackFeatureManifest,
  isLoading: false,
  isEnabled: (group, key) => Boolean(fallbackFeatureManifest.surfaces[group]?.[key]),
});

export function FeatureFlagsProvider({ children }: { children: React.ReactNode }) {
  const query = useQuery({
    queryKey: queryKeys.features,
    queryFn: () => featuresApi.get(),
    retry: 0,
    staleTime: 60_000,
  });

  const manifest = query.data ?? fallbackFeatureManifest;

  return (
    <FeatureFlagsContext.Provider
      value={{
        manifest,
        isLoading: query.isLoading,
        isEnabled: (group, key) => Boolean(manifest.surfaces[group]?.[key]),
      }}
    >
      {children}
    </FeatureFlagsContext.Provider>
  );
}

export function useFeatureFlags() {
  return useContext(FeatureFlagsContext);
}
