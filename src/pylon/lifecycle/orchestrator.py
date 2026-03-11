"""Product Lifecycle orchestration and deterministic multi-agent reference logic."""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime
from html import escape
from typing import Any
from urllib.parse import urlparse

from pylon.autonomy.routing import ModelRouteRequest
from pylon.providers.base import Message
from pylon.runtime.llm import LLMRuntime, ProviderRegistry
from pylon.workflow.result import NodeResult

PHASE_ORDER: tuple[str, ...] = (
    "research",
    "planning",
    "design",
    "approval",
    "development",
    "deploy",
    "iterate",
)

_MUTABLE_PROJECT_FIELDS = frozenset(
    {
        "name",
        "description",
        "githubRepo",
        "spec",
        "autonomyLevel",
        "researchConfig",
        "research",
        "analysis",
        "features",
        "milestones",
        "designVariants",
        "selectedDesignId",
        "approvalStatus",
        "approvalComments",
        "approvalRequestId",
        "buildCode",
        "buildCost",
        "buildIteration",
        "milestoneResults",
        "planEstimates",
        "selectedPreset",
        "orchestrationMode",
        "phaseStatuses",
        "deployChecks",
        "releases",
        "feedbackItems",
        "recommendations",
        "artifacts",
        "decisionLog",
        "skillInvocations",
        "delegations",
        "phaseRuns",
    }
)


