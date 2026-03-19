import { describe, expect, it } from "vitest";
import {
  buildIdentityAutofillMessages,
  describeProductIdentityState,
  resolveProductIdentityForResearch,
} from "@/lifecycle/productIdentity";
import { auditResearchQuality } from "@/lifecycle/researchAudit";
import type { MarketResearch } from "@/types/lifecycle";

function makeResearch(overrides: Partial<MarketResearch> = {}): MarketResearch {
  return {
    competitors: [],
    market_size: "市場規模は精査中",
    trends: [],
    opportunities: [],
    threats: [],
    tech_feasibility: { score: 0.72, notes: "実装可能" },
    user_research: {
      signals: [],
      pain_points: [],
      segment: "B2B",
    },
    claims: [],
    evidence: [],
    dissent: [],
    open_questions: [],
    winning_theses: [],
    source_links: [],
    confidence_summary: { average: 0.72, floor: 0.68, accepted: 0 },
    ...overrides,
  };
}

describe("research identity autofill", () => {
  it("surfaces fallback assistance when optional identity fields are blank", () => {
    expect(buildIdentityAutofillMessages({
      companyName: "Pylon Labs",
      productName: "Pylon",
      officialWebsite: "",
      officialDomains: [],
      aliases: [],
      excludedEntityNames: [],
    })).toEqual([
      "公式サイトが空でも、決まっている名称から検索軸を固定します。",
      "別名・略称が空でも、表記ゆれ候補を自動生成して照合します。",
      "除外候補が空でも、同名他社らしいソースを自動で隔離します。",
    ]);
  });

  it("derives compact alias variants for research matching", () => {
    expect(resolveProductIdentityForResearch({
      companyName: "Revenue Labs",
      productName: "Revenue Command Center",
      officialWebsite: "",
      officialDomains: [],
      aliases: [],
      excludedEntityNames: [],
    }).aliases).toContain("RevenueCommandCenter");
  });

  it("describes concept, company-only, and product-only identity states", () => {
    expect(describeProductIdentityState({
      companyName: "",
      productName: "",
      officialWebsite: "",
      officialDomains: [],
      aliases: [],
      excludedEntityNames: [],
    })).toMatchObject({
      mode: "concept_only",
      badgeLabel: "未定でも可",
    });

    expect(describeProductIdentityState({
      companyName: "Pylon Labs",
      productName: "",
      officialWebsite: "",
      officialDomains: [],
      aliases: [],
      excludedEntityNames: [],
    })).toMatchObject({
      mode: "company_context",
      badgeLabel: "会社軸あり",
    });

    expect(describeProductIdentityState({
      companyName: "",
      productName: "Pylon",
      officialWebsite: "",
      officialDomains: [],
      aliases: [],
      excludedEntityNames: [],
    })).toMatchObject({
      mode: "product_context",
      badgeLabel: "構想名あり",
    });
  });

  it("quarantines same-name off-target sources even without optional identity fields", () => {
    const audit = auditResearchQuality(makeResearch({
      source_links: ["https://www.baslerweb.com/en/products/software/basler-pylon-software-suite/"],
      evidence: [
        {
          id: "ev-1",
          source_ref: "https://www.baslerweb.com/en/products/software/basler-pylon-software-suite/",
          source_type: "url",
          snippet: "Basler pylon Software Suite",
          recency: "current",
          relevance: "medium",
        },
      ],
      competitors: [
        {
          name: "Basler pylon",
          url: "https://www.baslerweb.com/en/products/software/basler-pylon-software-suite/",
          strengths: ["Machine vision tooling"],
          weaknesses: [],
          pricing: "要問い合わせ",
          target: "Manufacturing",
        },
      ],
    }), {
      projectSpec: "運用品質と意思決定を支える AI オペレーション基盤",
      identityProfile: {
        companyName: "Pylon Labs",
        productName: "Pylon",
        officialWebsite: "",
        officialDomains: [],
        aliases: [],
        excludedEntityNames: [],
      },
    });

    expect(audit.sourceLinks.quarantined).toHaveLength(1);
    expect(audit.evidence.quarantined).toHaveLength(1);
    expect(audit.competitors.quarantined).toHaveLength(1);
    expect(audit.sourceLinks.quarantined[0]?.reason).toContain("別会社");
  });

  it("asks for minimal identity help only when same-name collisions appear", () => {
    const audit = auditResearchQuality(makeResearch({
      source_links: ["https://www.baslerweb.com/en/products/software/basler-pylon-software-suite/"],
      evidence: [
        {
          id: "ev-1",
          source_ref: "https://www.baslerweb.com/en/products/software/basler-pylon-software-suite/",
          source_type: "url",
          snippet: "Basler pylon Software Suite",
          recency: "current",
          relevance: "medium",
        },
      ],
      competitors: [
        {
          name: "Basler pylon",
          url: "https://www.baslerweb.com/en/products/software/basler-pylon-software-suite/",
          strengths: ["Machine vision tooling"],
          weaknesses: [],
          pricing: "要問い合わせ",
          target: "Manufacturing",
        },
      ],
    }), {
      projectSpec: "運用品質と意思決定を支える AI オペレーション基盤",
      identityProfile: {
        companyName: "",
        productName: "Pylon",
        officialWebsite: "",
        officialDomains: [],
        aliases: [],
        excludedEntityNames: [],
      },
    });

    expect(audit.issues).toContain("同名候補が混ざっているため、会社名・運営主体か公式サイトを追加してください。");
  });
});
