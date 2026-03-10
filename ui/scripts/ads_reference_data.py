"""Reference data extracted from claude-ads for Pylon backend audit engine."""

SEVERITY_MULTIPLIERS = {
    "critical": 5.0,
    "high": 3.0,
    "medium": 1.5,
    "low": 0.5,
}

GRADE_THRESHOLDS = [
    (90, "A"),
    (75, "B"),
    (60, "C"),
    (40, "D"),
    (0, "F"),
]

PLATFORM_CATEGORY_WEIGHTS = {
    "google": {
        "Conversion Tracking": 0.25,
        "Wasted Spend / Negatives": 0.20,
        "Account Structure": 0.15,
        "Keywords & Quality Score": 0.15,
        "Ads & Assets": 0.15,
        "Settings & Targeting": 0.10,
    },
    "meta": {
        "Pixel / CAPI Health": 0.30,
        "Creative (Diversity & Fatigue)": 0.30,
        "Account Structure": 0.20,
        "Audience & Targeting": 0.20,
    },
    "linkedin": {
        "Technical Setup": 0.25,
        "Audience Quality": 0.25,
        "Creative & Formats": 0.20,
        "Lead Gen Forms": 0.15,
        "Bidding & Budget": 0.15,
    },
    "tiktok": {
        "Creative Quality": 0.30,
        "Technical Setup": 0.25,
        "Bidding & Learning": 0.20,
        "Structure & Settings": 0.15,
        "Performance": 0.10,
    },
    "microsoft": {
        "Technical Setup": 0.25,
        "Syndication & Bidding": 0.20,
        "Structure & Audience": 0.20,
        "Creative & Extensions": 0.20,
        "Settings & Performance": 0.15,
    },
}

PLATFORM_CHECK_COUNTS = {
    "google": 74,
    "meta": 46,
    "linkedin": 25,
    "tiktok": 25,
    "microsoft": 20,
}

INDUSTRY_TEMPLATES = {
    "saas": {
        "name": "SaaS",
        "platforms": {"google": 0.40, "linkedin": 0.35, "meta": 0.20, "youtube": 0.05},
        "min_monthly": 5000,
        "primary_kpi": "Pipeline ROI, LTV:CAC",
        "time_to_profit": "3-6 months",
        "description": "SaaS B2B with high-intent search and LinkedIn professional targeting",
    },
    "ecommerce": {
        "name": "E-commerce",
        "platforms": {"meta": 0.55, "google": 0.27, "tiktok": 0.13, "email": 0.05},
        "min_monthly": 3000,
        "primary_kpi": "ROAS, MER, POAS",
        "time_to_profit": "0-2 months",
        "description": "E-commerce DTC with Meta-heavy creative and Google PMax",
    },
    "local-service": {
        "name": "Local Service",
        "platforms": {"google": 0.60, "meta": 0.30, "microsoft": 0.10},
        "min_monthly": 1500,
        "primary_kpi": "Cost Per Lead/Booking",
        "time_to_profit": "1 month",
        "description": "Local service businesses with Google LSA/Search focus",
    },
    "b2b-enterprise": {
        "name": "B2B Enterprise",
        "platforms": {"linkedin": 0.50, "google": 0.28, "abm_display": 0.17, "programmatic": 0.05},
        "min_monthly": 10000,
        "primary_kpi": "Pipeline, SQLs",
        "time_to_profit": "6-12 months",
        "description": "B2B enterprise with LinkedIn-dominant ABM strategy",
    },
    "info-products": {
        "name": "Info Products",
        "platforms": {"youtube": 0.40, "meta": 0.40, "email": 0.20},
        "min_monthly": 2000,
        "primary_kpi": "ROAS, Webinar CPL",
        "time_to_profit": "1-3 months",
        "description": "Info products and courses with YouTube and Meta funnel",
    },
    "mobile-app": {
        "name": "Mobile App",
        "platforms": {"apple_search": 0.30, "google": 0.30, "meta_tiktok": 0.40},
        "min_monthly": 5000,
        "primary_kpi": "CPI, LTV, D7 Retention",
        "time_to_profit": "3-6 months",
        "description": "Mobile app install campaigns across app stores and social",
    },
    "real-estate": {
        "name": "Real Estate",
        "platforms": {"meta": 0.50, "google": 0.40, "linkedin": 0.10},
        "min_monthly": 2500,
        "primary_kpi": "Cost Per Lead",
        "time_to_profit": "2-4 months",
        "description": "Real estate lead generation with Meta Lead Forms focus",
    },
    "healthcare": {
        "name": "Healthcare",
        "platforms": {"google": 0.55, "meta": 0.20, "microsoft": 0.10, "youtube_display": 0.15},
        "min_monthly": 4000,
        "primary_kpi": "Cost Per Patient",
        "time_to_profit": "2-5 months",
        "description": "Healthcare patient acquisition with compliance-heavy search",
    },
    "finance": {
        "name": "Finance",
        "platforms": {"google": 0.45, "linkedin": 0.25, "meta": 0.15, "youtube_display": 0.15},
        "min_monthly": 8000,
        "primary_kpi": "CAC, LTV:CAC",
        "time_to_profit": "4-8 months",
        "description": "Finance/Fintech with regulated search and LinkedIn B2B",
    },
    "agency": {
        "name": "Agency",
        "platforms": {"linkedin": 0.50, "meta": 0.30, "google": 0.20},
        "min_monthly": 1500,
        "primary_kpi": "Cost Per Lead",
        "time_to_profit": "1-3 months",
        "description": "Agency self-promotion with LinkedIn professional focus",
    },
    "generic": {
        "name": "Generic",
        "platforms": {"meta": 0.50, "google": 0.20, "tiktok": 0.30},
        "min_monthly": 2000,
        "primary_kpi": "ROAS, CAC",
        "time_to_profit": "1-3 months",
        "description": "B2C/DTC default split with Meta and TikTok social focus",
    },
}