def _utc_now_iso() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _slug(value: str, *, prefix: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    if not cleaned:
        cleaned = f"{prefix}-{uuid.uuid4().hex[:6]}"
    return cleaned[:48]


def _keywords(spec: str) -> list[str]:
    lowered = str(spec).replace("・", " ").replace("/", " ").replace("_", " ").lower()
    tokens = [token.strip(".,:;!?()[]{}\"'") for token in lowered.split()]
    return [token for token in tokens if token]


def _contains_any(spec: str, *terms: str) -> bool:
    lowered = spec.lower()
    return any(term.lower() in lowered for term in terms)


_PRODUCT_KIND_SIGNALS: dict[str, tuple[tuple[str, int], ...]] = {
    "learning": (
        ("学習", 3),
        ("勉強", 3),
        ("lesson", 3),
        ("quiz", 3),
        ("education", 3),
        ("child", 3),
        ("kids", 3),
        ("family", 2),
        ("game", 2),
        ("ゲーム", 2),
    ),
    "operations": (
        ("workflow", 3),
        ("approval", 3),
        ("operator", 3),
        ("orchestration", 3),
        ("運用", 3),
        ("承認", 3),
        ("監査", 3),
        ("control plane", 3),
        ("platform", 1),
        ("agent", 1),
        ("ops", 1),
        ("studio", 1),
    ),
    "commerce": (
        ("checkout", 3),
        ("commerce", 3),
        ("e-commerce", 3),
        ("注文", 3),
        ("shop", 2),
        ("store", 2),
        ("cart", 2),
        ("order", 2),
        ("販売", 2),
    ),
}

_PRODUCT_KIND_PRIORITY = {
    "learning": 3,
    "commerce": 2,
    "operations": 1,
    "generic": 0,
}


def _weighted_keyword_score(spec: str, terms: tuple[tuple[str, int], ...]) -> int:
    lowered = spec.lower()
    prefix = lowered[:600]
    score = 0
    for term, weight in terms:
        normalized = term.lower()
        hits = lowered.count(normalized)
        if hits <= 0:
            continue
        score += hits * weight
        if normalized in prefix:
            score += weight
    return score


def _selected_feature_names(state: dict[str, Any]) -> list[str]:
    selected = []
    for item in state.get("features", []) or state.get("selected_features", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("selected", True):
            name = str(item.get("feature", "")).strip()
            if name:
                selected.append(name)
    return selected


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _compact_lifecycle_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 2:
        if isinstance(value, str):
            return value[:280]
        if isinstance(value, list):
            return f"{len(value)} items"
        if isinstance(value, dict):
            return f"{len(value)} fields"
        return value
    if isinstance(value, str):
        return value[:280]
    if isinstance(value, list):
        return [_compact_lifecycle_value(item, depth=depth + 1) for item in value[:6]]
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 10:
                compacted["_truncated"] = True
                break
            compacted[str(key)] = _compact_lifecycle_value(item, depth=depth + 1)
        return compacted
    return value


def _infer_product_kind(spec: str) -> str:
    tokens = set(_keywords(spec))
    if "ec" in tokens:
        return "commerce"
    scores = {
        kind: _weighted_keyword_score(spec, terms)
        for kind, terms in _PRODUCT_KIND_SIGNALS.items()
    }
    top_kind, top_score = max(
        scores.items(),
        key=lambda item: (item[1], _PRODUCT_KIND_PRIORITY[item[0]]),
    )
    if top_score > 0:
        return top_kind
    return "generic"


def _research_context(state: dict[str, Any]) -> dict[str, Any]:
    research = _as_dict(state.get("research"))
    user_research = _as_dict(research.get("user_research")) or _as_dict(state.get("user_research"))
    return {
        "research": research,
        "user_signals": [str(item) for item in _as_list(user_research.get("signals")) if str(item).strip()],
        "pain_points": [str(item) for item in _as_list(user_research.get("pain_points")) if str(item).strip()],
        "opportunities": [str(item) for item in _as_list(research.get("opportunities")) if str(item).strip()],
        "threats": [str(item) for item in _as_list(research.get("threats")) if str(item).strip()],
        "segment": str(user_research.get("segment") or _segment_from_spec(str(state.get("spec", "")))),
    }


def _base_design_tokens(spec: str) -> dict[str, Any]:
    kind = _infer_product_kind(spec)
    if kind == "learning":
        return {
            "style": {
                "name": "Playful Learning",
                "keywords": ["friendly", "bright", "encouraging"],
                "best_for": "family learning journeys and short-session retention",
                "performance": "lightweight card-based UI with clear progress cues",
                "accessibility": "high-contrast labels and large tap targets",
            },
            "colors": {
                "primary": "#2563eb",
                "secondary": "#22c55e",
                "cta": "#f59e0b",
                "background": "#f8fafc",
                "text": "#1e293b",
                "notes": "Use warm reward accents sparingly to keep focus on the learning loop.",
            },
            "typography": {
                "heading": "Plus Jakarta Sans",
                "body": "Noto Sans JP",
                "mood": ["playful", "clear", "reassuring"],
            },
            "effects": ["gentle progress glow", "soft card lift", "streak celebration accents"],
            "anti_patterns": ["dense admin dashboards", "small caption-heavy controls", "low-contrast reward states"],
            "rationale": "The interface should motivate repeated short sessions while still feeling safe and legible for guardians.",
        }
    if kind == "commerce":
        return {
            "style": {
                "name": "Trust Commerce",
                "keywords": ["confident", "clean", "conversion-focused"],
                "best_for": "catalog browsing, checkout, and order confidence",
                "performance": "fast browsing with clear merchandising hierarchy",
                "accessibility": "strong contrast and explicit form states",
            },
            "colors": {
                "primary": "#0f172a",
                "secondary": "#0ea5e9",
                "cta": "#ef4444",
                "background": "#ffffff",
                "text": "#111827",
                "notes": "Keep CTA contrast high and reserve red for decisive commerce actions.",
            },
            "typography": {
                "heading": "IBM Plex Sans",
                "body": "Noto Sans JP",
                "mood": ["trustworthy", "direct", "efficient"],
            },
            "effects": ["sticky CTA emphasis", "hover elevation for product cards", "quiet checkout motion"],
            "anti_patterns": ["hidden fees", "ambiguous status colors", "over-decorated checkout forms"],
            "rationale": "Commerce flows need trust and speed more than novelty, so the visual system should reduce hesitation.",
        }
    if kind == "operations":
        return {
            "style": {
                "name": "Operational Clarity",
                "keywords": ["structured", "audit-ready", "high-density"],
                "best_for": "operator workflows and decision-heavy platform surfaces",
                "performance": "dense but scannable layouts with clear state changes",
                "accessibility": "semantic contrast and explicit status signaling",
            },
            "colors": {
                "primary": "#0f172a",
                "secondary": "#1d4ed8",
                "cta": "#f97316",
                "background": "#f8fafc",
                "text": "#0f172a",
                "notes": "Use amber as an operator action color and blue for system state.",
            },
            "typography": {
                "heading": "IBM Plex Sans",
                "body": "Noto Sans JP",
                "mood": ["precise", "technical", "controlled"],
            },
            "effects": ["status pulse for active runs", "subtle panel depth", "artifact lineage emphasis"],
            "anti_patterns": ["ornamental gradients", "ambiguous badges", "oversized marketing hero blocks"],
            "rationale": "Operator products need trustworthy density and fast scanability rather than decorative novelty.",
        }
    return {
        "style": {
            "name": "Balanced Product",
            "keywords": ["clear", "adaptive", "modern"],
            "best_for": "general-purpose digital products with mixed audiences",
            "performance": "progressive disclosure and responsive content grouping",
            "accessibility": "clear semantic hierarchy and keyboard-safe interactions",
        },
        "colors": {
            "primary": "#1d4ed8",
            "secondary": "#14b8a6",
            "cta": "#f97316",
            "background": "#f8fafc",
            "text": "#0f172a",
            "notes": "Keep the palette restrained so feature priority and content hierarchy carry the UI.",
        },
        "typography": {
            "heading": "IBM Plex Sans",
            "body": "Noto Sans JP",
            "mood": ["balanced", "practical", "modern"],
        },
        "effects": ["subtle entry fades", "hover elevation", "clear focus rings"],
        "anti_patterns": ["generic dashboard filler", "weak empty states", "low-information hero sections"],
        "rationale": "The product should stay adaptable while preserving clear task hierarchy and predictable interactions.",
    }


def _build_persona_bundle(state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    spec = str(state.get("spec", ""))
    kind = _infer_product_kind(spec)
    context = _research_context(state)
    signals = context["user_signals"] or ["価値をすばやく理解したい", "迷わず次の行動に進みたい"]
    pain_points = context["pain_points"] or ["文脈が失われやすい", "品質の見通しが持ちづらい"]
    segment = context["segment"]

    if kind == "learning":
        personas = [
            {
                "name": "Haruka",
                "role": "保護者",
                "age_range": "32-45",
                "goals": _dedupe_strings(["子どもが毎日無理なく続けられること", "学習の進み具合を短時間で把握すること", signals[0]]),
                "frustrations": _dedupe_strings(["続けにくい教材だと習慣化しない", "成果が見えないと課金継続を判断しづらい", pain_points[0]]),
                "tech_proficiency": "medium",
                "context": "忙しい生活の中で、短時間でも継続できる学習体験を求めている。",
            },
            {
                "name": "Sota",
                "role": "学習者",
                "age_range": "6-11",
                "goals": ["毎日少しずつ達成感を得ること", "ゲーム感覚で学び続けること"],
                "frustrations": ["難しすぎると離脱する", "単調だと飽きやすい"],
                "tech_proficiency": "medium",
                "context": "スマホやタブレットで短い学習セッションを繰り返す。",
            },
        ]
        stories = [
            {
                "role": "保護者",
                "action": "1日の学習量と継続状況を確認したい",
                "benefit": "無理のない学習習慣を支援できる",
                "acceptance_criteria": ["今日の達成状況が見える", "継続日数が一目で分かる", "次の推奨行動が提示される"],
                "priority": "must",
            },
            {
                "role": "学習者",
                "action": "短いチャレンジを遊ぶように完了したい",
                "benefit": "毎日続けるモチベーションが保てる",
                "acceptance_criteria": ["1回5分以内で完了できる", "達成時に報酬がある", "難易度が調整される"],
                "priority": "must",
            },
            {
                "role": "保護者",
                "action": "子どもに合わせて学習設定を変えたい",
                "benefit": "年齢や進度に合った学習体験を維持できる",
                "acceptance_criteria": ["目標を変更できる", "通知や時間帯を設定できる"],
                "priority": "should",
            },
        ]
        journeys = [
            {
                "persona_name": "Haruka",
                "touchpoints": [
                    {"phase": "awareness", "persona": "Haruka", "action": "子ども向け学習アプリを探す", "touchpoint": "App listing", "emotion": "neutral", "pain_point": "本当に続くか判断しづらい", "opportunity": "短時間で続く設計を明示する"},
                    {"phase": "consideration", "persona": "Haruka", "action": "無料体験を比較する", "touchpoint": "Onboarding preview", "emotion": "neutral", "opportunity": "保護者向けの進捗可視化を先に見せる"},
                    {"phase": "acquisition", "persona": "Haruka", "action": "初回設定を行う", "touchpoint": "Goal setup", "emotion": "positive", "opportunity": "年齢別おすすめ設定を提案する"},
                    {"phase": "usage", "persona": "Haruka", "action": "進捗と継続を確認する", "touchpoint": "Guardian dashboard", "emotion": "positive", "opportunity": "今日の一言サマリーを表示する"},
                    {"phase": "advocacy", "persona": "Haruka", "action": "他の保護者に共有する", "touchpoint": "Progress share", "emotion": "positive", "opportunity": "達成バッジを共有可能にする"},
                ],
            }
        ]
        return personas, stories, journeys

    if kind == "commerce":
        personas = [
            {
                "name": "Mina",
                "role": "購入者",
                "age_range": "24-40",
                "goals": _dedupe_strings(["欲しい商品を迷わず見つけること", "安心して購入を完了すること", signals[0]]),
                "frustrations": _dedupe_strings(["比較や在庫状況が見えにくい", "購入途中で不安になる", pain_points[0]]),
                "tech_proficiency": "medium",
                "context": "スマホ中心で比較検討から購入までを短時間で済ませたい。",
            },
            {
                "name": "Riku",
                "role": "店舗運営担当",
                "age_range": "28-42",
                "goals": ["売れ筋と離脱ポイントを把握すること", "在庫切れや問い合わせ負荷を減らすこと"],
                "frustrations": ["販促の効果測定が遅い", "顧客の迷いポイントが見えない"],
                "tech_proficiency": "high",
                "context": "商品運営とCVR改善を兼務している。",
            },
        ]
        stories = [
            {
                "role": "購入者",
                "action": "条件に合う商品をすぐに絞り込みたい",
                "benefit": "比較の負担を減らして購入判断を早められる",
                "acceptance_criteria": ["カテゴリ・価格・在庫で絞り込める", "比較観点が分かりやすい"],
                "priority": "must",
            },
            {
                "role": "購入者",
                "action": "配送や支払い条件を確認して安心して決済したい",
                "benefit": "購入途中の離脱を減らせる",
                "acceptance_criteria": ["送料や到着見込みが明示される", "チェックアウト状態が分かる"],
                "priority": "must",
            },
            {
                "role": "店舗運営担当",
                "action": "在庫と売れ筋を把握したい",
                "benefit": "欠品や機会損失を減らせる",
                "acceptance_criteria": ["在庫警告がある", "人気商品を一覧できる"],
                "priority": "should",
            },
        ]
        journeys = [
            {
                "persona_name": "Mina",
                "touchpoints": [
                    {"phase": "awareness", "persona": "Mina", "action": "商品を検索する", "touchpoint": "Search results", "emotion": "neutral", "opportunity": "比較軸をカード上で見せる"},
                    {"phase": "consideration", "persona": "Mina", "action": "候補を比較する", "touchpoint": "Product detail", "emotion": "neutral", "pain_point": "違いが分かりにくい", "opportunity": "仕様比較とレビュー要約を出す"},
                    {"phase": "acquisition", "persona": "Mina", "action": "購入する", "touchpoint": "Checkout", "emotion": "positive", "opportunity": "配送・支払情報を1画面で確信させる"},
                    {"phase": "usage", "persona": "Mina", "action": "配送状況を確認する", "touchpoint": "Order tracking", "emotion": "neutral", "opportunity": "通知と到着予測を提供する"},
                    {"phase": "advocacy", "persona": "Mina", "action": "レビューを書く", "touchpoint": "Review prompt", "emotion": "positive", "opportunity": "満足直後に投稿を促す"},
                ],
            }
        ]
        return personas, stories, journeys

    if kind == "operations":
        personas = [
            {
                "name": "Aiko",
                "role": f"{segment} Platform Lead",
                "age_range": "30-45",
                "goals": _dedupe_strings(["意思決定から実装までの文脈をつなぐこと", "品質と自律性を両立すること", signals[0]]),
                "frustrations": _dedupe_strings(["handoff ごとに文脈が失われる", "承認や監査の根拠が散らばる", pain_points[0]]),
                "tech_proficiency": "high",
                "context": "複数職能をまたいで delivery を統制する責任を持つ。",
            },
            {
                "name": "Ken",
                "role": "Workflow Operator",
                "age_range": "28-40",
                "goals": ["run の進行状況と blocker を即座に把握すること", "次の承認や修正指示を迷わず出すこと"],
                "frustrations": ["artifact とレビュー論点が分断される", "phase ごとの進捗根拠が薄い"],
                "tech_proficiency": "high",
                "context": "daily operation と release 判断を担う。",
            },
        ]
        stories = [
            {
                "role": "Platform Lead",
                "action": "調査から build までの意思決定根拠を残したい",
                "benefit": "レビューと承認の説明責任を果たせる",
                "acceptance_criteria": ["phase ごとに artifact が残る", "差し戻し理由が追える", "品質ゲートが見える"],
                "priority": "must",
            },
            {
                "role": "Workflow Operator",
                "action": "multi-agent run の状況と次の判断を把握したい",
                "benefit": "詰まりを早く解消できる",
                "acceptance_criteria": ["run 状態が見える", "agent handoff が分かる", "次アクションが示される"],
                "priority": "must",
            },
            {
                "role": "Platform Lead",
                "action": "選択した design と feature scope を一貫して build に渡したい",
                "benefit": "手戻りを減らせる",
                "acceptance_criteria": ["selected design が build に反映される", "feature scope と milestone が連動する"],
                "priority": "should",
            },
        ]
        journeys = [
            {
                "persona_name": "Aiko",
                "touchpoints": [
                    {"phase": "awareness", "persona": "Aiko", "action": "新しい product initiative を起票する", "touchpoint": "Research brief", "emotion": "neutral", "opportunity": "価値仮説と競合観点を最初に並べる"},
                    {"phase": "consideration", "persona": "Aiko", "action": "scope を調整する", "touchpoint": "Planning review", "emotion": "neutral", "pain_point": "優先順位と根拠が揃わない", "opportunity": "Must/Should/Could と rationale をセットで出す"},
                    {"phase": "acquisition", "persona": "Aiko", "action": "Go/No-Go を決める", "touchpoint": "Approval gate", "emotion": "positive", "opportunity": "差し戻し先に深くリンクする"},
                    {"phase": "usage", "persona": "Aiko", "action": "build と quality を確認する", "touchpoint": "Development review", "emotion": "positive", "opportunity": "artifact lineage と milestone を並べる"},
                    {"phase": "advocacy", "persona": "Aiko", "action": "運用チームに共有する", "touchpoint": "Release summary", "emotion": "positive", "opportunity": "release-ready 条件を明文化する"},
                ],
            }
        ]
        return personas, stories, journeys

    personas = [
        {
            "name": "Naoki",
            "role": f"{segment} Product Owner",
            "age_range": "28-42",
            "goals": _dedupe_strings(["ユーザーに価値が伝わる初期体験を作ること", "仕様と実装のズレを減らすこと", signals[0]]),
            "frustrations": _dedupe_strings(["要求が広がりやすい", "優先順位が曖昧だと開発がぶれる", pain_points[0]]),
            "tech_proficiency": "high",
            "context": "企画と実装の橋渡しを担う。",
        },
        {
            "name": "Yuna",
            "role": "Primary User",
            "age_range": "24-38",
            "goals": ["迷わず主要タスクを完了すること", "途中で価値を実感すること"],
            "frustrations": ["最初の導線が複雑だと離脱する", "状態が分かりにくいと不安になる"],
            "tech_proficiency": "medium",
            "context": "モバイルとデスクトップを横断して利用する。",
        },
    ]
    stories = [
        {
            "role": "Product Owner",
            "action": "主要な利用シナリオを先に定義したい",
            "benefit": "scope を早く固定できる",
            "acceptance_criteria": ["主要導線が明文化される", "優先順位が示される"],
            "priority": "must",
        },
        {
            "role": "Primary User",
            "action": "最初のタスクを短時間で完了したい",
            "benefit": "継続利用する価値をすぐに理解できる",
            "acceptance_criteria": ["初回導線が短い", "状態と次アクションが明示される"],
            "priority": "must",
        },
    ]
    journeys = [
        {
            "persona_name": "Yuna",
            "touchpoints": [
                {"phase": "awareness", "persona": "Yuna", "action": "価値を知る", "touchpoint": "Landing / first view", "emotion": "neutral", "opportunity": "主要価値を1画面で伝える"},
                {"phase": "consideration", "persona": "Yuna", "action": "試すか判断する", "touchpoint": "Onboarding", "emotion": "neutral", "opportunity": "主要ユースケースだけ先に見せる"},
                {"phase": "acquisition", "persona": "Yuna", "action": "初回設定を完了する", "touchpoint": "Setup", "emotion": "positive", "opportunity": "progressive disclosure を使う"},
                {"phase": "usage", "persona": "Yuna", "action": "主要タスクを実行する", "touchpoint": "Primary workflow", "emotion": "positive", "opportunity": "空状態と次アクションを強くする"},
                {"phase": "advocacy", "persona": "Yuna", "action": "チームに共有する", "touchpoint": "Share / export", "emotion": "positive", "opportunity": "成果物を共有しやすくする"},
            ],
        }
    ]
    return personas, stories, journeys


def _build_story_architecture_bundle(state: dict[str, Any]) -> dict[str, Any]:
    spec = str(state.get("spec", ""))
    kind = _infer_product_kind(spec)
    feature_names = _selected_feature_names(state)

    if kind == "learning":
        return {
            "job_stories": [
                {
                    "situation": "When a child opens the app for a short daily study session",
                    "motivation": "I want the next lesson to feel achievable and fun",
                    "outcome": "So I can keep the habit going without parental prompting",
                    "priority": "core",
                    "related_features": ["日次レッスン", "ごほうび", "進捗トラッキング"],
                },
                {
                    "situation": "When a guardian checks progress after a busy day",
                    "motivation": "I want a quick summary of what was learned and what needs help",
                    "outcome": "So I can support the child without reading a long report",
                    "priority": "supporting",
                    "related_features": ["保護者ダッシュボード", "進捗トラッキング"],
                },
            ],
            "actors": [
                {"name": "Guardian", "type": "primary", "description": "学習習慣を支援する保護者", "goals": ["継続率の把握", "安全な利用"], "interactions": ["progress review", "settings"]},
                {"name": "Learner", "type": "primary", "description": "短時間の学習を行う子ども", "goals": ["達成感", "楽しい学習"], "interactions": ["daily lesson", "rewards"]},
                {"name": "Recommendation Engine", "type": "external_system", "description": "難易度や次の課題を提案する外部ロジック", "goals": ["最適難易度提示"], "interactions": ["lesson personalization"]},
            ],
            "roles": [
                {"name": "Guardian", "responsibilities": ["目標設定", "利用管理", "進捗確認"], "permissions": ["view_progress", "update_goals", "manage_notifications"], "related_actors": ["Guardian"]},
                {"name": "Learner", "responsibilities": ["日次課題の実行", "報酬の受け取り"], "permissions": ["start_lesson", "view_rewards"], "related_actors": ["Learner"]},
                {"name": "Content Admin", "responsibilities": ["問題セットの更新", "学習シナリオの管理"], "permissions": ["manage_content", "review_metrics"], "related_actors": ["Recommendation Engine"]},
            ],
            "use_cases": [
                {"id": "uc-learn-001", "title": "Start daily lesson", "actor": "Learner", "category": "学習体験", "sub_category": "実行", "preconditions": ["今日の課題が生成されている"], "main_flow": ["ホームを開く", "今日の課題を開始する", "問題に回答する", "結果と報酬を受け取る"], "postconditions": ["学習結果が保存される"], "priority": "must", "related_stories": ["日次レッスン"]},
                {"id": "uc-learn-002", "title": "Review guardian summary", "actor": "Guardian", "category": "保護者管理", "sub_category": "確認", "preconditions": ["学習履歴が存在する"], "main_flow": ["進捗画面を開く", "今日の達成と継続日数を確認する", "次の推奨行動を確認する"], "postconditions": ["支援内容を判断できる"], "priority": "must", "related_stories": ["進捗トラッキング"]},
                {"id": "uc-learn-003", "title": "Adjust learning plan", "actor": "Guardian", "category": "保護者管理", "sub_category": "設定", "preconditions": ["利用者プロフィールが存在する"], "main_flow": ["目標設定を開く", "難易度や時間帯を変更する", "通知設定を保存する"], "postconditions": ["次回提案に設定が反映される"], "priority": "should", "related_stories": ["保護者コントロール"]},
            ],
            "ia_analysis": {
                "navigation_model": "hierarchical",
                "site_map": [
                    {"id": "home", "label": "ホーム", "description": "今日の課題と継続状況", "priority": "primary", "children": []},
                    {"id": "lessons", "label": "レッスン", "description": "学習コンテンツ一覧", "priority": "primary", "children": []},
                    {"id": "progress", "label": "進捗", "description": "習慣と理解度の確認", "priority": "primary", "children": []},
                    {"id": "guardian", "label": "保護者設定", "description": "目標・通知・制限の管理", "priority": "secondary", "children": []},
                    {"id": "support", "label": "ヘルプ", "description": "FAQ と問い合わせ", "priority": "utility", "children": []},
                ],
                "key_paths": [
                    {"name": "Daily lesson loop", "steps": ["ホーム", "今日の課題", "結果", "報酬"]},
                    {"name": "Guardian review", "steps": ["進捗", "学習サマリー", "目標設定"]},
                ],
            },
        }

    if kind == "commerce":
        return {
            "job_stories": [
                {"situation": "When a buyer is comparing multiple products on mobile", "motivation": "I want filters and trust signals to narrow my choices fast", "outcome": "So I can buy without second-guessing the decision", "priority": "core", "related_features": ["商品検索", "比較", "在庫表示"]},
                {"situation": "When an operator spots a low-stock item", "motivation": "I want to react before high-intent demand is lost", "outcome": "So I can protect conversion and reduce support load", "priority": "supporting", "related_features": ["在庫アラート", "注文管理"]},
            ],
            "actors": [
                {"name": "Buyer", "type": "primary", "description": "購入検討中のユーザー", "goals": ["比較の簡略化", "安心して決済"], "interactions": ["search", "checkout"]},
                {"name": "Store Operator", "type": "primary", "description": "商品と注文を管理する運営担当", "goals": ["在庫最適化", "CVR改善"], "interactions": ["inventory", "order review"]},
                {"name": "Payment Provider", "type": "external_system", "description": "決済を処理する外部サービス", "goals": ["安全な決済"], "interactions": ["checkout"]},
            ],
            "roles": [
                {"name": "Buyer", "responsibilities": ["商品探索", "注文", "配送確認"], "permissions": ["browse_products", "checkout", "view_orders"], "related_actors": ["Buyer"]},
                {"name": "Merchandiser", "responsibilities": ["商品情報更新", "在庫管理"], "permissions": ["manage_catalog", "manage_inventory"], "related_actors": ["Store Operator"]},
                {"name": "Support Operator", "responsibilities": ["注文対応", "返品確認"], "permissions": ["view_orders", "update_order_status"], "related_actors": ["Store Operator"]},
            ],
            "use_cases": [
                {"id": "uc-commerce-001", "title": "Browse and filter products", "actor": "Buyer", "category": "商品探索", "sub_category": "検索・比較", "preconditions": ["商品データが存在する"], "main_flow": ["商品一覧を開く", "条件で絞り込む", "比較候補を選ぶ", "詳細を確認する"], "postconditions": ["比較候補が決まる"], "priority": "must", "related_stories": ["商品検索"]},
                {"id": "uc-commerce-002", "title": "Complete checkout", "actor": "Buyer", "category": "購入", "sub_category": "決済", "preconditions": ["カートに商品が入っている"], "main_flow": ["配送先を入力する", "支払方法を選ぶ", "合計金額を確認する", "注文を確定する"], "postconditions": ["注文が作成される"], "priority": "must", "related_stories": ["チェックアウト"]},
                {"id": "uc-commerce-003", "title": "Manage inventory risk", "actor": "Merchandiser", "category": "運営管理", "sub_category": "在庫", "preconditions": ["在庫データが連携されている"], "main_flow": ["在庫画面を開く", "欠品リスクを確認する", "補充アクションを決める"], "postconditions": ["在庫リスクが整理される"], "priority": "should", "related_stories": ["在庫アラート"]},
            ],
            "ia_analysis": {
                "navigation_model": "hierarchical",
                "site_map": [
                    {"id": "catalog", "label": "商品一覧", "description": "カテゴリ・検索・比較", "priority": "primary", "children": []},
                    {"id": "product", "label": "商品詳細", "description": "比較と購入判断", "priority": "primary", "children": []},
                    {"id": "checkout", "label": "チェックアウト", "description": "配送と決済", "priority": "primary", "children": []},
                    {"id": "orders", "label": "注文管理", "description": "購入履歴と配送確認", "priority": "secondary", "children": []},
                    {"id": "ops", "label": "運営管理", "description": "在庫・販促・問い合わせ", "priority": "secondary", "children": []},
                ],
                "key_paths": [
                    {"name": "Browse to buy", "steps": ["商品一覧", "商品詳細", "チェックアウト", "注文確認"]},
                    {"name": "Inventory mitigation", "steps": ["運営管理", "在庫一覧", "補充判断"]},
                ],
            },
        }

    if kind == "operations":
        return {
            "job_stories": [
                {"situation": "When a product team starts a new initiative", "motivation": "I want the system to turn evidence into a decision-ready plan", "outcome": "So I can move into delivery without losing context", "priority": "core", "related_features": ["research workspace", "planning synthesis", "approval gate"]},
                {"situation": "When a release is blocked by quality or governance concerns", "motivation": "I want the blocking artifacts and next action to be obvious", "outcome": "So I can resolve the issue quickly instead of chasing context", "priority": "core", "related_features": ["artifact lineage", "release gate", "operator console"]},
            ],
            "actors": [
                {"name": "Platform Lead", "type": "primary", "description": "product delivery を統制する責任者", "goals": ["意思決定速度", "説明責任"], "interactions": ["planning review", "approval gate"]},
                {"name": "Lifecycle Operator", "type": "primary", "description": "phase 実行と blocker 解消を担う運用者", "goals": ["run 可視化", "handoff 制御"], "interactions": ["run monitor", "deploy review"]},
                {"name": "Audit Peer", "type": "external_system", "description": "承認・安全性の妥当性を確認する peer", "goals": ["監査可能性"], "interactions": ["approval", "security review"]},
            ],
            "roles": [
                {"name": "Platform Lead", "responsibilities": ["scope judgment", "approval", "release oversight"], "permissions": ["approve", "select_design", "view_costs"], "related_actors": ["Platform Lead"]},
                {"name": "Lifecycle Operator", "responsibilities": ["phase execution", "exception handling", "deploy checks"], "permissions": ["run_phase", "view_artifacts", "create_release"], "related_actors": ["Lifecycle Operator"]},
                {"name": "Reviewer", "responsibilities": ["quality and security review", "rework guidance"], "permissions": ["comment", "request_changes", "view_operator_console"], "related_actors": ["Audit Peer"]},
            ],
            "use_cases": [
                {"id": "uc-ops-001", "title": "Run discovery-to-build workflow", "actor": "Lifecycle Operator", "category": "ワークフロー運用", "sub_category": "実行・監視", "preconditions": ["spec が存在する"], "main_flow": ["research を開始する", "planning をレビューする", "design を選択する", "development を実行する"], "postconditions": ["build artifact と phase history が残る"], "priority": "must", "related_stories": ["research workspace"]},
                {"id": "uc-ops-002", "title": "Approve or rework a phase", "actor": "Platform Lead", "category": "ガバナンス", "sub_category": "承認", "preconditions": ["phase artifact が揃っている"], "main_flow": ["approval gate を開く", "根拠を確認する", "承認または差し戻しを行う"], "postconditions": ["決定履歴が残る"], "priority": "must", "related_stories": ["approval gate"]},
                {"id": "uc-ops-003", "title": "Trace artifact lineage", "actor": "Reviewer", "category": "品質管理", "sub_category": "調査", "preconditions": ["run が完了している"], "main_flow": ["artifact を開く", "関連 decision を確認する", "どの agent が作成したか追う"], "postconditions": ["根拠が説明できる"], "priority": "should", "related_stories": ["artifact lineage"]},
            ],
            "ia_analysis": {
                "navigation_model": "hub-and-spoke",
                "site_map": [
                    {"id": "workspace", "label": "Lifecycle Workspace", "description": "phase ごとの主作業領域", "priority": "primary", "children": []},
                    {"id": "runs", "label": "Runs", "description": "run と checkpoint の確認", "priority": "primary", "children": []},
                    {"id": "approvals", "label": "Approvals", "description": "承認待ちと差し戻し履歴", "priority": "primary", "children": []},
                    {"id": "artifacts", "label": "Artifacts", "description": "phase 成果物と lineage", "priority": "secondary", "children": []},
                    {"id": "settings", "label": "Settings", "description": "policy と環境設定", "priority": "utility", "children": []},
                ],
                "key_paths": [
                    {"name": "Idea to approval", "steps": ["Lifecycle Workspace", "Research", "Planning", "Approval"]},
                    {"name": "Build to release", "steps": ["Development", "Runs", "Deploy", "Release"]},
                ],
            },
        }

    return {
        "job_stories": [
            {"situation": "When a user first tries the product", "motivation": "I want the core path to be obvious", "outcome": "So I can reach value without reading a manual", "priority": "core", "related_features": feature_names[:3] or ["onboarding", "primary workflow"]},
            {"situation": "When a product team scopes the first release", "motivation": "I want a crisp definition of the MVP", "outcome": "So I can ship without uncontrolled scope growth", "priority": "supporting", "related_features": feature_names[:3] or ["MVP scope"]},
        ],
        "actors": [
            {"name": "Primary User", "type": "primary", "description": "主要タスクを実行する利用者", "goals": ["価値到達", "迷わない操作"], "interactions": ["onboarding", "main workflow"]},
            {"name": "Product Owner", "type": "secondary", "description": "価値仮説と scope を管理する担当者", "goals": ["初期リリース成功"], "interactions": ["planning", "review"]},
        ],
        "roles": [
            {"name": "Primary User", "responsibilities": ["主要タスク実行"], "permissions": ["use_core_flow"], "related_actors": ["Primary User"]},
            {"name": "Admin", "responsibilities": ["設定と品質管理"], "permissions": ["configure", "review_metrics"], "related_actors": ["Product Owner"]},
        ],
        "use_cases": [
            {"id": "uc-generic-001", "title": "Complete the primary workflow", "actor": "Primary User", "category": "主要体験", "sub_category": "実行", "preconditions": ["利用開始条件が満たされている"], "main_flow": ["ホームを開く", "主要タスクを開始する", "結果を確認する"], "postconditions": ["価値が伝わる"], "priority": "must", "related_stories": feature_names[:2]},
            {"id": "uc-generic-002", "title": "Adjust settings", "actor": "Admin", "category": "設定管理", "sub_category": "構成", "preconditions": ["設定権限がある"], "main_flow": ["設定画面を開く", "主要設定を変更する", "保存する"], "postconditions": ["次回利用に反映される"], "priority": "should", "related_stories": feature_names[:2]},
        ],
        "ia_analysis": {
            "navigation_model": "hierarchical",
            "site_map": [
                {"id": "home", "label": "ホーム", "description": "主要情報の要約", "priority": "primary", "children": []},
                {"id": "workflow", "label": "主要導線", "description": "最も価値のある操作", "priority": "primary", "children": []},
                {"id": "history", "label": "履歴", "description": "過去の操作と成果", "priority": "secondary", "children": []},
                {"id": "settings", "label": "設定", "description": "環境や通知の設定", "priority": "utility", "children": []},
            ],
            "key_paths": [
                {"name": "First-run success", "steps": ["ホーム", "主要導線", "結果"]},
                {"name": "Configuration", "steps": ["設定", "保存"]},
            ],
        },
    }


def _feature_catalog_for_spec(state: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    spec = str(state.get("spec", ""))
    kind = _infer_product_kind(spec)
    if kind == "learning":
        return [
            ("日次レッスン", "must-be", "medium", "短時間でも継続しやすい学習ループを作る"),
            ("進捗トラッキング", "must-be", "medium", "保護者が継続状況を把握できる"),
            ("ごほうび・ストリーク", "one-dimensional", "medium", "習慣化の動機を強める"),
            ("難易度の自動調整", "one-dimensional", "high", "年齢や理解度に合わせて体験を最適化する"),
            ("保護者コントロール", "must-be", "medium", "利用時間や通知を安全に管理できる"),
            ("音声ガイド", "attractive", "medium", "低年齢ユーザーの没入感を高める"),
        ]
    if kind == "commerce":
        return [
            ("商品検索と絞り込み", "must-be", "medium", "比較と発見を素早くする"),
            ("商品比較", "one-dimensional", "medium", "購買判断を短縮する"),
            ("チェックアウト", "must-be", "high", "購入完了までの離脱を減らす"),
            ("在庫アラート", "one-dimensional", "medium", "欠品による機会損失を抑える"),
            ("配送トラッキング", "one-dimensional", "medium", "購入後の不安を減らす"),
            ("レコメンド", "attractive", "high", "客単価と回遊を伸ばす"),
        ]
    if kind == "operations":
        return [
            ("research workspace", "must-be", "medium", "仮説と証拠を1か所に集約する"),
            ("planning synthesis", "must-be", "medium", "優先順位と実装計画を明文化する"),
            ("artifact lineage", "one-dimensional", "medium", "どの根拠から判断したかを追跡できる"),
            ("approval gate", "must-be", "medium", "説明責任のあるGo/Rework判断を可能にする"),
            ("operator console", "one-dimensional", "high", "run 状況と specialist handoff を監視できる"),
            ("release readiness", "attractive", "medium", "build から deploy までを統制する"),
        ]
    return [
        ("guided onboarding", "must-be", "low", "最初の価値到達を早める"),
        ("primary workflow", "must-be", "medium", "主要ユースケースを成立させる"),
        ("status visibility", "one-dimensional", "low", "利用中の不安を減らす"),
        ("notifications", "one-dimensional", "medium", "継続利用を促す"),
        ("history and recovery", "one-dimensional", "medium", "再訪時の文脈復元を容易にする"),
        ("personalization", "attractive", "high", "利用継続時の満足度を高める"),
    ]


def _solution_bundle(state: dict[str, Any]) -> dict[str, Any]:
    spec = str(state.get("spec", ""))
    kind = _infer_product_kind(spec)
    selected_features = _selected_feature_names(state)
    prominent = selected_features[:3] or [item[0] for item in _feature_catalog_for_spec(state)[:3]]

    if kind == "learning":
        business_model = {
            "value_propositions": ["短時間でも続く学習体験", "保護者が安心して見守れる進捗可視化"],
            "customer_segments": ["保護者", "学習者", "教育事業者"],
            "channels": ["App Store", "教育コミュニティ", "口コミ"],
            "revenue_streams": ["Family subscription", "Education bundle", "Premium content packs"],
        }
        milestones = [
            {"id": "ms-alpha", "name": "Daily learning loop", "criteria": f"{prominent[0]} と {prominent[1]} が1日の学習導線で完結する", "rationale": "最初に継続の核となる日次体験を成立させる", "phase": "alpha", "depends_on_use_cases": ["uc-learn-001"]},
            {"id": "ms-beta", "name": "Guardian confidence", "criteria": "保護者が進捗と設定を1画面で確認・変更できる", "rationale": "継続課金の判断材料を作る", "phase": "beta", "depends_on_use_cases": ["uc-learn-002", "uc-learn-003"]},
            {"id": "ms-release", "name": "Habit-ready release", "criteria": "通知、レスポンシブ、アクセシビリティが整い7日継続を支援できる", "rationale": "習慣化に必要な運用品質を満たす", "phase": "release", "depends_on_use_cases": ["uc-learn-001", "uc-learn-002"]},
        ]
        return {"business_model": business_model, "recommended_milestones": milestones, "design_tokens": _base_design_tokens(spec)}

    if kind == "commerce":
        business_model = {
            "value_propositions": ["比較しやすく安心して買える購入体験", "在庫と注文を見える化する運営支援"],
            "customer_segments": ["購入者", "D2C 運営チーム", "小売事業者"],
            "channels": ["Web storefront", "広告流入", "メール・CRM"],
            "revenue_streams": ["Product margin", "Subscription perks", "Merchant tooling upsell"],
        }
        milestones = [
            {"id": "ms-alpha", "name": "Browse to buy", "criteria": "検索・比較・チェックアウトまでの購入導線が成立する", "rationale": "最初にCVRを生むコアループを作る", "phase": "alpha", "depends_on_use_cases": ["uc-commerce-001", "uc-commerce-002"]},
            {"id": "ms-beta", "name": "Operational confidence", "criteria": "在庫リスクと注文状況を運営者が確認できる", "rationale": "運営上のボトルネックを減らす", "phase": "beta", "depends_on_use_cases": ["uc-commerce-003"]},
            {"id": "ms-release", "name": "Trustworthy commerce release", "criteria": "レスポンシブ、アクセシビリティ、配送通知が整った購入体験を提供する", "rationale": "実運用での安心感を確保する", "phase": "release", "depends_on_use_cases": ["uc-commerce-001", "uc-commerce-002"]},
        ]
        return {"business_model": business_model, "recommended_milestones": milestones, "design_tokens": _base_design_tokens(spec)}

    if kind == "operations":
        business_model = {
            "value_propositions": ["意思決定から実装までの context loss を減らす", "ガバナンス付き自律実行を安全に進める"],
            "customer_segments": ["AI プラットフォームチーム", "プロダクト運用チーム", "内部開発基盤チーム"],
            "channels": ["Developer tooling", "Internal platform rollout", "Ops enablement"],
            "revenue_streams": ["Platform seat", "Usage-based orchestration", "Premium governance modules"],
        }
        milestones = [
            {"id": "ms-alpha", "name": "Evidence-to-build loop", "criteria": "research から development までの artifact lineage が1本で追える", "rationale": "完全自律より先に traceability を成立させる", "phase": "alpha", "depends_on_use_cases": ["uc-ops-001"]},
            {"id": "ms-beta", "name": "Governed delivery", "criteria": "approval と rework が phase deep link 付きで運用できる", "rationale": "マルチエージェント運用の制御面を固める", "phase": "beta", "depends_on_use_cases": ["uc-ops-002"]},
            {"id": "ms-release", "name": "Operator-ready release", "criteria": "run telemetry、release gate、feedback loop が一貫して利用できる", "rationale": "運用に渡せる完成度を作る", "phase": "release", "depends_on_use_cases": ["uc-ops-001", "uc-ops-003"]},
        ]
        return {"business_model": business_model, "recommended_milestones": milestones, "design_tokens": _base_design_tokens(spec)}

    business_model = {
        "value_propositions": ["主要ユースケースを迷わず完了できる", "仕様と実装の整合を保ちやすい"],
        "customer_segments": ["Primary users", "Product teams"],
        "channels": ["Web", "Mobile", "Team sharing"],
        "revenue_streams": ["Subscription", "Team plan", "Premium capabilities"],
    }
    milestones = [
        {"id": "ms-alpha", "name": "Core workflow ready", "criteria": f"{prominent[0]} と {prominent[1]} を含む主要導線が成立する", "rationale": "最初に価値到達を成立させる", "phase": "alpha", "depends_on_use_cases": ["uc-generic-001"]},
        {"id": "ms-beta", "name": "Configuration and recovery", "criteria": "設定変更と履歴復元ができる", "rationale": "継続利用の土台を作る", "phase": "beta", "depends_on_use_cases": ["uc-generic-002"]},
        {"id": "ms-release", "name": "Release quality", "criteria": "レスポンシブ・a11y・主要状態表示が揃う", "rationale": "運用品質の下限を満たす", "phase": "release", "depends_on_use_cases": ["uc-generic-001", "uc-generic-002"]},
    ]
    return {"business_model": business_model, "recommended_milestones": milestones, "design_tokens": _base_design_tokens(spec)}


def _planning_recommendations(state: dict[str, Any]) -> list[str]:
    spec = str(state.get("spec", ""))
    kind = _infer_product_kind(spec)
    context = _research_context(state)
    technical = _as_dict(_as_dict(state.get("research")).get("tech_feasibility"))
    score = float(technical.get("score", 0.75) or 0.75)

    recommendations: list[str] = []
    if kind == "learning":
        recommendations.extend([
            "初回は保護者の安心感よりも、子どもが5分で達成感を得られる日次導線を優先する",
            "進捗可視化と通知設定を beta までに入れて継続判断の材料を作る",
        ])
    elif kind == "commerce":
        recommendations.extend([
            "比較と決済の迷いを減らす導線を優先し、checkout での不安要素を最小化する",
            "運営側には在庫と注文の可視化を先に渡して欠品・問い合わせコストを抑える",
        ])
    elif kind == "operations":
        recommendations.extend([
            "phase ごとの artifact lineage を first-class にし、承認判断の根拠を失わないようにする",
            "multi-agent の並列実行より先に、handoff と rework の制御面を固める",
        ])
    else:
        recommendations.extend([
            "初回価値到達までの導線を最短化し、二次導線は progressive disclosure で後ろに送る",
            "主要状態と次アクションを常に明示して、利用中の迷いを減らす",
        ])
    if context["opportunities"]:
        recommendations.append(f"市場機会: {context['opportunities'][0]}")
    if context["threats"]:
        recommendations.append(f"リスク: {context['threats'][0]}")
    if score < 0.78:
        recommendations.append("技術実現性スコアが相対的に低いため、alpha では scope を絞って検証可能性を優先する")
    return _dedupe_strings(recommendations)


def _artifacts(*items: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in items]


def _provider_backed_lifecycle_available(provider_registry: ProviderRegistry | None) -> bool:
    return provider_registry is not None and bool(provider_registry.provider_names())


def _clamp_score(value: Any, *, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, round(numeric, 2)))


def _color_or(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if text.startswith("#") and len(text) in {4, 7}:
        return text
    return fallback


def _preview_title(spec: str) -> str:
    for line in str(spec or "").splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:64]
    return "Lifecycle Product"


def _prototype_overrides_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "prototype_kind": str(payload.get("prototype_kind") or payload.get("prototypeKind") or "").strip(),
        "navigation_style": str(payload.get("navigation_style") or payload.get("navigationStyle") or "").strip(),
        "density": str(payload.get("density") or "").strip(),
        "screen_labels": [
            str(item).strip()
            for item in _as_list(payload.get("screen_labels") or payload.get("screenLabels"))
            if str(item).strip()
        ],
        "interaction_principles": [
            str(item).strip()
            for item in _as_list(payload.get("interaction_principles") or payload.get("interactionPrinciples"))
            if str(item).strip()
        ],
    }


def _default_site_map_for_kind(kind: str) -> list[dict[str, str]]:
    if kind == "learning":
        return [
            {"id": "home", "label": "ホーム", "priority": "primary"},
            {"id": "lessons", "label": "レッスン", "priority": "primary"},
            {"id": "progress", "label": "進捗", "priority": "primary"},
            {"id": "guardian", "label": "保護者設定", "priority": "secondary"},
        ]
    if kind == "commerce":
        return [
            {"id": "catalog", "label": "商品一覧", "priority": "primary"},
            {"id": "product", "label": "商品詳細", "priority": "primary"},
            {"id": "checkout", "label": "チェックアウト", "priority": "primary"},
            {"id": "ops", "label": "運営管理", "priority": "secondary"},
        ]
    if kind == "operations":
        return [
            {"id": "workspace", "label": "Lifecycle Workspace", "priority": "primary"},
            {"id": "runs", "label": "Runs", "priority": "primary"},
            {"id": "approvals", "label": "Approvals", "priority": "primary"},
            {"id": "artifacts", "label": "Artifacts", "priority": "secondary"},
        ]
    return [
        {"id": "home", "label": "ホーム", "priority": "primary"},
        {"id": "workflow", "label": "主要導線", "priority": "primary"},
        {"id": "history", "label": "履歴", "priority": "secondary"},
        {"id": "settings", "label": "設定", "priority": "utility"},
    ]


def _default_key_paths_for_kind(kind: str) -> list[dict[str, Any]]:
    if kind == "learning":
        return [
            {"name": "Daily lesson loop", "steps": ["ホーム", "今日の課題", "結果", "報酬"]},
            {"name": "Guardian review", "steps": ["進捗", "学習サマリー", "目標設定"]},
        ]
    if kind == "commerce":
        return [
            {"name": "Browse to buy", "steps": ["商品一覧", "商品詳細", "チェックアウト", "注文確認"]},
            {"name": "Inventory mitigation", "steps": ["運営管理", "在庫一覧", "補充判断"]},
        ]
    if kind == "operations":
        return [
            {"name": "Idea to approval", "steps": ["Lifecycle Workspace", "Research", "Planning", "Approval"]},
            {"name": "Build to release", "steps": ["Development", "Runs", "Deploy", "Release"]},
        ]
    return [
        {"name": "First-run success", "steps": ["ホーム", "主要導線", "結果"]},
        {"name": "Configuration", "steps": ["設定", "保存"]},
    ]


def _shell_layout_for_kind(kind: str) -> str:
    if kind == "commerce":
        return "top-nav"
    return "sidebar"


def _screen_layout_for_kind(kind: str, *, index: int) -> str:
    if kind == "operations":
        return "command-center" if index == 0 else "split-review"
    if kind == "commerce":
        return "catalog-grid" if index == 0 else "decision-panel"
    if kind == "learning":
        return "guided-lesson" if index == 0 else "progress-console"
    return "product-workspace" if index == 0 else "detail-canvas"


def _screen_modules_for_context(
    *,
    kind: str,
    label: str,
    features: list[str],
    use_case: dict[str, Any],
    key_path: dict[str, Any],
    personas: list[dict[str, Any]],
    milestones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lowered = label.lower()
    role = str((_as_dict(personas[0]).get("role") if personas else "") or (_as_dict(personas[0]).get("name") if personas else "") or "Primary user")
    flow_steps = [str(item) for item in _as_list(use_case.get("main_flow")) if str(item).strip()] or [
        str(item) for item in _as_list(key_path.get("steps")) if str(item).strip()
    ]
    related = [str(item) for item in _as_list(use_case.get("related_stories")) if str(item).strip()] or features[:3]
    milestone_names = [
        str(_as_dict(item).get("name") or _as_dict(item).get("criteria") or "").strip()
        for item in milestones[:3]
        if str(_as_dict(item).get("name") or _as_dict(item).get("criteria") or "").strip()
    ]

    if "approval" in lowered or "承認" in lowered:
        return [
            {"name": "Review queue", "type": "queue", "items": related[:3] or ["Approval packet", "Rework request", "Decision note"]},
            {"name": "Decision checklist", "type": "checklist", "items": flow_steps[:4] or ["Inspect evidence", "Review risks", "Approve or rework"]},
            {"name": "Governance context", "type": "summary", "items": milestone_names[:3] or ["Policy coverage", "Audit trail", "Decision owner"]},
        ]
    if "run" in lowered or "telemetry" in lowered or "実行" in lowered:
        return [
            {"name": "Run monitor", "type": "timeline", "items": related[:3] or ["Active run", "Blocked node", "Next step"]},
            {"name": "Checkpoint lane", "type": "timeline", "items": flow_steps[:4] or ["Queued", "Running", "Review", "Released"]},
            {"name": "Operator notes", "type": "summary", "items": milestone_names[:3] or ["Escalations", "Retry budget", "Handoff clarity"]},
        ]
    if "artifact" in lowered or "履歴" in lowered or "lineage" in lowered:
        return [
            {"name": "Lineage explorer", "type": "graph", "items": related[:3] or ["Evidence source", "Decision log", "Build artifact"]},
            {"name": "Trace path", "type": "timeline", "items": flow_steps[:4] or ["Research", "Planning", "Design", "Build"]},
            {"name": "Reference rail", "type": "summary", "items": milestone_names[:3] or ["Owner", "Timestamp", "Export"]},
        ]
    if "setting" in lowered or "設定" in lowered:
        return [
            {"name": "Policy groups", "type": "form", "items": related[:3] or ["Notifications", "Permissions", "Automation"]},
            {"name": "Change flow", "type": "timeline", "items": flow_steps[:4] or ["Edit", "Review", "Apply"]},
            {"name": "Safety defaults", "type": "summary", "items": milestone_names[:3] or ["Fallback", "Rollback", "Retention"]},
        ]
    if kind == "commerce":
        return [
            {"name": "Decision shelf", "type": "cards", "items": related[:3] or ["Top picks", "Trust signals", "Saved items"]},
            {"name": "Purchase flow", "type": "timeline", "items": flow_steps[:4] or ["Compare", "Detail", "Checkout", "Confirm"]},
            {"name": "Operator insight", "type": "summary", "items": [role, *(milestone_names[:2] or ["Stock risk", "Order state"])]},
        ]
    if kind == "learning":
        return [
            {"name": "Progress snapshot", "type": "summary", "items": related[:3] or ["Today's lesson", "Streak", "Reward"]},
            {"name": "Learning loop", "type": "timeline", "items": flow_steps[:4] or ["Start", "Practice", "Result", "Celebrate"]},
            {"name": "Guardian support", "type": "summary", "items": [role, *(milestone_names[:2] or ["Goal check", "Next recommendation"])]},
        ]
    if kind == "operations":
        return [
            {"name": "Decision snapshot", "type": "summary", "items": related[:3] or ["Next action", "Blocked phase", "Approval state"]},
            {"name": "Workflow lane", "type": "timeline", "items": flow_steps[:4] or ["Research", "Planning", "Design", "Deploy"]},
            {"name": "Operator context", "type": "summary", "items": [role, *(milestone_names[:2] or ["Risk register", "Release signal"])]},
        ]
    return [
        {"name": "Primary tasks", "type": "summary", "items": related[:3] or ["Core workflow", "Status", "Recovery"]},
        {"name": "Task flow", "type": "timeline", "items": flow_steps[:4] or ["Open", "Act", "Review"]},
        {"name": "Support context", "type": "summary", "items": [role, *(milestone_names[:2] or ["Help", "Settings"])]},
    ]


def _build_design_prototype(
    *,
    spec: str,
    analysis: dict[str, Any],
    selected_features: list[str],
    pattern_name: str,
    description: str,
    prototype_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind = _infer_product_kind(spec)
    overrides = prototype_overrides or {}
    ia_analysis = _as_dict(analysis.get("ia_analysis"))
    personas = [dict(item) for item in _as_list(analysis.get("personas")) if isinstance(item, dict)]
    use_cases = [dict(item) for item in _as_list(analysis.get("use_cases")) if isinstance(item, dict)]
    key_paths = [dict(item) for item in _as_list(ia_analysis.get("key_paths")) if isinstance(item, dict)] or _default_key_paths_for_kind(kind)
    site_map = [dict(item) for item in _as_list(ia_analysis.get("site_map")) if isinstance(item, dict)] or _default_site_map_for_kind(kind)
    design_tokens = _as_dict(analysis.get("design_tokens")) or _base_design_tokens(spec)
    milestones = [dict(item) for item in _as_list(analysis.get("recommended_milestones")) if isinstance(item, dict)]
    if not milestones:
        milestones = [dict(item) for item in _as_list(analysis.get("milestones")) if isinstance(item, dict)]
    screen_labels = [label for label in overrides.get("screen_labels", []) if label]

    screens: list[dict[str, Any]] = []
    for index, raw in enumerate(site_map[:4]):
        node = _as_dict(raw)
        label = screen_labels[index] if index < len(screen_labels) else str(node.get("label") or node.get("id") or f"Screen {index + 1}")
        use_case = use_cases[index] if index < len(use_cases) else (use_cases[0] if use_cases else {})
        key_path = key_paths[index] if index < len(key_paths) else (key_paths[0] if key_paths else {})
        modules = _screen_modules_for_context(
            kind=kind,
            label=label,
            features=selected_features,
            use_case=_as_dict(use_case),
            key_path=_as_dict(key_path),
            personas=personas,
            milestones=milestones,
        )
        primary_actions = _dedupe_strings(
            [
                *(str(item) for item in _as_list(_as_dict(use_case).get("main_flow"))[:2]),
                f"Open {label}",
                *(str(item) for item in _as_list(_as_dict(key_path).get("steps"))[:1]),
            ]
        )[:3]
        screens.append(
            {
                "id": str(node.get("id") or _slug(label, prefix="screen")),
                "title": label,
                "purpose": str(node.get("description") or _as_dict(use_case).get("title") or description),
                "layout": _screen_layout_for_kind(kind, index=index),
                "headline": str(_as_dict(use_case).get("title") or f"{label} workspace"),
                "supporting_text": str(_as_dict(key_path).get("name") or description),
                "primary_actions": primary_actions or [f"Open {label}"],
                "modules": modules,
                "success_state": str(
                    _as_dict(use_case).get("postconditions")
                    or (milestones[index]["criteria"] if index < len(milestones) else "")
                    or "The next action and current state are obvious at a glance."
                ),
            }
        )

    flows = []
    for index, raw in enumerate(key_paths[:3]):
        path = _as_dict(raw)
        steps = [str(item) for item in _as_list(path.get("steps")) if str(item).strip()]
        if not steps:
            continue
        flows.append(
            {
                "id": f"flow-{index + 1}",
                "name": str(path.get("name") or f"Primary flow {index + 1}"),
                "steps": steps,
                "goal": str(path.get("goal") or screens[min(index, len(screens) - 1)].get("success_state") or ""),
            }
        )

    interaction_principles = _dedupe_strings(
        list(overrides.get("interaction_principles", []))
        + [str(item) for item in _as_list(design_tokens.get("effects")) if str(item).strip()]
        + [
            "Show the next action close to the active work surface.",
            "Keep evidence, decision context, and execution status in the same viewport.",
            "Prefer dense but scannable panels over marketing copy blocks.",
        ]
    )[:5]

    primary_nav = [
        {
            "id": str(item.get("id") or _slug(str(item.get("label") or "nav"), prefix="nav")),
            "label": str(item.get("label") or item.get("id") or "Section"),
            "priority": str(item.get("priority") or "primary"),
        }
        for item in site_map[:5]
    ]
    prototype_kind = overrides.get("prototype_kind") or (
        "control-center" if kind == "operations"
        else "storefront" if kind == "commerce"
        else "guided-product" if kind == "learning"
        else "product-workspace"
    )
    density = overrides.get("density") or ("high" if kind == "operations" else "medium")

    return {
        "kind": prototype_kind,
        "app_shell": {
            "layout": overrides.get("navigation_style") or _shell_layout_for_kind(kind),
            "density": density,
            "primary_navigation": primary_nav,
            "status_badges": _dedupe_strings(selected_features[:3] or [screen["title"] for screen in screens[:3]]),
        },
        "screens": screens,
        "flows": flows,
        "interaction_principles": interaction_principles,
        "design_anchor": {
            "pattern_name": pattern_name,
            "description": description,
            "style_name": str(_as_dict(design_tokens.get("style")).get("name") or ""),
        },
    }


def _looks_like_prototype_html(code: str) -> bool:
    lowered = str(code or "").lower()
    return (
        "<html" in lowered
        and "<main" in lowered
        and "primary navigation" in lowered
        and "data-screen-id" in lowered
        and "data-prototype-kind" in lowered
    )


def _extract_json_object(content: str) -> dict[str, Any] | None:
    text = str(content or "").strip()
    if not text:
        return None
    candidates = [text]
    if "```" in text:
        segments = text.split("```")
        candidates.extend(segment.strip() for segment in segments if segment.strip())
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        cleaned = candidate.strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _llm_event_payload(result: Any, *, purpose: str, raw_content: str) -> dict[str, Any]:
    usage = result.response.usage
    usage_payload = None
    if usage is not None:
        usage_payload = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
        }
    return {
        "purpose": purpose,
        "provider": result.route.provider_name,
        "model": result.response.model,
        "estimated_cost_usd": result.estimated_cost_usd,
        "usage": usage_payload,
        "route": result.route.to_dict(),
        "context": dict(result.context),
        "response_preview": raw_content[:400],
    }


async def _lifecycle_llm_json(
    *,
    provider_registry: ProviderRegistry | None,
    llm_runtime: LLMRuntime | None,
    preferred_model: str,
    purpose: str,
    static_instruction: str,
    user_prompt: str,
    quality_sensitive: bool = True,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
    if not _provider_backed_lifecycle_available(provider_registry):
        return None, [], ""
    runtime = llm_runtime or LLMRuntime()
    request = ModelRouteRequest(
        purpose=purpose,
        input_tokens_estimate=max(len(static_instruction + user_prompt) // 4, 256),
        requires_tools=False,
        latency_sensitive=not quality_sensitive,
        quality_sensitive=quality_sensitive,
        cacheable_prefix=True,
        batch_eligible=False,
    )
    try:
        result = await runtime.chat(
            registry=provider_registry,
            request=request,
            messages=[Message(role="user", content=user_prompt)],
            preferred_model=preferred_model,
            static_instruction=static_instruction,
        )
    except Exception as exc:
        return None, [{"purpose": purpose, "error": str(exc)}], ""
    raw_content = str(result.response.content or "")
    payload = _extract_json_object(raw_content)
    return payload, [_llm_event_payload(result, purpose=purpose, raw_content=raw_content)], raw_content


_LIFECYCLE_MODEL_STRATEGIES: dict[str, dict[str, Any]] = {
    "competitor-analyst": {
        "archetype": "long-context competitive comparator",
        "candidates": ("moonshot/kimi-k2.5", "gemini/gemini-3-pro-preview", "anthropic/claude-sonnet-4-6"),
    },
    "market-researcher": {
        "archetype": "broad market synthesizer",
        "candidates": ("gemini/gemini-3-pro-preview", "moonshot/kimi-k2.5", "openai/gpt-5-mini"),
    },
    "user-researcher": {
        "archetype": "qualitative interviewer",
        "candidates": ("anthropic/claude-sonnet-4-6", "moonshot/kimi-k2.5", "openai/gpt-5-mini"),
    },
    "tech-evaluator": {
        "archetype": "system feasibility reasoner",
        "candidates": ("zhipu/glm-4-plus", "openai/gpt-5-mini", "anthropic/claude-sonnet-4-6"),
    },
    "research-synthesizer": {
        "archetype": "structured synthesis engine",
        "candidates": ("openai/gpt-5-mini", "moonshot/kimi-k2.5", "anthropic/claude-sonnet-4-6"),
    },
    "evidence-librarian": {
        "archetype": "source normalizer",
        "candidates": ("moonshot/kimi-k2.5", "gemini/gemini-3-pro-preview", "openai/gpt-5-mini"),
    },
    "devils-advocate-researcher": {
        "archetype": "adversarial systems critic",
        "candidates": ("zhipu/glm-4-plus", "anthropic/claude-sonnet-4-6", "openai/gpt-5-mini"),
    },
    "cross-examiner": {
        "archetype": "structured contradiction detector",
        "candidates": ("openai/gpt-5-mini", "zhipu/glm-4-plus", "gemini/gemini-3-pro-preview"),
    },
    "research-judge": {
        "archetype": "decision calibrator",
        "candidates": ("anthropic/claude-sonnet-4-6", "openai/gpt-5-mini", "zhipu/glm-4-plus"),
    },
    "persona-builder": {
        "archetype": "persona and motivation mapper",
        "candidates": ("anthropic/claude-sonnet-4-6", "moonshot/kimi-k2.5", "gemini/gemini-3-pro-preview"),
    },
    "story-architect": {
        "archetype": "journey and IA composer",
        "candidates": ("moonshot/kimi-k2.5", "gemini/gemini-3-pro-preview", "anthropic/claude-sonnet-4-6"),
    },
    "feature-analyst": {
        "archetype": "scope and prioritization reasoner",
        "candidates": ("zhipu/glm-4-plus", "openai/gpt-5-mini", "anthropic/claude-sonnet-4-6"),
    },
    "solution-architect": {
        "archetype": "delivery architecture planner",
        "candidates": ("zhipu/glm-4-plus", "anthropic/claude-sonnet-4-6", "openai/gpt-5-mini"),
    },
    "planning-synthesizer": {
        "archetype": "decision-table synthesizer",
        "candidates": ("openai/gpt-5-mini", "moonshot/kimi-k2.5", "anthropic/claude-sonnet-4-6"),
    },
    "scope-skeptic": {
        "archetype": "scope reduction critic",
        "candidates": ("zhipu/glm-4-plus", "openai/gpt-5-mini", "gemini/gemini-3-pro-preview"),
    },
    "assumption-auditor": {
        "archetype": "assumption auditor",
        "candidates": ("anthropic/claude-sonnet-4-6", "zhipu/glm-4-plus", "openai/gpt-5-mini"),
    },
    "negative-persona-challenger": {
        "archetype": "failure-mode generator",
        "candidates": ("gemini/gemini-3-pro-preview", "moonshot/kimi-k2.5", "zhipu/glm-4-plus"),
    },
    "milestone-falsifier": {
        "archetype": "verification gate critic",
        "candidates": ("zhipu/glm-4-plus", "openai/gpt-5-mini", "anthropic/claude-sonnet-4-6"),
    },
    "planning-judge": {
        "archetype": "portfolio and tradeoff judge",
        "candidates": ("anthropic/claude-sonnet-4-6", "openai/gpt-5-mini", "zhipu/glm-4-plus"),
    },
    "claude-designer": {
        "archetype": "premium interaction designer",
        "candidates": ("anthropic/claude-sonnet-4-6", "moonshot/kimi-k2.5", "gemini/gemini-3-pro-preview"),
    },
    "openai-designer": {
        "archetype": "high-iteration UI concept generator",
        "candidates": ("moonshot/kimi-k2.5", "openai/gpt-5-mini", "gemini/gemini-3-pro-preview"),
    },
    "gemini-designer": {
        "archetype": "exploratory visual systems designer",
        "candidates": ("gemini/gemini-3-pro-preview", "moonshot/kimi-k2.5", "anthropic/claude-sonnet-4-6"),
    },
    "design-evaluator": {
        "archetype": "design judge and rubric scorer",
        "candidates": ("zhipu/glm-4-plus", "anthropic/claude-sonnet-4-6", "openai/gpt-5-mini"),
    },
    "planner": {
        "archetype": "delivery planner",
        "candidates": ("openai/gpt-5-mini", "zhipu/glm-4-plus", "anthropic/claude-sonnet-4-6"),
    },
    "frontend-builder": {
        "archetype": "UI implementation specialist",
        "candidates": ("moonshot/kimi-k2.5", "anthropic/claude-sonnet-4-6", "openai/gpt-5-mini"),
    },
    "backend-builder": {
        "archetype": "backend systems implementer",
        "candidates": ("zhipu/glm-4-plus", "openai/gpt-5-mini", "anthropic/claude-sonnet-4-6"),
    },
    "integrator": {
        "archetype": "cross-artifact integrator",
        "candidates": ("anthropic/claude-sonnet-4-6", "openai/gpt-5-mini", "moonshot/kimi-k2.5"),
    },
    "reviewer": {
        "archetype": "final quality reviewer",
        "candidates": ("anthropic/claude-sonnet-4-6", "openai/gpt-5-mini", "zhipu/glm-4-plus"),
    },
}


def _preferred_lifecycle_model(
    node_id: str,
    provider_registry: ProviderRegistry | None = None,
) -> str:
    strategy = _as_dict(_LIFECYCLE_MODEL_STRATEGIES.get(node_id))
    raw_candidates = strategy.get("candidates")
    candidates = [
        str(item).strip()
        for item in (list(raw_candidates) if isinstance(raw_candidates, (list, tuple)) else [])
        if str(item).strip()
    ]
    if not candidates:
        return ""
    if provider_registry is None:
        return candidates[0]
    available = set(provider_registry.provider_names())
    for candidate in candidates:
        provider_name, _ = candidate.split("/", 1)
        if provider_name in available:
            return candidate
    return candidates[0]


def _design_variant_payload(
    *,
    node_id: str,
    model_name: str,
    pattern_name: str,
    description: str,
    primary: str,
    accent: str,
    selected_features: list[str],
    spec: str,
    analysis: dict[str, Any] | None = None,
    rationale: str = "",
    quality_focus: list[str] | None = None,
    score_overrides: dict[str, Any] | None = None,
    provider_note: str = "",
    prototype_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scores = {
        "ux_quality": round(0.78 + (0.02 if "Minimal" in pattern_name else 0.0), 2),
        "code_quality": 0.82,
        "performance": round(0.86 - (0.03 if "Dashboard" in pattern_name else 0.0), 2),
        "accessibility": round(0.84 + (0.04 if "Minimal" in pattern_name else 0.0), 2),
    }
    for score_name, default in tuple(scores.items()):
        if score_overrides is None:
            continue
        scores[score_name] = _clamp_score(score_overrides.get(score_name), default=default)
    preview_features = selected_features or ["Autonomous workflow", "Approval gates", "Quality review"]
    analysis_payload = _as_dict(analysis)
    prototype = _build_design_prototype(
        spec=spec,
        analysis=analysis_payload,
        selected_features=preview_features,
        pattern_name=pattern_name,
        description=description,
        prototype_overrides=prototype_overrides,
    )
    design_tokens = _as_dict(analysis_payload.get("design_tokens"))
    variant = {
        "id": node_id,
        "model": model_name,
        "pattern_name": pattern_name,
        "description": description,
        "preview_html": _build_preview_html(
            title=_preview_title(spec),
            subtitle=description,
            primary=primary,
            accent=accent,
            features=preview_features,
            prototype=prototype,
            design_tokens=design_tokens,
        ),
        "prototype": prototype,
        "primary_color": primary,
        "accent_color": accent,
        "tokens": {"in": 320 + len(preview_features) * 14, "out": 900 + len(preview_features) * 20},
        "cost_usd": round(0.18 + len(preview_features) * 0.02, 3),
        "scores": scores,
        "rationale": rationale or description,
        "quality_focus": list(quality_focus or []),
    }
    if provider_note:
        variant["provider_note"] = provider_note
    return variant


def _development_quality_snapshot(
    state: dict[str, Any],
    *,
    code: str,
) -> dict[str, Any]:
    milestones = []
    for raw in state.get("milestones", []) or []:
        if not isinstance(raw, dict):
            continue
        criteria = str(raw.get("criteria", ""))
        score = _milestone_score(criteria, code)
        milestones.append(
            {
                "id": str(raw.get("id", "")),
                "name": str(raw.get("name", "")),
                "status": "satisfied" if score >= 0.6 else "not_satisfied",
                "reason": (
                    "Build contains the required structural signals."
                    if score >= 0.6
                    else "Criteria is only partially represented in the current build artifact."
                ),
                "score": round(score, 2),
            }
        )
    if not milestones:
        milestones.append(
            {
                "id": "alpha-default",
                "name": "Alpha readiness",
                "status": "satisfied" if "<html" in code.lower() else "not_satisfied",
                "reason": (
                    "Generated build is previewable and structurally complete."
                    if "<html" in code.lower()
                    else "No previewable build artifact was generated."
                ),
                "score": 1.0 if "<html" in code.lower() else 0.0,
            }
        )
    findings = []
    if "eval(" in code:
        findings.append("Avoid eval() in generated artifacts.")
    if "innerHTML =" in code:
        findings.append("Prefer DOM-safe rendering over innerHTML assignment.")
    if "<main" not in code.lower():
        findings.append("Include a semantic <main> landmark.")
    if "aria-" not in code.lower():
        findings.append("Add ARIA labels to actionable controls.")
    if "viewport" not in code.lower():
        findings.append("Include responsive viewport metadata for mobile quality.")
    security_status = "pass" if not findings else "warning"
    satisfied = sum(1 for item in milestones if _as_dict(item).get("status") == "satisfied")
    blockers = [
        f"Milestone not satisfied: {item['name']}"
        for item in milestones
        if _as_dict(item).get("status") != "satisfied"
    ]
    blockers.extend(findings)
    return {
        "milestone_results": milestones,
        "security_report": {
            "status": security_status,
            "findings": findings or ["No obvious unsafe DOM execution pattern was detected."],
        },
        "milestones_satisfied": satisfied,
        "milestones_total": len(milestones),
        "blockers": blockers,
    }


def _skill_plan_state_key(node_id: str) -> str:
    return f"{node_id}_skill_plan"


def _delegation_state_key(node_id: str) -> str:
    return f"{node_id}_delegations"


def _peer_feedback_state_key(node_id: str) -> str:
    return f"{node_id}_peer_feedback"


def _phase_blueprint_for_node(phase: str, node_id: str) -> dict[str, Any]:
    phase_blueprint = build_lifecycle_phase_blueprints("catalog").get(phase, {})
    for agent in _as_list(phase_blueprint.get("team")):
        if isinstance(agent, dict) and str(agent.get("id", "")) == node_id:
            return dict(agent)
    return {}


def _phase_quality_targets(phase: str) -> list[str]:
    phase_blueprint = build_lifecycle_phase_blueprints("catalog").get(phase, {})
    return [
        str(item.get("title", ""))
        for item in _as_list(phase_blueprint.get("quality_gates"))
        if isinstance(item, dict) and str(item.get("title", "")).strip()
    ]


def _phase_support_skills(phase: str) -> list[str]:
    if phase == "research":
        return [
            "market-research",
            "competitive-intelligence",
            "evidence-audit",
            "counterexample-generation",
            "cross-examination",
            "decision-calibration",
        ]
    if phase == "planning":
        return [
            "persona-design",
            "use-case-design",
            "feature-prioritization",
            "scope-challenge",
            "assumption-audit",
            "decision-calibration",
        ]
    if phase == "design":
        return ["design-critique", "accessibility-review", "performance-review"]
    if phase == "development":
        return [
            "code-review",
            "delivery-review",
            "security-review",
            "safety-review",
            "quality-assurance",
            "acceptance-testing",
        ]
    return []


def _peer_recommendation_payload(
    *,
    peer_name: str,
    skill_name: str,
    phase: str,
    artifact_payload: dict[str, Any],
    quality_targets: list[str],
) -> dict[str, Any]:
    code = str(artifact_payload.get("code", "") or artifact_payload.get("preview_html", "") or "")
    recommendations: list[str] = []
    strengths: list[str] = []
    blockers: list[str] = []
    summary = f"{peer_name} reviewed {skill_name} for {phase}."

    if peer_name == "design-critic":
        pattern_name = str(artifact_payload.get("pattern_name", "Design concept") or "Design concept")
        summary = f"{peer_name} validated the {pattern_name} concept for clarity and accessibility."
        strengths.extend(
            [
                "Concept presents a differentiated visual direction.",
                "The baseline is legible enough for operator workflows.",
            ]
        )
        recommendations.extend(
            [
                "Strengthen mobile density control with clearer section hierarchy.",
                "Raise contrast around primary operator actions and status labels.",
                "Make approval and readiness signals visible above the fold.",
            ]
        )
        if "viewport" not in code.lower():
            blockers.append("Design preview should explicitly represent responsive viewport behavior.")
    elif peer_name == "safety-guardian":
        summary = f"{peer_name} audited security and safety posture for {phase}."
        if "eval(" in code:
            blockers.append("Remove eval() from the generated artifact.")
        if "innerHTML =" in code:
            blockers.append("Avoid direct innerHTML assignment in preview code.")
        recommendations.extend(
            [
                "Prefer semantic landmarks and explicit ARIA labels for operator controls.",
                "Keep release actions distinct from navigation actions.",
            ]
        )
        if not blockers:
            strengths.append("No high-risk DOM execution pattern was detected.")
    elif peer_name == "build-craft":
        summary = f"{peer_name} reviewed build execution quality for {phase}."
        recommendations.extend(
            [
                "Promote the main task flow into a stronger hero-to-detail narrative.",
                "Reduce visual noise and make milestone state transitions easier to scan.",
                "Ensure mobile layout keeps action clusters within one thumb zone.",
            ]
        )
        if "<main" not in code.lower():
            blockers.append("Integrated build should include a semantic <main> landmark.")
        if "aria-" not in code.lower():
            blockers.append("Integrated build should label actionable controls with ARIA.")
    elif peer_name == "quality-lab":
        summary = f"{peer_name} validated delivery readiness for {phase}."
        recommendations.extend(
            [
                "Represent each milestone with explicit pass/fail evidence in the UI.",
                "Surface next action, blocker count, and release confidence in one panel.",
            ]
        )
        if "viewport" not in code.lower():
            blockers.append("Build should include responsive viewport metadata.")
    else:
        recommendations.extend(quality_targets[:2] or [f"Preserve quality gate coverage for {phase}."])

    return {
        "summary": summary,
        "strengths": strengths,
        "recommendations": recommendations,
        "blockers": blockers,
        "quality_targets": quality_targets,
    }


async def _delegate_to_lifecycle_peer(
    *,
    phase: str,
    node_id: str,
    peer_name: str,
    skill_name: str,
    artifact_payload: dict[str, Any],
    reason: str,
    quality_targets: list[str],
) -> dict[str, Any] | None:
    from pylon.lifecycle.operator_console import build_lifecycle_peer_registry
    from pylon.protocols.a2a.client import A2AClient
    from pylon.protocols.a2a.server import A2AServer
    from pylon.protocols.a2a.types import (
        A2AMessage,
        A2ATask,
        Part,
        TaskState,
    )
    from pylon.protocols.a2a.types import (
        Artifact as A2AArtifact,
    )

    peer_registry = build_lifecycle_peer_registry()
    peer_card = peer_registry.get(peer_name)
    if peer_card is None:
        return None

    sender = f"lifecycle:{phase}:{node_id}"
    server = A2AServer(allowed_peers={sender})

    @server.on_task
    async def _handle_peer_task(task: A2ATask) -> A2ATask:
        recommendation = _peer_recommendation_payload(
            peer_name=peer_name,
            skill_name=skill_name,
            phase=phase,
            artifact_payload=artifact_payload,
            quality_targets=quality_targets,
        )
        task.add_message(
            A2AMessage(
                role="agent",
                parts=[Part(type="text", content=recommendation["summary"])],
            )
        )
        task.add_artifact(
            A2AArtifact(
                name=f"{peer_name}-{skill_name}-review",
                description=recommendation["summary"],
                parts=[Part(type="data", content=recommendation)],
                metadata={
                    "peer": peer_name,
                    "skill": skill_name,
                    "phase": phase,
                    "sender": node_id,
                },
            )
        )
        task.transition_to(TaskState.COMPLETED)
        return task

    client = A2AClient(server, sender=sender)
    submitted = A2ATask(
        id=f"{phase}:{node_id}:{peer_name}:{skill_name}:{uuid.uuid4().hex[:8]}",
        messages=[
            A2AMessage(
                role="agent",
                parts=[
                    Part(
                        type="text",
                        content=f"Delegate {skill_name} to {peer_name} for {phase}/{node_id}: {reason}",
                    )
                ],
            )
        ],
        artifacts=[
            A2AArtifact(
                name=f"{node_id}-context",
                description=f"Lifecycle context for {phase}/{node_id}",
                parts=[Part(type="data", content=_compact_lifecycle_value(artifact_payload))],
                metadata={"phase": phase, "node_id": node_id},
            )
        ],
        metadata={
            "phase": phase,
            "node_id": node_id,
            "peer": peer_name,
            "skill": skill_name,
            "reason": reason,
        },
    )
    completed = await client.send_task(submitted)
    task_payload = completed.to_dict()
    review_payload = _as_dict(_as_list(task_payload.get("artifacts"))[-1]) if _as_list(task_payload.get("artifacts")) else {}
    review_data = _as_dict(_as_list(review_payload.get("parts"))[0].get("content")) if _as_list(review_payload.get("parts")) else {}
    return {
        "peer": peer_name,
        "skill": skill_name,
        "status": str(task_payload.get("state", TaskState.COMPLETED.value)),
        "reason": reason,
        "peerCard": peer_card.to_dict(),
        "task": task_payload,
        "feedback": review_data,
    }


async def _plan_node_collaboration(
    *,
    phase: str,
    node_id: str,
    state: dict[str, Any],
    objective: str,
    provider_registry: ProviderRegistry | None,
    llm_runtime: LLMRuntime | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from pylon.lifecycle.operator_console import (
        build_lifecycle_peer_registry,
        build_lifecycle_skill_catalog,
    )

    agent = _phase_blueprint_for_node(phase, node_id)
    skill_catalog = build_lifecycle_skill_catalog()
    peer_registry = build_lifecycle_peer_registry()
    own_skills = [str(item) for item in _as_list(agent.get("skills")) if str(item).strip()]
    candidate_skills = _dedupe_strings(own_skills + _phase_support_skills(phase))
    peer_candidates: list[dict[str, Any]] = []
    for skill_name in candidate_skills:
        peers = peer_registry.find_by_skill(skill_name)
        for peer in peers:
            peer_candidates.append(
                {
                    "peer": peer.name,
                    "skill": skill_name,
                    "description": str(next((item.description for item in peer.skills if item.name == skill_name), "")),
                }
            )
    quality_targets = _phase_quality_targets(phase)
    fallback_delegations = [
        {
            "peer": item["peer"],
            "skill": item["skill"],
            "reason": f"Use {item['peer']} to raise the quality bar on {item['skill']}.",
        }
        for item in peer_candidates[:2]
    ]
    fallback_plan = {
        "phase": phase,
        "node_id": node_id,
        "agent_label": str(agent.get("label", node_id) or node_id),
        "objective": objective,
        "candidate_skills": candidate_skills,
        "selected_skills": own_skills[:2] or candidate_skills[:2],
        "quality_targets": quality_targets,
        "delegations": fallback_delegations,
        "mode": "deterministic-reference",
        "execution_note": f"Start with {', '.join((own_skills[:2] or candidate_skills[:2])[:2])} and escalate quality via peer review when available.",
        "skill_details": {
            skill_name: _as_dict(skill_catalog.get(skill_name))
            for skill_name in candidate_skills
        },
    }
    if not _provider_backed_lifecycle_available(provider_registry):
        return fallback_plan, []

    payload, llm_events, _ = await _lifecycle_llm_json(
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
        preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
        purpose=f"lifecycle-skill-plan-{phase}-{node_id}",
        static_instruction=(
            "You are a multi-agent skill planner. Return JSON only. "
            "Choose the smallest high-leverage skill set and delegate only when a peer materially raises quality."
        ),
        user_prompt=(
            "Return JSON with keys selected_skills, quality_targets, delegations, execution_note.\n"
            f"Phase: {phase}\n"
            f"Node: {node_id}\n"
            f"Objective: {objective}\n"
            f"Spec: {state.get('spec')}\n"
            f"Candidate skills: {candidate_skills}\n"
            f"Peer candidates: {peer_candidates}\n"
            f"Quality targets: {quality_targets}\n"
        ),
    )
    if not isinstance(payload, dict):
        return {**fallback_plan, "mode": "provider-backed-fallback"}, llm_events

    selected_skills = [
        skill_name
        for skill_name in [str(item) for item in _as_list(payload.get("selected_skills")) if str(item).strip()]
        if skill_name in candidate_skills
    ] or fallback_plan["selected_skills"]
    allowed_peers = {(item["peer"], item["skill"]) for item in peer_candidates}
    delegations = []
    for raw in _as_list(payload.get("delegations")):
        item = _as_dict(raw)
        peer = str(item.get("peer", "")).strip()
        skill_name = str(item.get("skill", "")).strip()
        if (peer, skill_name) not in allowed_peers:
            continue
        delegations.append(
            {
                "peer": peer,
                "skill": skill_name,
                "reason": str(item.get("reason") or f"Delegate {skill_name} to {peer}."),
            }
        )
    plan = {
        **fallback_plan,
        "selected_skills": selected_skills,
        "quality_targets": [
            str(item)
            for item in _as_list(payload.get("quality_targets"))
            if str(item).strip()
        ] or quality_targets,
        "delegations": delegations or fallback_delegations,
        "mode": "provider-backed-autonomous",
        "execution_note": str(payload.get("execution_note") or fallback_plan["execution_note"]),
    }
    return plan, llm_events

def _phase_statuses() -> list[dict[str, Any]]:
    return [
        {
            "phase": phase,
            "status": "available" if index == 0 else "locked",
            "version": 1,
        }
        for index, phase in enumerate(PHASE_ORDER)
    ]


def default_lifecycle_project_record(
    project_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    now = _utc_now_iso()
    return {
        "id": str(project_id),
        "projectId": str(project_id),
        "tenant_id": tenant_id,
        "name": str(project_id),
        "description": "",
        "githubRepo": None,
        "spec": "",
        "autonomyLevel": "A3",
        "researchConfig": {
            "competitorUrls": [],
            "depth": "standard",
        },
        "research": None,
        "analysis": None,
        "features": [],
        "milestones": [],
        "designVariants": [],
        "selectedDesignId": None,
        "approvalStatus": "pending",
        "approvalComments": [],
        "approvalRequestId": None,
        "buildCode": None,
        "buildCost": 0.0,
        "buildIteration": 0,
        "milestoneResults": [],
        "planEstimates": [],
        "selectedPreset": "standard",
        "orchestrationMode": "workflow",
        "phaseStatuses": _phase_statuses(),
        "deployChecks": [],
        "releases": [],
        "feedbackItems": [],
        "recommendations": [],
        "artifacts": [],
        "decisionLog": [],
        "skillInvocations": [],
        "delegations": [],
        "phaseRuns": [],
        "createdAt": now,
        "updatedAt": now,
        "savedAt": now,
    }


def merge_lifecycle_project_record(
    existing: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing)
    for field_name in _MUTABLE_PROJECT_FIELDS:
        if field_name in patch:
            merged[field_name] = patch[field_name]
    now = _utc_now_iso()
    merged["updatedAt"] = now
    merged["savedAt"] = now
    return merged


def build_lifecycle_phase_blueprints(project_id: str) -> dict[str, Any]:
    return {
        "research": {
            "phase": "research",
            "title": "Research Swarm",
            "summary": "市場、競合、ユーザー、技術を並列に調べて証拠ベースの仮説を作る。",
            "team": [
                _agent_blueprint(
                    "competitor-analyst",
                    "Competitor Scout",
                    "競合比較と差別化ポイント抽出",
                    tools=["http", "browser"],
                    skills=["market-research", "competitive-intelligence"],
                ),
                _agent_blueprint(
                    "market-researcher",
                    "Market Researcher",
                    "市場規模、トレンド、需要シグナルの整理",
                    tools=["http", "browser"],
                    skills=["market-sizing", "trend-analysis"],
                ),
                _agent_blueprint(
                    "user-researcher",
                    "User Researcher",
                    "想定ユーザーと課題仮説の生成",
                    skills=["jtbd-analysis", "persona-research"],
                ),
                _agent_blueprint(
                    "tech-evaluator",
                    "Tech Evaluator",
                    "技術実現性と導入リスクの査定",
                    tools=["http"],
                    skills=["architecture-review", "risk-analysis"],
                ),
                _agent_blueprint(
                    "research-synthesizer",
                    "Research Synthesizer",
                    "調査結果を claim ledger に統合し、反証前の thesis pack を作る",
                    skills=["synthesis", "decision-support"],
                ),
                _agent_blueprint(
                    "evidence-librarian",
                    "Evidence Librarian",
                    "根拠と source link を正規化し、採択に使える証拠台帳を作る",
                    tools=["http", "browser"],
                    skills=["evidence-audit", "source-normalization"],
                ),
                _agent_blueprint(
                    "devils-advocate-researcher",
                    "Devil's Advocate",
                    "市場仮説、競合優位、ユーザー課題の反証を生成する",
                    skills=["counterexample-generation", "risk-analysis"],
                ),
                _agent_blueprint(
                    "cross-examiner",
                    "Cross Examiner",
                    "claim ごとに矛盾、弱い根拠、未解決の問いを洗い出す",
                    skills=["cross-examination", "fact-checking"],
                ),
                _agent_blueprint(
                    "research-judge",
                    "Research Judge",
                    "反証を踏まえて surviving thesis と confidence を確定する",
                    skills=["decision-calibration", "portfolio-review"],
                ),
            ],
            "artifacts": [
                _artifact_descriptor("market-research", "research", "市場機会レポート"),
                _artifact_descriptor("competitor-map", "research", "競合比較マップ"),
                _artifact_descriptor("risk-register", "research", "初期リスク登録簿"),
                _artifact_descriptor("claim-ledger", "research", "claim / evidence / dissent ledger"),
            ],
            "quality_gates": [
                _quality_gate("source-grounding", "採択主張が source と evidence に接地している"),
                _quality_gate("counterclaim-coverage", "主要仮説に対する反証が生成されている"),
                _quality_gate("critical-dissent-resolved", "重大な dissent が未解決のまま残っていない"),
                _quality_gate("confidence-floor", "採択 thesis が planning に渡せる信頼度を満たしている"),
            ],
        },
        "planning": {
            "phase": "planning",
            "title": "Planning Council",
            "summary": "課題定義から feature 優先度、WBS、マイルストーンまでを設計する。",
            "team": [
                _agent_blueprint(
                    "persona-builder",
                    "Persona Builder",
                    "ペルソナ、ユーザーストーリー、感情動線を定義",
                    skills=["persona-design", "story-mapping"],
                ),
                _agent_blueprint(
                    "story-architect",
                    "Story Architect",
                    "JTBD、ユースケース、役割モデルを整理",
                    skills=["jtbd-analysis", "use-case-design"],
                ),
                _agent_blueprint(
                    "feature-analyst",
                    "Feature Analyst",
                    "KANO と実装コストから feature を優先付けする",
                    skills=["feature-prioritization", "kano-analysis"],
                ),
                _agent_blueprint(
                    "solution-architect",
                    "Solution Architect",
                    "マイルストーン、WBS、実装方針を作る",
                    skills=["wbs-planning", "solution-architecture"],
                ),
                _agent_blueprint(
                    "planning-synthesizer",
                    "Planning Synthesizer",
                    "企画 artifact を暫定プランへ統合し、反証可能な decision table を作る",
                    skills=["roadmapping", "program-planning"],
                ),
                _agent_blueprint(
                    "scope-skeptic",
                    "Scope Skeptic",
                    "feature scope を削る側から攻撃し、不要な実装を落とす",
                    skills=["scope-challenge", "feature-pruning"],
                ),
                _agent_blueprint(
                    "assumption-auditor",
                    "Assumption Auditor",
                    "persona、JTBD、市場仮説の弱い前提を監査する",
                    skills=["assumption-audit", "risk-analysis"],
                ),
                _agent_blueprint(
                    "negative-persona-challenger",
                    "Negative Persona Challenger",
                    "導入失敗や誤用を招くユーザー像を明示して穴を洗い出す",
                    skills=["negative-scenario-design", "persona-research"],
                ),
                _agent_blueprint(
                    "milestone-falsifier",
                    "Milestone Falsifier",
                    "milestone の曖昧さと検証不能な完了条件を攻撃する",
                    skills=["milestone-testing", "delivery-risk-analysis"],
                ),
                _agent_blueprint(
                    "planning-judge",
                    "Planning Judge",
                    "scope、assumption、milestone の surviving plan を確定する",
                    skills=["decision-calibration", "roadmapping"],
                ),
            ],
            "artifacts": [
                _artifact_descriptor("product-brief", "planning", "課題定義と価値仮説"),
                _artifact_descriptor("delivery-plan", "planning", "WBS と見積"),
                _artifact_descriptor("milestone-plan", "planning", "検証可能なマイルストーン"),
                _artifact_descriptor("decision-table", "planning", "採択 / 却下 / 保留の decision ledger"),
            ],
            "quality_gates": [
                _quality_gate("feature-traceability", "主要 feature が research claim と use case に接続されている"),
                _quality_gate("assumption-audit", "主要前提に対する監査結果が残っている"),
                _quality_gate("negative-persona-coverage", "失敗しやすい利用文脈が明示されている"),
                _quality_gate("milestone-falsifiability", "milestone が検証条件と失敗条件を持っている"),
            ],
        },
        "design": {
            "phase": "design",
            "title": "Design Jury",
            "summary": "複数コンセプトを生成し、UX・可読性・アクセシビリティで比較する。",
            "team": [
                _agent_blueprint(
                    "claude-designer",
                    "Concept Designer A",
                    "情報密度を抑えた構成案を生成",
                    skills=["ui-concepting", "visual-hierarchy"],
                ),
                _agent_blueprint(
                    "openai-designer",
                    "Concept Designer B",
                    "運用効率の高い dashboard-first 案を生成",
                    skills=["dashboard-design", "information-design"],
                ),
                _agent_blueprint(
                    "gemini-designer",
                    "Concept Designer C",
                    "モバイル適性の高い card-based 案を生成",
                    skills=["responsive-design", "component-patterns"],
                ),
                _agent_blueprint(
                    "design-evaluator",
                    "Design Judge",
                    "UX / code quality / performance / accessibility の観点で採点",
                    skills=["accessibility-review", "performance-review", "design-critique"],
                ),
            ],
            "artifacts": [
                _artifact_descriptor("design-candidates", "design", "複数の設計候補"),
                _artifact_descriptor("design-scorecard", "design", "採点結果と比較表"),
            ],
            "quality_gates": [
                _quality_gate("variant-diversity", "少なくとも 3 種類の設計アプローチが提示されている"),
                _quality_gate("a11y-floor", "全候補に基本的なアクセシビリティ考慮がある"),
            ],
        },
        "approval": {
            "phase": "approval",
            "title": "Approval Gate",
            "summary": "構想から設計までの artifact をレビューし、Go / Rework を決定する。",
            "team": [
                _agent_blueprint(
                    "approval-chair",
                    "Approval Chair",
                    "レビュー論点を整理して決裁情報をまとめる",
                    skills=["review-facilitation", "risk-summary"],
                )
            ],
            "artifacts": [
                _artifact_descriptor("approval-thread", "approval", "承認コメントと決定履歴"),
            ],
            "quality_gates": [
                _quality_gate("review-complete", "仕様、優先度、設計、マイルストーンが確認済み"),
            ],
        },
        "development": {
            "phase": "development",
            "title": "Build Mesh",
            "summary": "設計を specialist team に分解し、統合・品質確認までを担う。",
            "team": [
                _agent_blueprint(
                    "planner",
                    "Build Planner",
                    "作業分解、担当割り当て、成功条件の定義",
                    skills=["task-routing", "implementation-planning"],
                ),
                _agent_blueprint(
                    "frontend-builder",
                    "Frontend Builder",
                    "画面構造と UI 実装を担当",
                    tools=["code-edit", "file-write"],
                    skills=["frontend-implementation", "responsive-ui"],
                ),
                _agent_blueprint(
                    "backend-builder",
                    "Backend Builder",
                    "データモデルと連携仕様を整理",
                    skills=["api-design", "domain-modeling"],
                ),
                _agent_blueprint(
                    "integrator",
                    "Integrator",
                    "成果物を単一の build artifact に統合",
                    tools=["code-edit", "file-write"],
                    skills=["integration", "artifact-assembly"],
                ),
                _agent_blueprint(
                    "qa-engineer",
                    "QA Engineer",
                    "受け入れ条件と milestone を検証",
                    skills=["acceptance-testing", "quality-assurance"],
                ),
                _agent_blueprint(
                    "security-reviewer",
                    "Security Reviewer",
                    "安全性と運用リスクを確認",
                    skills=["security-review", "safety-review"],
                ),
                _agent_blueprint(
                    "reviewer",
                    "Release Reviewer",
                    "最終レビューと build quality 判定",
                    skills=["code-review", "delivery-review"],
                ),
            ],
            "artifacts": [
                _artifact_descriptor("implementation-plan", "development", "実装方針と作業分解"),
                _artifact_descriptor("build-artifact", "development", "プレビュー可能な build"),
                _artifact_descriptor("milestone-report", "development", "達成判定レポート"),
            ],
            "quality_gates": [
                _quality_gate("feature-coverage", "選択した主要機能が build に反映されている"),
                _quality_gate("milestone-readiness", "少なくとも alpha 相当のマイルストーンが満たされている"),
            ],
        },
        "deploy": {
            "phase": "deploy",
            "title": "Release Gate",
            "summary": "build artifact を品質ゲートに通し、配布可能な release として記録する。",
            "team": [
                _agent_blueprint(
                    "release-manager",
                    "Release Manager",
                    "品質ゲートと release 記録を管理",
                    skills=["release-management", "quality-gating"],
                )
            ],
            "artifacts": [
                _artifact_descriptor("deploy-checks", "deploy", "デプロイ前品質チェック"),
                _artifact_descriptor("release-record", "deploy", "公開可能な release 記録"),
            ],
            "quality_gates": [
                _quality_gate("release-ready", "HTML / responsive / a11y / security / performance が許容水準"),
            ],
        },
        "iterate": {
            "phase": "iterate",
            "title": "Iteration Engine",
            "summary": "実利用フィードバックを集約し、次の改善計画へ反映する。",
            "team": [
                _agent_blueprint(
                    "feedback-triager",
                    "Feedback Triager",
                    "フィードバックの分類と影響度評価",
                    skills=["feedback-analysis", "backlog-triage"],
                ),
                _agent_blueprint(
                    "roadmap-optimizer",
                    "Roadmap Optimizer",
                    "改善優先度と次の iteration 推奨を生成",
                    skills=["roadmap-optimization", "product-ops"],
                ),
            ],
            "artifacts": [
                _artifact_descriptor("feedback-backlog", "iterate", "投票付き改善バックログ"),
                _artifact_descriptor("iteration-recommendations", "iterate", "次アクション提案"),
            ],
            "quality_gates": [
                _quality_gate("feedback-closed-loop", "フィードバックが次の意思決定へ反映されている"),
            ],
        },
    }


def _agent_blueprint(
    agent_id: str,
    label: str,
    role: str,
    *,
    autonomy: str = "A2",
    tools: list[str] | None = None,
    skills: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": agent_id,
        "label": label,
        "role": role,
        "autonomy": autonomy,
        "tools": list(tools or []),
        "skills": list(skills or []),
    }


def _artifact_descriptor(artifact_id: str, phase: str, title: str) -> dict[str, Any]:
    return {"id": artifact_id, "phase": phase, "title": title}


def _quality_gate(gate_id: str, title: str) -> dict[str, Any]:
    return {"id": gate_id, "title": title}


def build_lifecycle_workflow_definition(project_id: str, phase: str) -> dict[str, Any]:
    workflow_id = f"lifecycle-{phase}-{project_id}"
    if phase == "research":
        project = {
            "version": "1",
            "name": "lifecycle-research",
            "description": "Research swarm with synthesis of competition, market, user, and technical signals.",
            "agents": {
                "competitor-analyst": _agent_def("competitive-intelligence", tools=["http", "browser"]),
                "market-researcher": _agent_def("market-sizing", tools=["http", "browser"]),
                "user-researcher": _agent_def("persona-research"),
                "tech-evaluator": _agent_def("technical-feasibility", tools=["http"]),
                "research-synthesizer": _agent_def("evidence-synthesis"),
                "evidence-librarian": _agent_def("evidence-audit", tools=["http", "browser"]),
                "devils-advocate-researcher": _agent_def("counterexample-generation"),
                "cross-examiner": _agent_def("cross-examination"),
                "research-judge": _agent_def("decision-calibration"),
            },
            "workflow": {
                "type": "graph",
                "nodes": {
                    "competitor-analyst": {"agent": "competitor-analyst", "next": ["research-synthesizer"]},
                    "market-researcher": {"agent": "market-researcher", "next": ["research-synthesizer"]},
                    "user-researcher": {"agent": "user-researcher", "next": ["research-synthesizer"]},
                    "tech-evaluator": {"agent": "tech-evaluator", "next": ["research-synthesizer"]},
                    "research-synthesizer": {"agent": "research-synthesizer", "join_policy": "all_resolved", "next": ["evidence-librarian", "devils-advocate-researcher"]},
                    "evidence-librarian": {"agent": "evidence-librarian", "next": ["cross-examiner"]},
                    "devils-advocate-researcher": {"agent": "devils-advocate-researcher", "next": ["cross-examiner"]},
                    "cross-examiner": {
                        "agent": "cross-examiner",
                        "join_policy": "all_resolved",
                        "next": ["research-judge"],
                    },
                    "research-judge": {
                        "agent": "research-judge",
                        "join_policy": "all_resolved",
                        "next": "END",
                    },
                },
            },
            "policy": {"max_cost_usd": 0.8, "max_duration": "5m"},
        }
    elif phase == "planning":
        project = {
            "version": "1",
            "name": "lifecycle-planning",
            "description": "Planning council that turns research into personas, prioritized scope, and milestones.",
            "agents": {
                "persona-builder": _agent_def("persona-design"),
                "story-architect": _agent_def("story-mapping"),
                "feature-analyst": _agent_def("feature-prioritization"),
                "solution-architect": _agent_def("solution-architecture"),
                "planning-synthesizer": _agent_def("delivery-planning"),
                "scope-skeptic": _agent_def("scope-challenge"),
                "assumption-auditor": _agent_def("assumption-audit"),
                "negative-persona-challenger": _agent_def("negative-persona-challenge"),
                "milestone-falsifier": _agent_def("milestone-falsification"),
                "planning-judge": _agent_def("decision-calibration"),
            },
            "workflow": {
                "type": "graph",
                "nodes": {
                    "persona-builder": {"agent": "persona-builder", "next": ["planning-synthesizer"]},
                    "story-architect": {"agent": "story-architect", "next": ["planning-synthesizer"]},
                    "feature-analyst": {"agent": "feature-analyst", "next": ["planning-synthesizer"]},
                    "solution-architect": {"agent": "solution-architect", "next": ["planning-synthesizer"]},
                    "planning-synthesizer": {"agent": "planning-synthesizer", "join_policy": "all_resolved", "next": ["scope-skeptic", "assumption-auditor", "negative-persona-challenger", "milestone-falsifier"]},
                    "scope-skeptic": {"agent": "scope-skeptic", "next": ["planning-judge"]},
                    "assumption-auditor": {"agent": "assumption-auditor", "next": ["planning-judge"]},
                    "negative-persona-challenger": {"agent": "negative-persona-challenger", "next": ["planning-judge"]},
                    "milestone-falsifier": {"agent": "milestone-falsifier", "next": ["planning-judge"]},
                    "planning-judge": {
                        "agent": "planning-judge",
                        "join_policy": "all_resolved",
                        "next": "END",
                    },
                },
            },
            "policy": {"max_cost_usd": 0.7, "max_duration": "6m"},
        }
    elif phase == "design":
        project = {
            "version": "1",
            "name": "lifecycle-design",
            "description": "Design jury that compares three design directions and judges them on quality gates.",
            "agents": {
                "claude-designer": _agent_def("design-concept-a"),
                "openai-designer": _agent_def("design-concept-b"),
                "gemini-designer": _agent_def("design-concept-c"),
                "design-evaluator": _agent_def("design-judge"),
            },
            "workflow": {
                "type": "graph",
                "nodes": {
                    "claude-designer": {"agent": "claude-designer", "next": ["design-evaluator"]},
                    "openai-designer": {"agent": "openai-designer", "next": ["design-evaluator"]},
                    "gemini-designer": {"agent": "gemini-designer", "next": ["design-evaluator"]},
                    "design-evaluator": {
                        "agent": "design-evaluator",
                        "join_policy": "all_resolved",
                        "next": "END",
                    },
                },
            },
            "policy": {"max_cost_usd": 1.4, "max_duration": "10m", "require_approval_above": "A3"},
        }
    elif phase == "development":
        project = {
            "version": "1",
            "name": "lifecycle-development",
            "description": "Specialist build mesh with planning, implementation, integration, QA, security, and review.",
            "agents": {
                "planner": _agent_def("build-planning"),
                "frontend-builder": _agent_def("frontend-implementation", tools=["code-edit", "file-write"]),
                "backend-builder": _agent_def("backend-implementation"),
                "integrator": _agent_def("artifact-integration", tools=["code-edit", "file-write"]),
                "qa-engineer": _agent_def("qa-review"),
                "security-reviewer": _agent_def("security-review"),
                "reviewer": _agent_def("release-review"),
            },
            "workflow": {
                "type": "graph",
                "nodes": {
                    "planner": {"agent": "planner", "next": ["frontend-builder", "backend-builder"]},
                    "frontend-builder": {"agent": "frontend-builder", "next": ["integrator"]},
                    "backend-builder": {"agent": "backend-builder", "next": ["integrator"]},
                    "integrator": {"agent": "integrator", "join_policy": "all_resolved", "next": ["qa-engineer", "security-reviewer"]},
                    "qa-engineer": {"agent": "qa-engineer", "next": ["reviewer"]},
                    "security-reviewer": {"agent": "security-reviewer", "next": ["reviewer"]},
                    "reviewer": {"agent": "reviewer", "join_policy": "all_resolved", "next": "END"},
                },
            },
            "policy": {"max_cost_usd": 3.5, "max_duration": "20m", "require_approval_above": "A3"},
        }
    else:
        raise ValueError(f"Unsupported lifecycle phase: {phase}")
    return {"id": workflow_id, "project": project}


def _agent_def(role: str, *, tools: list[str] | None = None) -> dict[str, Any]:
    return {
        "role": role,
        "autonomy": "A2",
        "sandbox": "gvisor",
        "tools": list(tools or []),
    }


def build_lifecycle_workflow_handlers(
    phase: str,
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> dict[str, Any]:
    if phase == "research":
        return {
            "competitor-analyst": _research_competitor_handler,
            "market-researcher": _research_market_handler,
            "user-researcher": _research_user_handler,
            "tech-evaluator": _research_tech_handler,
            "research-synthesizer": _research_synthesizer_handler,
            "evidence-librarian": _research_evidence_librarian_handler,
            "devils-advocate-researcher": lambda node_id, state: _research_devils_advocate_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "cross-examiner": lambda node_id, state: _research_cross_examiner_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "research-judge": lambda node_id, state: _research_judge_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
        }
    if phase == "planning":
        return {
            "persona-builder": _planning_persona_handler,
            "story-architect": _planning_story_handler,
            "feature-analyst": _planning_feature_handler,
            "solution-architect": _planning_solution_handler,
            "planning-synthesizer": _planning_synthesizer_handler,
            "scope-skeptic": lambda node_id, state: _planning_scope_skeptic_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "assumption-auditor": lambda node_id, state: _planning_assumption_auditor_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "negative-persona-challenger": lambda node_id, state: _planning_negative_persona_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "milestone-falsifier": lambda node_id, state: _planning_milestone_falsifier_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "planning-judge": lambda node_id, state: _planning_judge_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
        }
    if phase == "design":
        return {
            "claude-designer": _design_variant_handler(
                "Claude Sonnet 4.6",
                "Modern Minimal",
                "Focuses on calm hierarchy and premium clarity.",
                "#0f172a",
                "#f97316",
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "openai-designer": _design_variant_handler(
                "Kimi K2.5",
                "Dashboard First",
                "Optimizes for rapid UI iteration, long-context layout synthesis, and dense operator surfaces.",
                "#0b3b2e",
                "#10b981",
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "gemini-designer": _design_variant_handler(
                "Gemini 3 Pro",
                "Card Mosaic",
                "Optimizes for exploratory visual systems and modular mobile scanning.",
                "#312e81",
                "#06b6d4",
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "design-evaluator": lambda node_id, state: _design_evaluator_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
        }
    if phase == "development":
        return {
            "planner": lambda node_id, state: _development_planner_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "frontend-builder": lambda node_id, state: _development_frontend_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "backend-builder": lambda node_id, state: _development_backend_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "integrator": lambda node_id, state: _development_integrator_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "qa-engineer": _development_qa_handler,
            "security-reviewer": lambda node_id, state: _development_security_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "reviewer": lambda node_id, state: _development_reviewer_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
        }
    raise ValueError(f"Unsupported lifecycle phase: {phase}")


def build_deploy_checks(project_record: dict[str, Any]) -> dict[str, Any]:
    build_code = str(project_record.get("buildCode") or "")
    feature_count = len(project_record.get("features") or [])
    selected_features = sum(
        1
        for item in project_record.get("features") or []
        if isinstance(item, dict) and item.get("selected") is True
    )

    checks = [
        _deploy_check(
            "html-structure",
            "HTML structure",
            "pass" if "<html" in build_code.lower() and "<body" in build_code.lower() else "fail",
            "HTML document contains root structure.",
        ),
        _deploy_check(
            "responsive",
            "Responsive readiness",
            "pass"
            if "viewport" in build_code.lower() or "@media" in build_code.lower()
            else "warning",
            "Responsive viewport or media-query support is present.",
        ),
        _deploy_check(
            "a11y",
            "Accessibility floor",
            "pass"
            if any(token in build_code.lower() for token in ("aria-", "<main", "<nav", "<button"))
            else "warning",
            "Semantic landmarks and accessible controls are present.",
        ),
        _deploy_check(
            "security",
            "Security posture",
            "fail" if "eval(" in build_code or "innerHTML =" in build_code else "pass",
            "Avoids obvious unsafe DOM execution patterns.",
        ),
        _deploy_check(
            "performance",
            "Payload size",
            "pass" if len(build_code.encode("utf-8")) < 60_000 else "warning",
            "Generated payload stays within the local preview performance budget.",
        ),
        _deploy_check(
            "feature-coverage",
            "Feature coverage",
            "pass" if selected_features > 0 and feature_count > 0 else "warning",
            "Selected feature set is reflected in the generated artifact.",
        ),
    ]
    score_map = {"pass": 100, "warning": 70, "fail": 30}
    overall_score = round(sum(score_map[item["status"]] for item in checks) / len(checks))
    release_ready = all(item["status"] != "fail" for item in checks)
    return {
        "checks": checks,
        "summary": {
            "overallScore": overall_score,
            "releaseReady": release_ready,
            "passed": sum(1 for item in checks if item["status"] == "pass"),
            "warnings": sum(1 for item in checks if item["status"] == "warning"),
            "failed": sum(1 for item in checks if item["status"] == "fail"),
        },
    }


def build_release_record(project_record: dict[str, Any], *, note: str = "") -> dict[str, Any]:
    checks_payload = build_deploy_checks(project_record)
    if not checks_payload["summary"]["releaseReady"]:
        raise ValueError("Lifecycle project is not release-ready")
    build_code = str(project_record.get("buildCode") or "")
    selected_design = str(project_record.get("selectedDesignId") or "")
    release_id = f"release-{uuid.uuid4().hex[:10]}"
    timestamp = _utc_now_iso()
    return {
        "id": release_id,
        "createdAt": timestamp,
        "version": f"v{max(_completed_phase_count(project_record), 1)}.0",
        "note": note.strip(),
        "selectedDesignId": selected_design,
        "artifactBytes": len(build_code.encode("utf-8")),
        "qualitySummary": checks_payload["summary"],
    }


def refresh_lifecycle_recommendations(project_record: dict[str, Any]) -> list[dict[str, Any]]:
    feedbacks = [
        item for item in project_record.get("feedbackItems", [])
        if isinstance(item, dict)
    ]
    recommendations: list[dict[str, Any]] = []
    if feedbacks:
        ordered = sorted(
            feedbacks,
            key=lambda item: (
                -int(item.get("votes", 0)),
                {"high": 0, "medium": 1, "low": 2}.get(str(item.get("impact", "medium")), 1),
            ),
        )
        top = ordered[0]
        recommendations.append(
            {
                "id": "top-feedback",
                "title": "Close the highest-signal feedback loop",
                "reason": str(top.get("text", "Most-voted feedback should be addressed first.")),
                "priority": "high",
            }
        )
    deploy_checks = [
        item for item in project_record.get("deployChecks", [])
        if isinstance(item, dict)
    ]
    failing_checks = [item for item in deploy_checks if item.get("status") == "fail"]
    if failing_checks:
        recommendations.append(
            {
                "id": "release-blocker",
                "title": "Resolve release blockers before the next deploy",
                "reason": ", ".join(str(item.get("label", item.get("id", ""))) for item in failing_checks),
                "priority": "critical",
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "id": "expand-scope-carefully",
                "title": "Promote one Should feature into the next iteration",
                "reason": "The current lifecycle record has no blocking release or feedback issue, so the next value step is controlled scope expansion.",
                "priority": "medium",
            }
        )
    return recommendations


def _deploy_check(check_id: str, label: str, status: str, detail: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "detail": detail,
    }


def _completed_phase_count(project_record: dict[str, Any]) -> int:
    return sum(
        1
        for item in project_record.get("phaseStatuses", [])
        if isinstance(item, dict) and item.get("status") == "completed"
    )


_RESEARCH_PROPOSAL_NODES: tuple[str, ...] = (
    "competitor-analyst",
    "market-researcher",
    "user-researcher",
    "tech-evaluator",
)
_RESEARCH_REVIEW_NODES: tuple[str, ...] = (
    "evidence-librarian",
    "devils-advocate-researcher",
    "cross-examiner",
    "research-judge",
)
_PLANNING_PROPOSAL_NODES: tuple[str, ...] = (
    "persona-builder",
    "story-architect",
    "feature-analyst",
    "solution-architect",
)
_PLANNING_REVIEW_NODES: tuple[str, ...] = (
    "scope-skeptic",
    "assumption-auditor",
    "negative-persona-challenger",
    "milestone-falsifier",
    "planning-judge",
)
_SEVERITY_WEIGHT = {"critical": 0.22, "high": 0.14, "medium": 0.08, "low": 0.04}


def _node_state_key(node_id: str, suffix: str) -> str:
    return f"{node_id}_{suffix}"


def _provider_family(model_name: str) -> str:
    text = str(model_name or "").strip()
    return text.split("/", 1)[0] if "/" in text else (text or "deterministic")


def _phase_model_assignments(node_ids: list[str] | tuple[str, ...]) -> dict[str, str]:
    return {node_id: (_preferred_lifecycle_model(node_id) or "deterministic-reference") for node_id in node_ids}


def _phase_low_diversity_mode(node_ids: list[str] | tuple[str, ...]) -> bool:
    families = {
        _provider_family(model_name)
        for model_name in _phase_model_assignments(node_ids).values()
        if model_name != "deterministic-reference"
    }
    return len(families) < 2


def _claim_entry(
    claim_id: str,
    *,
    statement: str,
    owner: str,
    category: str,
    evidence_ids: list[str],
    confidence: float = 0.7,
    status: str = "provisional",
    counterevidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": claim_id,
        "statement": statement,
        "owner": owner,
        "category": category,
        "evidence_ids": _dedupe_strings(evidence_ids),
        "counterevidence_ids": _dedupe_strings(list(counterevidence_ids or [])),
        "confidence": _clamp_score(confidence, default=0.7),
        "status": status,
    }


def _evidence_entry(
    evidence_id: str,
    *,
    source_ref: str,
    source_type: str,
    snippet: str,
    relevance: str,
    recency: str = "current cycle",
) -> dict[str, Any]:
    return {
        "id": evidence_id,
        "source_ref": source_ref,
        "source_type": source_type,
        "snippet": snippet,
        "recency": recency,
        "relevance": relevance,
    }


def _dissent_entry(
    dissent_id: str,
    *,
    claim_id: str,
    challenger: str,
    argument: str,
    severity: str,
    resolved: bool = False,
    recommended_test: str = "",
    resolution: str = "",
) -> dict[str, Any]:
    return {
        "id": dissent_id,
        "claim_id": claim_id,
        "challenger": challenger,
        "argument": argument,
        "severity": severity,
        "resolved": resolved,
        "recommended_test": recommended_test,
        "resolution": resolution,
    }


def _finding_entry(
    finding_id: str,
    *,
    title: str,
    challenger: str,
    severity: str,
    impact: str,
    recommendation: str,
    related_feature: str = "",
) -> dict[str, Any]:
    payload = {
        "id": finding_id,
        "title": title,
        "challenger": challenger,
        "severity": severity,
        "impact": impact,
        "recommendation": recommendation,
    }
    if related_feature:
        payload["related_feature"] = related_feature
    return payload


def _negative_persona_entry(
    persona_id: str,
    *,
    name: str,
    scenario: str,
    risk: str,
    mitigation: str,
) -> dict[str, Any]:
    return {
        "id": persona_id,
        "name": name,
        "scenario": scenario,
        "risk": risk,
        "mitigation": mitigation,
    }


def _collect_state_lists(
    state: dict[str, Any],
    *,
    node_ids: list[str] | tuple[str, ...],
    suffix: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for node_id in node_ids:
        for raw in _as_list(state.get(_node_state_key(node_id, suffix))):
            record = _as_dict(raw)
            if record:
                items.append(record)
    return items


def _claim_confidence(
    *,
    evidence_count: int,
    unresolved_dissent: list[dict[str, Any]],
    default: float = 0.72,
) -> float:
    penalty = sum(_SEVERITY_WEIGHT.get(str(item.get("severity", "medium")), 0.08) for item in unresolved_dissent)
    return _clamp_score(default + min(evidence_count * 0.06, 0.18) - penalty, default=default)


def _claim_status(confidence: float, unresolved_dissent: list[dict[str, Any]]) -> str:
    severities = {str(item.get("severity", "")) for item in unresolved_dissent}
    if "critical" in severities or confidence < 0.58:
        return "blocked"
    if "high" in severities or confidence < 0.72:
        return "contested"
    return "accepted"


def _winning_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        claims,
        key=lambda item: (
            0 if str(item.get("status")) == "accepted" else 1,
            -float(item.get("confidence", 0.0) or 0.0),
            str(item.get("statement", "")),
        ),
    )
    winners = [item for item in ordered if str(item.get("status")) == "accepted"][:3]
    return winners or ordered[:2]


def _feature_supporting_claim_ids(state: dict[str, Any], *, limit: int = 2) -> list[str]:
    research = _as_dict(state.get("research"))
    winning = [_as_dict(item) for item in _as_list(research.get("claims")) if _as_dict(item).get("status") == "accepted"]
    if not winning:
        winning = [_as_dict(item) for item in _as_list(research.get("claims"))]
    return [
        str(item.get("id"))
        for item in winning[:limit]
        if str(item.get("id", "")).strip()
    ]


def _build_feature_decisions(state: dict[str, Any], features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    supporting_claim_ids = _feature_supporting_claim_ids(state)
    decisions: list[dict[str, Any]] = []
    for item in features:
        feature = str(item.get("feature", "")).strip()
        if not feature:
            continue
        selected = item.get("selected") is True
        cost = str(item.get("implementation_cost", "medium"))
        decisions.append(
            {
                "feature": feature,
                "selected": selected,
                "supporting_claim_ids": supporting_claim_ids,
                "counterarguments": [],
                "rejection_reason": (
                    ""
                    if selected
                    else "Deliberately held for later to keep the first release scope falsifiable."
                ),
                "uncertainty": round(0.42 if cost == "high" else 0.24 if selected else 0.33, 2),
            }
        )
    return decisions


def _build_traceability(state: dict[str, Any], features: list[dict[str, Any]], milestones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    research = _as_dict(state.get("research"))
    claims = [_as_dict(item) for item in _as_list(research.get("claims")) if _as_dict(item)]
    use_cases = [_as_dict(item) for item in _as_list(state.get("use_cases")) if _as_dict(item)]
    traces: list[dict[str, Any]] = []
    for index, item in enumerate(features):
        feature_name = str(item.get("feature", "")).strip()
        if not feature_name or item.get("selected") is not True:
            continue
        claim = claims[min(index, len(claims) - 1)] if claims else {}
        use_case = use_cases[min(index, len(use_cases) - 1)] if use_cases else {}
        milestone = _as_dict(milestones[min(index, len(milestones) - 1)]) if milestones else {}
        traces.append(
            {
                "claim_id": str(claim.get("id", "")),
                "claim": str(claim.get("statement", "")),
                "use_case_id": str(use_case.get("id", "")),
                "use_case": str(use_case.get("title", "")),
                "feature": feature_name,
                "milestone_id": str(milestone.get("id", "")),
                "milestone": str(milestone.get("name", "")),
                "confidence": float(claim.get("confidence", 0.72) or 0.72),
            }
        )
    return traces


def _research_competitor_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    urls = state.get("competitor_urls", []) or []
    spec = str(state.get("spec", ""))
    competitors: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for index, raw_url in enumerate(urls[:4]):
        parsed = urlparse(str(raw_url))
        host = (parsed.hostname or "competitor").replace("www.", "")
        name = host.split(".")[0].replace("-", " ").title()
        competitors.append(
            {
                "name": name or "Competitor",
                "url": str(raw_url),
                "strengths": ["認知が高い", "導入事例が多い", "オンボーディングが分かりやすい"],
                "weaknesses": ["差別化が弱い", "運用体験が画一的", "深い自律化には弱い"],
                "pricing": "問い合わせ",
                "target": _segment_from_spec(spec),
            }
        )
        evidence.append(
            _evidence_entry(
                f"ev-competitor-{index + 1}",
                source_ref=str(raw_url),
                source_type="url",
                snippet=f"{name or 'Competitor'} appears positioned for {_segment_from_spec(spec)} buyers with broad onboarding promises.",
                relevance="Competitive positioning reference",
            )
        )
    if not competitors:
        base_names = ["Pulse", "Atlas", "Launchpad"]
        for index, base_name in enumerate(base_names):
            name = f"{base_name} {spec[:18].strip() or 'Suite'}".strip()
            competitors.append(
                {
                    "name": name,
                    "strengths": ["セットアップが速い", "一貫した UI", "導入説明が明快"],
                    "weaknesses": ["深い制御が弱い", "運用品質の可視化が浅い"],
                    "pricing": "SaaS tier",
                    "target": _segment_from_spec(spec),
                }
            )
            evidence.append(
                _evidence_entry(
                    f"ev-competitor-{index + 1}",
                    source_ref=f"synthetic://competitor/{_slug(name, prefix='competitor')}",
                    source_type="synthetic-reference",
                    snippet=f"{name} represents the common fast-setup but low-governance baseline in this segment.",
                    relevance="Competitive baseline for differentiation",
                )
            )
    claims = [
        _claim_entry(
            "claim-competitive-gap",
            statement="Most adjacent products optimize onboarding and breadth before governed autonomous execution, leaving a differentiation gap around traceable decision-making.",
            owner=node_id,
            category="competition",
            evidence_ids=[item["id"] for item in evidence[:2]],
            confidence=0.71,
        ),
    ]
    return NodeResult(
        state_patch={
            "competitor_report": competitors,
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "evidence"): evidence,
        },
        artifacts=_artifacts(
            {"name": "competitor-map", "kind": "research", "items": competitors},
            {"name": "competitor-claims", "kind": "research", "claims": claims, "evidence": evidence},
        ),
        metrics={"competitor_count": len(competitors)},
    )


def _research_market_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    spec = str(state.get("spec", ""))
    keywords = _keywords(spec)
    trends = _market_trends(spec)
    opportunities = [
        "安全性と自律性の両立を前提にした運用体験を提供する",
        "プロダクト判断の根拠を artifact として残し、監査可能にする",
    ]
    if _contains_any(spec, "agent", "エージェント", "workflow", "ワークフロー"):
        opportunities.append("複数 agent の協調と handoff を見える化する")
    payload = {
        "market_size": _market_size_from_spec(spec, keywords),
        "trends": trends,
        "opportunities": opportunities,
        "threats": [
            "機能幅だけが増え、運用品質が伴わないプラットフォーム化",
            "UI と backend の契約ドリフトによる信頼低下",
        ],
    }
    evidence = [
        _evidence_entry(
            "ev-market-size",
            source_ref="derived://market-size",
            source_type="derived-analysis",
            snippet=payload["market_size"],
            relevance="Market sizing thesis",
        ),
        *[
            _evidence_entry(
                f"ev-trend-{index + 1}",
                source_ref=f"derived://trend/{index + 1}",
                source_type="derived-analysis",
                snippet=trend,
                relevance="Observed market trend",
            )
            for index, trend in enumerate(trends[:2])
        ],
    ]
    claims = [
        _claim_entry(
            "claim-market-demand",
            statement="The segment is shifting toward evidence-backed automation and governance, so products that keep decisions and execution context in one loop have a timing advantage.",
            owner=node_id,
            category="market",
            evidence_ids=[item["id"] for item in evidence],
            confidence=0.74,
        ),
    ]
    return NodeResult(
        state_patch={
            "market_report": payload,
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "evidence"): evidence,
        },
        artifacts=_artifacts(
            {"name": "market-research", "kind": "research", **payload},
            {"name": "market-claims", "kind": "research", "claims": claims, "evidence": evidence},
        ),
        metrics={"trend_count": len(trends)},
    )


def _research_user_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    spec = str(state.get("spec", ""))
    payload = {
        "signals": [
            "意思決定の根拠を共有したい",
            "手戻りなく企画から実装へ繋ぎたい",
            "agent に任せても制御を失いたくない",
        ],
        "pain_points": [
            "ツールが分断されていて handoff のたびに文脈が失われる",
            "自律化しても品質保証が弱くレビュー負債が残る",
        ],
        "segment": _segment_from_spec(spec),
    }
    evidence = [
        _evidence_entry(
            "ev-user-signal-1",
            source_ref="derived://user-signal/continuity",
            source_type="derived-analysis",
            snippet=payload["signals"][0],
            relevance="Primary user demand signal",
        ),
        _evidence_entry(
            "ev-user-pain-1",
            source_ref="derived://user-pain/handoff",
            source_type="derived-analysis",
            snippet=payload["pain_points"][0],
            relevance="Primary friction to solve",
        ),
    ]
    claims = [
        _claim_entry(
            "claim-user-trust",
            statement="The product must preserve context continuity and controllability, otherwise users will not trust autonomous execution beyond simple happy paths.",
            owner=node_id,
            category="user",
            evidence_ids=[item["id"] for item in evidence],
            confidence=0.76,
        ),
    ]
    return NodeResult(
        state_patch={
            "user_research": payload,
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "evidence"): evidence,
        },
        artifacts=_artifacts(
            {"name": "user-signals", "kind": "research", **payload},
            {"name": "user-claims", "kind": "research", "claims": claims, "evidence": evidence},
        ),
    )


def _research_tech_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    spec = str(state.get("spec", ""))
    score = 0.84 if _contains_any(spec, "workflow", "agent", "ui", "dashboard", "app") else 0.72
    payload = {
        "score": round(score, 2),
        "notes": "Reference implementation can be delivered quickly; production hardening depends on durable state, quality gates, and approval integration.",
    }
    evidence = [
        _evidence_entry(
            "ev-tech-score",
            source_ref="derived://technical-feasibility",
            source_type="derived-analysis",
            snippet=f"Technical feasibility score {payload['score']:.2f}. {payload['notes']}",
            relevance="Delivery feasibility assessment",
        )
    ]
    claims = [
        _claim_entry(
            "claim-technical-feasibility",
            statement="The concept is technically feasible for a prototype, but autonomous quality depends on durable state, explicit quality gates, and operator-visible recovery paths.",
            owner=node_id,
            category="technical",
            evidence_ids=[item["id"] for item in evidence],
            confidence=0.79 if score >= 0.8 else 0.68,
        ),
    ]
    return NodeResult(
        state_patch={
            "technical_report": payload,
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "evidence"): evidence,
        },
        artifacts=_artifacts(
            {"name": "risk-register", "kind": "research", "tech_feasibility": payload},
            {"name": "tech-claims", "kind": "research", "claims": claims, "evidence": evidence},
        ),
    )


def _research_synthesizer_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    market = _as_dict(state.get("market_report"))
    technical = _as_dict(state.get("technical_report"))
    user_research = _as_dict(state.get("user_research"))
    claims = _collect_state_lists(state, node_ids=_RESEARCH_PROPOSAL_NODES, suffix="claims")
    evidence = _collect_state_lists(state, node_ids=_RESEARCH_PROPOSAL_NODES, suffix="evidence")
    winning = _winning_claims(claims)
    confidence_values = [float(item.get("confidence", 0.0) or 0.0) for item in claims]
    research = {
        "competitors": list(state.get("competitor_report", [])),
        "market_size": market.get("market_size", "Early but expanding operational market"),
        "trends": list(market.get("trends", [])),
        "opportunities": list(market.get("opportunities", [])),
        "threats": list(market.get("threats", [])),
        "user_research": {
            "signals": list(user_research.get("signals", [])),
            "pain_points": list(user_research.get("pain_points", [])),
            "segment": user_research.get("segment", _segment_from_spec(str(state.get("spec", "")))),
        },
        "tech_feasibility": {
            "score": technical.get("score", 0.75),
            "notes": technical.get("notes", ""),
        },
        "claims": claims,
        "evidence": evidence,
        "dissent": [],
        "open_questions": [],
        "winning_theses": [str(item.get("statement", "")) for item in winning if str(item.get("statement", "")).strip()],
        "confidence_summary": {
            "average": round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else 0.0,
            "floor": round(min(confidence_values), 2) if confidence_values else 0.0,
        },
        "model_assignments": _phase_model_assignments(list(_RESEARCH_PROPOSAL_NODES) + list(_RESEARCH_REVIEW_NODES)),
        "low_diversity_mode": _phase_low_diversity_mode(list(_RESEARCH_PROPOSAL_NODES) + list(_RESEARCH_REVIEW_NODES)),
    }
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "evidence"): evidence,
            "research": research,
            "output": research,
        },
        artifacts=_artifacts({"name": "research-report", "kind": "research", **research}),
    )


def _research_evidence_librarian_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    research = _as_dict(state.get("research"))
    evidence = _collect_state_lists(state, node_ids=_RESEARCH_PROPOSAL_NODES + ("research-synthesizer",), suffix="evidence")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in evidence:
        evidence_id = str(item.get("id", "")).strip()
        if not evidence_id or evidence_id in seen_ids:
            continue
        seen_ids.add(evidence_id)
        normalized.append(item)
    source_links = _dedupe_strings(
        [
            str(item.get("source_ref", "")).strip()
            for item in normalized
            if str(item.get("source_type", "")).strip() in {"url", "synthetic-reference", "derived-analysis"}
        ]
    )
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "evidence"): normalized,
            _node_state_key(node_id, "source_links"): source_links,
            "research": {**research, "evidence": normalized, "source_links": source_links},
        },
        artifacts=_artifacts({"name": "claim-ledger", "kind": "research", "evidence": normalized, "source_links": source_links}),
    )


async def _research_devils_advocate_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    research = _as_dict(state.get("research"))
    claims = [_as_dict(item) for item in _as_list(research.get("claims")) if _as_dict(item)]
    threats = [str(item) for item in _as_list(research.get("threats")) if str(item).strip()]
    fallback_dissent = [
        _dissent_entry(
            f"dissent-{index + 1}",
            claim_id=str(claim.get("id", "")),
            challenger=node_id,
            argument=(
                threats[index % len(threats)]
                if threats
                else "This claim could collapse if the product becomes feature-broad before it proves operator trust and recovery."
            ),
            severity="high" if str(claim.get("category")) in {"competition", "technical"} else "medium",
            recommended_test="Define the observable evidence that would falsify this claim in the first milestone.",
        )
        for index, claim in enumerate(claims[:3])
        if str(claim.get("id", "")).strip()
    ]
    fallback_questions = _dedupe_strings(
        [
            "どの claim が外れていた場合に alpha scope を即座に縮小するか",
            "競合優位が UI の見た目ではなく運用面で再現可能か",
            "ユーザーは自律化より traceability を先に求めていないか",
        ]
    )
    llm_events: list[dict[str, Any]] = []
    if _provider_backed_lifecycle_available(provider_registry) and claims:
        payload, llm_events, _ = await _lifecycle_llm_json(
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
            preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
            purpose=f"lifecycle-research-{node_id}",
            static_instruction=(
                "You are a devil's advocate for product research. Return JSON only with keys dissent and open_questions. "
                "Attack weak assumptions, not formatting."
            ),
            user_prompt=(
                "Return JSON only.\n"
                f"Claims: {claims}\n"
                f"Threats: {threats}\n"
                f"User signals: {_as_dict(research.get('user_research')).get('signals')}\n"
                "dissent items must include claim_id, argument, severity, recommended_test."
            ),
        )
        raw_dissent = [
            _dissent_entry(
                f"dissent-llm-{index + 1}",
                claim_id=str(_as_dict(item).get("claim_id", "")),
                challenger=node_id,
                argument=str(_as_dict(item).get("argument", "")).strip(),
                severity=str(_as_dict(item).get("severity", "medium")).strip() or "medium",
                recommended_test=str(_as_dict(item).get("recommended_test", "")).strip(),
            )
            for index, item in enumerate(_as_list(_as_dict(payload).get("dissent")))
            if str(_as_dict(item).get("claim_id", "")).strip() and str(_as_dict(item).get("argument", "")).strip()
        ]
        if raw_dissent:
            fallback_dissent = raw_dissent
        llm_questions = _dedupe_strings(
            [str(item).strip() for item in _as_list(_as_dict(payload).get("open_questions")) if str(item).strip()]
        )
        if llm_questions:
            fallback_questions = llm_questions
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "dissent"): fallback_dissent,
            _node_state_key(node_id, "open_questions"): fallback_questions,
        },
        artifacts=_artifacts({"name": "research-dissent", "kind": "research", "dissent": fallback_dissent, "open_questions": fallback_questions}),
        llm_events=llm_events,
        metrics={"review_mode": "provider-backed" if llm_events else "deterministic-reference"},
    )


def _research_cross_examiner_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    del provider_registry, llm_runtime
    research = _as_dict(state.get("research"))
    claims = [_as_dict(item) for item in _as_list(research.get("claims")) if _as_dict(item)]
    evidence = [_as_dict(item) for item in _as_list(research.get("evidence")) if _as_dict(item)]
    evidence_map = {str(item.get("id")): item for item in evidence if str(item.get("id", "")).strip()}
    dissent = _collect_state_lists(state, node_ids=("devils-advocate-researcher",), suffix="dissent")
    updated_claims: list[dict[str, Any]] = []
    updated_dissent: list[dict[str, Any]] = []
    open_questions = _dedupe_strings(
        [str(item) for item in _as_list(state.get(_node_state_key("devils-advocate-researcher", "open_questions"))) if str(item).strip()]
    )
    for claim in claims:
        claim_id = str(claim.get("id", "")).strip()
        claim_dissent = [item for item in dissent if str(item.get("claim_id", "")) == claim_id]
        evidence_count = sum(1 for ev_id in _as_list(claim.get("evidence_ids")) if str(ev_id) in evidence_map)
        resolved_claim_dissent: list[dict[str, Any]] = []
        for item in claim_dissent:
            patched = dict(item)
            severity = str(item.get("severity", "medium"))
            resolved = evidence_count >= 2 or (severity == "high" and evidence_count >= 1 and float(_as_dict(research.get("tech_feasibility")).get("score", 0.0) or 0.0) >= 0.8)
            if resolved:
                patched["resolved"] = True
                patched["resolution"] = "Cross examination found enough evidence or delivery control to keep this claim alive."
            resolved_claim_dissent.append(patched)
        unresolved = [item for item in resolved_claim_dissent if item.get("resolved") is not True]
        confidence = _claim_confidence(evidence_count=evidence_count, unresolved_dissent=unresolved, default=float(claim.get("confidence", 0.72) or 0.72))
        updated_claims.append({**claim, "confidence": confidence, "status": _claim_status(confidence, unresolved)})
        updated_dissent.extend(resolved_claim_dissent)
        if evidence_count < 2:
            open_questions.append(f"{claim.get('statement')} を裏づける追加 evidence が必要")
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "claims"): updated_claims,
            _node_state_key(node_id, "dissent"): updated_dissent,
            _node_state_key(node_id, "open_questions"): _dedupe_strings(open_questions),
        },
        artifacts=_artifacts({"name": "research-cross-examination", "kind": "research", "claims": updated_claims, "dissent": updated_dissent}),
    )


