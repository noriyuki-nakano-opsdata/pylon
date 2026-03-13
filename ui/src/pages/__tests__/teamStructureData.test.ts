import { describe, expect, it } from "vitest";

import {
  buildModelOptions,
  getTeamMeta,
  mergeTeamDefs,
  resolveTeamDef,
} from "@/pages/teamStructureData";

describe("teamStructureData", () => {
  it("keeps discovered dynamic teams instead of collapsing them into product", () => {
    const teamDefs = mergeTeamDefs(undefined, ["advertising"]);

    const advertising = resolveTeamDef("advertising", teamDefs);

    expect(advertising.id).toBe("advertising");
    expect(advertising.nameJa).toBe("広告運用");
  });

  it("builds a stable fallback for unknown teams", () => {
    const teamDefs = mergeTeamDefs();

    const growth = resolveTeamDef("growth-ops", teamDefs);

    expect(growth.id).toBe("growth-ops");
    expect(growth.name).toBe("Growth Ops");
    expect(getTeamMeta("growth-ops").description).toContain("Growth Ops");
  });

  it("preserves the current model in the edit select options", () => {
    const options = buildModelOptions("anthropic/claude-haiku-4-5-20251001");

    expect(options[0]).toBe("anthropic/claude-haiku-4-5-20251001");
    expect(options).toContain("openai/gpt-5-mini");
  });
});