PLATFORM_BENCHMARKS = {
    "google": {
        "ctr": {"average": 6.66, "good": 8.0},
        "cpc": {"average": 5.26, "good": 3.50},
        "cvr": {"average": 7.52, "good": 10.0},
        "cpl": {"average": 70.0, "good": 50.0},
    },
    "meta": {
        "ctr": {"average": 1.71, "good": 2.50},
        "cpc": {"average": 0.85, "good": 0.60},
        "cvr": {"average": 7.72, "good": 10.0},
        "cpm": {"average": 12.50, "good": 8.00},
        "roas": {"average": 2.19, "good": 4.52},
    },
    "linkedin": {
        "ctr": {"average": 0.44, "good": 0.65},
        "cpc": {"average": 5.50, "good": 3.94},
        "cpm": {"average": 34.50, "good": 31.00},
        "cvr": {"average": 13.0, "good": 15.0},
    },
    "tiktok": {
        "ctr": {"average": 0.84, "good": 1.50},
        "cpc": {"average": 1.00, "good": 0.50},
        "cvr": {"average": 0.46, "good": 1.00},
        "cpm": {"average": 4.26, "good": 3.21},
        "roas": {"average": 1.54, "good": 1.67},
    },
    "microsoft": {
        "ctr": {"average": 2.83, "good": 3.10},
        "cpc": {"average": 1.55, "good": 1.20},
    },
}

QUALITY_GATES = [
    {
        "id": "QG-01",
        "name": "Broad Match Safety",
        "rule": "Broad Match keywords must NOT use Manual CPC bidding. Use Smart Bidding or switch to Exact/Phrase match.",
        "platforms": ["google"],
    },
    {
        "id": "QG-02",
        "name": "3x Kill Rule",
        "rule": "Pause any ad/ad set/campaign immediately if spend > 3x target CPA with zero conversions.",
        "platforms": ["google", "meta", "linkedin", "tiktok", "microsoft"],
    },
    {
        "id": "QG-03",
        "name": "Budget Sufficiency",
        "rule": "Meta: daily budget >= 5x target CPA per ad set. TikTok: daily budget >= 50x target CPA per ad group.",
        "platforms": ["meta", "tiktok"],
    },
    {
        "id": "QG-04",
        "name": "Learning Phase Protection",
        "rule": "Do not make significant changes (budget >20%, targeting, creative edits, bid strategy) while in learning phase.",
        "platforms": ["google", "meta", "linkedin", "tiktok", "microsoft"],
    },
]