async def _research_judge_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    research = _as_dict(state.get("research"))
    claims = _collect_state_lists(state, node_ids=("cross-examiner",), suffix="claims") or [_as_dict(item) for item in _as_list(research.get("claims")) if _as_dict(item)]
    dissent = _collect_state_lists(state, node_ids=("cross-examiner",), suffix="dissent")
    open_questions = _dedupe_strings(
        [str(item) for item in _as_list(state.get(_node_state_key("cross-examiner", "open_questions"))) if str(item).strip()]
    )
    llm_events: list[dict[str, Any]] = []
    llm_summary = ""
    if _provider_backed_lifecycle_available(provider_registry) and claims:
        payload, llm_events, _ = await _lifecycle_llm_json(
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
            preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
            purpose=f"lifecycle-research-{node_id}",
            static_instruction=(
                "You are a research judge. Return JSON only with keys winning_theses, claim_confidence_overrides, summary, open_questions. "
                "Use conservative confidence updates."
            ),
            user_prompt=(
                "Return JSON only.\n"
                f"Claims: {claims}\n"
                f"Dissent: {dissent}\n"
                f"Open questions: {open_questions}\n"
            ),
        )
        llm_summary = str(_as_dict(payload).get("summary", "")).strip()
        overrides = _as_dict(_as_dict(payload).get("claim_confidence_overrides"))
        if overrides:
            patched_claims = []
            for claim in claims:
                claim_id = str(claim.get("id", ""))
                if claim_id in overrides:
                    confidence = _clamp_score(overrides.get(claim_id), default=float(claim.get("confidence", 0.72) or 0.72))
                    unresolved = [item for item in dissent if str(item.get("claim_id", "")) == claim_id and item.get("resolved") is not True]
                    patched_claims.append({**claim, "confidence": confidence, "status": _claim_status(confidence, unresolved)})
                else:
                    patched_claims.append(claim)
            claims = patched_claims
        llm_questions = _dedupe_strings([str(item).strip() for item in _as_list(_as_dict(payload).get("open_questions")) if str(item).strip()])
        if llm_questions:
            open_questions = _dedupe_strings(open_questions + llm_questions)
    winners = _winning_claims(claims)
    confidence_values = [float(item.get("confidence", 0.0) or 0.0) for item in claims]
    final_research = {
        **research,
        "claims": claims,
        "evidence": _collect_state_lists(state, node_ids=("evidence-librarian",), suffix="evidence") or _as_list(research.get("evidence")),
        "dissent": dissent,
        "source_links": _as_list(state.get(_node_state_key("evidence-librarian", "source_links"))) or _as_list(research.get("source_links")),
        "open_questions": open_questions,
        "winning_theses": [str(item.get("statement", "")) for item in winners if str(item.get("statement", "")).strip()],
        "confidence_summary": {
            "average": round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else 0.0,
            "floor": round(min(confidence_values), 2) if confidence_values else 0.0,
            "accepted": sum(1 for item in claims if str(item.get("status")) == "accepted"),
        },
        "judge_summary": llm_summary or "Claims that survived dissent are passed to planning together with unresolved questions.",
        "critical_dissent_count": sum(1 for item in dissent if str(item.get("severity")) == "critical" and item.get("resolved") is not True),
        "resolved_dissent_count": sum(1 for item in dissent if item.get("resolved") is True),
        "model_assignments": _phase_model_assignments(list(_RESEARCH_PROPOSAL_NODES) + list(_RESEARCH_REVIEW_NODES)),
        "low_diversity_mode": _phase_low_diversity_mode(list(_RESEARCH_PROPOSAL_NODES) + list(_RESEARCH_REVIEW_NODES)),
    }
    return NodeResult(
        state_patch={"research": final_research, "output": final_research},
        artifacts=_artifacts({"name": "research-judgement", "kind": "research", **final_research}),
        llm_events=llm_events,
        metrics={"review_mode": "provider-backed" if llm_events else "deterministic-reference"},
    )


