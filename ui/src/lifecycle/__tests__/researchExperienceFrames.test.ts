import { describe, expect, it } from "vitest";
import type { MarketResearch } from "@/types/lifecycle";
import { auditResearchQuality } from "@/lifecycle/researchAudit";
import { buildResearchExperienceFrames } from "@/lifecycle/researchExperienceFrames";

describe("buildResearchExperienceFrames", () => {
  it("builds journey, story, kano, and IA frames from trusted research inputs", () => {
    const research: MarketResearch = {
      competitors: [
        {
          name: "Ops Canvas",
          url: "https://example.com/ops-canvas",
          strengths: ["導入フローが明快"],
          weaknesses: ["運用品質の可視化が弱い"],
          pricing: "要問い合わせ",
          target: "開発責任者",
        },
      ],
      market_size: "市場は継続拡大",
      trends: ["導入判断では信頼できる根拠と説明責任が重視される"],
      opportunities: ["運用品質を最初から見せる導線に機会がある"],
      threats: ["比較時に記事断片が混ざると誤判断が起きる"],
      tech_feasibility: { score: 0.82, notes: "実装可能" },
      user_research: {
        signals: ["短時間で比較できることが重要"],
        pain_points: ["根拠が散らばると稟議が止まる"],
        segment: "プロダクト責任者",
      },
      winning_theses: ["運用品質と説明責任の可視化が差別化になる"],
      source_links: ["https://example.com/ops-canvas"],
      evidence: [
        {
          id: "ev-1",
          source_ref: "https://example.com/ops-canvas",
          source_type: "url",
          snippet: "Operational quality and governance controls are visible.",
          recency: "current",
          relevance: "high",
        },
      ],
      dissent: [],
      open_questions: ["どこまでをアルファ範囲に含めるか"],
    };

    const audit = auditResearchQuality(research, {
      projectSpec: "自律開発と品質保証を行う開発プラットフォーム",
      seedUrls: ["https://example.com/ops-canvas"],
    });

    const frames = buildResearchExperienceFrames({
      projectSpec: "自律開発と品質保証を行う開発プラットフォーム",
      research,
      audit,
      trustedCompetitors: research.competitors,
      trustedTrends: research.trends,
      trustedOpportunities: research.opportunities,
      trustedThreats: research.threats,
      trustedUserSignals: research.user_research?.signals ?? [],
      trustedPainPoints: research.user_research?.pain_points ?? [],
    });

    expect(frames.userJourney.touchpoints).toHaveLength(5);
    expect(frames.userStories).toHaveLength(3);
    expect(frames.jobStories).toHaveLength(3);
    expect(frames.kanoFeatures).toHaveLength(4);
    expect(frames.iaAnalysis.key_paths).toHaveLength(3);
    expect(frames.personaLabel).toBe("プロダクト責任者");
  });
});