AUDIT_AGENT_PROMPTS = {
    "audit-google": (
        "You are a Google Ads audit agent. Analyze the provided Google Ads account data "
        "against the 74-check audit checklist. Evaluate categories: Conversion Tracking (25%), "
        "Wasted Spend/Negatives (20%), Account Structure (15%), Keywords & Quality Score (15%), "
        "Ads & Assets (15%), Settings & Targeting (10%). "
        "Critical checks (5.0x): conversion actions defined, enhanced conversions, Consent Mode v2, "
        "duplicate conversion counting, Google Tag firing, search term recency <14d, "
        "negative keyword lists >=3, wasted spend <5%, no Broad Match + Manual CPC, "
        "brand/non-brand separation, tCPA/tROAS within 20% of historical. "
        "Benchmarks: CTR avg 6.66%, CPC avg $5.26, CVR avg 7.52%, QS target >=7. "
        "Output a JSON array of check results: "
        '[{"id": "G42", "category": "Conversion Tracking", "name": "...", '
        '"severity": "critical|high|medium|low", "result": "PASS|WARNING|FAIL|N/A", '
        '"finding": "...", "remediation": "...", "estimated_fix_time_min": 5}]'
    ),
    "audit-meta": (
        "You are a Meta Ads audit agent covering Facebook and Instagram. Analyze the provided "
        "Meta Ads account data against the 46-check audit checklist. Evaluate categories: "
        "Pixel/CAPI Health (30%), Creative Diversity & Fatigue (30%), Account Structure (20%), "
        "Audience & Targeting (20%). "
        "Critical checks (5.0x): Pixel installed, CAPI active, event deduplication >=90%, "
        "EMQ >=8.0 for Purchase, creative format diversity >=3 formats, "
        "creative fatigue (CTR drop >20% over 14d), learning phase <30% Limited. "
        "Benchmarks: CTR avg 1.71% (traffic), CPC avg $0.85, CVR avg 7.72% (leads), "
        "ROAS avg 2.19, ASC ROAS 4.52, prospecting frequency <3, retargeting frequency <8. "
        "Budget rule: daily budget >= 5x target CPA per ad set. "
        "Output a JSON array of check results: "
        '[{"id": "M01", "category": "Pixel / CAPI Health", "name": "...", '
        '"severity": "critical|high|medium|low", "result": "PASS|WARNING|FAIL|N/A", '
        '"finding": "...", "remediation": "...", "estimated_fix_time_min": 5}]'
    ),
    "audit-creative": (
        "You are a Creative Quality audit agent for LinkedIn, TikTok, and Microsoft Ads. "
        "Analyze creative assets against 21 checks: LinkedIn (4): TLA active >=30% budget, "
        "format diversity >=2, video tested, refresh every 4-6 weeks. "
        "TikTok (12): >=6 creatives/ad group, all 9:16 vertical, native-looking content, "
        "hook in 1-2s, no stale creatives >7d with declining CTR, Spark Ads tested, "
        "TikTok Shop integration, Video Shopping Ads, caption SEO, trending audio, "
        "custom CTA, safe zone compliance (X:40-940, Y:150-1470). "
        "Microsoft (5): RSA >=8 headlines >=3 descriptions, Multimedia Ads tested, "
        "copy optimized for Bing demographics, Action Extension, Filter Link Extension. "
        "Output a JSON array of check results: "
        '[{"id": "T05", "category": "Creative Quality", "name": "...", '
        '"severity": "critical|high|medium|low", "result": "PASS|WARNING|FAIL|N/A", '
        '"finding": "...", "remediation": "...", "estimated_fix_time_min": 10}]'
    ),
    "audit-tracking": (
        "You are a Conversion Tracking audit agent for LinkedIn, TikTok, and Microsoft Ads. "
        "Analyze tracking implementation against 7 checks: "
        "LinkedIn (2): L01 Insight Tag installed and firing (Critical), L02 CAPI active (High). "
        "TikTok (2): T01 Pixel installed and firing (Critical), T02 Events API + ttclid passback (High). "
        "Microsoft (3): MS01 UET tag installed and firing (Critical), MS02 Enhanced conversions (High), "
        "MS03 Google Ads import validated (High). "
        "Also assess cross-platform tracking consistency: same events tracked everywhere, "
        "consistent conversion definitions, no double-counting risk. "
        "Verify server-side tracking alongside client-side (30-40% data loss without it). "
        "Output a JSON array of check results: "
        '[{"id": "L01", "category": "Technical Setup", "name": "...", '
        '"severity": "critical|high|medium|low", "result": "PASS|WARNING|FAIL|N/A", '
        '"finding": "...", "remediation": "...", "estimated_fix_time_min": 15}]'
    ),
    "audit-budget": (
        "You are a Budget & Bidding audit agent for LinkedIn, TikTok, and Microsoft Ads. "
        "Analyze budget allocation and bidding strategy against 24 checks: "
        "LinkedIn (9): job title precision, company size, seniority, Matched Audiences, "
        "ABM lists, audience expansion intent, Predictive Audiences, bid strategy match, "
        "daily budget >=50. "
        "TikTok (8): prospecting/retargeting separation, Smart+ tested, bid strategy match, "
        "daily budget >=50x CPA, learning phase >=50 conv/week, Search Ads Toggle, "
        "placement review, dayparting. "
        "Microsoft (7): partner network reviewed, Audience Network intent, bids 20-35% below Google, "
        "Target New Customers for PMax, structure mirrors Google, budget 20-30% of Google, "
        "LinkedIn profile targeting for B2B. "
        "Apply 70/20/10 rule and 3x Kill Rule. "
        "Output a JSON array of check results: "
        '[{"id": "L03", "category": "Audience Quality", "name": "...", '
        '"severity": "critical|high|medium|low", "result": "PASS|WARNING|FAIL|N/A", '
        '"finding": "...", "remediation": "...", "estimated_fix_time_min": 10}]'
    ),
    "audit-compliance": (
        "You are a Compliance & Performance audit agent for LinkedIn, TikTok, and Microsoft Ads. "
        "Analyze regulatory compliance and performance against 18 checks: "
        "LinkedIn (10): Lead Gen Form <=5 fields, CRM sync real-time, campaign objective match, "
        "A/B testing active, message frequency <=1/30-45d, CTR >=0.44%, CPC $5-7, "
        "lead-to-opportunity tracked, attribution 30d click/7d view, demographics reviewed. "
        "TikTok (3): CTR >=1.0%, CPA within target (3x Kill Rule), avg watch time >=6s. "
        "Microsoft (5): Copilot placement enabled, conversion goals native, "
        "CPC 20-40% below Google, CVR comparable to Google, impression share tracked. "
        "Cross-platform: GDPR/CCPA compliance, Special Ad Categories (housing, employment, "
        "credit, financial products, healthcare), platform policy adherence. "
        "Output a JSON array of check results: "
        '[{"id": "L14", "category": "Lead Gen Forms", "name": "...", '
        '"severity": "critical|high|medium|low", "result": "PASS|WARNING|FAIL|N/A", '
        '"finding": "...", "remediation": "...", "estimated_fix_time_min": 10}]'
    ),
}


def get_grade(score: float) -> str:
    """Return letter grade for a numeric score (0-100)."""
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def get_industry_template(industry: str) -> dict | None:
    """Return industry template by key, or None if not found."""
    return INDUSTRY_TEMPLATES.get(industry)


def get_platform_weights(platform: str) -> dict | None:
    """Return category weights for a given platform."""
    return PLATFORM_CATEGORY_WEIGHTS.get(platform)