def _planning_persona_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    personas, stories, journeys = _build_persona_bundle(state)
    return NodeResult(
        state_patch={
            "persona_report": personas,
            "story_report": stories,
            "journey_report": journeys,
        },
        artifacts=_artifacts({"name": "product-brief", "kind": "planning", "personas": personas}),
    )


def _planning_story_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    payload = _build_story_architecture_bundle(state)
    return NodeResult(
        state_patch=payload,
        artifacts=_artifacts({"name": "story-architecture", "kind": "planning", **payload}),
    )


def _planning_feature_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    base_features = _feature_catalog_for_spec(state)
    kano_features = [
        {
            "feature": name,
            "category": category,
            "user_delight": 0.95 if category == "attractive" else 0.82 if category == "one-dimensional" else 0.72,
            "implementation_cost": cost,
            "rationale": rationale,
        }
        for name, category, cost, rationale in base_features
    ]
    features = [
        {
            "feature": item["feature"],
            "category": item["category"],
            "selected": item["category"] != "attractive",
            "priority": "must" if item["category"] == "must-be" else "should" if item["category"] == "one-dimensional" else "could",
            "user_delight": item["user_delight"],
            "implementation_cost": item["implementation_cost"],
            "rationale": item["rationale"],
        }
        for item in kano_features
    ]
    return NodeResult(
        state_patch={
            "kano_report": kano_features,
            "feature_selections": features,
            _node_state_key(node_id, "feature_decisions"): _build_feature_decisions(state, features),
        },
        artifacts=_artifacts({"name": "feature-priority-matrix", "kind": "planning", "features": features}),
    )


