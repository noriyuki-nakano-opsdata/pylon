import { apiFetch } from "./client";
import type { GtmOverview } from "@/types/gtm";

export const gtmApi = {
  getOverview: () => apiFetch<GtmOverview>("/v1/gtm/overview"),
};