def _planning_solution_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    plan_estimates = _build_plan_estimates(state)
    solution = _solution_bundle(state)
    return NodeResult(
        state_patch={
            "recommended_milestones": solution["recommended_milestones"],
            "plan_estimates_report": plan_estimates,
            "business_model_report": solution["business_model"],
            "design_tokens_report": solution["design_tokens"],
        },
        artifacts=_artifacts({"name": "delivery-plan", "kind": "planning", "plan_estimates": plan_estimates}),
    )


def _planning_synthesizer_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    features = list(state.get("feature_selections", []))
    plan_estimates = list(state.get("plan_estimates_report", []))
    milestones = list(state.get("recommended_milestones", []))
    analysis = {
        "personas": list(state.get("persona_report", [])),
        "user_stories": list(state.get("story_report", [])),
        "kano_features": list(state.get("kano_report", [])),
        "recommendations": _planning_recommendations(state),
        "business_model": _as_dict(state.get("business_model_report")),
        "user_journeys": list(state.get("journey_report", [])),
        "job_stories": list(state.get("job_stories", [])),
        "actors": list(state.get("actors", [])),
        "roles": list(state.get("roles", [])),
        "use_cases": list(state.get("use_cases", [])),
        "ia_analysis": _as_dict(state.get("ia_analysis")),
        "recommended_milestones": milestones,
        "design_tokens": _as_dict(state.get("design_tokens_report")),
        "feature_decisions": _build_feature_decisions(state, features),
        "rejected_features": [
            {
                "feature": str(item.get("feature", "")),
                "reason": "Held for later to preserve falsifiable scope and delivery confidence.",
                "counterarguments": ["This feature increases complexity before the first evidence loop is validated."],
            }
            for item in features
            if item.get("selected") is not True and str(item.get("feature", "")).strip()
        ],
        "assumptions": [],
        "red_team_findings": [],
        "negative_personas": [],
        "kill_criteria": [],
        "traceability": _build_traceability(state, features, milestones),
        "model_assignments": _phase_model_assignments(list(_PLANNING_PROPOSAL_NODES) + list(_PLANNING_REVIEW_NODES)),
        "low_diversity_mode": _phase_low_diversity_mode(list(_PLANNING_PROPOSAL_NODES) + list(_PLANNING_REVIEW_NODES)),
    }
    planning_payload = {**analysis, "features": features, "plan_estimates": plan_estimates}
    return NodeResult(
        state_patch={
            "analysis": analysis,
            "features": features,
            "planEstimates": plan_estimates,
            "planning": planning_payload,
            "output": planning_payload,
        },
        artifacts=_artifacts({"name": "planning-summary", "kind": "planning", **planning_payload}),
    )


async def _planning_scope_skeptic_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    features = [_as_dict(item) for item in _as_list(state.get("feature_selections")) if _as_dict(item)]
    fallback_rejected = [
        {
            "feature": str(item.get("feature", "")),
            "reason": "Deferred because it adds breadth before the core evidence loop is validated.",
            "counterarguments": ["Increases delivery surface without tightening the first milestone signal."],
        }
        for item in features
        if item.get("selected") is not True and str(item.get("feature", "")).strip()
    ]
    fallback_findings = [
        _finding_entry(
            f"scope-{index + 1}",
            title=f"Scope pressure around {item.get('feature')}",
            challenger=node_id,
            severity="high" if str(item.get("implementation_cost")) == "high" else "medium",
            impact="If this remains in the first cut, the team may lose falsifiability and review speed.",
            recommendation="Keep this out of the first release unless a research claim explicitly requires it.",
            related_feature=str(item.get("feature", "")),
        )
        for index, item in enumerate(features)
        if item.get("selected") is True and str(item.get("implementation_cost")) == "high"
    ] or [
        _finding_entry(
            "scope-guardrail",
            title="Protect first-release scope",
            challenger=node_id,
            severity="medium",
            impact="Adding convenience features early would blur whether the core workflow is actually working.",
            recommendation="Keep the first milestone focused on a single evidence-to-decision loop.",
        )
    ]
    llm_events: list[dict[str, Any]] = []
    if _provider_backed_lifecycle_available(provider_registry) and features:
        payload, llm_events, _ = await _lifecycle_llm_json(
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
            preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
            purpose=f"lifecycle-planning-{node_id}",
            static_instruction=(
                "You are a scope skeptic. Return JSON only with keys rejected_features and red_team_findings. "
                "Prefer cutting scope over vague risk language."
            ),
            user_prompt=f"Features: {features}\nResearch: {_as_dict(state.get('research'))}\n",
        )
        raw_rejected = [
            {
                "feature": str(_as_dict(item).get("feature", "")).strip(),
                "reason": str(_as_dict(item).get("reason", "")).strip(),
                "counterarguments": [str(arg).strip() for arg in _as_list(_as_dict(item).get("counterarguments")) if str(arg).strip()],
            }
            for item in _as_list(_as_dict(payload).get("rejected_features"))
            if str(_as_dict(item).get("feature", "")).strip() and str(_as_dict(item).get("reason", "")).strip()
        ]
        raw_findings = [
            _finding_entry(
                f"scope-llm-{index + 1}",
                title=str(_as_dict(item).get("title", "")).strip() or "Scope finding",
                challenger=node_id,
                severity=str(_as_dict(item).get("severity", "medium")).strip() or "medium",
                impact=str(_as_dict(item).get("impact", "")).strip(),
                recommendation=str(_as_dict(item).get("recommendation", "")).strip(),
                related_feature=str(_as_dict(item).get("related_feature", "")).strip(),
            )
            for index, item in enumerate(_as_list(_as_dict(payload).get("red_team_findings")))
            if str(_as_dict(item).get("recommendation", "")).strip()
        ]
        if raw_rejected:
            fallback_rejected = raw_rejected
        if raw_findings:
            fallback_findings = raw_findings
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "rejected_features"): fallback_rejected,
            _node_state_key(node_id, "red_team_findings"): fallback_findings,
        },
        artifacts=_artifacts({"name": "scope-review", "kind": "planning", "rejected_features": fallback_rejected, "red_team_findings": fallback_findings}),
        llm_events=llm_events,
        metrics={"review_mode": "provider-backed" if llm_events else "deterministic-reference"},
    )


def _planning_assumption_auditor_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    del provider_registry, llm_runtime
    personas = [_as_dict(item) for item in _as_list(state.get("persona_report")) if _as_dict(item)]
    research = _research_context(state)
    assumptions = _dedupe_strings(
        [
            f"{str(personas[0].get('name', 'Primary user')) if personas else 'Primary user'} will trade setup breadth for stronger control and traceability.",
            "The first milestone can be validated before full-scale automation breadth is delivered.",
            *(f"Research assumption: {item}" for item in research["user_signals"][:1]),
        ]
    )
    findings = [
        _finding_entry(
            "assumption-gap",
            title="Planning relies on a narrow trust assumption",
            challenger=node_id,
            severity="medium",
            impact="If users actually value speed over governance, the proposed scope may be too heavy.",
            recommendation="Validate control-plane depth against onboarding friction in the first user loop.",
        )
    ]
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "assumptions"): [{"id": f"assumption-{index + 1}", "statement": text, "severity": "medium"} for index, text in enumerate(assumptions)],
            _node_state_key(node_id, "red_team_findings"): findings,
        },
        artifacts=_artifacts({"name": "assumption-audit", "kind": "planning", "assumptions": assumptions, "red_team_findings": findings}),
    )


def _planning_negative_persona_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    del provider_registry, llm_runtime
    kind = _infer_product_kind(str(state.get("spec", "")))
    if kind == "operations":
        personas = [
            _negative_persona_entry(
                "negative-ops-1",
                name="Shadow Automator",
                scenario="Runs autonomous flows without reviewing evidence or approval states.",
                risk="Can create silent drift between plan, approval, and build.",
                mitigation="Keep approval status and lineage visible in every primary workflow.",
            ),
            _negative_persona_entry(
                "negative-ops-2",
                name="Audit Skeptic",
                scenario="Needs traceability to trust the system but only sees generated output.",
                risk="Rejects autonomous adoption if artifact lineage is not first-class.",
                mitigation="Surface claim-to-feature traceability and unresolved dissent above the fold.",
            ),
        ]
    else:
        personas = [
            _negative_persona_entry(
                "negative-generic-1",
                name="Impatient Evaluator",
                scenario="Judges the product after one incomplete run.",
                risk="Leaves before the core loop demonstrates value.",
                mitigation="Make the first successful workflow obvious and measurable.",
            )
        ]
    findings = [
        _finding_entry(
            "negative-persona-risk",
            title="The plan does not naturally protect against the hardest-to-serve user",
            challenger=node_id,
            severity="medium",
            impact="Without explicit handling, failure modes stay hidden until rollout.",
            recommendation="Turn these negative personas into acceptance and instrumentation checks.",
        )
    ]
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "negative_personas"): personas,
            _node_state_key(node_id, "red_team_findings"): findings,
        },
        artifacts=_artifacts({"name": "negative-persona-review", "kind": "planning", "negative_personas": personas}),
    )


def _planning_milestone_falsifier_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    del provider_registry, llm_runtime
    milestones = [_as_dict(item) for item in _as_list(state.get("recommended_milestones")) if _as_dict(item)]
    kill_criteria = [
        {
            "id": f"kill-{index + 1}",
            "milestone_id": str(item.get("id", "")),
            "condition": f"If {str(item.get('name', 'the milestone')).strip()} cannot show observable completion evidence, stop scope expansion and re-open planning.",
            "rationale": "Milestones must be falsifiable instead of narrative.",
        }
        for index, item in enumerate(milestones[:3])
    ]
    findings = [
        _finding_entry(
            f"milestone-{index + 1}",
            title=f"Milestone {str(item.get('name', 'Milestone'))} needs a failure condition",
            challenger=node_id,
            severity="medium",
            impact="A milestone without a stop condition will let the team ship momentum instead of evidence.",
            recommendation="Add the observable failure signal next to the success criteria.",
        )
        for index, item in enumerate(milestones[:2])
    ]
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "kill_criteria"): kill_criteria,
            _node_state_key(node_id, "red_team_findings"): findings,
        },
        artifacts=_artifacts({"name": "milestone-falsification", "kind": "planning", "kill_criteria": kill_criteria, "red_team_findings": findings}),
    )


async def _planning_judge_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    analysis = _as_dict(state.get("analysis"))
    features = [_as_dict(item) for item in _as_list(state.get("feature_selections")) if _as_dict(item)]
    milestones = [_as_dict(item) for item in _as_list(state.get("recommended_milestones")) if _as_dict(item)]
    feature_decisions = [_as_dict(item) for item in _as_list(analysis.get("feature_decisions")) if _as_dict(item)] or _build_feature_decisions(state, features)
    rejected_features = _collect_state_lists(state, node_ids=("scope-skeptic",), suffix="rejected_features") or _as_list(analysis.get("rejected_features"))
    assumptions = _collect_state_lists(state, node_ids=("assumption-auditor",), suffix="assumptions")
    negative_personas = _collect_state_lists(state, node_ids=("negative-persona-challenger",), suffix="negative_personas")
    kill_criteria = _collect_state_lists(state, node_ids=("milestone-falsifier",), suffix="kill_criteria")
    findings = (
        _collect_state_lists(state, node_ids=("scope-skeptic", "assumption-auditor", "negative-persona-challenger", "milestone-falsifier"), suffix="red_team_findings")
        or _as_list(analysis.get("red_team_findings"))
    )
    traceability = _build_traceability(state, features, milestones)
    llm_events: list[dict[str, Any]] = []
    judge_summary = ""
    if _provider_backed_lifecycle_available(provider_registry) and feature_decisions:
        payload, llm_events, _ = await _lifecycle_llm_json(
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
            preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
            purpose=f"lifecycle-planning-{node_id}",
            static_instruction=(
                "You are a planning judge. Return JSON only with keys recommendations and headline_risks. "
                "Focus on what should survive to design and development."
            ),
            user_prompt=(
                "Return JSON only.\n"
                f"Feature decisions: {feature_decisions}\n"
                f"Red team findings: {findings}\n"
                f"Assumptions: {assumptions}\n"
                f"Negative personas: {negative_personas}\n"
            ),
        )
        llm_recommendations = _dedupe_strings([str(item).strip() for item in _as_list(_as_dict(payload).get("recommendations")) if str(item).strip()])
        if llm_recommendations:
            analysis["recommendations"] = _dedupe_strings(llm_recommendations + [str(item) for item in _as_list(analysis.get("recommendations")) if str(item).strip()])
        judge_summary = ", ".join(
            str(item).strip() for item in _as_list(_as_dict(payload).get("headline_risks")) if str(item).strip()
        )
    decision_map = {str(item.get("feature", "")): dict(item) for item in feature_decisions if str(item.get("feature", "")).strip()}
    rejected_map = {str(item.get("feature", "")): dict(item) for item in rejected_features if str(item.get("feature", "")).strip()}
    for feature in features:
        name = str(feature.get("feature", "")).strip()
        if not name or name not in decision_map:
            continue
        decision = decision_map[name]
        if name in rejected_map:
            decision["selected"] = False
            decision["rejection_reason"] = str(rejected_map[name].get("reason", decision.get("rejection_reason", "")))
            decision["counterarguments"] = _dedupe_strings(
                [str(item) for item in _as_list(decision.get("counterarguments")) if str(item).strip()]
                + [str(item) for item in _as_list(rejected_map[name].get("counterarguments")) if str(item).strip()]
            )
        elif str(feature.get("implementation_cost")) == "high":
            decision["counterarguments"] = _dedupe_strings(
                [str(item) for item in _as_list(decision.get("counterarguments")) if str(item).strip()]
                + ["High-cost scope must prove its necessity with a first-milestone signal."]
            )
    final_features = []
    for feature in features:
        name = str(feature.get("feature", "")).strip()
        decision = decision_map.get(name, {})
        final_features.append({**feature, "selected": decision.get("selected", feature.get("selected")) is True})
    confidence_values = [1.0 - float(item.get("uncertainty", 0.3) or 0.3) for item in decision_map.values()] or [0.7]
    final_analysis = {
        **analysis,
        "feature_decisions": list(decision_map.values()),
        "rejected_features": list(rejected_map.values()),
        "assumptions": assumptions,
        "red_team_findings": findings,
        "negative_personas": negative_personas,
        "kill_criteria": kill_criteria,
        "traceability": traceability,
        "confidence_summary": {
            "average": round(sum(confidence_values) / len(confidence_values), 2),
            "floor": round(min(confidence_values), 2),
            "critical_findings": sum(1 for item in findings if str(item.get("severity")) == "critical"),
        },
        "judge_summary": judge_summary or "The plan keeps only features that remain traceable to research claims and falsifiable milestones.",
        "model_assignments": _phase_model_assignments(list(_PLANNING_PROPOSAL_NODES) + list(_PLANNING_REVIEW_NODES)),
        "low_diversity_mode": _phase_low_diversity_mode(list(_PLANNING_PROPOSAL_NODES) + list(_PLANNING_REVIEW_NODES)),
    }
    final_plan_estimates = list(state.get("plan_estimates_report", []))
    planning_payload = {**final_analysis, "features": final_features, "plan_estimates": final_plan_estimates}
    return NodeResult(
        state_patch={
            "analysis": final_analysis,
            "features": final_features,
            "planEstimates": final_plan_estimates,
            "planning": planning_payload,
            "output": planning_payload,
        },
        artifacts=_artifacts({"name": "planning-judgement", "kind": "planning", **planning_payload}),
        llm_events=llm_events,
        metrics={"review_mode": "provider-backed" if llm_events else "deterministic-reference"},
    )


def _design_variant_handler(
    model_name: str,
    pattern_name: str,
    description: str,
    primary: str,
    accent: str,
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
):
    def handler(node_id: str, state: dict[str, Any]) -> NodeResult:
        selected_features = _selected_feature_names(state)
        spec = str(state.get("spec", ""))
        plan = {
            "phase": "design",
            "node_id": node_id,
            "agent_label": model_name,
            "objective": "Produce a differentiated design direction with strong operator clarity.",
            "candidate_skills": [],
            "selected_skills": [],
            "quality_targets": _phase_quality_targets("design"),
            "delegations": [],
            "mode": "deterministic-reference",
            "execution_note": description,
        }
        variant = _design_variant_payload(
            node_id=node_id,
            model_name=model_name,
            pattern_name=pattern_name,
            description=description,
            primary=primary,
            accent=accent,
            selected_features=selected_features,
            spec=spec,
            analysis=_as_dict(state.get("analysis")),
            rationale=description,
        )
        return NodeResult(
            state_patch={
                f"{node_id}_variant": variant,
                _skill_plan_state_key(node_id): plan,
                _delegation_state_key(node_id): [],
                _peer_feedback_state_key(node_id): [],
            },
            artifacts=_artifacts(
                {"name": f"{node_id}-variant", "kind": "design", **variant},
                {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **plan},
            ),
            metrics={"design_mode": "deterministic-reference"},
        )

    async def autonomous_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
        selected_features = _selected_feature_names(state)
        spec = str(state.get("spec", ""))
        analysis = _as_dict(state.get("analysis"))
        personas = _as_list(analysis.get("personas"))
        design_tokens = _as_dict(analysis.get("design_tokens"))
        plan, plan_events = await _plan_node_collaboration(
            phase="design",
            node_id=node_id,
            state=state,
            objective="Produce a differentiated design direction with operator trust, accessibility, and mobile resilience.",
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
        proposal_prompt = (
            "Design a high-quality product experience for the following product.\n"
            "Return a JSON object with keys: "
            "pattern_name, description, primary_color, accent_color, rationale, "
            "quality_focus, scores, and optional prototype_kind, navigation_style, density, "
            "screen_labels, interaction_principles.\n"
            "The scores object must include ux_quality, code_quality, performance, accessibility as 0-1 floats.\n"
            f"Current design theme anchor: {pattern_name} / {description}\n"
            f"Product spec: {spec}\n"
            f"Selected features: {selected_features}\n"
            f"Primary persona summary: {personas[:2]}\n"
            f"Design tokens: {design_tokens}\n"
            f"IA analysis: {_as_dict(analysis.get('ia_analysis'))}\n"
            f"Use cases: {_as_list(analysis.get('use_cases'))[:3]}\n"
            f"Job stories: {_as_list(analysis.get('job_stories'))[:2]}\n"
            f"Selected skills: {plan.get('selected_skills')}\n"
            f"Quality targets: {plan.get('quality_targets')}\n"
            f"Delegation plan: {plan.get('delegations')}\n"
            "Bias toward clarity, mobile resilience, accessibility, and differentiation. "
            "Treat this as a product prototype brief, not a marketing landing page. "
            "Prefer app shells, task flows, and operational screens over hero-led storytelling."
        )
        proposal, llm_events, _ = await _lifecycle_llm_json(
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
            preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
            purpose=f"lifecycle-design-{node_id}",
            static_instruction=(
                "You are a principal product designer improving a lifecycle artifact. "
                "Return JSON only and optimize for operator trust, visual clarity, accessibility, and strong differentiation."
            ),
            user_prompt=proposal_prompt,
        )
        critique_prompt = (
            "Critique and improve this design concept. Return JSON only with the same keys "
            "plus optional provider_note.\n"
            f"Original concept: {proposal or {'pattern_name': pattern_name, 'description': description}}\n"
            f"Selected features: {selected_features}\n"
            f"IA analysis: {_as_dict(analysis.get('ia_analysis'))}\n"
            "Raise the quality bar on hierarchy, contrast, responsiveness, decision support, and prototype fidelity. "
            "Avoid landing-page hero compositions."
        )
        refined, critique_events, _ = await _lifecycle_llm_json(
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
            preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
            purpose=f"lifecycle-design-{node_id}-critique",
            static_instruction=(
                "You are a design critic and reviser. Return JSON only. "
                "Strengthen weaknesses instead of restating the same concept."
            ),
            user_prompt=critique_prompt,
        )
        payload = refined or proposal
        if not isinstance(payload, dict):
            return handler(node_id, state)
        peer_feedback: list[dict[str, Any]] = []
        delegations: list[dict[str, Any]] = []
        for delegation in _as_list(plan.get("delegations"))[:2]:
            delegation_payload = _as_dict(delegation)
            delegated = await _delegate_to_lifecycle_peer(
                phase="design",
                node_id=node_id,
                peer_name=str(delegation_payload.get("peer", "")),
                skill_name=str(delegation_payload.get("skill", "")),
                artifact_payload=payload,
                reason=str(delegation_payload.get("reason", "")),
                quality_targets=[str(item) for item in _as_list(plan.get("quality_targets")) if str(item).strip()],
            )
            if delegated is None:
                continue
            delegations.append(delegated)
            feedback = _as_dict(delegated.get("feedback"))
            if feedback:
                peer_feedback.append(feedback)
        peer_recommendations = _dedupe_strings(
            [
                str(item)
                for feedback in peer_feedback
                for item in _as_list(_as_dict(feedback).get("recommendations"))
                if str(item).strip()
            ]
        )
        variant = _design_variant_payload(
            node_id=node_id,
            model_name=model_name,
            pattern_name=str(payload.get("pattern_name") or pattern_name),
            description=str(payload.get("description") or description),
            primary=_color_or(payload.get("primary_color"), primary),
            accent=_color_or(payload.get("accent_color"), accent),
            selected_features=selected_features,
            spec=spec,
            analysis=analysis,
            rationale=_dedupe_strings(
                [
                    str(payload.get("rationale") or description),
                    *[str(item.get("summary", "")) for item in peer_feedback if isinstance(item, dict)],
                ]
            )[0],
            quality_focus=_dedupe_strings(
                [str(item) for item in _as_list(payload.get("quality_focus")) if str(item).strip()] + peer_recommendations
            ),
            score_overrides=_as_dict(payload.get("scores")),
            provider_note=_dedupe_strings(
                [
                    str(payload.get("provider_note") or ""),
                    *[str(_as_dict(item).get("summary", "")) for item in peer_feedback if isinstance(item, dict)],
                ]
            )[0] if _dedupe_strings(
                [
                    str(payload.get("provider_note") or ""),
                    *[str(_as_dict(item).get("summary", "")) for item in peer_feedback if isinstance(item, dict)],
                ]
            ) else "",
            prototype_overrides=_prototype_overrides_from_payload(payload),
        )
        return NodeResult(
            state_patch={
                f"{node_id}_variant": variant,
                _skill_plan_state_key(node_id): plan,
                _delegation_state_key(node_id): delegations,
                _peer_feedback_state_key(node_id): peer_feedback,
            },
            artifacts=_artifacts(
                {"name": f"{node_id}-variant", "kind": "design", **variant},
                {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **plan},
                *[
                    {
                        "name": f"{node_id}-{str(item.get('peer', 'peer'))}-review",
                        "kind": "peer-review",
                        **_as_dict(item.get("feedback")),
                    }
                    for item in delegations
                ],
            ),
            llm_events=[*plan_events, *llm_events, *critique_events],
            metrics={"design_mode": "provider-backed-autonomous"},
        )

    return autonomous_handler if _provider_backed_lifecycle_available(provider_registry) else handler


def _design_evaluator_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    variants = [
        item
        for key, item in state.items()
        if key.endswith("_variant") and isinstance(item, dict)
    ]
    peer_feedback = [
        dict(item)
        for key, value in state.items()
        if key.endswith("_peer_feedback") and isinstance(value, list)
        for item in value
        if isinstance(item, dict)
    ]
    ordered = sorted(variants, key=lambda item: (-float(_as_dict(item).get("scores", {}).get("ux_quality", 0)), str(item.get("model", ""))))

    async def autonomous() -> NodeResult:
        plan, plan_events = await _plan_node_collaboration(
            phase="design",
            node_id=node_id,
            state=state,
            objective="Judge competing design concepts, integrate peer critique, and select the strongest baseline.",
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
        evaluation_prompt = (
            "Evaluate these design variants and rank them for product quality.\n"
            "Return JSON only with keys ranking, selected_design_id, score_adjustments, critique.\n"
            f"Variants: {ordered}\n"
            f"Peer feedback: {peer_feedback}\n"
            f"Selected skills: {plan.get('selected_skills')}\n"
            "score_adjustments must be an object keyed by variant id with optional ux_quality, code_quality, performance, accessibility overrides."
        )
        payload, llm_events, _ = await _lifecycle_llm_json(
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
            preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
            purpose="lifecycle-design-judge",
            static_instruction=(
                "You are a principal design judge. Return JSON only. "
                "Prefer variants that are differentiated, accessible, responsive, and clearly aligned with the selected product scope."
            ),
            user_prompt=evaluation_prompt,
        )
        if not isinstance(payload, dict):
            design_payload = {"variants": ordered}
            return NodeResult(
                state_patch={
                    "variants": ordered,
                    "design": design_payload,
                    "output": design_payload,
                    _skill_plan_state_key(node_id): plan,
                    _delegation_state_key(node_id): [],
                },
                artifacts=_artifacts(
                    {"name": "design-scorecard", "kind": "design", "variants": ordered},
                    {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **plan},
                ),
                metrics={"design_mode": "provider-backed-autonomous-fallback"},
                llm_events=[*plan_events, *llm_events],
            )
        ranking = [str(item) for item in _as_list(payload.get("ranking")) if str(item).strip()]
        by_id = {str(item.get("id", "")): dict(item) for item in ordered}
        adjusted: list[dict[str, Any]] = []
        for variant_id in ranking:
            variant = by_id.pop(variant_id, None)
            if variant is None:
                continue
            overrides = _as_dict(_as_dict(payload.get("score_adjustments")).get(variant_id))
            if overrides:
                variant_scores = dict(_as_dict(variant.get("scores")))
                for score_name, default in tuple(variant_scores.items()):
                    variant_scores[score_name] = _clamp_score(overrides.get(score_name), default=float(default))
                variant["scores"] = variant_scores
            adjusted.append(variant)
        adjusted.extend(by_id.values())
        adjusted = sorted(
            adjusted,
            key=lambda item: (-float(_as_dict(item).get("scores", {}).get("ux_quality", 0)), str(item.get("model", ""))),
        )
        selected_design_id = str(payload.get("selected_design_id") or adjusted[0].get("id", "") if adjusted else "")
        critique = [str(item) for item in _as_list(payload.get("critique")) if str(item).strip()]
        design_payload = {
            "variants": adjusted,
            "selected_design_id": selected_design_id,
            "critique": critique,
        }
        artifact_payload = {"name": "design-scorecard", "kind": "design", "variants": adjusted, "critique": critique}
        return NodeResult(
            state_patch={
                "variants": adjusted,
                "selected_design_id": selected_design_id,
                "design": design_payload,
                "output": design_payload,
                _skill_plan_state_key(node_id): plan,
                _delegation_state_key(node_id): [],
            },
            artifacts=_artifacts(
                artifact_payload,
                {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **plan},
            ),
            llm_events=[*plan_events, *llm_events],
            metrics={"design_mode": "provider-backed-autonomous"},
        )

    if _provider_backed_lifecycle_available(provider_registry):
        return autonomous()

    design_payload = {"variants": ordered}
    return NodeResult(
        state_patch={"variants": ordered, "design": design_payload, "output": design_payload},
        artifacts=_artifacts({"name": "design-scorecard", "kind": "design", "variants": ordered}),
        metrics={"design_mode": "deterministic-reference"},
    )


def _development_planner_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    selected_features = _selected_feature_names(state)
    workstreams = [
        {"agent": "frontend-builder", "focus": "UI shell and interaction layout", "skills": ["responsive-ui", "component-composition"]},
        {"agent": "backend-builder", "focus": "Domain model and data contract", "skills": ["api-design", "state-modeling"]},
    ]
    if state.get("milestones"):
        workstreams.append({"agent": "qa-engineer", "focus": "Milestone verification", "skills": ["acceptance-testing"]})
    plan = {
        "selected_features": selected_features,
        "workstreams": workstreams,
        "success_definition": "Selected design plus must-have features are visible in a release-reviewable build artifact.",
    }
    if _provider_backed_lifecycle_available(provider_registry):
        async def autonomous() -> NodeResult:
            collaboration_plan, plan_events = await _plan_node_collaboration(
                phase="development",
                node_id=node_id,
                state=state,
                objective="Route implementation work to the smallest high-leverage skill set and identify where peer review should be delegated.",
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            )
            payload, llm_events, _ = await _lifecycle_llm_json(
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
                preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
                purpose="lifecycle-development-plan",
                static_instruction=(
                    "You are an autonomous build planner. Return JSON only. "
                    "Create a concise but high-quality implementation plan grounded in the provided design and milestones."
                ),
                user_prompt=(
                    "Return JSON with keys selected_features, workstreams, success_definition.\n"
                    f"Spec: {state.get('spec')}\n"
                    f"Selected features: {selected_features}\n"
                    f"Milestones: {state.get('milestones')}\n"
                    f"Selected design: {state.get('selected_design') or state.get('design')}\n"
                    f"Skill plan: {collaboration_plan}\n"
                ),
            )
            if not isinstance(payload, dict):
                return NodeResult(
                    state_patch={
                        "implementation_plan": plan,
                        _skill_plan_state_key(node_id): collaboration_plan,
                        _delegation_state_key(node_id): [],
                    },
                    artifacts=_artifacts(
                        {"name": "implementation-plan", "kind": "development", **plan},
                        {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **collaboration_plan},
                    ),
                    metrics={"development_mode": "provider-backed-fallback"},
                    llm_events=[*plan_events, *llm_events],
                )
            llm_plan = {
                "selected_features": [str(item) for item in _as_list(payload.get("selected_features")) if str(item).strip()] or selected_features,
                "workstreams": [dict(item) for item in _as_list(payload.get("workstreams")) if isinstance(item, dict)] or workstreams,
                "success_definition": str(payload.get("success_definition") or plan["success_definition"]),
            }
            return NodeResult(
                state_patch={
                    "implementation_plan": llm_plan,
                    _skill_plan_state_key(node_id): collaboration_plan,
                    _delegation_state_key(node_id): [],
                },
                artifacts=_artifacts(
                    {"name": "implementation-plan", "kind": "development", **llm_plan},
                    {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **collaboration_plan},
                ),
                metrics={"development_mode": "provider-backed-autonomous"},
                llm_events=[*plan_events, *llm_events],
            )

        return autonomous()
    return NodeResult(
        state_patch={
            "implementation_plan": plan,
            _skill_plan_state_key(node_id): {
                "phase": "development",
                "node_id": node_id,
                "agent_label": "Build Planner",
                "objective": "Break delivery into the highest-leverage workstreams.",
                "candidate_skills": ["task-routing", "implementation-planning"],
                "selected_skills": ["task-routing", "implementation-planning"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [],
                "mode": "deterministic-reference",
                "execution_note": "Route work first, delegate review later.",
            },
            _delegation_state_key(node_id): [],
        },
        artifacts=_artifacts({"name": "implementation-plan", "kind": "development", **plan}),
    )


def _development_frontend_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    selected_features = _selected_feature_names(state)
    analysis = _as_dict(state.get("analysis"))
    selected_design = _as_dict(state.get("selected_design")) or _selected_design_from_state(state)
    prototype = _as_dict(selected_design.get("prototype")) or _build_design_prototype(
        spec=str(state.get("spec", "")),
        analysis=analysis,
        selected_features=selected_features,
        pattern_name=str(selected_design.get("pattern_name") or "Prototype baseline"),
        description=str(selected_design.get("description") or "Build-ready product prototype"),
    )
    prototype_screens = [dict(item) for item in _as_list(prototype.get("screens")) if isinstance(item, dict)]
    sections = [
        str(screen.get("id") or f"screen-{index + 1}")
        for index, screen in enumerate(prototype_screens[:4])
        if str(screen.get("id") or "").strip()
    ] or [
        "workspace",
        "workflow-map",
        "readiness-rail",
    ]
    cards = _dedupe_strings(
        [str(screen.get("title") or screen.get("headline") or "") for screen in prototype_screens[:4]]
        + selected_features
    ) or ["Primary workspace", "Key flow", "Readiness rail"]
    interaction_notes = [
        str(item) for item in _as_list(prototype.get("interaction_principles")) if str(item).strip()
    ][:4]
    payload = {
        "sections": sections,
        "feature_cards": cards,
        "css_tokens": {
            "radius": "18px",
            "shadow": "0 20px 60px rgba(15,23,42,0.12)",
            "layout": str(_as_dict(prototype.get("app_shell")).get("layout") or "sidebar"),
        },
        "interaction_notes": interaction_notes,
    }
    if _provider_backed_lifecycle_available(provider_registry):
        async def autonomous() -> NodeResult:
            collaboration_plan, plan_events = await _plan_node_collaboration(
                phase="development",
                node_id=node_id,
                state=state,
                objective="Choose the skills that will maximize differentiated, accessible, mobile-safe UI execution.",
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            )
            llm_payload, llm_events, _ = await _lifecycle_llm_json(
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
                preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
                purpose="lifecycle-development-frontend-plan",
                static_instruction=(
                    "You are a principal frontend architect. Return JSON only. "
                    "Produce a UI composition plan that is differentiated, accessible, and mobile-safe."
                ),
                user_prompt=(
                    "Return JSON with keys sections, feature_cards, css_tokens, interaction_notes.\n"
                    f"Spec: {state.get('spec')}\n"
                    f"Selected features: {selected_features}\n"
                    f"Design prototype: {prototype}\n"
                    f"Design context: {state.get('selected_design') or state.get('design')}\n"
                    f"Skill plan: {collaboration_plan}\n"
                    "Bias toward application/workspace surfaces. Do not collapse the layout into a landing page."
                ),
            )
            if not isinstance(llm_payload, dict):
                return NodeResult(
                    state_patch={
                        "frontend_bundle": payload,
                        _skill_plan_state_key(node_id): collaboration_plan,
                        _delegation_state_key(node_id): [],
                    },
                    llm_events=[*plan_events, *llm_events],
                    metrics={"frontend_mode": "provider-backed-fallback"},
                )
            llm_bundle = {
                "sections": [str(item) for item in _as_list(llm_payload.get("sections")) if str(item).strip()] or sections,
                "feature_cards": [str(item) for item in _as_list(llm_payload.get("feature_cards")) if str(item).strip()] or cards,
                "css_tokens": _as_dict(llm_payload.get("css_tokens")) or payload["css_tokens"],
                "interaction_notes": [str(item) for item in _as_list(llm_payload.get("interaction_notes")) if str(item).strip()],
            }
            return NodeResult(
                state_patch={
                    "frontend_bundle": llm_bundle,
                    _skill_plan_state_key(node_id): collaboration_plan,
                    _delegation_state_key(node_id): [],
                },
                llm_events=[*plan_events, *llm_events],
                metrics={"frontend_mode": "provider-backed-autonomous"},
            )

        return autonomous()
    return NodeResult(
        state_patch={
            "frontend_bundle": payload,
            _skill_plan_state_key(node_id): {
                "phase": "development",
                "node_id": node_id,
                "agent_label": "Frontend Builder",
                "objective": "Translate the selected design into a resilient UI composition.",
                "candidate_skills": ["frontend-implementation", "responsive-ui"],
                "selected_skills": ["frontend-implementation", "responsive-ui"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [],
                "mode": "deterministic-reference",
                "execution_note": "Favor responsive structure and clear operator hierarchy.",
            },
            _delegation_state_key(node_id): [],
        }
    )


def _development_backend_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    selected_features = _selected_feature_names(state)
    payload = {
        "entities": [
            {"name": "LifecycleProject", "fields": ["phaseStatuses", "artifacts", "releases", "feedbackItems"]},
            {"name": "PhaseArtifact", "fields": ["phase", "kind", "summary", "createdAt"]},
        ],
        "automation_notes": [
            "Persist project record as control-plane surface record.",
            "Derive release gates from build artifact checks.",
        ],
        "exposed_capabilities": selected_features,
    }
    if _provider_backed_lifecycle_available(provider_registry):
        async def autonomous() -> NodeResult:
            collaboration_plan, plan_events = await _plan_node_collaboration(
                phase="development",
                node_id=node_id,
                state=state,
                objective="Choose the backend/domain skills that keep the implementation durable and operable.",
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            )
            llm_payload, llm_events, _ = await _lifecycle_llm_json(
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
                preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
                purpose="lifecycle-development-backend-plan",
                static_instruction=(
                    "You are a principal backend architect. Return JSON only. "
                    "Design a durable domain model and execution contract for the requested product."
                ),
                user_prompt=(
                    "Return JSON with keys entities, automation_notes, exposed_capabilities, api_endpoints.\n"
                    f"Spec: {state.get('spec')}\n"
                    f"Selected features: {selected_features}\n"
                    f"Milestones: {state.get('milestones')}\n"
                    f"Skill plan: {collaboration_plan}\n"
                ),
            )
            if not isinstance(llm_payload, dict):
                return NodeResult(
                    state_patch={
                        "backend_bundle": payload,
                        _skill_plan_state_key(node_id): collaboration_plan,
                        _delegation_state_key(node_id): [],
                    },
                    llm_events=[*plan_events, *llm_events],
                    metrics={"backend_mode": "provider-backed-fallback"},
                )
            llm_bundle = {
                "entities": [dict(item) for item in _as_list(llm_payload.get("entities")) if isinstance(item, dict)] or payload["entities"],
                "automation_notes": [str(item) for item in _as_list(llm_payload.get("automation_notes")) if str(item).strip()] or payload["automation_notes"],
                "exposed_capabilities": [str(item) for item in _as_list(llm_payload.get("exposed_capabilities")) if str(item).strip()] or selected_features,
                "api_endpoints": [dict(item) for item in _as_list(llm_payload.get("api_endpoints")) if isinstance(item, dict)],
            }
            return NodeResult(
                state_patch={
                    "backend_bundle": llm_bundle,
                    _skill_plan_state_key(node_id): collaboration_plan,
                    _delegation_state_key(node_id): [],
                },
                llm_events=[*plan_events, *llm_events],
                metrics={"backend_mode": "provider-backed-autonomous"},
            )

        return autonomous()
    return NodeResult(
        state_patch={
            "backend_bundle": payload,
            _skill_plan_state_key(node_id): {
                "phase": "development",
                "node_id": node_id,
                "agent_label": "Backend Builder",
                "objective": "Model a durable backend contract for lifecycle delivery.",
                "candidate_skills": ["api-design", "domain-modeling"],
                "selected_skills": ["api-design", "domain-modeling"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [],
                "mode": "deterministic-reference",
                "execution_note": "Prioritize durable entities and a truthful API contract.",
            },
            _delegation_state_key(node_id): [],
        }
    )


def _development_integrator_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    analysis = _as_dict(state.get("analysis"))
    selected_design = _as_dict(state.get("selected_design")) or _selected_design_from_state(state)
    selected_features = _selected_feature_names(state)
    prototype = _as_dict(selected_design.get("prototype")) or _build_design_prototype(
        spec=str(state.get("spec", "")),
        analysis=analysis,
        selected_features=selected_features,
        pattern_name=str(selected_design.get("pattern_name") or "Integrated prototype"),
        description=str(selected_design.get("description") or "Integrated build artifact"),
    )
    design_tokens = _as_dict(analysis.get("design_tokens"))
    primary_color = _color_or(selected_design.get("primary_color"), _color_or(_as_dict(design_tokens.get("colors")).get("primary"), "#0f172a"))
    accent_color = _color_or(selected_design.get("accent_color"), _color_or(_as_dict(design_tokens.get("colors")).get("cta"), "#10b981"))
    feature_cards = _as_dict(state.get("frontend_bundle")).get("feature_cards", [])
    frontend_sections = _as_dict(state.get("frontend_bundle")).get("sections", [])
    interaction_notes = [str(item) for item in _as_list(_as_dict(state.get("frontend_bundle")).get("interaction_notes")) if str(item).strip()]
    backend_entities = _as_dict(state.get("backend_bundle")).get("entities", [])
    code = _build_preview_html(
        title=_preview_title(str(state.get("spec", ""))),
        subtitle=str(selected_design.get("description") or "Integrated build artifact aligned to the selected prototype."),
        primary=primary_color,
        accent=accent_color,
        features=[str(item) for item in feature_cards if isinstance(item, str)] or selected_features,
        prototype=prototype,
        design_tokens=design_tokens,
        backend_entities=[dict(item) for item in backend_entities if isinstance(item, dict)],
        milestones=[dict(item) for item in state.get("milestones", []) if isinstance(item, dict)],
        interaction_notes=interaction_notes,
        section_focus=[str(item) for item in frontend_sections if str(item).strip()],
        mode="build",
    )
    payload = {
        "code": code,
        "build_sections": frontend_sections or [str(screen.get("id") or "") for screen in _as_list(prototype.get("screens")) if isinstance(screen, dict)],
        "prototype": prototype,
    }
    if _provider_backed_lifecycle_available(provider_registry):
        async def autonomous() -> NodeResult:
            collaboration_plan, plan_events = await _plan_node_collaboration(
                phase="development",
                node_id=node_id,
                state=state,
                objective="Assemble a single-file build artifact that is coherent, accessible, and reviewable.",
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            )
            llm_payload, llm_events, _ = await _lifecycle_llm_json(
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
                preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
                purpose="lifecycle-development-integrate",
                static_instruction=(
                    "You are an autonomous product engineer. Return JSON only. "
                    "Produce a single-file HTML app with embedded CSS and JS, strong accessibility, responsive behavior, "
                    "and product-prototype fidelity."
                ),
                user_prompt=(
                    "Return JSON with keys code, build_sections, implementation_notes.\n"
                    f"Spec: {state.get('spec')}\n"
                    f"Selected design: {selected_design}\n"
                    f"Prototype blueprint: {prototype}\n"
                    f"Frontend bundle: {_as_dict(state.get('frontend_bundle'))}\n"
                    f"Backend bundle: {_as_dict(state.get('backend_bundle'))}\n"
                    f"Milestones: {state.get('milestones')}\n"
                    f"Skill plan: {collaboration_plan}\n"
                    "The code must be previewable HTML, include <main>, aria labels for primary actions, "
                    "a viewport meta tag, real application navigation, and multiple prototype screen surfaces. "
                    "Do not return a landing page or hero-only layout."
                ),
            )
            llm_code = str(_as_dict(llm_payload).get("code") or "")
            llm_sections = [str(item) for item in _as_list(_as_dict(llm_payload).get("build_sections")) if str(item).strip()] or frontend_sections
            integrated_code = llm_code if _looks_like_prototype_html(llm_code) else code
            integrated_payload = {"code": integrated_code, "build_sections": llm_sections, "prototype": prototype}
            return NodeResult(
                state_patch={
                    "integrated_build": integrated_payload,
                    "code": integrated_code,
                    _skill_plan_state_key(node_id): collaboration_plan,
                    _delegation_state_key(node_id): [],
                },
                artifacts=_artifacts({"name": "build-artifact", "kind": "development", "code_bytes": len(integrated_code.encode('utf-8'))}),
                llm_events=[*plan_events, *llm_events],
                metrics={"integrator_mode": "provider-backed-autonomous" if integrated_code == llm_code else "provider-backed-fallback"},
            )

        return autonomous()
    return NodeResult(
        state_patch={
            "integrated_build": payload,
            "code": code,
            _skill_plan_state_key(node_id): {
                "phase": "development",
                "node_id": node_id,
                "agent_label": "Integrator",
                "objective": "Assemble a previewable and reviewable artifact.",
                "candidate_skills": ["integration", "artifact-assembly"],
                "selected_skills": ["integration", "artifact-assembly"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [],
                "mode": "deterministic-reference",
                "execution_note": "Integrate frontend and backend outputs into one coherent artifact.",
            },
            _delegation_state_key(node_id): [],
        },
        artifacts=_artifacts({"name": "build-artifact", "kind": "development", "code_bytes": len(code.encode('utf-8'))}),
    )


def _development_qa_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    build = _as_dict(state.get("integrated_build"))
    code = str(build.get("code", ""))
    milestones = []
    for raw in state.get("milestones", []) or []:
        if not isinstance(raw, dict):
            continue
        criteria = str(raw.get("criteria", ""))
        score = _milestone_score(criteria, code)
        milestones.append(
            {
                "id": str(raw.get("id", "")),
                "name": str(raw.get("name", "")),
                "status": "satisfied" if score >= 0.6 else "not_satisfied",
                "reason": "Build contains the required structural signals." if score >= 0.6 else "Criteria is only partially represented in the current build artifact.",
            }
        )
    if not milestones:
        milestones.append(
            {
                "id": "alpha-default",
                "name": "Alpha readiness",
                "status": "satisfied" if "<html" in code.lower() else "not_satisfied",
                "reason": "Generated build is previewable and structurally complete." if "<html" in code.lower() else "No previewable build artifact was generated.",
            }
        )
    return NodeResult(
        state_patch={
            "qa_report": {"milestone_results": milestones},
            _skill_plan_state_key(node_id): {
                "phase": "development",
                "node_id": node_id,
                "agent_label": "QA Engineer",
                "objective": "Validate milestone and acceptance readiness.",
                "candidate_skills": ["acceptance-testing", "quality-assurance"],
                "selected_skills": ["acceptance-testing", "quality-assurance"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [],
                "mode": "deterministic-reference",
                "execution_note": "Convert milestone criteria into explicit acceptance checks.",
            },
            _delegation_state_key(node_id): [],
        }
    )


def _development_security_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    code = str(_as_dict(state.get("integrated_build")).get("code", ""))
    findings = []
    if "eval(" in code:
        findings.append("Avoid eval() in generated artifacts.")
    if "innerHTML =" in code:
        findings.append("Prefer DOM-safe rendering over innerHTML assignment.")
    if not findings:
        findings.append("No obvious unsafe DOM execution pattern was detected.")
    status = "pass" if len(findings) == 1 and findings[0].startswith("No obvious") else "warning"

    async def autonomous() -> NodeResult:
        collaboration_plan, plan_events = await _plan_node_collaboration(
            phase="development",
            node_id=node_id,
            state=state,
            objective="Escalate security and safe-autonomy review to the right peer when it materially improves release confidence.",
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
        delegations: list[dict[str, Any]] = []
        peer_feedback: list[dict[str, Any]] = []
        for delegation in _as_list(collaboration_plan.get("delegations"))[:2]:
            delegated = await _delegate_to_lifecycle_peer(
                phase="development",
                node_id=node_id,
                peer_name=str(_as_dict(delegation).get("peer", "")),
                skill_name=str(_as_dict(delegation).get("skill", "")),
                artifact_payload={"code": code},
                reason=str(_as_dict(delegation).get("reason", "")),
                quality_targets=[str(item) for item in _as_list(collaboration_plan.get("quality_targets")) if str(item).strip()],
            )
            if delegated is None:
                continue
            delegations.append(delegated)
            feedback = _as_dict(delegated.get("feedback"))
            if feedback:
                peer_feedback.append(feedback)
        merged_findings = _dedupe_strings(
            findings + [
                str(item)
                for feedback in peer_feedback
                for item in _as_list(_as_dict(feedback).get("blockers")) + _as_list(_as_dict(feedback).get("recommendations"))
                if str(item).strip()
            ]
        )
        security_report = {
            "status": "pass" if not [item for item in merged_findings if "Avoid " in item or "Remove " in item] else "warning",
            "findings": merged_findings or findings,
        }
        return NodeResult(
            state_patch={
                "security_report": security_report,
                _skill_plan_state_key(node_id): collaboration_plan,
                _delegation_state_key(node_id): delegations,
                _peer_feedback_state_key(node_id): peer_feedback,
            },
            artifacts=_artifacts(
                {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **collaboration_plan},
                *[
                    {
                        "name": f"{node_id}-{str(item.get('peer', 'peer'))}-review",
                        "kind": "peer-review",
                        **_as_dict(item.get("feedback")),
                    }
                    for item in delegations
                ],
            ),
            llm_events=plan_events,
            metrics={"security_mode": "provider-backed-autonomous" if delegations else "provider-backed-fallback"},
        )

    if _provider_backed_lifecycle_available(provider_registry):
        return autonomous()
    return NodeResult(
        state_patch={
            "security_report": {"status": status, "findings": findings},
            _skill_plan_state_key(node_id): {
                "phase": "development",
                "node_id": node_id,
                "agent_label": "Security Reviewer",
                "objective": "Protect the release from obvious safety and security regressions.",
                "candidate_skills": ["security-review", "safety-review"],
                "selected_skills": ["security-review", "safety-review"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [{"peer": "safety-guardian", "skill": "security-review", "reason": "Escalate security posture when external scrutiny is useful."}],
                "mode": "deterministic-reference",
                "execution_note": "Check unsafe DOM patterns before release.",
            },
            _delegation_state_key(node_id): [],
        }
    )


def _development_reviewer_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    build = _as_dict(state.get("integrated_build"))
    qa_report = _as_dict(state.get("qa_report"))
    security_report = _as_dict(state.get("security_report"))
    initial_code = str(build.get("code", ""))
    build_sections = [str(item) for item in _as_list(build.get("build_sections")) if str(item).strip()]

    def finalize(
        *,
        code: str,
        snapshot: dict[str, Any],
        iteration_count: int,
        llm_events: list[dict[str, Any]] | None = None,
        critique_history: list[dict[str, Any]] | None = None,
        collaboration_plan: dict[str, Any] | None = None,
        delegations: list[dict[str, Any]] | None = None,
        peer_feedback: list[dict[str, Any]] | None = None,
        mode: str,
    ) -> NodeResult:
        llm_event_log = list(llm_events or [])
        plan = dict(collaboration_plan or {})
        delegation_records = list(delegations or [])
        peer_reviews = list(peer_feedback or [])
        review_milestones = [dict(item) for item in _as_list(snapshot.get("milestone_results"))]
        review_security = _as_dict(snapshot.get("security_report"))
        estimated_cost = round(
            0.9
            + len(_selected_feature_names(state)) * 0.08
            + len(review_milestones) * 0.04
            + sum(float(_as_dict(item).get("estimated_cost_usd", 0.0) or 0.0) for item in llm_event_log),
            3,
        )
        development = {
            "code": code,
            "milestone_results": review_milestones,
            "review_summary": {
                "milestonesSatisfied": int(snapshot.get("milestones_satisfied", 0) or 0),
                "milestonesTotal": int(snapshot.get("milestones_total", len(review_milestones)) or len(review_milestones)),
                "securityStatus": str(review_security.get("status", "pass") or "pass"),
                "blockerCount": len(_as_list(snapshot.get("blockers"))),
            },
        }
        if critique_history:
            development["critique_history"] = critique_history
        if peer_reviews:
            development["peer_feedback"] = peer_reviews
        integrated_build = dict(build)
        integrated_build["code"] = code
        if build_sections:
            integrated_build["build_sections"] = build_sections
        artifact_payload = {"name": "milestone-report", "kind": "development", **development}
        return NodeResult(
            state_patch={
                "integrated_build": integrated_build,
                "code": code,
                "qa_report": {"milestone_results": review_milestones},
                "security_report": review_security,
                "development": development,
                "review": development,
                "_build_iteration": iteration_count,
                "estimated_cost_usd": estimated_cost,
                "output": development,
                _skill_plan_state_key(node_id): plan,
                _delegation_state_key(node_id): delegation_records,
                _peer_feedback_state_key(node_id): peer_reviews,
            },
            artifacts=_artifacts(
                artifact_payload,
                *([{"name": f"{node_id}-skill-plan", "kind": "skill-plan", **plan}] if plan else []),
                *[
                    {
                        "name": f"{node_id}-{str(item.get('peer', 'peer'))}-review",
                        "kind": "peer-review",
                        **_as_dict(item.get("feedback")),
                    }
                    for item in delegation_records
                ],
            ),
            llm_events=llm_event_log,
            metrics={"review_mode": mode},
        )

    baseline_snapshot = _development_quality_snapshot(state, code=initial_code)
    if qa_report.get("milestone_results"):
        baseline_snapshot["milestone_results"] = list(qa_report.get("milestone_results", []))
        baseline_snapshot["milestones_satisfied"] = sum(
            1 for item in baseline_snapshot["milestone_results"] if _as_dict(item).get("status") == "satisfied"
        )
        baseline_snapshot["milestones_total"] = len(baseline_snapshot["milestone_results"])
    if security_report:
        baseline_snapshot["security_report"] = security_report
        if security_report.get("status") == "pass":
            baseline_snapshot["blockers"] = [
                item
                for item in _as_list(baseline_snapshot.get("blockers"))
                if isinstance(item, str) and item not in _as_list(security_report.get("findings"))
            ]
    if not _provider_backed_lifecycle_available(provider_registry):
        return finalize(
            code=initial_code,
            snapshot=baseline_snapshot,
            iteration_count=1 if int(baseline_snapshot.get("milestones_satisfied", 0) or 0) == int(baseline_snapshot.get("milestones_total", 0) or 0) else 2,
            collaboration_plan={
                "phase": "development",
                "node_id": node_id,
                "agent_label": "Release Reviewer",
                "objective": "Judge release readiness and push the build over the quality bar.",
                "candidate_skills": ["code-review", "delivery-review"],
                "selected_skills": ["code-review", "delivery-review"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [],
                "mode": "deterministic-reference",
                "execution_note": "Review the integrated build against milestones and release quality gates.",
            },
            mode="deterministic-reference",
        )

    async def autonomous() -> NodeResult:
        collaboration_plan, plan_events = await _plan_node_collaboration(
            phase="development",
            node_id=node_id,
            state=state,
            objective="Use the minimum skill set and the right peers to raise release quality before final approval.",
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
        current_code = initial_code
        snapshot = baseline_snapshot
        critique_history: list[dict[str, Any]] = []
        llm_events: list[dict[str, Any]] = list(plan_events)
        delegations: list[dict[str, Any]] = []
        peer_feedback: list[dict[str, Any]] = []
        iteration_count = 1
        max_iterations = 3
        for delegation in _as_list(collaboration_plan.get("delegations"))[:2]:
            delegated = await _delegate_to_lifecycle_peer(
                phase="development",
                node_id=node_id,
                peer_name=str(_as_dict(delegation).get("peer", "")),
                skill_name=str(_as_dict(delegation).get("skill", "")),
                artifact_payload={"code": current_code},
                reason=str(_as_dict(delegation).get("reason", "")),
                quality_targets=[str(item) for item in _as_list(collaboration_plan.get("quality_targets")) if str(item).strip()],
            )
            if delegated is None:
                continue
            delegations.append(delegated)
            feedback = _as_dict(delegated.get("feedback"))
            if feedback:
                peer_feedback.append(feedback)
        peer_blockers = [
            str(item)
            for feedback in peer_feedback
            for item in _as_list(_as_dict(feedback).get("blockers"))
            if str(item).strip()
        ]
        if peer_blockers:
            snapshot = dict(snapshot)
            snapshot["blockers"] = _dedupe_strings(
                [str(item) for item in _as_list(snapshot.get("blockers")) if str(item).strip()] + peer_blockers
            )
        while _as_list(snapshot.get("blockers")) and iteration_count <= max_iterations:
            blockers = [str(item) for item in _as_list(snapshot.get("blockers")) if str(item).strip()]
            payload, events, _ = await _lifecycle_llm_json(
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
                preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
                purpose=f"lifecycle-development-review-{iteration_count}",
                static_instruction=(
                    "You are an autonomous reviewer and reviser for a production-bound single-file app. "
                    "Return JSON only. Improve the build instead of summarizing it. "
                    "Always preserve a complete previewable HTML document with embedded CSS and JS."
                ),
                user_prompt=(
                    "Return JSON with keys code, revision_summary, resolved_blockers, remaining_risks.\n"
                    f"Spec: {state.get('spec')}\n"
                    f"Selected features: {_selected_feature_names(state)}\n"
                    f"Milestones: {state.get('milestones')}\n"
                    f"Current quality snapshot: {snapshot}\n"
                    f"Peer feedback: {peer_feedback}\n"
                    f"Skill plan: {collaboration_plan}\n"
                    f"Current blockers: {blockers}\n"
                    "Revise the current HTML so the blockers are addressed while improving accessibility, responsive behavior, and clarity.\n"
                    f"Current HTML:\n{current_code}"
                ),
            )
            llm_events.extend(events)
            if not isinstance(payload, dict):
                break
            revised_code = str(payload.get("code") or "")
            critique_history.append(
                {
                    "iteration": iteration_count,
                    "blockers": blockers,
                    "revision_summary": str(payload.get("revision_summary") or "No revision summary returned."),
                    "resolved_blockers": [
                        str(item) for item in _as_list(payload.get("resolved_blockers")) if str(item).strip()
                    ],
                    "remaining_risks": [
                        str(item) for item in _as_list(payload.get("remaining_risks")) if str(item).strip()
                    ],
                }
            )
            if "<html" not in revised_code.lower() or "<main" not in revised_code.lower():
                break
            if revised_code.strip() == current_code.strip():
                break
            current_code = revised_code
            snapshot = _development_quality_snapshot(state, code=current_code)
            iteration_count += 1

        mode = "provider-backed-autonomous" if critique_history else "provider-backed-fallback"
        return finalize(
            code=current_code,
            snapshot=snapshot,
            iteration_count=iteration_count,
            llm_events=llm_events,
            critique_history=critique_history,
            collaboration_plan=collaboration_plan,
            delegations=delegations,
            peer_feedback=peer_feedback,
            mode=mode,
        )

    return autonomous()


def _segment_from_spec(spec: str) -> str:
    if _contains_any(spec, "enterprise", "B2B", "業務", "運用"):
        return "B2B"
    if _contains_any(spec, "consumer", "toC", "ユーザー向け", "モバイル"):
        return "B2C"
    return "Product"


def _market_trends(spec: str) -> list[str]:
    trends = [
        "意思決定の根拠を artifact として残す要求が高まっている",
        "単体 AI から orchestrated workflow への移行が進んでいる",
    ]
    if _contains_any(spec, "approval", "承認", "safety", "安全"):
        trends.append("ガバナンス付き自律実行への関心が強い")
    if _contains_any(spec, "dashboard", "運用", "studio"):
        trends.append("operator UI の品質が採用可否を左右する")
    return trends


def _market_size_from_spec(spec: str, keywords: list[str]) -> str:
    if _contains_any(spec, "enterprise", "B2B", "workflow", "platform"):
        return "Mid-market to enterprise orchestration spend with expanding platform budgets"
    if len(keywords) > 8:
        return "Cross-functional delivery tooling budget with clear consolidation pressure"
    return "Early but expanding workflow productivity segment"


def _build_plan_estimates(state: dict[str, Any]) -> list[dict[str, Any]]:
    feature_count = len(list(state.get("feature_selections", [])))
    base_effort = max(feature_count, 4) * 10
    presets = [
        ("minimal", "Minimal", 0.7, 0.6, ["planner", "frontend-builder", "reviewer"], ["feature-prioritization", "responsive-ui"]),
        ("standard", "Standard", 1.0, 1.0, ["planner", "frontend-builder", "backend-builder", "reviewer"], ["feature-prioritization", "responsive-ui", "api-design"]),
        ("full", "Full", 1.35, 1.4, ["planner", "frontend-builder", "backend-builder", "qa-engineer", "security-reviewer", "reviewer"], ["feature-prioritization", "responsive-ui", "api-design", "quality-assurance", "security-review"]),
    ]
    estimates: list[dict[str, Any]] = []
    for preset, label, effort_factor, cost_factor, agents, skills in presets:
        effort = math.ceil(base_effort * effort_factor)
        duration_weeks = max(1, math.ceil(effort / 32))
        estimates.append(
            {
                "preset": preset,
                "label": label,
                "description": f"{label} scope for the selected lifecycle features",
                "total_effort_hours": effort,
                "total_cost_usd": round(2800 * cost_factor + feature_count * 180, 2),
                "duration_weeks": duration_weeks,
                "epics": [
                    {
                        "id": f"epic-{preset}-foundation",
                        "name": "Lifecycle foundation",
                        "description": "Backend record, phase flow, and operator UI alignment",
                        "use_cases": ["uc-lifecycle-001"],
                        "priority": "must",
                        "stories": ["0", "1"],
                    }
                ],
                "wbs": [
                    {
                        "id": f"wbs-{preset}-01",
                        "epic_id": f"epic-{preset}-foundation",
                        "title": "Model lifecycle state in the control plane",
                        "description": "Persist phase state, artifacts, releases, and feedback.",
                        "assignee_type": "agent",
                        "assignee": "planner",
                        "skills": ["solution-architecture"],
                        "depends_on": [],
                        "effort_hours": max(6, effort // 4),
                        "start_day": 0,
                        "duration_days": max(2, duration_weeks * 2),
                        "status": "pending",
                    }
                ],
                "agents_used": agents,
                "skills_used": skills,
            }
        )
    return estimates


def _selected_design_from_state(state: dict[str, Any]) -> dict[str, Any]:
    design_input = state.get("design")
    if isinstance(design_input, dict):
        return dict(design_input)
    variants = state.get("designVariants", [])
    selected_id = state.get("selectedDesignId")
    if isinstance(variants, list) and selected_id:
        for variant in variants:
            if isinstance(variant, dict) and variant.get("id") == selected_id:
                return dict(variant)
    return {}


def _build_preview_html(
    *,
    title: str,
    subtitle: str,
    primary: str,
    accent: str,
    features: list[str],
    prototype: dict[str, Any] | None = None,
    design_tokens: dict[str, Any] | None = None,
    backend_entities: list[dict[str, Any]] | None = None,
    milestones: list[dict[str, Any]] | None = None,
    interaction_notes: list[str] | None = None,
    section_focus: list[str] | None = None,
    mode: str = "design",
) -> str:
    prototype_payload = _as_dict(prototype)
    design_tokens_payload = _as_dict(design_tokens)
    shell = _as_dict(prototype_payload.get("app_shell"))
    screens = [dict(item) for item in _as_list(prototype_payload.get("screens")) if isinstance(item, dict)]
    flows = [dict(item) for item in _as_list(prototype_payload.get("flows")) if isinstance(item, dict)]
    primary_navigation = [dict(item) for item in _as_list(shell.get("primary_navigation")) if isinstance(item, dict)]
    status_badges = [str(item) for item in _as_list(shell.get("status_badges")) if str(item).strip()] or features[:3]
    focus_ids = {str(item).strip() for item in _as_list(section_focus) if str(item).strip()}
    if focus_ids:
        ordered = [screen for screen in screens if str(screen.get("id")) in focus_ids]
        screens = ordered or screens
    active_screen = screens[0] if screens else {}
    active_modules = [dict(item) for item in _as_list(_as_dict(active_screen).get("modules")) if isinstance(item, dict)]
    interaction_principles = [
        str(item) for item in _as_list(prototype_payload.get("interaction_principles")) if str(item).strip()
    ]
    if interaction_notes:
        interaction_principles = _dedupe_strings(interaction_principles + [str(item) for item in interaction_notes if str(item).strip()])
    backend_modules = [dict(item) for item in _as_list(backend_entities) if isinstance(item, dict)]
    milestone_payload = [dict(item) for item in _as_list(milestones) if isinstance(item, dict)]
    body_font = str(_as_dict(design_tokens_payload.get("typography")).get("body") or "Noto Sans JP")
    heading_font = str(_as_dict(design_tokens_payload.get("typography")).get("heading") or "IBM Plex Sans")
    background = str(_as_dict(design_tokens_payload.get("colors")).get("background") or "#f8fafc")
    prototype_kind = str(prototype_payload.get("kind") or "product-workspace")
    shell_layout = str(shell.get("layout") or "sidebar")
    density = str(shell.get("density") or "medium")

    nav_items_html = "".join(
        f'<li><a href="#{escape(str(item.get("id") or "screen"))}">{escape(str(item.get("label") or "Section"))}</a></li>'
        for item in primary_navigation[:6]
    )
    badge_html = "".join(
        f"<span class='status-badge'>{escape(item)}</span>"
        for item in status_badges[:4]
    )
    action_html = "".join(
        f'<button type="button" aria-label="{escape(str(action))}">{escape(str(action))}</button>'
        for action in _as_list(_as_dict(active_screen).get("primary_actions"))[:3]
        if str(action).strip()
    )
    active_module_html = "".join(
        (
            "<article class='module-card'>"
            f"<p class='module-type'>{escape(str(module.get('type') or 'panel'))}</p>"
            f"<h3>{escape(str(module.get('name') or 'Module'))}</h3>"
            f"<ul>{''.join(f'<li>{escape(str(item))}</li>' for item in _as_list(module.get('items'))[:4] if str(item).strip())}</ul>"
            "</article>"
        )
        for module in active_modules[:4]
    )
    screen_gallery_html = "".join(
        (
            f'<article class="screen-frame" id="{escape(str(screen.get("id") or "screen"))}" data-screen-id="{escape(str(screen.get("id") or "screen"))}">'
            '<div class="screen-topbar">'
            f"<span>{escape(str(screen.get('title') or 'Screen'))}</span>"
            f"<span>{escape(str(screen.get('layout') or 'layout'))}</span>"
            "</div>"
            f"<h3>{escape(str(screen.get('headline') or screen.get('title') or 'Screen headline'))}</h3>"
            f"<p>{escape(str(screen.get('purpose') or ''))}</p>"
            '<div class="screen-modules">'
            + "".join(
                (
                    '<div class="mini-module">'
                    f"<p>{escape(str(module.get('name') or 'Module'))}</p>"
                    f"<span>{escape(str((_as_list(module.get('items')) or [''])[0]))}</span>"
                    "</div>"
                )
                for module in [dict(item) for item in _as_list(screen.get("modules")) if isinstance(item, dict)][:3]
            )
            + "</div>"
            "</article>"
        )
        for screen in screens[:4]
    )
    flow_html = "".join(
        (
            "<article class='flow-card'>"
            f"<h3>{escape(str(flow.get('name') or 'Flow'))}</h3>"
            f"<ol>{''.join(f'<li>{escape(str(step))}</li>' for step in _as_list(flow.get('steps'))[:5] if str(step).strip())}</ol>"
            f"<p>{escape(str(flow.get('goal') or ''))}</p>"
            "</article>"
        )
        for flow in flows[:3]
    )
    principle_html = "".join(
        f"<li>{escape(item)}</li>"
        for item in interaction_principles[:4]
    )
    entity_html = "".join(
        f"<li>{escape(str(entity.get('name') or entity.get('title') or 'Entity'))}</li>"
        for entity in backend_modules[:6]
    )
    milestone_html = "".join(
        (
            "<li>"
            f"<strong>{escape(str(item.get('name') or item.get('id') or 'Milestone'))}</strong>"
            f"<span>{escape(str(item.get('criteria') or item.get('status') or ''))}</span>"
            "</li>"
        )
        for item in milestone_payload[:4]
    )
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: {background};
      --panel: rgba(255,255,255,0.88);
      --text: {primary};
      --accent: {accent};
      --muted: #5b6474;
      --border: rgba(15, 23, 42, 0.12);
      --surface: rgba(255,255,255,0.72);
      --surface-strong: rgba(15, 23, 42, 0.05);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "{escape(body_font)}", "Hiragino Sans", sans-serif;
      color: var(--text);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.85), rgba(255,255,255,0.55)),
        radial-gradient(circle at top left, rgba(59,130,246,0.08), transparent 28%),
        linear-gradient(160deg, #e2e8f0 0%, {background} 58%, #eef2ff 100%);
    }}
    main {{
      max-width: 1360px;
      margin: 0 auto;
      padding: 28px 24px 56px;
    }}
    .workspace {{
      display: grid;
      grid-template-columns: {("260px 1fr" if shell_layout == "sidebar" else "1fr")};
      gap: 20px;
      align-items: start;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 24px;
      padding: 24px;
      box-shadow: 0 24px 60px rgba(15, 23, 42, 0.08);
      backdrop-filter: blur(10px);
    }}
    h1, h2, h3, h4 {{ font-family: "{escape(heading_font)}", "Hiragino Sans", sans-serif; }}
    h1 {{ margin: 0; font-size: clamp(1.5rem, 3vw, 2.6rem); line-height: 1.05; }}
    h2 {{ margin: 0 0 10px; font-size: 0.95rem; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted); }}
    h3 {{ margin: 0; font-size: 1rem; }}
    p {{ color: var(--muted); line-height: 1.6; margin: 0; }}
    ul, ol {{ margin: 0; padding-left: 18px; color: var(--text); }}
    .sidebar {{
      position: sticky;
      top: 24px;
    }}
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 7px 11px;
      border-radius: 999px;
      background: rgba(255,255,255,0.72);
      border: 1px solid var(--border);
      font-size: 0.82rem;
    }}
    .accent {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 24px color-mix(in srgb, var(--accent) 60%, white);
    }}
    .sidebar nav ul {{
      list-style: none;
      padding: 0;
      margin: 18px 0 0;
      display: grid;
      gap: 10px;
    }}
    .sidebar nav a {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      text-decoration: none;
      color: var(--text);
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid transparent;
      background: rgba(15, 23, 42, 0.03);
    }}
    .sidebar nav a:hover {{
      border-color: var(--border);
      background: rgba(255,255,255,0.92);
    }}
    .status-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 18px;
    }}
    .status-badge {{
      display: inline-flex;
      align-items: center;
      padding: 8px 10px;
      border-radius: 999px;
      background: rgba(255,255,255,0.8);
      border: 1px solid var(--border);
      font-size: 0.76rem;
    }}
    .content {{
      display: grid;
      gap: 20px;
    }}
    .topbar {{
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      gap: 20px;
    }}
    .topbar-copy {{
      max-width: 640px;
      display: grid;
      gap: 12px;
    }}
    .topbar-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
    }}
    .topbar-actions button {{
      appearance: none;
      border: 1px solid color-mix(in srgb, var(--accent) 24%, var(--border));
      background: color-mix(in srgb, var(--accent) 16%, white);
      color: var(--text);
      border-radius: 14px;
      padding: 11px 14px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
    }}
    .hero-surface {{
      display: grid;
      gap: 16px;
      background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(255,255,255,0.78));
    }}
    .hero-metadata {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .metric {{
      border-radius: 16px;
      background: var(--surface);
      border: 1px solid var(--border);
      padding: 14px;
    }}
    .metric p:first-child {{
      font-size: 0.75rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .metric strong {{
      display: block;
      margin-top: 6px;
      font-size: 1rem;
    }}
    .module-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
      margin-top: 16px;
    }}
    .module-card {{
      border-radius: 18px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.9);
      padding: 16px;
    }}
    .module-card ul {{
      margin-top: 12px;
      display: grid;
      gap: 8px;
    }}
    .module-type {{
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.72rem;
      color: var(--muted);
      margin-bottom: 8px;
    }}
    .secondary-grid {{
      display: grid;
      grid-template-columns: 1.45fr 0.95fr;
      gap: 20px;
    }}
    .screen-gallery {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .screen-frame {{
      border-radius: 22px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.92);
      padding: 16px;
      min-height: 240px;
      display: grid;
      align-content: start;
      gap: 12px;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.5);
    }}
    .screen-topbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: var(--muted);
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .screen-modules {{
      display: grid;
      gap: 10px;
    }}
    .mini-module {{
      border-radius: 14px;
      background: var(--surface-strong);
      padding: 12px;
      border: 1px solid rgba(15,23,42,0.06);
    }}
    .mini-module p {{
      color: var(--text);
      font-size: 0.82rem;
      font-weight: 600;
      margin-bottom: 4px;
    }}
    .mini-module span {{
      color: var(--muted);
      font-size: 0.8rem;
    }}
    .flow-card {{
      border-radius: 18px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.9);
      padding: 16px;
      display: grid;
      gap: 12px;
    }}
    .flow-card ol {{
      display: grid;
      gap: 8px;
    }}
    .rail-list {{
      display: grid;
      gap: 10px;
    }}
    .rail-list li {{
      border-radius: 14px;
      background: var(--surface-strong);
      padding: 12px;
      display: grid;
      gap: 6px;
      list-style: none;
    }}
    .rail-list strong {{
      font-size: 0.86rem;
    }}
    .principles {{
      display: grid;
      gap: 8px;
    }}
    .principles li {{
      margin-left: 18px;
    }}
    .mode-chip {{
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    @media (max-width: 1100px) {{
      .workspace, .secondary-grid, .screen-gallery, .module-grid, .hero-metadata {{
        grid-template-columns: 1fr;
      }}
      .sidebar {{
        position: static;
      }}
    }}
    @media (max-width: 860px) {{
      main {{ padding: 18px 14px 32px; }}
      .panel, .screen-frame {{ border-radius: 18px; }}
    }}
  </style>
</head>
<body data-prototype-kind="{escape(prototype_kind)}" data-density="{escape(density)}">
  <main>
    <section class="workspace" aria-label="Prototype workspace">
      <aside class="sidebar panel">
        <div class="eyebrow"><span class="accent" aria-hidden="true"></span> Product Prototype</div>
        <h1>{escape(title)}</h1>
        <p style="margin-top:12px">{escape(subtitle)}</p>
        <div class="status-row">{badge_html}</div>
        <nav aria-label="Primary navigation">
          <ul>{nav_items_html}</ul>
        </nav>
      </aside>
      <div class="content">
        <section class="panel hero-surface">
          <div class="topbar">
            <div class="topbar-copy">
              <span class="mode-chip">{escape(mode)} prototype</span>
              <h1>{escape(str(_as_dict(active_screen).get("headline") or title))}</h1>
              <p>{escape(str(_as_dict(active_screen).get("purpose") or subtitle))}</p>
            </div>
            <div class="topbar-actions">{action_html}</div>
          </div>
          <div class="hero-metadata">
            <div class="metric">
              <p>Active Screen</p>
              <strong>{escape(str(_as_dict(active_screen).get("title") or "Primary workspace"))}</strong>
            </div>
            <div class="metric">
              <p>Primary Flow</p>
              <strong>{escape(str(_as_dict(flows[0] if flows else {}).get("name") or "Core workflow"))}</strong>
            </div>
            <div class="metric">
              <p>Layout</p>
              <strong>{escape(str(_as_dict(active_screen).get("layout") or shell_layout))}</strong>
            </div>
          </div>
          <div class="module-grid">{active_module_html}</div>
        </section>
        <section class="secondary-grid">
          <div class="panel">
            <h2>Prototype Screens</h2>
            <div class="screen-gallery" aria-label="Prototype screens">{screen_gallery_html}</div>
          </div>
          <div class="panel">
            <h2>Interaction Principles</h2>
            <ul class="principles">{principle_html}</ul>
          </div>
        </section>
        <section class="secondary-grid">
          <div class="panel">
            <h2>Primary Flows</h2>
            <div class="rail-list">{flow_html}</div>
          </div>
          <div class="panel">
            <h2>{escape("Milestone Readiness" if mode == "build" else "System Signals")}</h2>
            <ul class="rail-list">{milestone_html or entity_html}</ul>
          </div>
        </section>
      </div>
    </section>
  </main>
</body>
</html>"""


def _milestone_score(criteria: str, code: str) -> float:
    criteria_words = [word for word in _keywords(criteria) if len(word) > 2]
    if not criteria_words:
        return 1.0 if code else 0.0
    hits = sum(1 for word in criteria_words if word in code.lower())
    return hits / max(len(criteria_words), 1)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
