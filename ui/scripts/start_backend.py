"""Start the Pylon API server for UI development testing.

Registers:
  - Anthropic LLM provider for real AI agent execution
  - todo-app-builder workflow with custom node handlers
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root / "src"))

# Load .env file
env_file = project_root / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                k = key.strip()
                v = value.strip()
                # Override empty env vars too (Claude Code sets empty strings)
                if v and not os.environ.get(k):
                    os.environ[k] = v

import anthropic
try:
    from ui.scripts.dev_seed_agents import upsert_seeded_agents as reconcile_seeded_agents
except ModuleNotFoundError:
    from dev_seed_agents import upsert_seeded_agents as reconcile_seeded_agents

from pylon.api.factory import (
    APIServerConfig,
    APIMiddlewareConfig,
    AuthMiddlewareConfig,
    AuthBackend,
    TenantMiddlewareConfig,
    build_http_api_server,
)
from pylon.control_plane import ControlPlaneBackend, ControlPlaneStoreConfig
from pylon.providers.anthropic import AnthropicProvider
from pylon.runtime.llm import ProviderRegistry

# ── LLM Clients ───────────────────────────────────────
client_anthropic = anthropic.Anthropic()
MODEL = "claude-sonnet-4-6"
HAIKU_MODEL = "claude-haiku-4-5-20251001"
AUTONOMOUS_REVIEWER_NAME = "milestone-reviewer"

import openai as _openai
client_openai = _openai.OpenAI()

# Moonshot/Kimi client (OpenAI-compatible)
_moonshot_key = os.environ.get("MOONSHOT_API_KEY", "")
_moonshot_base = "https://api.kimi.com/coding/v1" if _moonshot_key.startswith("sk-kimi-") else "https://api.moonshot.ai/v1"
client_moonshot = _openai.OpenAI(api_key=_moonshot_key, base_url=_moonshot_base) if _moonshot_key else None

# Google Gemini client (OpenAI-compatible endpoint)
_gemini_key = os.environ.get("GEMINI_API_KEY", "")
client_gemini = _openai.OpenAI(
    api_key=_gemini_key,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
) if _gemini_key else None
GEMINI_MODEL = "gemini-3-flash-preview"

# ZhipuAI client (OpenAI-compatible)
_zhipu_key = os.environ.get("ZHIPU_API_KEY", "")
client_zhipu = _openai.OpenAI(
    api_key=_zhipu_key,
    base_url="https://open.bigmodel.cn/api/paas/v4/",
) if _zhipu_key else None

# ── Multi-Model Support ──────────────────────────────
import json as _json_mod
import re as _re
import datetime as _datetime

FALLBACK_CHAIN = ["anthropic", "openai", "gemini", "moonshot"]

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-5-mini",
    "gemini": "gemini-3-flash-preview",
    "moonshot": "kimi-k2.5",
    "zhipu": "glm-4-plus",
}

_model_policies: dict[str, dict] = {
    "anthropic": {"policy": "auto", "pin": None},
    "openai": {"policy": "auto", "pin": None},
    "moonshot": {"policy": "stable", "pin": None},
    "gemini": {"policy": "auto", "pin": None},
    "zhipu": {"policy": "stable", "pin": None},
}

_MODEL_CACHE_PATH = Path(__file__).parent / ".model_cache.json"
_MODEL_CACHE_TTL_DAYS = 7

# Fallback model lists when provider APIs are unreachable
_FALLBACK_MODEL_LISTS: dict[str, list[dict]] = {
    "anthropic": [
        {"id": "claude-opus-4-6", "name": "Claude Opus 4.6", "version": (4, 6), "created": 0},
        {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "version": (4, 6), "created": 0},
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "version": (4, 5), "created": 0},
    ],
    "openai": [
        {"id": "gpt-5-mini", "name": "GPT-5 Mini", "version": (5, 0), "created": 0},
        {"id": "gpt-4.1", "name": "GPT-4.1", "version": (4, 1), "created": 0},
        {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini", "version": (4, 1), "created": 0},
        {"id": "o4-mini", "name": "O4 Mini", "version": (4, 0), "created": 0},
    ],
    "gemini": [
        {"id": "gemini-3-flash-preview", "name": "Gemini 3 Flash Preview", "version": (3, 0), "created": 0},
        {"id": "gemini-3-pro-preview", "name": "Gemini 3 Pro Preview", "version": (3, 0), "created": 0},
    ],
    "moonshot": [
        {"id": "kimi-k2.5", "name": "Kimi K2.5", "version": (2, 5), "created": 0},
    ],
    "zhipu": [
        {"id": "glm-4-plus", "name": "GLM-4 Plus", "version": (4, 0), "created": 0},
    ],
}

# In-memory model registry: {provider: [model_dict, ...]}
_model_registry: dict[str, list[dict]] = {}


def _parse_model_version(model_id: str) -> tuple:
    """Parse semantic version from model ID.

    Examples:
        'claude-sonnet-4-6'   -> (4, 6)
        'gpt-5-mini'          -> (5, 0)
        'gemini-2.5-pro'      -> (2, 5)
        'gpt-4.1-mini'        -> (4, 1)
        'kimi-k2.5'           -> (2, 5)
    """
    # Try dotted version first: e.g. "4.1", "2.5"
    m = _re.search(r'(\d+)\.(\d+)', model_id)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    # Try hyphen-separated trailing digits: e.g. "sonnet-4-6"
    m = _re.search(r'-(\d+)-(\d+)(?:-|$)', model_id)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    # Single version number: e.g. "gpt-5-mini"
    m = _re.search(r'-(\d+)(?:-|$)', model_id)
    if m:
        return (int(m.group(1)), 0)
    # k-prefix: "k2.5"
    m = _re.search(r'k(\d+)\.(\d+)', model_id)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (0, 0)


def _load_model_cache() -> dict:
    """Load cached model data from disk."""
    if not _MODEL_CACHE_PATH.exists():
        return {}
    try:
        return _json_mod.loads(_MODEL_CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_model_cache(cache: dict) -> None:
    """Persist model cache to disk."""
    try:
        _MODEL_CACHE_PATH.write_text(_json_mod.dumps(cache, indent=2))
    except Exception as exc:
        print(f"[model-cache] Failed to save: {exc}")


def _is_cache_valid(provider_cache: dict) -> bool:
    """Check if a provider's cache entry is within the TTL."""
    updated = provider_cache.get("updated_at", "")
    if not updated:
        return False
    try:
        ts = _datetime.datetime.fromisoformat(updated)
        age = _datetime.datetime.now(_datetime.timezone.utc) - ts.replace(tzinfo=_datetime.timezone.utc)
        return age.days < _MODEL_CACHE_TTL_DAYS
    except Exception:
        return False


def _model_display_name(model_id: str) -> str:
    """Generate a human-friendly display name from model ID."""
    parts = model_id.replace("-", " ").replace(".", " ").title()
    return parts


def _fetch_provider_models(provider: str) -> list[dict]:
    """Fetch available models from a provider API. Uses cache with 7-day TTL."""
    cache = _load_model_cache()

    # Return cached data if valid
    if provider in cache and _is_cache_valid(cache[provider]):
        return cache[provider].get("models", [])

    models: list[dict] = []
    try:
        if provider == "anthropic":
            # Anthropic doesn't have a list-models endpoint in the standard SDK;
            # use the REST API if available, otherwise fall back.
            import urllib.request
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key:
                req = urllib.request.Request(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = _json_mod.loads(resp.read())
                for m in data.get("data", []):
                    mid = m.get("id", "")
                    models.append({
                        "id": mid,
                        "name": m.get("display_name", _model_display_name(mid)),
                        "version": list(_parse_model_version(mid)),
                        "created": m.get("created_at", 0),
                    })

        elif provider == "openai":
            resp = client_openai.models.list()
            for m in resp.data:
                mid = m.id
                # Filter to chat models only
                if any(k in mid for k in ("gpt-", "o4", "o3", "o1")):
                    models.append({
                        "id": mid,
                        "name": _model_display_name(mid),
                        "version": list(_parse_model_version(mid)),
                        "created": getattr(m, "created", 0),
                    })

        elif provider == "gemini" and client_gemini:
            import urllib.request
            api_key = os.environ.get("GEMINI_API_KEY", "")
            if api_key:
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = _json_mod.loads(resp.read())
                for m in data.get("models", []):
                    mid = m.get("name", "").replace("models/", "")
                    if "gemini" in mid:
                        models.append({
                            "id": mid,
                            "name": m.get("displayName", _model_display_name(mid)),
                            "version": list(_parse_model_version(mid)),
                            "created": 0,
                        })

        elif provider == "moonshot" and client_moonshot:
            resp = client_moonshot.models.list()
            for m in resp.data:
                mid = m.id
                models.append({
                    "id": mid,
                    "name": _model_display_name(mid),
                    "version": list(_parse_model_version(mid)),
                    "created": getattr(m, "created", 0),
                })

        elif provider == "zhipu" and client_zhipu:
            resp = client_zhipu.models.list()
            for m in resp.data:
                mid = m.id
                models.append({
                    "id": mid,
                    "name": _model_display_name(mid),
                    "version": list(_parse_model_version(mid)),
                    "created": getattr(m, "created", 0),
                })

    except Exception as exc:
        print(f"[model-registry] Failed to fetch {provider} models: {exc}")

    # Fall back to static list if API call returned nothing
    if not models:
        models = [
            {**m, "version": list(m["version"])} for m in _FALLBACK_MODEL_LISTS.get(provider, [])
        ]

    # Update cache
    cache[provider] = {
        "models": models,
        "updated_at": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
    }
    _save_model_cache(cache)

    # Update in-memory registry
    _model_registry[provider] = models
    return models


def _select_best_model(provider: str, policy: str = "auto") -> str:
    """Select a model based on the given policy.

    Policies:
      - auto:   pick the model with the highest version (latest)
      - stable: pick the default/proven model for the provider
      - pinned: use the exact model stored in _model_policies[provider]['pin']
    """
    pol = _model_policies.get(provider, {})
    effective_policy = policy if policy != "auto" else pol.get("policy", "auto")

    if effective_policy == "pinned":
        pin = pol.get("pin")
        if pin:
            return pin

    if effective_policy == "stable":
        return DEFAULT_MODELS.get(provider, "")

    # "auto" — pick latest by version
    models = _model_registry.get(provider) or _fetch_provider_models(provider)
    if not models:
        return DEFAULT_MODELS.get(provider, "")

    best = max(models, key=lambda m: (m.get("version", [0, 0]), m.get("created", 0)))
    return best["id"]


def _get_provider_client(provider: str):
    """Return the client object for a given provider name."""
    return {
        "anthropic": client_anthropic,
        "openai": client_openai,
        "moonshot": client_moonshot,
        "gemini": client_gemini,
        "zhipu": client_zhipu,
    }.get(provider)


# Populate registry from cache at startup
_startup_cache = _load_model_cache()
for _prov, _pdata in _startup_cache.items():
    if _is_cache_valid(_pdata):
        _model_registry[_prov] = _pdata.get("models", [])
print(f"Model registry: {sum(len(v) for v in _model_registry.values())} models cached across {len(_model_registry)} providers")

# ── Provider Registry ──────────────────────────────────
provider_registry = ProviderRegistry()
provider_registry.register("anthropic", lambda model_id: AnthropicProvider(model=model_id, max_tokens=8192))

for name, key_env in [("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY"), ("moonshot", "MOONSHOT_API_KEY"), ("gemini", "GEMINI_API_KEY"), ("zhipu", "ZHIPU_API_KEY")]:
    has_key = bool(os.environ.get(key_env))
    print(f"Provider: {name} ({'set' if has_key else 'NOT SET'})")

# ── Node Handlers ──────────────────────────────────────

def plan_handler(node_id: str, state: dict) -> dict:
    """Planner agent: analyze spec, produce implementation plan."""
    spec = state.get("spec", "")
    _track_task(task_id=f"wf_{node_id}", title="実装計画", description="仕様分析と実装プラン策定", status="in_progress", assignee="architect", priority="high", phase="planning", node_id=node_id)
    print(f"[plan] Calling Claude ({MODEL}) for implementation plan...")
    response = client_anthropic.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": (
                "You are a senior frontend architect. "
                "Given this spec, produce a detailed implementation plan as JSON with keys: "
                "files, components, data_model, steps. Be concise.\n\n"
                f"Spec:\n{spec}"
            ),
        }],
    )
    plan_text = response.content[0].text
    usage = response.usage
    print(f"[plan] Done. Tokens: {usage.input_tokens}in/{usage.output_tokens}out")
    _track_task(task_id=f"wf_{node_id}", title="実装計画", description="", status="done", assignee="architect")
    return {
        "plan": plan_text,
        "plan_tokens_in": usage.input_tokens,
        "plan_tokens_out": usage.output_tokens,
    }


def implement_handler(node_id: str, state: dict) -> dict:
    """Coder agent: write the complete app HTML."""
    spec = state.get("spec", "")
    plan = state.get("plan", "")
    _track_task(task_id=f"wf_{node_id}", title="コード生成", description="完全なアプリケーションHTMLの生成", status="in_progress", assignee="fullstack-builder", priority="high", phase="implementation", node_id=node_id)
    print(f"[implement] Calling Claude ({MODEL}) for code generation...")
    response = client_anthropic.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": (
                "You are an expert frontend developer. Write a COMPLETE, SELF-CONTAINED "
                "single HTML file based on this plan and spec. "
                "Include ALL HTML, CSS (dark theme), and JavaScript inline. "
                "Output ONLY the raw HTML code — no markdown fences, no explanations.\n\n"
                f"Plan:\n{plan}\n\nSpec:\n{spec}"
            ),
        }],
    )
    code = response.content[0].text
    usage = response.usage
    # Strip markdown fences if present
    if "```html" in code:
        code = code.split("```html", 1)[1]
        if "```" in code:
            code = code.rsplit("```", 1)[0]
    elif "```" in code:
        code = code.split("```", 1)[1]
        if "```" in code:
            code = code.rsplit("```", 1)[0]
    code = code.strip()

    # Calculate cost (Sonnet: $3/M input, $15/M output)
    plan_in = state.get("plan_tokens_in", 0)
    plan_out = state.get("plan_tokens_out", 0)
    total_in = plan_in + usage.input_tokens
    total_out = plan_out + usage.output_tokens
    cost = (total_in * 3 / 1_000_000) + (total_out * 15 / 1_000_000)

    print(f"[implement] Done. Tokens: {usage.input_tokens}in/{usage.output_tokens}out, Code: {len(code)} chars")
    print(f"[implement] Total cost: ${cost:.4f}")

    # Save generated file (outside ui/public/ to avoid Vite full-reload)
    output_path = project_root / "output" / "generated-app.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(code)
    print(f"[implement] Saved to: {output_path}")
    _track_task(task_id=f"wf_{node_id}", title="コード生成", description="", status="done", assignee="fullstack-builder")

    return {
        "code": code,
        "implement_tokens_in": usage.input_tokens,
        "implement_tokens_out": usage.output_tokens,
        "estimated_cost_usd": cost,
        "generated_file": str(output_path),
    }


# ── Server ─────────────────────────────────────────────
_DEFAULT_CONTROL_PLANE_PATH = project_root / ".pylon" / "ui-dev-control-plane.db"
_control_plane_backend = os.environ.get(
    "PYLON_CONTROL_PLANE_BACKEND",
    ControlPlaneBackend.SQLITE.value,
)
_control_plane_path = os.environ.get(
    "PYLON_CONTROL_PLANE_PATH",
    str(_DEFAULT_CONTROL_PLANE_PATH),
)

config = APIServerConfig(
    control_plane=ControlPlaneStoreConfig.from_mapping(
        {
            "backend": _control_plane_backend,
            "path": _control_plane_path,
        },
        default_backend=ControlPlaneBackend.SQLITE,
        default_path=str(_DEFAULT_CONTROL_PLANE_PATH),
    ),
    middleware=APIMiddlewareConfig(
        auth=AuthMiddlewareConfig(backend=AuthBackend.NONE),
        tenant=TenantMiddlewareConfig(require_tenant=False),
    ),
)

print("Starting Pylon API server on http://127.0.0.1:8080 ...")
print(
    "Control plane backend:",
    config.control_plane.backend.value,
    f"({config.control_plane.path or 'in-memory'})",
)
http_server, route_store = build_http_api_server(
    config,
    host="127.0.0.1",
    port=8080,
    provider_registry=provider_registry,
)

# ── Register agents ───────────────────────────────────
import uuid

_agents_to_register = [
    # ── Engineering ──
    {"name": "planner",          "model": f"anthropic/{MODEL}",          "role": "Analyze spec and create implementation plan",            "autonomy": "A2", "tools": [],                              "sandbox": "gvisor"},
    {"name": "architect",        "model": f"anthropic/{MODEL}",          "role": "System architecture design and API contracts",           "autonomy": "A2", "tools": [],                              "sandbox": "gvisor"},
    {"name": "frontend-coder",   "model": f"anthropic/{MODEL}",          "role": "React/TypeScript frontend implementation",               "autonomy": "A2", "tools": ["file-write", "shell"],          "sandbox": "docker"},
    {"name": "backend-coder",    "model": "openai/gpt-5-mini",           "role": "Python/Node.js backend API implementation",              "autonomy": "A2", "tools": ["file-write", "shell"],          "sandbox": "docker"},
    {"name": "fullstack-builder","model": f"anthropic/{MODEL}",          "role": "Full-stack developer building complete products",         "autonomy": "A2", "tools": ["file-write", "shell"],          "sandbox": "docker"},
    {"name": "reviewer",         "model": f"anthropic/{HAIKU_MODEL}",    "role": "Code review, quality checks and standards enforcement",   "autonomy": "A2", "tools": [],                              "sandbox": "gvisor"},
    {"name": "tester",           "model": "openai/gpt-5-mini",           "role": "Test planning, writing and execution",                    "autonomy": "A2", "tools": ["file-write", "shell"],          "sandbox": "docker"},
    {"name": "devops-engineer",  "model": "openai/gpt-5-mini",           "role": "CI/CD pipelines, Docker, Kubernetes and IaC",             "autonomy": "A3", "tools": ["shell"],                        "sandbox": "docker"},
    # ── Design ──
    {"name": "ui-designer",      "model": f"anthropic/{MODEL}",          "role": "UI component design and design system management",        "autonomy": "A2", "tools": ["file-write"],                   "sandbox": "gvisor"},
    {"name": "ux-analyst",       "model": f"anthropic/{MODEL}",          "role": "UX research, personas, user journey mapping",             "autonomy": "A2", "tools": [],                              "sandbox": "gvisor"},
    {"name": "design-reviewer",  "model": "moonshot/kimi-k2.5",          "role": "Design critique, accessibility and usability audit",      "autonomy": "A2", "tools": [],                              "sandbox": "gvisor"},
    # ── Research & Writing ──
    {"name": "researcher",       "model": "openai/gpt-5-mini",           "role": "Market research, competitive analysis and trend reports", "autonomy": "A2", "tools": ["http", "browser"],              "sandbox": "gvisor"},
    {"name": "tech-writer",      "model": f"anthropic/{HAIKU_MODEL}",    "role": "Technical documentation, API docs and runbooks",          "autonomy": "A2", "tools": ["file-write"],                   "sandbox": "gvisor"},
    {"name": "content-writer",   "model": "moonshot/kimi-k2.5",          "role": "Blog posts, marketing copy and release notes",            "autonomy": "A2", "tools": ["file-write"],                   "sandbox": "gvisor"},
    # ── Data & AI ──
    {"name": "data-analyst",     "model": f"gemini/{GEMINI_MODEL}",      "role": "Data analysis, SQL queries and visualization",            "autonomy": "A2", "tools": ["shell"],                        "sandbox": "docker"},
    {"name": "ml-engineer",      "model": f"anthropic/{MODEL}",          "role": "ML model development, training and evaluation",           "autonomy": "A3", "tools": ["file-write", "shell"],          "sandbox": "docker"},
    {"name": "data-engineer",    "model": f"gemini/{GEMINI_MODEL}",      "role": "Data pipelines, ETL, BigQuery and schema design",         "autonomy": "A2", "tools": ["shell"],                        "sandbox": "docker"},
    # ── Security ──
    {"name": "security-auditor", "model": f"anthropic/{MODEL}",          "role": "Security scanning, OWASP review and vulnerability triage","autonomy": "A2", "tools": ["shell"],                        "sandbox": "gvisor"},
    {"name": "security-reviewer","model": "openai/gpt-5-mini",           "role": "Dependency audit, secrets detection and policy check",    "autonomy": "A2", "tools": ["shell"],                        "sandbox": "gvisor"},
    # ── Product & Operations ──
    {"name": "product-manager",  "model": f"anthropic/{MODEL}",          "role": "PRD writing, feature prioritization and roadmap",         "autonomy": "A2", "tools": [],                              "sandbox": "gvisor"},
    {"name": "scrum-master",     "model": f"anthropic/{HAIKU_MODEL}",    "role": "Sprint planning, standup facilitation and velocity tracking","autonomy": "A2", "tools": [],                            "sandbox": "gvisor"},
    {"name": "sre-engineer",     "model": "openai/gpt-5-mini",           "role": "Monitoring, alerting, incident response and SLA management","autonomy": "A3", "tools": ["shell"],                      "sandbox": "docker"},
    {"name": "infra-ops",        "model": f"anthropic/{HAIKU_MODEL}",    "role": "Infrastructure provisioning, cost optimization",          "autonomy": "A3", "tools": ["shell"],                        "sandbox": "docker"},
    {"name": "qa-lead",          "model": f"gemini/{GEMINI_MODEL}",      "role": "QA strategy, test coverage analysis and release readiness","autonomy": "A2", "tools": [],                              "sandbox": "gvisor"},
    {"name": "perf-engineer",    "model": f"gemini/{GEMINI_MODEL}",      "role": "Performance profiling, load testing and optimization",    "autonomy": "A2", "tools": ["shell"],                        "sandbox": "docker"},
    # ── Advertising ──
    {"name": "audit-google",     "model": f"anthropic/{MODEL}",          "role": "Google Ads audit (Search, PMax, YouTube) - 74 checks",    "autonomy": "A2", "tools": [],                              "sandbox": "gvisor"},
    {"name": "audit-meta",       "model": f"anthropic/{MODEL}",          "role": "Meta Ads audit (FB, IG, Advantage+) - 46 checks",         "autonomy": "A2", "tools": [],                              "sandbox": "gvisor"},
    {"name": "audit-creative",   "model": f"anthropic/{HAIKU_MODEL}",    "role": "Creative quality and fatigue assessment across platforms", "autonomy": "A2", "tools": [],                              "sandbox": "gvisor"},
    {"name": "audit-tracking",   "model": f"anthropic/{HAIKU_MODEL}",    "role": "Conversion tracking health (Pixel, CAPI, UET)",           "autonomy": "A2", "tools": [],                              "sandbox": "gvisor"},
    {"name": "audit-budget",     "model": f"anthropic/{HAIKU_MODEL}",    "role": "Budget allocation and bidding strategy analysis",          "autonomy": "A2", "tools": [],                              "sandbox": "gvisor"},
    {"name": "audit-compliance", "model": f"anthropic/{HAIKU_MODEL}",    "role": "Ad compliance and privacy verification",                  "autonomy": "A2", "tools": [],                              "sandbox": "gvisor"},
]

_AGENT_DEFAULT_SKILLS: dict[str, list[str]] = {
    "planner": [],
    "architect": ["api-designer"],
    "frontend-coder": ["code-review"],
    "backend-coder": ["code-review", "api-designer"],
    "fullstack-builder": ["code-review", "api-designer"],
    "reviewer": ["code-review", "security-scan"],
    AUTONOMOUS_REVIEWER_NAME: ["code-review", "security-scan"],
    "tester": ["test-generator"],
    "devops-engineer": ["deployment-helper"],
    "ui-designer": [],
    "ux-analyst": [],
    "design-reviewer": [],
    "researcher": [],
    "tech-writer": ["doc-generator"],
    "content-writer": ["doc-generator"],
    "data-analyst": ["performance-profiler"],
    "ml-engineer": [],
    "data-engineer": [],
    "security-auditor": ["security-scan"],
    "security-reviewer": ["security-scan"],
    "product-manager": [],
    "scrum-master": [],
    "sre-engineer": ["performance-profiler", "deployment-helper"],
    "infra-ops": ["deployment-helper"],
    "qa-lead": ["test-generator"],
    "perf-engineer": ["performance-profiler"],
}

def _agent_team(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ["audit-google","audit-meta","audit-creative","audit-tracking","audit-budget","audit-compliance"]): return "advertising"
    if any(k in n for k in ["planner","architect","frontend","backend","fullstack","builder","reviewer","tester","devops","qa","perf"]): return "development"
    if any(k in n for k in ["ui-design","ux","design"]): return "design"
    if any(k in n for k in ["researcher","research","tech-writer","content-writer"]): return "research"
    if any(k in n for k in ["data","ml"]): return "data"
    if "security" in n: return "security"
    return "product"

seed_summary = reconcile_seeded_agents(
    route_store.agents,
    [(f"core:{agent_def['name']}", agent_def) for agent_def in _agents_to_register],
    tenant_id="default",
    team_for_name=_agent_team,
    default_skills_by_name=_AGENT_DEFAULT_SKILLS,
    prune_prefixes=("core:",),
)
print(
    "Agents: reconciled seeded registry",
    f"(desired={seed_summary['desired']}, updated={seed_summary['updated']}, removed_duplicates={seed_summary['removed_duplicates']}, pruned={seed_summary['pruned']})",
)

# ── Register demo workflow ─────────────────────────────
from pylon.dsl.parser import PylonProject

try:
    project = PylonProject.model_validate({
        "version": "1",
        "name": "todo-app-builder",
        "description": "Build an app with AI agents: plan → implement",
        "agents": {
            "planner": {
                "model": f"anthropic/{MODEL}",
                "role": "Analyze spec and create implementation plan",
                "autonomy": "A2",
                "tools": [],
                "sandbox": "gvisor",
            },
            "coder": {
                "model": f"anthropic/{MODEL}",
                "role": "Write application code as a single HTML file",
                "autonomy": "A2",
                "tools": ["file-write"],
                "sandbox": "docker",
            },
        },
        "workflow": {
            "type": "graph",
            "nodes": {
                "plan": {"agent": "planner", "node_type": "agent", "next": "implement"},
                "implement": {"agent": "coder", "node_type": "agent", "next": "END"},
            },
        },
        "policy": {
            "max_cost_usd": 5.0,
            "require_approval_above": "A4",
        },
    })
    route_store.register_workflow_project("todo-app-builder", project, tenant_id="default")

    # Register custom node handlers for LLM execution
    route_store.control_plane_store.set_handlers(
        "todo-app-builder",
        node_handlers={
            "plan": plan_handler,
            "implement": implement_handler,
        },
    )
    print(f"Workflow: todo-app-builder registered (model: anthropic/{MODEL})")
    print(f"  Node handlers: plan (planner), implement (coder)")
except Exception as e:
    print(f"Warning: Could not register demo workflow: {e}")
    import traceback
    traceback.print_exc()

# ── Register UX Analysis → Product Builder workflow ──
import json as _json

def ux_analyze_handler(node_id: str, state: dict) -> dict:
    """UX Analyst agent: perform comprehensive analysis."""
    spec = state.get("spec", "")
    _track_task(task_id=f"wf_{node_id}", title="UX分析", description="ペルソナ・ユーザーストーリー・KANO分析", status="in_progress", assignee="ux-analyst", priority="high", phase="ux-analysis", node_id=node_id)
    print(f"[ux-analyze] Calling Claude ({MODEL}) for UX analysis...")
    response = client_anthropic.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": (
                "You are a world-class UX strategist. Analyze this product/service "
                "and output a comprehensive JSON analysis with these keys:\n"
                "- personas: [{name, role, age_range, goals[], frustrations[], tech_proficiency, context}]\n"
                "- user_stories: [{role, action, benefit, acceptance_criteria[], priority(must/should/could/wont)}]\n"
                "- kano_features: [{feature, category(must-be/one-dimensional/attractive/indifferent), "
                "user_delight(-1.0 to 1.0), implementation_cost(low/medium/high), rationale}]\n"
                "- recommendations: [string]\n\n"
                "Output ONLY valid JSON, no markdown.\n\n"
                f"Product:\n{spec}"
            ),
        }],
    )
    analysis_text = response.content[0].text
    usage = response.usage
    # Try to parse JSON
    try:
        # Strip markdown fences
        text = analysis_text
        if "```json" in text:
            text = text.split("```json", 1)[1]
            if "```" in text:
                text = text.rsplit("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1]
            if "```" in text:
                text = text.rsplit("```", 1)[0]
        analysis = _json.loads(text.strip())
    except Exception:
        analysis = {"raw_analysis": analysis_text}

    print(f"[ux-analyze] Done. Tokens: {usage.input_tokens}in/{usage.output_tokens}out")
    _track_task(task_id=f"wf_{node_id}", title="UX分析", description="", status="done", assignee="ux-analyst")
    return {
        "analysis": analysis,
        "analysis_raw": analysis_text,
        "analysis_tokens_in": usage.input_tokens,
        "analysis_tokens_out": usage.output_tokens,
    }


def product_plan_handler(node_id: str, state: dict) -> dict:
    """Product Planner: take selected features and create detailed build plan."""
    spec = state.get("spec", "")
    selected_features = state.get("selected_features", [])
    analysis = state.get("analysis", {})
    _track_task(task_id=f"wf_{node_id}", title="プロダクト計画", description="機能選定に基づく詳細実装計画", status="in_progress", assignee="architect", priority="high", phase="product-planning", node_id=node_id)
    print(f"[product-plan] Planning {len(selected_features)} features...")
    response = client_anthropic.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                "You are a senior software architect. Based on the product spec, UX analysis, "
                "and selected features, create a detailed implementation plan.\n\n"
                "Output as JSON with keys:\n"
                "- project_name: string\n"
                "- tech_stack: {frontend, backend, database, deployment}\n"
                "- components: [{name, description, priority, estimated_complexity}]\n"
                "- implementation_steps: [{step, description, agent, output}]\n"
                "- data_model: [{entity, fields[], relationships[]}]\n"
                "- api_endpoints: [{method, path, description}]\n\n"
                "Output ONLY valid JSON.\n\n"
                f"Product Spec:\n{spec}\n\n"
                f"Selected Features:\n{_json.dumps(selected_features, ensure_ascii=False)}\n\n"
                f"UX Analysis Summary:\n{_json.dumps(analysis, ensure_ascii=False)[:3000]}"
            ),
        }],
    )
    plan_text = response.content[0].text
    usage = response.usage
    try:
        text = plan_text
        if "```json" in text:
            text = text.split("```json", 1)[1].rsplit("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1].rsplit("```", 1)[0]
        build_plan = _json.loads(text.strip())
    except Exception:
        build_plan = {"raw_plan": plan_text}

    print(f"[product-plan] Done. Tokens: {usage.input_tokens}in/{usage.output_tokens}out")
    _track_task(task_id=f"wf_{node_id}", title="プロダクト計画", description="", status="done", assignee="architect")
    return {
        "build_plan": build_plan,
        "build_plan_raw": plan_text,
        "plan_tokens_in": usage.input_tokens,
        "plan_tokens_out": usage.output_tokens,
    }


def product_build_handler(node_id: str, state: dict) -> dict:
    """Product Builder: generate the complete product code."""
    spec = state.get("spec", "")
    build_plan = state.get("build_plan", {})
    selected_features = state.get("selected_features", [])
    _track_task(task_id=f"wf_{node_id}", title="プロダクトビルド", description="完全なプロダクトコードの生成", status="in_progress", assignee="fullstack-builder", priority="high", phase="product-build", node_id=node_id)
    print(f"[product-build] Building product...")
    response = client_anthropic.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": (
                "You are an expert full-stack developer. Build a COMPLETE, SELF-CONTAINED "
                "single HTML file implementing the product based on this plan.\n\n"
                "Requirements:\n"
                "- Include ALL HTML, CSS (modern dark theme), and JavaScript inline\n"
                "- Implement ALL selected features fully functional\n"
                "- Use responsive design\n"
                "- Include proper error handling and loading states\n"
                "- Add realistic sample data\n"
                "- Make it production-quality\n\n"
                "Output ONLY the raw HTML code — no markdown fences, no explanations.\n\n"
                f"Build Plan:\n{_json.dumps(build_plan, ensure_ascii=False)[:4000]}\n\n"
                f"Selected Features:\n{_json.dumps(selected_features, ensure_ascii=False)}\n\n"
                f"Original Spec:\n{spec}"
            ),
        }],
    )
    code = response.content[0].text
    usage = response.usage
    # Strip markdown fences
    if "```html" in code:
        code = code.split("```html", 1)[1].rsplit("```", 1)[0]
    elif "```" in code:
        code = code.split("```", 1)[1].rsplit("```", 1)[0]
    code = code.strip()

    # Cost calculation
    total_in = (
        state.get("analysis_tokens_in", 0)
        + state.get("plan_tokens_in", 0)
        + usage.input_tokens
    )
    total_out = (
        state.get("analysis_tokens_out", 0)
        + state.get("plan_tokens_out", 0)
        + usage.output_tokens
    )
    cost = (total_in * 3 / 1_000_000) + (total_out * 15 / 1_000_000)

    # Save
    output_path = project_root / "output" / "product-build.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(code)

    print(f"[product-build] Done. {len(code)} chars, ${cost:.4f}")
    _track_task(task_id=f"wf_{node_id}", title="プロダクトビルド", description="", status="done", assignee="fullstack-builder")
    return {
        "code": code,
        "build_tokens_in": usage.input_tokens,
        "build_tokens_out": usage.output_tokens,
        "estimated_cost_usd": cost,
        "generated_file": str(output_path),
    }


try:
    # UX Analysis workflow (single-node, returns analysis JSON)
    ux_project = PylonProject.model_validate({
        "version": "1",
        "name": "ux-analysis",
        "description": "Comprehensive UX analysis: personas, user stories, KANO, recommendations",
        "agents": {
            "ux-analyst": {
                "model": f"anthropic/{MODEL}",
                "role": "UX strategist performing multi-framework product analysis",
                "autonomy": "A2",
                "tools": [],
                "sandbox": "gvisor",
            },
        },
        "workflow": {
            "type": "graph",
            "nodes": {
                "analyze": {"agent": "ux-analyst", "node_type": "agent", "next": "END"},
            },
        },
        "policy": {"max_cost_usd": 5.0, "require_approval_above": "A4"},
    })
    route_store.register_workflow_project("ux-analysis", ux_project, tenant_id="default")
    route_store.control_plane_store.set_handlers(
        "ux-analysis",
        node_handlers={"analyze": ux_analyze_handler},
    )
    print(f"Workflow: ux-analysis registered")

    # Product Builder workflow (plan → build)
    builder_project = PylonProject.model_validate({
        "version": "1",
        "name": "product-builder",
        "description": "Autonomous product builder: plan → build from UX analysis",
        "agents": {
            "architect": {
                "model": f"anthropic/{MODEL}",
                "role": "Software architect creating detailed build plans",
                "autonomy": "A2",
                "tools": [],
                "sandbox": "gvisor",
            },
            "builder": {
                "model": f"anthropic/{MODEL}",
                "role": "Full-stack developer building complete products",
                "autonomy": "A2",
                "tools": ["file-write"],
                "sandbox": "docker",
            },
        },
        "workflow": {
            "type": "graph",
            "nodes": {
                "plan": {"agent": "architect", "node_type": "agent", "next": "build"},
                "build": {"agent": "builder", "node_type": "agent", "next": "END"},
            },
        },
        "policy": {"max_cost_usd": 10.0, "require_approval_above": "A4"},
    })
    route_store.register_workflow_project("product-builder", builder_project, tenant_id="default")
    route_store.control_plane_store.set_handlers(
        "product-builder",
        node_handlers={
            "plan": product_plan_handler,
            "build": product_build_handler,
        },
    )
    print(f"Workflow: product-builder registered")
except Exception as e:
    print(f"Warning: Could not register UX/Builder workflows: {e}")
    import traceback
    traceback.print_exc()

# ── Register Autonomous Builder workflow (milestone-driven, loop nodes) ──

def autonomous_plan_handler(node_id: str, state: dict) -> dict:
    """Autonomous planner: create milestone-aware build plan."""
    spec = state.get("spec", "")
    selected_features = state.get("selected_features", [])
    milestones = state.get("milestones", [])
    analysis = state.get("analysis", {})
    iteration = state.get("_build_iteration", 0)
    previous_review = state.get("review_feedback", "")

    context_parts = [
        "You are a senior software architect planning an autonomous product build.",
        f"Spec:\n{spec}",
        f"Selected Features:\n{_json.dumps(selected_features, ensure_ascii=False)}",
        f"Analysis Summary:\n{_json.dumps(analysis, ensure_ascii=False)[:2000]}",
    ]
    if milestones:
        context_parts.append(f"Milestones to achieve:\n{_json.dumps(milestones, ensure_ascii=False)}")
    if iteration > 0 and previous_review:
        context_parts.append(f"Previous review feedback (iteration {iteration}):\n{previous_review}")
        context_parts.append("Revise the plan to address the feedback above.")

    context_parts.append(
        "\nOutput JSON with keys: project_name, milestones (array of {id, name, criteria, status:'pending'}), "
        "components, implementation_steps, tech_stack. Output ONLY valid JSON."
    )

    _track_task(task_id=f"wf_{node_id}", title="自律計画", description="マイルストーン対応の実装計画策定", status="in_progress", assignee="architect", priority="high", phase="autonomous-build", node_id=node_id)
    print(f"[auto-plan] Iteration {iteration}, planning {len(selected_features)} features, {len(milestones)} milestones...")
    response = client_anthropic.messages.create(
        model=MODEL, max_tokens=4096,
        messages=[{"role": "user", "content": "\n\n".join(context_parts)}],
    )
    plan_text = response.content[0].text
    usage = response.usage
    try:
        text = plan_text
        if "```json" in text:
            text = text.split("```json", 1)[1].rsplit("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1].rsplit("```", 1)[0]
        build_plan = _json.loads(text.strip())
    except Exception:
        build_plan = {"raw_plan": plan_text}

    print(f"[auto-plan] Done. Tokens: {usage.input_tokens}in/{usage.output_tokens}out")
    _track_task(task_id=f"wf_{node_id}", title="自律計画", description="", status="done", assignee="architect")
    return {
        "build_plan": build_plan,
        "plan_tokens_in": usage.input_tokens,
        "plan_tokens_out": usage.output_tokens,
        "_build_iteration": iteration,
    }


def autonomous_build_handler(node_id: str, state: dict) -> dict:
    """Autonomous builder: generate code implementing all milestones."""
    spec = state.get("spec", "")
    build_plan = state.get("build_plan", {})
    selected_features = state.get("selected_features", [])
    milestones = state.get("milestones", [])
    iteration = state.get("_build_iteration", 0)
    previous_code = state.get("code", "")
    review_feedback = state.get("review_feedback", "")

    prompt_parts = [
        "You are an expert full-stack developer. Build a COMPLETE, SELF-CONTAINED "
        "single HTML file implementing the product.\n\n"
        "Requirements:\n"
        "- ALL HTML, CSS (modern dark theme), and JavaScript inline\n"
        "- Implement ALL selected features fully functional\n"
        "- Responsive design, proper error handling, loading states\n"
        "- Realistic sample data, production-quality code\n",
        f"Build Plan:\n{_json.dumps(build_plan, ensure_ascii=False)[:4000]}",
        f"Selected Features:\n{_json.dumps(selected_features, ensure_ascii=False)}",
    ]
    if milestones:
        prompt_parts.append(f"Milestones to satisfy:\n{_json.dumps(milestones, ensure_ascii=False)}")
    if iteration > 0 and previous_code and review_feedback:
        prompt_parts.append(
            f"This is iteration {iteration}. Previous code had these issues:\n{review_feedback}\n"
            "Fix ALL issues while preserving working parts."
        )
    prompt_parts.append("\nOutput ONLY raw HTML code — no markdown fences, no explanations.")

    _track_task(task_id=f"wf_{node_id}", title="自律ビルド", description="マイルストーン実装のコード生成", status="in_progress", assignee="fullstack-builder", priority="high", phase="autonomous-build", node_id=node_id)
    print(f"[auto-build] Iteration {iteration}, building...")
    response = client_anthropic.messages.create(
        model=MODEL, max_tokens=8192,
        messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
    )
    code = response.content[0].text
    usage = response.usage
    if "```html" in code:
        code = code.split("```html", 1)[1].rsplit("```", 1)[0]
    elif "```" in code:
        code = code.split("```", 1)[1].rsplit("```", 1)[0]
    code = code.strip()

    output_path = project_root / "output" / f"autonomous-build-v{iteration}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(code)

    print(f"[auto-build] Done. {len(code)} chars saved to {output_path}")
    _track_task(task_id=f"wf_{node_id}", title="自律ビルド", description="", status="review", assignee="fullstack-builder")
    return {
        "code": code,
        "build_tokens_in": usage.input_tokens,
        "build_tokens_out": usage.output_tokens,
        "generated_file": str(output_path),
    }


def autonomous_review_handler(node_id: str, state: dict) -> dict:
    """Autonomous reviewer: evaluate code against milestones, provide feedback."""
    code = state.get("code", "")
    milestones = state.get("milestones", [])
    selected_features = state.get("selected_features", [])
    iteration = state.get("_build_iteration", 0)

    _track_task(task_id=f"wf_{node_id}", title="自律レビュー", description="マイルストーン達成度とコード品質の評価", status="in_progress", assignee=AUTONOMOUS_REVIEWER_NAME, priority="high", phase="autonomous-build", node_id=node_id)
    print(f"[auto-review] Iteration {iteration}, reviewing against {len(milestones)} milestones...")
    response = client_anthropic.messages.create(
        model=MODEL, max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                "You are a senior code reviewer and QA engineer. Review this HTML application "
                "against the milestones and features.\n\n"
                "For each milestone, evaluate if it is SATISFIED or NOT_SATISFIED.\n"
                "Output JSON with keys:\n"
                "- milestone_results: [{id, name, status:'satisfied'|'not_satisfied', reason}]\n"
                "- all_milestones_met: boolean\n"
                "- quality_score: 0.0-1.0 (overall quality)\n"
                "- feedback: string (specific improvements needed if not all met)\n"
                "- feature_coverage: [{feature, implemented: boolean}]\n\n"
                "Output ONLY valid JSON.\n\n"
                f"Milestones:\n{_json.dumps(milestones, ensure_ascii=False)}\n\n"
                f"Selected Features:\n{_json.dumps(selected_features, ensure_ascii=False)}\n\n"
                f"Code ({len(code)} chars):\n{code[:6000]}"
            ),
        }],
    )
    review_text = response.content[0].text
    usage = response.usage
    try:
        text = review_text
        if "```json" in text:
            text = text.split("```json", 1)[1].rsplit("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1].rsplit("```", 1)[0]
        review = _json.loads(text.strip())
    except Exception:
        review = {"all_milestones_met": True, "quality_score": 0.7, "feedback": "", "milestone_results": []}

    all_met = review.get("all_milestones_met", False)
    quality = review.get("quality_score", 0.5)
    feedback = review.get("feedback", "")

    # Cost calculation
    total_in = (
        state.get("analysis_tokens_in", 0)
        + state.get("plan_tokens_in", 0)
        + state.get("build_tokens_in", 0)
        + usage.input_tokens
    )
    total_out = (
        state.get("analysis_tokens_out", 0)
        + state.get("plan_tokens_out", 0)
        + state.get("build_tokens_out", 0)
        + usage.output_tokens
    )
    cost = (total_in * 3 / 1_000_000) + (total_out * 15 / 1_000_000)

    _track_task(task_id=f"wf_{node_id}", title="自律レビュー", description="", status="done" if all_met else "backlog", assignee=AUTONOMOUS_REVIEWER_NAME)
    print(f"[auto-review] Done. All milestones met: {all_met}, quality: {quality:.2f}, cost: ${cost:.4f}")
    return {
        "review": review,
        "review_feedback": feedback,
        "all_milestones_met": all_met,
        "quality_score": quality,
        "_build_iteration": iteration + 1,
        "review_tokens_in": usage.input_tokens,
        "review_tokens_out": usage.output_tokens,
        "estimated_cost_usd": cost,
    }


try:
    auto_project = PylonProject.model_validate({
        "version": "1",
        "name": "autonomous-builder",
        "description": "Milestone-driven autonomous builder: plan → build → review (loop until milestones met)",
        "agents": {
            "architect": {
                "model": f"anthropic/{MODEL}",
                "role": "Software architect creating milestone-aware build plans",
                "autonomy": "A3",
                "tools": [],
                "sandbox": "gvisor",
            },
            "builder": {
                "model": f"anthropic/{MODEL}",
                "role": "Full-stack developer building complete products",
                "autonomy": "A3",
                "tools": ["file-write"],
                "sandbox": "docker",
            },
            AUTONOMOUS_REVIEWER_NAME: {
                "model": f"anthropic/{MODEL}",
                "role": "QA reviewer evaluating code against milestones",
                "autonomy": "A3",
                "tools": [],
                "sandbox": "gvisor",
            },
        },
        "workflow": {
            "type": "graph",
            "nodes": {
                "plan": {"agent": "architect", "node_type": "agent", "next": "build"},
                "build": {"agent": "builder", "node_type": "agent", "next": "review"},
                "review": {
                    "agent": AUTONOMOUS_REVIEWER_NAME,
                    "node_type": "loop",
                    "loop_max_iterations": 5,
                    "loop_criterion": "state_value",
                    "loop_threshold": 1.0,
                    "loop_metadata": {"state_key": "all_milestones_met", "true_value": True},
                    "next": "END",
                },
            },
        },
        "policy": {"max_cost_usd": 20.0, "require_approval_above": "A4"},
    })
    route_store.register_workflow_project("autonomous-builder", auto_project, tenant_id="default")
    route_store.control_plane_store.set_handlers(
        "autonomous-builder",
        node_handlers={
            "plan": autonomous_plan_handler,
            "build": autonomous_build_handler,
            "review": autonomous_review_handler,
        },
    )
    seed_summary = reconcile_seeded_agents(
        route_store.agents,
        [("workflow:autonomous-builder:reviewer", {
            "name": AUTONOMOUS_REVIEWER_NAME,
            "model": f"anthropic/{MODEL}",
            "role": "QA reviewer evaluating code against milestones",
            "autonomy": "A3",
            "tools": [],
            "sandbox": "gvisor",
        })],
        tenant_id="default",
        team_for_name=_agent_team,
        default_skills_by_name=_AGENT_DEFAULT_SKILLS,
        prune_prefixes=("workflow:autonomous-builder:",),
    )
    print(
        "Agents: reconciled seeded registry",
        f"(desired={seed_summary['desired']}, updated={seed_summary['updated']}, removed_duplicates={seed_summary['removed_duplicates']}, pruned={seed_summary['pruned']})",
    )
    print(f"Workflow: autonomous-builder registered (loop review, max 5 iterations)")
except Exception as e:
    print(f"Warning: Could not register autonomous-builder: {e}")
    import traceback
    traceback.print_exc()

# ── Lifecycle Workflow Handlers ─────────────────────────
# These handlers are auto-attached when the UI registers lifecycle workflows.

# Model costs per million tokens: (input, output)
MODEL_COSTS = {
    # Anthropic (4.6 dropped date suffixes)
    "claude-opus-4-6": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    # OpenAI
    "gpt-5.4": (2.50, 10.0),
    "gpt-5.2": (2.0, 8.0),
    "gpt-5-mini": (0.40, 1.60),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o4-mini": (1.10, 4.40),
    # Moonshot/Kimi
    "kimi-k2.5": (2.0, 8.0),
    # Google
    "gemini-3-pro-preview": (1.25, 5.0),
    "gemini-3-flash-preview": (0.15, 0.60),
    # xAI
    "grok-4.1": (3.0, 15.0),
    # DeepSeek
    "deepseek-chat": (0.27, 1.10),
}

def _calc_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    costs = MODEL_COSTS.get(model, (3.0, 15.0))
    return (tokens_in * costs[0] / 1_000_000) + (tokens_out * costs[1] / 1_000_000)

# ── Cost tracking (persisted to JSONL) ──
import time as _time_mod
_COST_LOG_PATH = Path(__file__).parent / ".cost_log.jsonl"

def _load_cost_log() -> list[dict]:
    if not _COST_LOG_PATH.exists():
        return []
    entries = []
    for line in _COST_LOG_PATH.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(_json.loads(line))
            except Exception:
                pass
    return entries

_cost_log: list[dict] = _load_cost_log()
print(f"Costs: {len(_cost_log)} entries loaded from {_COST_LOG_PATH.name}")

def _record_cost(provider: str, model: str, tokens_in: int, tokens_out: int):
    cost = _calc_cost(model, tokens_in, tokens_out)
    entry = {
        "timestamp": _time_mod.time(),
        "provider": provider,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost,
    }
    _cost_log.append(entry)
    with open(_COST_LOG_PATH, "a") as f:
        f.write(_json.dumps(entry) + "\n")

def _strip_json_fences(text: str) -> str:
    if "```json" in text:
        text = text.split("```json", 1)[1].rsplit("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].rsplit("```", 1)[0]
    return text.strip()


def _repair_truncated_json(text: str) -> str:
    """Attempt to repair JSON that was truncated by max_tokens.

    Closes unclosed brackets/braces and removes trailing partial elements.
    """
    import re as _re
    stripped = _strip_json_fences(text)
    try:
        _json.loads(stripped)
        return stripped
    except _json.JSONDecodeError:
        pass
    # Remove trailing incomplete string/value after last comma
    # Then close open brackets
    s = stripped.rstrip()
    # Remove trailing partial content after last complete element
    # Find last valid closing bracket/brace/quote
    for _ in range(50):
        s = s.rstrip()
        if not s:
            return "{}"
        last = s[-1]
        if last in ('"', '}', ']', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'e', 'l', 'u'):
            break
        s = s[:-1]
    # Remove trailing comma
    s = s.rstrip().rstrip(',')
    # Count open/close brackets
    opens = []
    in_str = False
    escape = False
    for ch in s:
        if escape:
            escape = False
            continue
        if ch == '\\' and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in ('{', '['):
            opens.append(ch)
        elif ch == '}' and opens and opens[-1] == '{':
            opens.pop()
        elif ch == ']' and opens and opens[-1] == '[':
            opens.pop()
    # Close remaining open brackets
    for bracket in reversed(opens):
        s += ']' if bracket == '[' else '}'
    try:
        _json.loads(s)
        return s
    except _json.JSONDecodeError:
        return stripped

def _strip_html_fences(text: str) -> str:
    if "```html" in text:
        text = text.split("```html", 1)[1].rsplit("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].rsplit("```", 1)[0]
    return text.strip()

def _call_llm_single(model: str, prompt: str, max_tokens: int, provider: str) -> tuple[str, int, int]:
    """Call a single provider (no fallback). Raises on failure."""
    if provider in ("openai", "moonshot", "gemini", "zhipu"):
        client = _get_provider_client(provider)
        if client is None:
            raise RuntimeError(f"Provider {provider} client not configured")
        response = client.chat.completions.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content or ""
        tin, tout = response.usage.prompt_tokens, response.usage.completion_tokens
        _record_cost(provider, model, tin, tout)
        return text, tin, tout
    else:
        # Default: Anthropic
        response = client_anthropic.messages.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        tin, tout = response.usage.input_tokens, response.usage.output_tokens
        _record_cost("anthropic", model, tin, tout)
        return response.content[0].text, tin, tout


def _call_llm(model: str, prompt: str, max_tokens: int = 4096, *, provider: str = "anthropic", fallback: bool = True) -> tuple[str, int, int]:
    """Call LLM with optional fallback chain.

    Args:
        model: Model ID, or "auto" to use _select_best_model.
        prompt: The user prompt.
        max_tokens: Maximum tokens to generate.
        provider: Primary provider name.
        fallback: If True, try FALLBACK_CHAIN on failure.

    Returns:
        (text, tokens_in, tokens_out)
    """
    # Resolve "auto" model
    if model == "auto":
        model = _select_best_model(provider)

    # Build provider chain (circular: try all providers after the primary)
    if fallback:
        chain = [provider]
        if provider in FALLBACK_CHAIN:
            idx = FALLBACK_CHAIN.index(provider)
            # Wrap around: items after idx, then items before idx
            chain += [p for p in FALLBACK_CHAIN[idx + 1:] + FALLBACK_CHAIN[:idx] if p != provider]
        else:
            chain += [p for p in FALLBACK_CHAIN if p != provider]
        # Also include zhipu if not already in chain
        if "zhipu" not in chain and _get_provider_client("zhipu"):
            chain.append("zhipu")
    else:
        chain = [provider]

    last_error: Exception | None = None
    for prov in chain:
        # Skip providers with no client configured
        if prov != "anthropic" and _get_provider_client(prov) is None:
            continue
        use_model = model if prov == provider else DEFAULT_MODELS.get(prov, model)
        try:
            result = _call_llm_single(use_model, prompt, max_tokens, prov)
            if prov != provider:
                print(f"[fallback] {provider}/{model} failed, served by {prov}/{use_model}")
            return result
        except Exception as exc:
            last_error = exc
            print(f"[call_llm] {prov}/{use_model} failed: {exc}")
            continue

    raise RuntimeError(f"All providers failed. Last error: {last_error}")


def _build_skill_augmented_prompt(agent_name: str, base_prompt: str) -> str:
    """Prepend relevant skill instructions to the agent's prompt based on assigned skills."""
    agent = None
    for a in route_store.agents.values():
        if a["name"] == agent_name:
            agent = a
            break
    if not agent or not agent.get("skills"):
        return base_prompt

    skill_sections = []
    for skill_id in agent["skills"]:
        skill = _skill_registry.get(skill_id)
        if skill:
            content = _get_skill_content(skill)
            skill_sections.append(f"=== Skill: {skill['name']} ===\n{content}")

    if not skill_sections:
        return base_prompt

    augmented = "You have the following specialized skills available. Apply them when relevant:\n\n"
    augmented += "\n\n".join(skill_sections)
    augmented += "\n\n---\n\n" + base_prompt
    return augmented


def _agent_call_llm(
    agent_name: str,
    model: str,
    prompt: str,
    max_tokens: int = 4096,
    *,
    provider: str = "anthropic",
    fallback: bool = True,
) -> tuple[str, int, int]:
    """Call LLM with skill-augmented prompt based on agent's assigned skills."""
    augmented = _build_skill_augmented_prompt(agent_name, prompt)
    return _call_llm(model, augmented, max_tokens, provider=provider, fallback=fallback)


# ── Research Phase Handlers ──

def _cheap_model(provider: str) -> str:
    """Return cheapest available model for a provider."""
    return DEFAULT_MODELS.get(provider, HAIKU_MODEL)

def _pick_cheap_provider(*preferred: str) -> tuple[str, str]:
    """Pick first available cheap provider from preference list. Returns (provider, model)."""
    for prov in preferred:
        if prov == "anthropic":
            return ("anthropic", HAIKU_MODEL)
        client = _get_provider_client(prov)
        if client is not None:
            return (prov, _cheap_model(prov))
    return ("anthropic", HAIKU_MODEL)


import subprocess as _subprocess


def _query_design_skill(keywords: str, domain: str = "product", max_results: int = 5) -> str:
    """Query ui-ux-pro-max skill database for design recommendations."""
    skill_script = Path.home() / ".claude" / "skills" / "ui-ux-pro-max" / "scripts" / "search.py"
    if not skill_script.exists():
        return ""
    try:
        result = _subprocess.run(
            ["python3", str(skill_script), keywords, "--domain", domain, "-n", str(max_results)],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip()[:3000] if result.returncode == 0 else ""
    except Exception:
        return ""


def _query_design_system(keywords: str) -> str:
    """Get comprehensive design system recommendation from skill database."""
    skill_script = Path.home() / ".claude" / "skills" / "ui-ux-pro-max" / "scripts" / "search.py"
    if not skill_script.exists():
        return ""
    try:
        result = _subprocess.run(
            ["python3", str(skill_script), keywords, "--design-system", "-f", "markdown"],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip()[:4000] if result.returncode == 0 else ""
    except Exception:
        return ""


def _query_ux_guidelines(keywords: str = "accessibility animation responsive") -> str:
    """Get UX best practices from skill database."""
    return _query_design_skill(keywords, domain="ux", max_results=10)


def _infer_product_type(spec: str, features: list) -> str:
    """Infer product type keywords from spec and features for skill lookup."""
    spec_lower = spec.lower()
    keywords = []
    type_map = {
        "saas": ["saas", "subscription", "platform", "service"],
        "dashboard": ["dashboard", "analytics", "monitoring", "metrics"],
        "e-commerce": ["shop", "cart", "payment", "e-commerce", "store"],
        "healthcare": ["health", "medical", "patient", "clinic"],
        "fintech": ["finance", "payment", "banking", "trading"],
    }
    for product_type, kws in type_map.items():
        if any(kw in spec_lower for kw in kws):
            keywords.append(product_type)
    if not keywords:
        keywords.append("saas dashboard")
    # Add feature-derived keywords
    feature_names = [f.get("feature", "") if isinstance(f, dict) else str(f) for f in features[:5]]
    keywords.extend([fn[:30] for fn in feature_names if fn])
    return " ".join(keywords[:5])


def _research_depth_config(state: dict) -> dict:
    """Return depth-aware config: token budget, competitor count, detail level."""
    depth = state.get("depth", "standard")
    if depth == "quick":
        return {"max_tokens": 2048, "competitor_count": "2-3", "detail": "brief", "analysis_scope": "basic competitive landscape", "extra_instructions": "Keep analysis concise and focused on key points only."}
    if depth == "deep":
        return {"max_tokens": 12288, "competitor_count": "5-8", "detail": "comprehensive with data points", "analysis_scope": "comprehensive SWOT analysis with market sizing, strategic positioning, and actionable insights", "extra_instructions": "Be thorough. Include data estimates, market share %, pricing tiers, growth rates, and strategic recommendations."}
    # standard
    return {"max_tokens": 4096, "competitor_count": "3-5", "detail": "detailed", "analysis_scope": "market analysis with technology evaluation", "extra_instructions": ""}


def research_competitor_handler(node_id: str, state: dict) -> dict:
    spec = state.get("spec", "")
    dc = _research_depth_config(state)
    _track_task(task_id=f"wf_{node_id}", title="競合分析", description="競合他社の強み・弱み・価格を分析", status="in_progress", assignee="researcher", priority="high", phase="market-research", node_id=node_id)
    prov, mdl = _pick_cheap_provider("gemini", "moonshot", "zhipu", "anthropic")
    print(f"[research:competitor] Analyzing competitors (depth={state.get('depth','standard')}) with {prov}/{mdl}...")
    text, tin, tout = _call_llm(mdl, (
        "You are a competitive intelligence analyst. "
        f"Research and analyze competitors for this product. Depth: {dc['detail']}.\n"
        "Output JSON with key 'competitors': [{name, url, strengths:[], weaknesses:[], pricing, target}]. "
        f"Include {dc['competitor_count']} realistic competitors. {dc['extra_instructions']}\n"
        "Output ONLY valid JSON.\n\n"
        f"Product:\n{spec}"
    ), max_tokens=dc["max_tokens"], provider=prov)
    try:
        data = _json.loads(_strip_json_fences(text))
    except Exception:
        data = {"competitors": []}
    print(f"[research:competitor] Done. {tin}in/{tout}out (provider: {prov})")
    _track_task(task_id=f"wf_{node_id}", title="競合分析", description="", status="done", assignee="researcher")
    return {"competitor_data": data, "competitor_tokens_in": tin, "competitor_tokens_out": tout}


def research_market_handler(node_id: str, state: dict) -> dict:
    spec = state.get("spec", "")
    dc = _research_depth_config(state)
    _track_task(task_id=f"wf_{node_id}", title="市場調査", description="市場規模・トレンド・機会を調査", status="in_progress", assignee="researcher", priority="high", phase="market-research", node_id=node_id)
    prov, mdl = _pick_cheap_provider("moonshot", "zhipu", "gemini", "anthropic")
    print(f"[research:market] Researching market (depth={state.get('depth','standard')}) with {prov}/{mdl}...")
    text, tin, tout = _call_llm(mdl, (
        f"You are a market research analyst. Depth: {dc['analysis_scope']}.\n"
        "Analyze the market for this product/service. "
        "Output JSON with keys: market_size (string), trends (array of strings), "
        "opportunities (array of strings), growth_rate (string). "
        f"{dc['extra_instructions']}\n"
        "Output ONLY valid JSON.\n\n"
        f"Product:\n{spec}"
    ), max_tokens=dc["max_tokens"], provider=prov)
    try:
        data = _json.loads(_strip_json_fences(text))
    except Exception:
        data = {"market_size": "N/A", "trends": [], "opportunities": []}
    print(f"[research:market] Done. {tin}in/{tout}out (provider: {prov})")
    _track_task(task_id=f"wf_{node_id}", title="市場調査", description="", status="done", assignee="researcher")
    return {"market_data": data, "market_tokens_in": tin, "market_tokens_out": tout}


def research_tech_handler(node_id: str, state: dict) -> dict:
    spec = state.get("spec", "")
    dc = _research_depth_config(state)
    _track_task(task_id=f"wf_{node_id}", title="技術評価", description="技術的実現可能性の評価", status="in_progress", assignee="researcher", priority="high", phase="market-research", node_id=node_id)
    prov, mdl = _pick_cheap_provider("zhipu", "gemini", "moonshot", "anthropic")
    print(f"[research:tech] Evaluating tech feasibility (depth={state.get('depth','standard')}) with {prov}/{mdl}...")
    text, tin, tout = _call_llm(mdl, (
        f"You are a senior technology evaluator. Depth: {dc['detail']}.\n"
        "Assess the technical feasibility of this product. "
        "Output JSON with keys: score (0.0-1.0), notes (string), "
        "recommended_stack (object), risks (array of strings), threats (array of strings). "
        f"{dc['extra_instructions']}\n"
        "Output ONLY valid JSON.\n\n"
        f"Product:\n{spec}"
    ), max_tokens=dc["max_tokens"], provider=prov)
    try:
        data = _json.loads(_strip_json_fences(text))
    except Exception:
        data = {"score": 0.7, "notes": "Analysis completed", "risks": [], "threats": []}
    print(f"[research:tech] Done. {tin}in/{tout}out (provider: {prov})")
    _track_task(task_id=f"wf_{node_id}", title="技術評価", description="", status="done", assignee="researcher")
    return {"tech_data": data, "tech_tokens_in": tin, "tech_tokens_out": tout}


def research_user_handler(node_id: str, state: dict) -> dict:
    """user-researcher: Persona-level user research with behavioral insights."""
    spec = state.get("spec", "")
    dc = _research_depth_config(state)
    _track_task(task_id=f"wf_{node_id}", title="ユーザー調査", description="ターゲットユーザーの行動・ニーズ分析", status="in_progress", assignee="researcher", priority="high", phase="market-research", node_id=node_id)
    prov, mdl = _pick_cheap_provider("anthropic", "gemini", "moonshot", "zhipu")
    print(f"[research:user] Researching user needs (depth={state.get('depth','standard')}) with {prov}/{mdl}...")
    segment_count = "1-2" if dc["detail"] == "brief" else ("4-6" if dc["detail"] == "comprehensive with data points" else "2-4")
    text, tin, tout = _call_llm(mdl, (
        f"You are a user experience researcher. Depth: {dc['detail']}.\n"
        "Research target users, their behaviors, needs, pain points, and contexts of use.\n\n"
        "Output JSON with keys:\n"
        "- user_segments: [{name, size_estimate, demographics, behaviors:[], needs:[], pain_points:[], willingness_to_pay}]\n"
        "- usage_contexts: [{context, frequency, device, environment, emotional_state}]\n"
        "- adoption_barriers: [{barrier, severity:'high'|'medium'|'low', mitigation}]\n\n"
        f"Identify {segment_count} user segments. {dc['extra_instructions']}\n"
        "Output ONLY valid JSON.\n\n"
        f"Product:\n{spec}"
    ), max_tokens=dc["max_tokens"], provider=prov)
    try:
        data = _json.loads(_strip_json_fences(text))
    except Exception:
        data = {"user_segments": [], "usage_contexts": [], "adoption_barriers": []}
    print(f"[research:user] Done. {tin}in/{tout}out (provider: {prov})")
    _track_task(task_id=f"wf_{node_id}", title="ユーザー調査", description="", status="done", assignee="researcher")
    return {"user_data": data, "user_tokens_in": tin, "user_tokens_out": tout}


def research_synthesizer_handler(node_id: str, state: dict) -> dict:
    competitor_data = state.get("competitor_data", {})
    market_data = state.get("market_data", {})
    tech_data = state.get("tech_data", {})
    user_data = state.get("user_data", {})
    spec = state.get("spec", "")
    _track_task(task_id=f"wf_{node_id}", title="リサーチ統合", description="調査結果の統合分析", status="in_progress", assignee="researcher", priority="high", phase="market-research", node_id=node_id)
    synth_prov, synth_mdl = _pick_cheap_provider("gemini", "anthropic", "moonshot")
    print(f"[research:synthesizer] Synthesizing research results with {synth_prov}/{synth_mdl}...")
    text, tin, tout = _call_llm(synth_mdl, (
        "You are a senior product strategist. Synthesize these research results into a comprehensive analysis.\n\n"
        "Output JSON with these exact keys:\n"
        "- competitors: [{name, url, strengths:[], weaknesses:[], pricing, target}]\n"
        "- market_size: string\n"
        "- trends: [string]\n"
        "- opportunities: [string]\n"
        "- threats: [string]\n"
        "- tech_feasibility: {score: 0.0-1.0, notes: string}\n"
        "- user_segments: [{name, size_estimate, demographics, behaviors:[], needs:[], pain_points:[]}]\n"
        "- usage_contexts: [{context, frequency, device, environment}]\n\n"
        "Output ONLY valid JSON.\n\n"
        f"Product: {spec}\n\n"
        f"Competitor Analysis:\n{_json.dumps(competitor_data, ensure_ascii=False)[:4000]}\n\n"
        f"Market Research:\n{_json.dumps(market_data, ensure_ascii=False)[:3000]}\n\n"
        f"Tech Evaluation:\n{_json.dumps(tech_data, ensure_ascii=False)[:3000]}\n\n"
        f"User Research:\n{_json.dumps(user_data, ensure_ascii=False)[:3000]}"
    ), provider=synth_prov)
    try:
        research = _json.loads(_strip_json_fences(text))
    except Exception:
        research = {
            "competitors": competitor_data.get("competitors", []),
            "market_size": market_data.get("market_size", "N/A"),
            "trends": market_data.get("trends", []),
            "opportunities": market_data.get("opportunities", []),
            "threats": tech_data.get("threats", []),
            "tech_feasibility": {"score": tech_data.get("score", 0.7), "notes": tech_data.get("notes", "")},
        }
    print(f"[research:synthesizer] Done. {tin}in/{tout}out")
    _track_task(task_id=f"wf_{node_id}", title="リサーチ統合", description="", status="done", assignee="researcher")
    return {"research": research}


# ── Planning Phase Handlers ──

def planning_persona_handler(node_id: str, state: dict) -> dict:
    spec = state.get("spec", "")
    research = state.get("research", state.get("analysis", {}))
    _track_task(task_id=f"wf_{node_id}", title="ペルソナ設計", description="ターゲットユーザーペルソナの作成", status="in_progress", assignee="product-manager", priority="high", phase="product-planning", node_id=node_id)
    # Use Gemini for persona analysis (fast & cheap)
    prov, mdl = _pick_cheap_provider("gemini", "moonshot", "zhipu", "anthropic")
    print(f"[planning:persona] Building personas and user stories with {prov}/{mdl}...")
    text, tin, tout = _call_llm(mdl, (
        "You are a UX researcher. Create personas and user stories for this product.\n\n"
        "Output JSON with keys:\n"
        "- personas: [{name, role, age_range, goals:[], frustrations:[], tech_proficiency, context}]\n"
        "- user_stories: [{role, action, benefit, acceptance_criteria:[], priority: 'must'|'should'|'could'|'wont'}]\n\n"
        "Create 2-3 personas and 5-8 user stories. Output ONLY valid JSON, no markdown fences.\n\n"
        f"Product:\n{spec}\n\n"
        f"Research Context:\n{_json.dumps(research, ensure_ascii=False)[:4000]}"
    ), max_tokens=8192, provider=prov)
    try:
        repaired = _repair_truncated_json(text)
        data = _json.loads(repaired)
    except Exception as e:
        print(f"[planning:persona] JSON parse failed: {e}")
        print(f"[planning:persona] Raw text (first 500): {text[:500]}")
        data = {"personas": [], "user_stories": []}
    # Normalize: sometimes LLM wraps in an outer key
    if isinstance(data, dict) and len(data) == 1:
        inner = list(data.values())[0]
        if isinstance(inner, dict) and ("personas" in inner or "user_stories" in inner):
            data = inner
    print(f"[planning:persona] Done. {tin}in/{tout}out (provider: {prov}), personas={len(data.get('personas',[]))}, stories={len(data.get('user_stories',[]))}")
    _track_task(task_id=f"wf_{node_id}", title="ペルソナ設計", description="", status="done", assignee="product-manager")
    return {"persona_data": data, "persona_tokens_in": tin, "persona_tokens_out": tout}


def planning_feature_handler(node_id: str, state: dict) -> dict:
    spec = state.get("spec", "")
    research = state.get("research", state.get("analysis", {}))
    _track_task(task_id=f"wf_{node_id}", title="機能分析", description="機能の優先順位付けとスコープ定義", status="in_progress", assignee="product-manager", priority="high", phase="product-planning", node_id=node_id)
    # Use Moonshot/KIMI for feature analysis (different provider for parallelism)
    prov, mdl = _pick_cheap_provider("moonshot", "zhipu", "gemini", "anthropic")
    print(f"[planning:feature] Analyzing features with KANO model using {prov}/{mdl}...")
    text, tin, tout = _call_llm(mdl, (
        "You are a product strategist. Perform KANO analysis and feature prioritization.\n\n"
        "Output JSON with keys:\n"
        "- kano_features: [{feature, category: 'must-be'|'one-dimensional'|'attractive'|'indifferent', "
        "user_delight: -1.0 to 1.0, implementation_cost: 'low'|'medium'|'high', rationale}]\n"
        "- features: [{feature, category, selected: boolean, priority: 'must'|'should'|'could'|'wont', "
        "user_delight, implementation_cost, rationale}]\n"
        "- recommendations: [string]\n\n"
        "List 6-10 features. Output ONLY valid JSON, no markdown fences.\n\n"
        f"Product:\n{spec}\n\n"
        f"Research Context:\n{_json.dumps(research, ensure_ascii=False)[:4000]}"
    ), max_tokens=8192, provider=prov)
    try:
        repaired = _repair_truncated_json(text)
        data = _json.loads(repaired)
    except Exception as e:
        print(f"[planning:feature] JSON parse failed: {e}")
        print(f"[planning:feature] Raw text (first 500): {text[:500]}")
        data = {"kano_features": [], "features": [], "recommendations": []}
    print(f"[planning:feature] Done. {tin}in/{tout}out (provider: {prov}), kano={len(data.get('kano_features',[]))}, feats={len(data.get('features',[]))}")
    _track_task(task_id=f"wf_{node_id}", title="機能分析", description="", status="done", assignee="product-manager")
    return {"feature_data": data, "feature_tokens_in": tin, "feature_tokens_out": tout}


def planning_story_architect_handler(node_id: str, state: dict) -> dict:
    """story-architect: User journey mapping, JTBD analysis, and story decomposition."""
    spec = state.get("spec", "")
    research = state.get("research", state.get("analysis", {}))
    _track_task(task_id=f"wf_{node_id}", title="ストーリー設計", description="ユーザージャーニー・JTBD・ストーリー分解", status="in_progress", assignee="product-manager", priority="high", phase="product-planning", node_id=node_id)
    prov, mdl = _pick_cheap_provider("zhipu", "gemini", "moonshot", "anthropic")
    print(f"[planning:story-architect] Designing journeys & JTBD with {prov}/{mdl}...")
    text, tin, tout = _call_llm(mdl, (
        "You are a senior UX strategist specializing in story mapping and Jobs-to-be-Done framework.\n\n"
        "Output JSON with these exact keys:\n"
        "- user_journeys: [{persona_name, touchpoints:[{phase:'awareness'|'consideration'|'acquisition'|'usage'|'advocacy',\n"
        "    persona, action, touchpoint, emotion:'positive'|'neutral'|'negative', pain_point?, opportunity?}]}]\n"
        "  Create 2-3 journey maps with 5 phases each.\n"
        "- job_stories: JTBD format:\n"
        "  [{situation:'When...', motivation:'I want to...', outcome:'So I can...',\n"
        "    priority:'core'|'supporting'|'aspirational', related_features:[]}]\n"
        "  Generate 5-8 job stories covering core needs.\n"
        "- story_map: {backbone:[], walking_skeleton:[], iterations:[{name, stories:[]}]}\n\n"
        "Output ONLY valid JSON, no markdown fences.\n\n"
        f"Product:\n{spec}\n\n"
        f"Research Context:\n{_json.dumps(research, ensure_ascii=False)[:4000]}"
    ), max_tokens=8192, provider=prov)
    try:
        repaired = _repair_truncated_json(text)
        data = _json.loads(repaired)
    except Exception as e:
        print(f"[planning:story-architect] JSON parse failed: {e}")
        data = {"user_journeys": [], "job_stories": [], "story_map": {}}
    print(f"[planning:story-architect] Done. {tin}in/{tout}out (provider: {prov}), journeys={len(data.get('user_journeys',[]))}, jtbd={len(data.get('job_stories',[]))}")
    _track_task(task_id=f"wf_{node_id}", title="ストーリー設計", description="", status="done", assignee="product-manager")
    return {"story_data": data, "story_tokens_in": tin, "story_tokens_out": tout}


def planning_solution_architect_handler(node_id: str, state: dict) -> dict:
    """solution-architect: IA analysis, actor/role modeling, use case catalog."""
    spec = state.get("spec", "")
    research = state.get("research", state.get("analysis", {}))
    _track_task(task_id=f"wf_{node_id}", title="ソリューション設計", description="IA分析・アクター/ロールモデリング・ユースケース設計", status="in_progress", assignee="architect", priority="high", phase="product-planning", node_id=node_id)
    prov, mdl = _pick_cheap_provider("anthropic", "gemini", "moonshot", "zhipu")
    print(f"[planning:solution-architect] Designing IA & use cases with {prov}/{mdl}...")
    text, tin, tout = _call_llm(mdl, (
        "You are a senior solution architect specializing in information architecture and system design.\n\n"
        "Output JSON with these exact keys:\n"
        "- ia_analysis: {site_map:[{id, label, description?, children?:[], priority:'primary'|'secondary'|'utility'}],\n"
        "   navigation_model:'hierarchical'|'flat'|'hub-and-spoke'|'matrix',\n"
        "   key_paths:[{name, steps:[]}]}\n"
        "  Design the app's navigation structure and 3-5 key user flows.\n"
        "- actors: [{name, type:'primary'|'secondary'|'external_system', description, goals:[], interactions:[]}]\n"
        "  Identify 3-6 actors including end users, admins, and external systems.\n"
        "- roles: [{name, responsibilities:[], permissions:[], related_actors:[]}]\n"
        "  Define 2-5 roles with clear permission boundaries.\n"
        "- use_cases: [{id, title, actor, category, sub_category,\n"
        "    preconditions:[], main_flow:[], alternative_flows?:[{condition, steps:[]}],\n"
        "    postconditions:[], priority:'must'|'should'|'could', related_stories?:[]}]\n"
        "  Generate 6-10 use cases covering core functionality.\n\n"
        "Output ONLY valid JSON, no markdown fences.\n\n"
        f"Product:\n{spec}\n\n"
        f"Research Context:\n{_json.dumps(research, ensure_ascii=False)[:4000]}"
    ), max_tokens=12288, provider=prov)
    try:
        repaired = _repair_truncated_json(text)
        data = _json.loads(repaired)
    except Exception as e:
        print(f"[planning:solution-architect] JSON parse failed: {e}")
        data = {"ia_analysis": {}, "actors": [], "roles": [], "use_cases": []}
    print(f"[planning:solution-architect] Done. {tin}in/{tout}out (provider: {prov}), actors={len(data.get('actors',[]))}, use_cases={len(data.get('use_cases',[]))}")
    _track_task(task_id=f"wf_{node_id}", title="ソリューション設計", description="", status="done", assignee="architect")
    return {"solution_data": data, "solution_tokens_in": tin, "solution_tokens_out": tout}


def planning_synthesizer_handler(node_id: str, state: dict) -> dict:
    persona_data = state.get("persona_data", {})
    feature_data = state.get("feature_data", {})
    story_data = state.get("story_data", {})
    solution_data = state.get("solution_data", {})
    spec = state.get("spec", "")
    _track_task(task_id=f"wf_{node_id}", title="プランニング統合", description="計画結果の統合", status="in_progress", assignee="product-manager", priority="high", phase="product-planning", node_id=node_id)
    print(f"[planning:synthesizer] Synthesizing planning results...")

    # Gather registered agents and skills for context
    agent_names = [a.get("name", a.get("id", "")) for a in route_store.agents.values()]
    skill_names = list(_skill_registry.keys())

    # Use Gemini Flash for synthesis (large context window, cost-effective)
    synth_prov, synth_mdl = _pick_cheap_provider("gemini", "anthropic", "moonshot")
    print(f"[planning:synthesizer] Using {synth_prov}/{synth_mdl} for synthesis...")
    text, tin, tout = _call_llm(synth_mdl, (
        "You are a senior product manager and project planner. Synthesize analysis into a complete plan.\n\n"
        "Output JSON with these exact keys:\n"
        "- personas: [{name, role, age_range, goals:[], frustrations:[], tech_proficiency, context}]\n"
        "- user_stories: [{role, action, benefit, acceptance_criteria:[], priority}]\n"
        "- kano_features: [{feature, category, user_delight, implementation_cost, rationale}]\n"
        "- features: [{feature, category, selected: boolean, priority, user_delight, implementation_cost, rationale}]\n"
        "- recommendations: [string]\n"
        "- business_model: {value_propositions:[], customer_segments:[], channels:[], revenue_streams:[]}\n"
        "- user_journeys: array of journey maps per persona:\n"
        "  [{persona_name, touchpoints:[{phase:'awareness'|'consideration'|'acquisition'|'usage'|'advocacy',\n"
        "    persona, action, touchpoint, emotion:'positive'|'neutral'|'negative', pain_point?, opportunity?}]}]\n"
        "  Create 1 journey map per persona with 5 phases each.\n"
        "- job_stories: JTBD format stories:\n"
        "  [{situation:'When...', motivation:'I want to...', outcome:'So I can...',\n"
        "    priority:'core'|'supporting'|'aspirational', related_features:[]}]\n"
        "  Generate 5-8 job stories covering core needs.\n"
        "- ia_analysis: Information Architecture:\n"
        "  {site_map:[{id, label, description?, children?:[], priority:'primary'|'secondary'|'utility'}],\n"
        "   navigation_model:'hierarchical'|'flat'|'hub-and-spoke'|'matrix',\n"
        "   key_paths:[{name, steps:[]}]}\n"
        "  Design the app's navigation structure and 3-5 key user flows.\n"
        "- actors: Actor analysis (who interacts with the system):\n"
        "  [{name, type:'primary'|'secondary'|'external_system', description, goals:[], interactions:[]}]\n"
        "  Identify 3-6 actors including end users, admins, and external systems.\n"
        "- roles: Role analysis (RBAC model):\n"
        "  [{name, responsibilities:[], permissions:[], related_actors:[]}]\n"
        "  Define 2-5 roles with clear permission boundaries.\n"
        "- use_cases: Use case catalog with categories:\n"
        "  [{id, title, actor, category (大カテゴリ e.g. 'ワークフロー管理','プロジェクト管理','外部連携'),\n"
        "    sub_category (中カテゴリ e.g. '作成・編集','実行・監視','設定'),\n"
        "    preconditions:[], main_flow:[], alternative_flows?:[{condition, steps:[]}],\n"
        "    postconditions:[], priority:'must'|'should'|'could', related_stories?:[]}]\n"
        "  Generate 6-10 use cases covering core functionality. main_flow is step-by-step.\n"
        "  Group use cases under 3-5 大カテゴリ, each with 1-3 中カテゴリ.\n"
        "- recommended_milestones: Suggested milestones based on analysis:\n"
        "  [{id, name, criteria (measurable completion condition), rationale (why this milestone matters),\n"
        "    phase:'alpha'|'beta'|'release', depends_on_use_cases?:[UC IDs]}]\n"
        "  Generate 5-8 milestones covering alpha (core MVP), beta (extended features), release (production-ready).\n"
        "  Each milestone should have clear, testable criteria. Reference relevant use case IDs.\n"
        "- epics: [{id, name, description, use_cases:[], priority, stories:[]}]\n"
        "  Group features into 3-6 epics. use_cases are concrete user scenarios.\n"
        "- plan_estimates: an array of 3 plans with these presets:\n"
        "  [{preset: 'minimal', label, description, total_effort_hours, total_cost_usd, duration_weeks,\n"
        "    epics:[{id, name, description, use_cases:[], priority, stories:[]}],\n"
        "    wbs:[{id, epic_id, title, description, assignee_type, assignee, skills:[], depends_on:[], effort_hours, start_day, duration_days, status:'pending'}],\n"
        "    agents_used:[], skills_used:[]}]\n"
        "  - minimal: Must-have features only, lowest cost, shortest duration (AI-only, 1-2 agents)\n"
        "  - standard: Must + Should features, balanced cost/quality (3-4 agents + some skills)\n"
        "  - full: All features incl. attractive, highest quality (5+ agents, all relevant skills)\n"
        "  WBS items should have realistic dependencies (depends_on: previous item IDs). Assign AI agents from the available list.\n"
        "  start_day and duration_days should form a realistic timeline.\n\n"
        "Output ONLY valid JSON.\n\n"
        f"Product: {spec}\n\n"
        f"Available AI Agents: {_json.dumps(agent_names[:20], ensure_ascii=False)}\n"
        f"Available Skills: {_json.dumps(skill_names[:30], ensure_ascii=False)}\n\n"
        f"Persona Analysis:\n{_json.dumps(persona_data, ensure_ascii=False)[:5000]}\n\n"
        f"Feature Analysis:\n{_json.dumps(feature_data, ensure_ascii=False)[:5000]}\n\n"
        f"Story/Journey Analysis:\n{_json.dumps(story_data, ensure_ascii=False)[:5000]}\n\n"
        f"Solution Architecture:\n{_json.dumps(solution_data, ensure_ascii=False)[:5000]}"
    ), max_tokens=16384, provider=synth_prov)
    try:
        repaired = _repair_truncated_json(text)
        planning = _json.loads(repaired)
    except Exception as e:
        print(f"[planning:synthesizer] JSON parse failed: {e}")
        print(f"[planning:synthesizer] Raw text (first 1000): {text[:1000]}")
        planning = {
            **persona_data,
            **feature_data,
            **story_data,
            **solution_data,
        }
    print(f"[planning:synthesizer] Done. {tin}in/{tout}out, personas={len(planning.get('personas',[]))}, kano={len(planning.get('kano_features',[]))}")
    _track_task(task_id=f"wf_{node_id}", title="プランニング統合", description="", status="done", assignee="product-manager")

    # ── Design Token Analysis (runs as part of planning synthesis) ──
    design_tokens = _generate_design_tokens(spec, planning)
    if design_tokens:
        planning["design_tokens"] = design_tokens

    return {"planning": planning}


def _generate_design_tokens(spec: str, planning: dict) -> dict | None:
    """Analyze personas and KANO features to recommend design tokens using UI UX Pro Max methodology."""
    personas = planning.get("personas", [])
    kano = planning.get("kano_features", [])
    if not personas and not kano:
        return None

    persona_summary = ", ".join(
        f"{p.get('name', '?')} ({p.get('role', '?')}, {p.get('tech_proficiency', '?')})" for p in personas[:5]
    )
    kano_summary = ", ".join(f"{k.get('feature', '?')} [{k.get('category', '?')}]" for k in kano[:8])
    business = planning.get("business_model", {})
    segments = ", ".join(business.get("customer_segments", [])[:5])

    prov, mdl = _pick_cheap_provider("gemini", "zhipu", "moonshot", "anthropic")
    # Query skill database for matching design patterns
    product_keywords = _infer_product_type(spec, kano)
    skill_design_system = _query_design_system(product_keywords)
    skill_ux_rules = _query_ux_guidelines()
    skill_context = ""
    if skill_design_system:
        skill_context += f"\n\nREFERENCE DESIGN SYSTEM (from proven patterns database):\n{skill_design_system}\n"
    if skill_ux_rules:
        skill_context += f"\nUX BEST PRACTICES:\n{skill_ux_rules}\n"
    print(f"[planning:design-tokens] Generating design tokens with {prov}/{mdl}...")
    text, tin, tout = _call_llm(mdl, (
        "You are a senior UI/UX design system architect. Based on the user persona analysis and feature priorities, "
        "recommend a cohesive design token system.\n\n"
        "Output JSON with these exact keys:\n"
        "- style: {name (e.g. 'Dark Mode OLED','Glassmorphism','Minimalism'), keywords:[], best_for, performance, accessibility}\n"
        "- colors: {primary (hex), secondary (hex), cta (hex), background (hex), text (hex), notes}\n"
        "- typography: {heading (font name), body (font name), mood:[], google_fonts_url?}\n"
        "- effects: [string] (e.g. 'glass blur', 'subtle glow', 'smooth transitions 200ms')\n"
        "- anti_patterns: [string] (things to avoid for this audience)\n"
        "- rationale: string (explain WHY these tokens match the target users)\n\n"
        "Consider:\n"
        "- User tech proficiency → complexity level\n"
        "- User age range → readability, contrast\n"
        "- KANO 'must-be' features → must be prominent in UI\n"
        "- KANO 'attractive' features → visual delight opportunities\n"
        "- Business segments → professional vs consumer aesthetics\n"
        f"{skill_context}\n"
        "Output ONLY valid JSON.\n\n"
        f"Product: {spec}\n"
        f"Personas: {persona_summary}\n"
        f"KANO Features: {kano_summary}\n"
        f"Customer Segments: {segments}"
    ), provider=prov)
    try:
        tokens = _json.loads(_repair_truncated_json(text))
        print(f"[planning:design-tokens] Done. Style: {tokens.get('style', {}).get('name', '?')}. {tin}in/{tout}out (provider: {prov})")
        return tokens
    except Exception as e:
        print(f"[planning:design-tokens] Parse failed: {e}. {tin}in/{tout}out")
        return None


# ── Design Phase Handlers ──

def _design_handler(node_id: str, state: dict, *, llm_model: str, provider: str, model_label: str, pattern_name: str, style_hint: str, task_title: str = "", task_assignee: str = "ui-designer") -> dict:
    spec = state.get("spec", "")
    features = state.get("features", state.get("selected_features", []))
    analysis = state.get("analysis", {})
    # Extract design tokens from planning analysis for consistent styling
    design_tokens = analysis.get("design_tokens", {})
    dt_section = ""
    if design_tokens:
        dt_colors = design_tokens.get("colors", {})
        dt_typo = design_tokens.get("typography", {})
        dt_style = design_tokens.get("style", {})
        dt_section = (
            f"\n\nDESIGN SYSTEM (from persona analysis - MUST follow strictly):\n"
            f"- Style: {dt_style.get('name', 'N/A')} ({', '.join(dt_style.get('keywords', []))})\n"
            f"- Target: {dt_style.get('best_for', 'General audience')}\n"
            f"- Colors: primary={dt_colors.get('primary','')}, secondary={dt_colors.get('secondary','')}, "
            f"cta={dt_colors.get('cta','')}, bg={dt_colors.get('background','')}, text={dt_colors.get('text','')}\n"
            f"- Color Notes: {dt_colors.get('notes', '')}\n"
            f"- Typography: heading={dt_typo.get('heading','Inter')}, body={dt_typo.get('body','Inter')}\n"
            f"- Typography Mood: {', '.join(dt_typo.get('mood', []))}\n"
            f"- Google Fonts: {dt_typo.get('google_fonts_url', 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap')}\n"
            f"- Visual Effects: {', '.join(design_tokens.get('effects', []))}\n"
            f"- MUST AVOID: {', '.join(design_tokens.get('anti_patterns', []))}\n"
            f"- Accessibility: {dt_style.get('accessibility', 'WCAG AA minimum')}\n"
            f"- Rationale: {design_tokens.get('rationale', '')}\n"
        )
    if task_title:
        _track_task(task_id=f"wf_{node_id}", title=task_title, description=f"{model_label}によるデザインパターン生成", status="in_progress", assignee=task_assignee, priority="high", phase="design-generation", node_id=node_id)
    # Query skill DB for additional UX guidelines
    _ux_rules = _query_ux_guidelines("animation accessibility responsive dark-mode")
    _ux_section = f"\n\nUX GUIDELINES (from professional design database):\n{_ux_rules}\n" if _ux_rules else ""

    print(f"[design:{node_id}] Generating {pattern_name} design with {model_label} ({provider}/{llm_model})...")
    text, tin, tout = _call_llm(llm_model, (
        f"You are a senior UI/UX designer specializing in {style_hint} interfaces for production SaaS products.\n\n"
        "Generate a COMPLETE, SELF-CONTAINED single HTML file (target: 25-40KB) implementing a production-quality prototype.\n\n"
        "ARCHITECTURE REQUIREMENTS:\n"
        "- Single HTML file with ALL CSS and JavaScript inline\n"
        "- Use CSS custom properties (--var-name) for theming\n"
        "- Import Google Fonts via <link> in <head>\n"
        "- Include Tailwind CSS CDN: <script src='https://cdn.tailwindcss.com'></script>\n"
        "- Responsive: mobile-first (320px), tablet (768px), desktop (1200px+)\n\n"
        "VISUAL QUALITY REQUIREMENTS:\n"
        "- TYPOGRAPHY HIERARCHY: h1(2rem/700), h2(1.5rem/600), h3(1.25rem/600), body(0.875rem/400), caption(0.75rem)\n"
        "- SPACING SCALE: 4px grid system (p-1=4px, p-2=8px, p-3=12px, p-4=16px, p-6=24px, p-8=32px)\n"
        "- ELEVATION: shadow-sm(cards), shadow-md(dropdowns), shadow-lg(modals), shadow-xl(floating)\n"
        "- BORDERS: 1px borders with opacity 0.1-0.2, rounded-lg(8px) for cards, rounded-full for avatars\n"
        "- TRANSITIONS: all interactive elements 150-200ms ease-out\n"
        "- MICRO-INTERACTIONS: hover:scale(1.02) for cards, hover:brightness(1.1) for buttons\n"
        "- STATES: every interactive element must have hover, focus, active, disabled states\n"
        "- GLASS EFFECTS: Use backdrop-filter:blur(12px) + bg-opacity for glassmorphism elements\n\n"
        "COMPONENT REQUIREMENTS:\n"
        "- Sidebar navigation with active states, icons (use SVG or emoji as fallback), collapsible\n"
        "- Header with breadcrumbs, search, user avatar\n"
        "- Data cards with subtle gradients, hover elevation, click feedback\n"
        "- Status badges with semantic colors (green=success, amber=warning, red=error, blue=info)\n"
        "- Progress indicators (bars, circular, step indicators)\n"
        "- Modal/dialog with backdrop blur and smooth enter/exit animation\n"
        "- Toast notification system\n"
        "- Data tables with striped rows, sort indicators, hover highlight\n"
        "- Form inputs with focus ring, validation states, floating labels\n"
        "- Loading skeletons (pulsing placeholder blocks)\n\n"
        "CONTENT REQUIREMENTS:\n"
        "- Use realistic Japanese/English mixed content, NOT placeholder text\n"
        "- Include actual data values, chart mockups (CSS-only bar/donut charts), metrics\n"
        "- Navigation items with badge counts\n"
        "- User presence indicators (online dot, last active)\n\n"
        "DO NOT:\n"
        "- Generate wireframe-quality output\n"
        "- Use flat boxes without depth or hierarchy\n"
        "- Skip hover/focus states\n"
        "- Use generic placeholder text like 'Lorem ipsum'\n"
        "- Output less than 20KB of HTML\n"
        f"{dt_section}"
        f"{_ux_section}"
        "\nOutput ONLY the raw HTML code — no markdown fences, no explanations.\n\n"
        f"Product:\n{spec}\n\n"
        f"Selected Features:\n{_json.dumps(features, ensure_ascii=False)[:6000]}\n\n"
        f"Analysis (personas, KANO, business model):\n{_json.dumps(analysis, ensure_ascii=False)[:4000]}"
    ), max_tokens=16384, provider=provider)
    html = _strip_html_fences(text)
    cost = _calc_cost(llm_model, tin, tout)
    print(f"[design:{node_id}] Done. {len(html)} chars, ${cost:.4f}")
    if task_title:
        _track_task(task_id=f"wf_{node_id}", title=task_title, description="", status="done", assignee=task_assignee)
    return {
        f"design_{node_id}": {
            "html": html,
            "model": model_label,
            "pattern_name": pattern_name,
            "tokens_in": tin,
            "tokens_out": tout,
            "cost_usd": cost,
        }
    }


def design_claude_handler(node_id: str, state: dict) -> dict:
    return _design_handler(node_id, state, llm_model=MODEL, provider="anthropic", model_label="Claude Sonnet 4.6", pattern_name="Modern Minimal", style_hint="clean, minimal, whitespace-focused", task_title="デザイン生成 (Claude)")


def design_openai_handler(node_id: str, state: dict) -> dict:
    return _design_handler(node_id, state, llm_model="gpt-5-mini", provider="openai", model_label="GPT-5 Mini", pattern_name="Dashboard-First", style_hint="data-rich dashboard with cards and charts", task_title="デザイン生成 (OpenAI)")


def design_gemini_handler(node_id: str, state: dict) -> dict:
    # Use Gemini if configured
    if client_gemini:
        return _design_handler(node_id, state, llm_model=GEMINI_MODEL, provider="gemini", model_label="Gemini 3 Flash", pattern_name="Card-Based", style_hint="card-based layout with visual hierarchy", task_title="デザイン生成 (Gemini)")
    # Fallback to Moonshot/Kimi
    if client_moonshot:
        return _design_handler(node_id, state, llm_model="kimi-k2.5", provider="moonshot", model_label="Kimi K2.5", pattern_name="Card-Based", style_hint="card-based layout with visual hierarchy", task_title="デザイン生成 (Gemini)")
    # Fallback to OpenAI
    return _design_handler(node_id, state, llm_model="gpt-4.1-nano", provider="openai", model_label="GPT-4.1 Nano", pattern_name="Card-Based", style_hint="card-based layout with visual hierarchy", task_title="デザイン生成 (Gemini)")


def design_evaluator_handler(node_id: str, state: dict) -> dict:
    designs = {}
    for key in ["design_claude-designer", "design_openai-designer", "design_gemini-designer"]:
        if key in state:
            designs[key] = state[key]
    _track_task(task_id=f"wf_{node_id}", title="デザイン評価", description="3つのデザイン案を比較評価", status="in_progress", assignee="design-reviewer", priority="high", phase="design-generation", node_id=node_id)
    print(f"[design:evaluator] Evaluating {len(designs)} design variants...")
    design_summaries = []
    for key, d in designs.items():
        html = d.get("html", "")
        design_summaries.append(f"Design: {d.get('pattern_name', 'Unknown')} (model: {d.get('model', '?')})\nHTML preview ({len(html)} chars):\n{html[:2000]}")

    text, tin, tout = _call_llm(MODEL, (
        "You are a senior UX/UI evaluator. Score each design variant on 4 criteria (0.0-1.0).\n"
        "Each design was generated by a DIFFERENT AI model, so scores should reflect genuine differences.\n\n"
        "Output JSON with key 'variants': [{\n"
        "  id: string, model: string, pattern_name: string, description: string,\n"
        "  scores: {ux_quality: 0-1, code_quality: 0-1, performance: 0-1, accessibility: 0-1}\n"
        "}]\n\n"
        "Output ONLY valid JSON.\n\n"
        + "\n\n---\n\n".join(design_summaries)
    ), provider="anthropic")
    try:
        evaluation = _json.loads(_strip_json_fences(text))
    except Exception:
        evaluation = {"variants": []}

    # Merge HTML into variants
    variants = evaluation.get("variants", [])
    design_list = list(designs.values())
    for i, v in enumerate(variants):
        if i < len(design_list):
            v["preview_html"] = design_list[i].get("html", "")
            v["cost_usd"] = design_list[i].get("cost_usd", 0)
            v["tokens"] = {"in": design_list[i].get("tokens_in", 0), "out": design_list[i].get("tokens_out", 0)}
            if "model" not in v:
                v["model"] = design_list[i].get("model", "unknown")
            if "pattern_name" not in v:
                v["pattern_name"] = design_list[i].get("pattern_name", "Untitled")
            if "id" not in v:
                v["id"] = f"variant-{i}"

    print(f"[design:evaluator] Done. {len(variants)} variants scored.")
    _track_task(task_id=f"wf_{node_id}", title="デザイン評価", description="", status="done", assignee="design-reviewer")
    return {"design": {"variants": variants}, "variants": variants}


# ── Development Phase Handlers ──

def dev_planner_handler(node_id: str, state: dict) -> dict:
    spec = state.get("spec", "")
    selected_features = state.get("selected_features", [])
    analysis = state.get("analysis", {})
    design = state.get("design", {})
    milestones = state.get("milestones", [])
    iteration = state.get("_build_iteration", 0)
    review_feedback = state.get("review_feedback", "")

    # Gather full context from all previous phases
    research = state.get("research", {})
    design_tokens = analysis.get("design_tokens", {})
    selected_design = design.get("selected", design.get("variants", [{}])[0] if design.get("variants") else {})

    parts = [
        "You are a senior software architect planning the implementation of a product.\n"
        "You have access to complete research, analysis, and design context from previous phases.\n"
        "Create a detailed implementation plan that is consistent with all prior decisions.\n",
        f"Product Spec:\n{spec}",
    ]
    if research:
        parts.append(f"Market Research:\n{_json.dumps(research, ensure_ascii=False)[:2000]}")
    if analysis:
        parts.append(f"UX Analysis (personas, KANO, business model):\n{_json.dumps(analysis, ensure_ascii=False)[:3000]}")
    if design_tokens:
        parts.append(f"Design System:\n{_json.dumps(design_tokens, ensure_ascii=False)[:1500]}")
    if selected_design:
        parts.append(f"Selected Design Pattern: {selected_design.get('pattern_name', 'N/A')} (by {selected_design.get('model', 'N/A')})")
    parts.append(f"Selected Features:\n{_json.dumps(selected_features, ensure_ascii=False)[:4000]}")
    if milestones:
        parts.append(f"Milestones:\n{_json.dumps(milestones, ensure_ascii=False)}")
    if iteration > 0 and review_feedback:
        parts.append(f"Previous review feedback (iteration {iteration}):\n{review_feedback}")
        parts.append("Revise the plan to address the feedback.")
    parts.append(
        "\nOutput JSON: {project_name, tech_stack, components:[], implementation_steps:[], data_model:[]}. "
        "Output ONLY valid JSON."
    )

    _track_task(task_id=f"wf_{node_id}", title="実装計画", description="アーキテクチャ設計と実装計画の策定", status="in_progress", assignee="architect", priority="high", phase="iterative-development", node_id=node_id)
    print(f"[dev:planner] Iteration {iteration}, planning...")
    text, tin, tout = _agent_call_llm("architect", MODEL, "\n\n".join(parts))
    try:
        build_plan = _json.loads(_strip_json_fences(text))
    except Exception:
        build_plan = {"raw_plan": text}
    print(f"[dev:planner] Done. {tin}in/{tout}out")
    _track_task(task_id=f"wf_{node_id}", title="実装計画", description="", status="done", assignee="architect")
    return {
        "build_plan": build_plan,
        "plan_tokens_in": tin,
        "plan_tokens_out": tout,
        "_build_iteration": iteration,
    }


def dev_coder_handler(node_id: str, state: dict) -> dict:
    spec = state.get("spec", "")
    build_plan = state.get("build_plan", {})
    selected_features = state.get("selected_features", [])
    design = state.get("design", {})
    milestones = state.get("milestones", [])
    iteration = state.get("_build_iteration", 0)
    previous_code = state.get("code", "")
    review_feedback = state.get("review_feedback", "")

    # Inject full context from all previous phases
    analysis = state.get("analysis", {})
    research = state.get("research", {})
    design_tokens = analysis.get("design_tokens", {})
    selected_design = design.get("selected", {})
    selected_html = selected_design.get("preview_html", "")

    # Enhanced prompt with design system
    dt_section = ""
    if design_tokens:
        dt_colors = design_tokens.get("colors", {})
        dt_typo = design_tokens.get("typography", {})
        dt_style = design_tokens.get("style", {})
        dt_section = (
            f"\nDESIGN SYSTEM (MUST follow):\n"
            f"- Style: {dt_style.get('name', 'N/A')}\n"
            f"- Colors: primary={dt_colors.get('primary','')}, secondary={dt_colors.get('secondary','')}, "
            f"cta={dt_colors.get('cta','')}, bg={dt_colors.get('background','')}, text={dt_colors.get('text','')}\n"
            f"- Typography: heading={dt_typo.get('heading','Inter')}, body={dt_typo.get('body','Inter')}\n"
            f"- Effects: {', '.join(design_tokens.get('effects', []))}\n"
            f"- AVOID: {', '.join(design_tokens.get('anti_patterns', []))}\n"
        )

    parts = [
        "You are an expert full-stack developer. Build a COMPLETE, SELF-CONTAINED "
        "single HTML file implementing the product.\n\n"
        "Requirements:\n"
        "- ALL HTML, CSS, and JavaScript inline in a single file\n"
        "- Include <script src='https://cdn.tailwindcss.com'></script>\n"
        "- Import Google Fonts via <link> tag\n"
        "- Use CSS custom properties for theming\n"
        "- Responsive: mobile-first, tablet, desktop breakpoints\n"
        "- MUST implement ALL selected features as functional UI\n"
        "- Include realistic sample data (Japanese/English mixed)\n"
        "- Add hover/focus/active states for all interactive elements\n"
        "- Include loading skeletons, error states, empty states\n"
        "- Production-quality: not a wireframe, a real application\n"
        f"{dt_section}\n",
    ]
    if selected_html and len(selected_html) > 1000:
        # Pass reference design HTML (first 8K) as style reference
        parts.append(f"REFERENCE DESIGN (follow this visual style closely):\n{selected_html[:8000]}\n")
    if research:
        parts.append(f"Market Context:\n{_json.dumps(research, ensure_ascii=False)[:1500]}")
    if analysis:
        parts.append(f"UX Analysis:\n{_json.dumps(analysis, ensure_ascii=False)[:2000]}")
    parts.append(f"Build Plan:\n{_json.dumps(build_plan, ensure_ascii=False)[:4000]}")
    parts.append(f"Selected Features:\n{_json.dumps(selected_features, ensure_ascii=False)}")
    if milestones:
        parts.append(f"Milestones:\n{_json.dumps(milestones, ensure_ascii=False)}")
    if iteration > 0 and previous_code and review_feedback:
        parts.append(f"Iteration {iteration}. Previous issues:\n{review_feedback}\nFix ALL issues.")
    parts.append("\nOutput ONLY raw HTML code — no markdown fences, no explanations.")

    _track_task(task_id=f"wf_{node_id}", title="コーディング", description="機能実装とコード生成", status="in_progress", assignee="fullstack-builder", priority="high", phase="iterative-development", node_id=node_id)
    print(f"[dev:coder] Iteration {iteration}, building...")
    text, tin, tout = _agent_call_llm("fullstack-builder", MODEL, "\n\n".join(parts), max_tokens=16384)
    code = _strip_html_fences(text)

    output_path = project_root / "output" / f"lifecycle-dev-v{iteration}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(code)

    print(f"[dev:coder] Done. {len(code)} chars, saved to {output_path}")
    _track_task(task_id=f"wf_{node_id}", title="コーディング", description="", status="review", assignee="fullstack-builder")
    return {
        "frontend_code": code,
        "code": code,
        "build_tokens_in": tin,
        "build_tokens_out": tout,
        "generated_file": str(output_path),
    }


def dev_backend_builder_handler(node_id: str, state: dict) -> dict:
    """backend-builder: Generates API design, data models, and backend logic."""
    spec = state.get("spec", "")
    build_plan = state.get("build_plan", {})
    analysis = state.get("analysis", {})
    iteration = state.get("_build_iteration", 0)

    _track_task(task_id=f"wf_{node_id}", title="バックエンド実装", description="API設計・データモデル・ビジネスロジック", status="in_progress", assignee="backend-builder", priority="high", phase="iterative-development", node_id=node_id)
    print(f"[dev:backend-builder] Iteration {iteration}, building backend...")

    ia_analysis = analysis.get("ia_analysis", {})
    use_cases = analysis.get("use_cases", [])

    text, tin, tout = _agent_call_llm("backend-builder", MODEL, (
        "You are an expert backend architect. Design the complete backend for this product.\n\n"
        "Output JSON with these keys:\n"
        "- api_endpoints: [{method, path, description, request_body?, response, auth_required:boolean}]\n"
        "- data_models: [{name, fields:[{name, type, required, description}], relationships:[]}]\n"
        "- business_rules: [{name, description, trigger, conditions:[], actions:[]}]\n"
        "- integrations: [{service, purpose, api_type:'REST'|'GraphQL'|'WebSocket'|'gRPC'}]\n"
        "- error_handling: [{error_code, description, http_status, user_message}]\n\n"
        "Output ONLY valid JSON.\n\n"
        f"Product:\n{spec}\n\n"
        f"Build Plan:\n{_json.dumps(build_plan, ensure_ascii=False)[:4000]}\n\n"
        f"IA Analysis:\n{_json.dumps(ia_analysis, ensure_ascii=False)[:2000]}\n\n"
        f"Use Cases:\n{_json.dumps(use_cases, ensure_ascii=False)[:3000]}"
    ), max_tokens=12288)
    try:
        backend = _json.loads(_strip_json_fences(text))
    except Exception:
        backend = {"api_endpoints": [], "data_models": [], "business_rules": []}
    print(f"[dev:backend-builder] Done. {tin}in/{tout}out, endpoints={len(backend.get('api_endpoints',[]))}")
    _track_task(task_id=f"wf_{node_id}", title="バックエンド実装", description="", status="done", assignee="backend-builder")
    return {
        "backend_design": backend,
        "backend_tokens_in": tin,
        "backend_tokens_out": tout,
    }


def dev_integrator_handler(node_id: str, state: dict) -> dict:
    """integrator: Merges frontend + backend into unified artifact."""
    frontend_code = state.get("frontend_code", state.get("code", ""))
    backend_design = state.get("backend_design", {})
    build_plan = state.get("build_plan", {})
    spec = state.get("spec", "")
    iteration = state.get("_build_iteration", 0)

    _track_task(task_id=f"wf_{node_id}", title="統合", description="フロントエンド・バックエンドの統合", status="in_progress", assignee="integrator", priority="high", phase="iterative-development", node_id=node_id)
    print(f"[dev:integrator] Iteration {iteration}, integrating...")

    text, tin, tout = _agent_call_llm("integrator", MODEL, (
        "You are a senior integration engineer. Merge the frontend HTML application with the backend API design.\n\n"
        "Take the existing frontend HTML and enhance it by:\n"
        "1. Adding JavaScript fetch() calls to the designed API endpoints\n"
        "2. Implementing realistic data loading with mock responses\n"
        "3. Adding error handling for all API interactions\n"
        "4. Ensuring the data models align between frontend display and backend schema\n"
        "5. Adding loading states for all async operations\n\n"
        "Output the COMPLETE integrated HTML file. Output ONLY raw HTML code.\n\n"
        f"Product:\n{spec}\n\n"
        f"Backend API Design:\n{_json.dumps(backend_design, ensure_ascii=False)[:6000]}\n\n"
        f"Frontend HTML ({len(frontend_code)} chars):\n{frontend_code[:12000]}"
    ), max_tokens=16384)
    code = _strip_html_fences(text)

    output_path = project_root / "output" / f"lifecycle-integrated-v{iteration}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(code)

    print(f"[dev:integrator] Done. {len(code)} chars, saved to {output_path}")
    _track_task(task_id=f"wf_{node_id}", title="統合", description="", status="done", assignee="integrator")
    return {
        "code": code,
        "integrated_code": code,
        "integration_tokens_in": tin,
        "integration_tokens_out": tout,
        "generated_file": str(output_path),
    }


def dev_qa_engineer_handler(node_id: str, state: dict) -> dict:
    """qa-engineer: Quality assurance review with test scenarios."""
    code = state.get("code", state.get("integrated_code", ""))
    milestones = state.get("milestones", [])
    selected_features = state.get("selected_features", [])
    iteration = state.get("_build_iteration", 0)

    _track_task(task_id=f"wf_{node_id}", title="QAテスト", description="品質保証テストシナリオの設計と評価", status="in_progress", assignee="qa-engineer", priority="high", phase="iterative-development", node_id=node_id)
    print(f"[dev:qa-engineer] Iteration {iteration}, testing...")

    prov, mdl = _pick_cheap_provider("gemini", "anthropic", "moonshot")
    text, tin, tout = _call_llm(mdl, (
        "You are a senior QA engineer. Review the application code and create test evaluation.\n\n"
        "Output JSON with these keys:\n"
        "- test_scenarios: [{id, name, category:'functional'|'ui'|'integration'|'edge-case', steps:[], expected_result, status:'pass'|'fail'|'untestable', notes}]\n"
        "- coverage_score: 0.0-1.0 (what % of features are implemented)\n"
        "- qa_issues: [{severity:'critical'|'major'|'minor', component, description, recommendation}]\n"
        "- accessibility_audit: [{element, issue, wcag_criterion, fix}]\n"
        "- performance_notes: [{area, concern, recommendation}]\n\n"
        "Output ONLY valid JSON.\n\n"
        f"Features:\n{_json.dumps(selected_features, ensure_ascii=False)[:3000]}\n\n"
        f"Milestones:\n{_json.dumps(milestones, ensure_ascii=False)[:2000]}\n\n"
        f"Code ({len(code)} chars):\n{code[:14000]}"
    ), max_tokens=8192, provider=prov)
    try:
        qa_result = _json.loads(_strip_json_fences(text))
    except Exception:
        qa_result = {"test_scenarios": [], "coverage_score": 0.5, "qa_issues": []}
    print(f"[dev:qa-engineer] Done. {tin}in/{tout}out, scenarios={len(qa_result.get('test_scenarios',[]))}")
    _track_task(task_id=f"wf_{node_id}", title="QAテスト", description="", status="done", assignee="qa-engineer")
    return {
        "qa_result": qa_result,
        "qa_tokens_in": tin,
        "qa_tokens_out": tout,
    }


def dev_security_reviewer_handler(node_id: str, state: dict) -> dict:
    """security-reviewer: OWASP-based security review."""
    code = state.get("code", state.get("integrated_code", ""))
    backend_design = state.get("backend_design", {})
    iteration = state.get("_build_iteration", 0)

    _track_task(task_id=f"wf_{node_id}", title="セキュリティレビュー", description="OWASPベースのセキュリティ監査", status="in_progress", assignee="security-reviewer", priority="high", phase="iterative-development", node_id=node_id)
    print(f"[dev:security-reviewer] Iteration {iteration}, auditing...")

    prov, mdl = _pick_cheap_provider("anthropic", "gemini", "moonshot")
    text, tin, tout = _call_llm(mdl, (
        "You are a senior application security reviewer (OWASP specialist).\n"
        "Audit this application for security vulnerabilities.\n\n"
        "Output JSON with these keys:\n"
        "- vulnerabilities: [{id, severity:'critical'|'high'|'medium'|'low', category (OWASP Top 10 category), description, location, recommendation, cwe_id?}]\n"
        "- security_score: 0.0-1.0 (overall security posture)\n"
        "- auth_review: {has_auth:boolean, method, issues:[]}\n"
        "- data_handling: {pii_detected:boolean, encryption:boolean, issues:[]}\n"
        "- recommendations: [{priority:'immediate'|'short-term'|'long-term', action, rationale}]\n\n"
        "Output ONLY valid JSON.\n\n"
        f"Backend API Design:\n{_json.dumps(backend_design, ensure_ascii=False)[:4000]}\n\n"
        f"Code ({len(code)} chars):\n{code[:12000]}"
    ), max_tokens=8192, provider=prov)
    try:
        security_result = _json.loads(_strip_json_fences(text))
    except Exception:
        security_result = {"vulnerabilities": [], "security_score": 0.5, "recommendations": []}
    print(f"[dev:security-reviewer] Done. {tin}in/{tout}out, vulns={len(security_result.get('vulnerabilities',[]))}")
    _track_task(task_id=f"wf_{node_id}", title="セキュリティレビュー", description="", status="done", assignee="security-reviewer")
    return {
        "security_result": security_result,
        "security_tokens_in": tin,
        "security_tokens_out": tout,
    }


def dev_reviewer_handler(node_id: str, state: dict) -> dict:
    code = state.get("code", "")
    milestones = state.get("milestones", [])
    selected_features = state.get("selected_features", [])
    iteration = state.get("_build_iteration", 0)
    qa_result = state.get("qa_result", {})
    security_result = state.get("security_result", {})

    _track_task(task_id=f"wf_{node_id}", title="リリースレビュー", description="QA・セキュリティ結果を統合した最終評価", status="in_progress", assignee="reviewer", priority="high", phase="iterative-development", node_id=node_id)
    print(f"[dev:reviewer] Iteration {iteration}, reviewing (with QA + security context)...")

    # Build QA/Security summary for reviewer context
    qa_summary = ""
    if qa_result:
        qa_summary = (
            f"\n\nQA Results: coverage={qa_result.get('coverage_score', 'N/A')}, "
            f"issues={len(qa_result.get('qa_issues', []))}\n"
            f"{_json.dumps(qa_result, ensure_ascii=False)[:3000]}"
        )
    sec_summary = ""
    if security_result:
        sec_summary = (
            f"\n\nSecurity Audit: score={security_result.get('security_score', 'N/A')}, "
            f"vulns={len(security_result.get('vulnerabilities', []))}\n"
            f"{_json.dumps(security_result, ensure_ascii=False)[:3000]}"
        )

    text, tin, tout = _agent_call_llm("reviewer", MODEL, (
        "You are a senior release reviewer. You have QA and security audit results to incorporate.\n"
        "Review the application code, QA findings, and security audit for release readiness.\n"
        "Be STRICT in evaluation. Only mark milestones as 'satisfied' if code clearly implements them.\n\n"
        "Evaluate:\n"
        "1. Milestone completion against criteria\n"
        "2. Code quality: HTML semantics, CSS architecture, JS patterns\n"
        "3. QA findings: unresolved issues blocking release\n"
        "4. Security posture: critical/high vulnerabilities must be addressed\n"
        "5. UX quality: visual hierarchy, interaction states\n"
        "6. Accessibility and responsiveness\n\n"
        "Output JSON:\n"
        "- milestone_results: [{id, name, status:'satisfied'|'not_satisfied', reason}]\n"
        "- all_milestones_met: boolean\n"
        "- quality_score: 0.0-1.0 (be honest, 0.7+ means production-ready)\n"
        "- feedback: string (specific improvements needed)\n"
        "- ux_issues: [{element, issue, suggestion}]\n"
        "- release_blockers: [{source:'qa'|'security'|'code', description, severity}]\n\n"
        "Output ONLY valid JSON.\n\n"
        f"Milestones:\n{_json.dumps(milestones, ensure_ascii=False)}\n\n"
        f"Features:\n{_json.dumps(selected_features, ensure_ascii=False)}\n\n"
        f"Code ({len(code)} chars):\n{code[:14000]}"
        f"{qa_summary}{sec_summary}"
    ))
    try:
        review = _json.loads(_strip_json_fences(text))
    except Exception:
        # SAFE fallback: assume NOT met (don't skip review)
        review = {"all_milestones_met": False, "quality_score": 0.3, "feedback": "Review parse failed, re-review needed", "milestone_results": []}

    all_met = review.get("all_milestones_met", False)
    feedback = review.get("feedback", "")

    # Cost
    total_in = state.get("plan_tokens_in", 0) + state.get("build_tokens_in", 0) + tin
    total_out = state.get("plan_tokens_out", 0) + state.get("build_tokens_out", 0) + tout
    cost = (total_in * 3 / 1_000_000) + (total_out * 15 / 1_000_000)

    _track_task(task_id=f"wf_{node_id}", title="コードレビュー", description="", status="done" if all_met else "backlog", assignee="reviewer")
    print(f"[dev:reviewer] Done. All met: {all_met}, quality: {review.get('quality_score', 0):.2f}, cost: ${cost:.4f}")
    return {
        "review": review,
        "review_feedback": feedback,
        "all_milestones_met": all_met,
        "_build_iteration": iteration + 1,
        "estimated_cost_usd": cost,
    }


# ── Handler Registry (keyed by project name) ──

# LLM handlers keyed by DAG node IDs — shared between standalone and lifecycle workflows
_RESEARCH_HANDLERS = {
    "competitor-analyst": research_competitor_handler,
    "market-researcher": research_market_handler,
    "user-researcher": research_user_handler,
    "tech-evaluator": research_tech_handler,
    "research-synthesizer": research_synthesizer_handler,
}

_PLANNING_HANDLERS = {
    "persona-builder": planning_persona_handler,
    "story-architect": planning_story_architect_handler,
    "feature-analyst": planning_feature_handler,
    "solution-architect": planning_solution_architect_handler,
    "planning-synthesizer": planning_synthesizer_handler,
}

_DESIGN_HANDLERS = {
    "claude-designer": design_claude_handler,
    "openai-designer": design_openai_handler,
    "gemini-designer": design_gemini_handler,
    "design-evaluator": design_evaluator_handler,
}

_DEVELOPMENT_HANDLERS = {
    "planner": dev_planner_handler,
    "frontend-builder": dev_coder_handler,
    "backend-builder": dev_backend_builder_handler,
    "integrator": dev_integrator_handler,
    "qa-engineer": dev_qa_engineer_handler,
    "security-reviewer": dev_security_reviewer_handler,
    "reviewer": dev_reviewer_handler,
}

WORKFLOW_NODE_HANDLERS: dict[str, dict[str, object]] = {
    # Standalone workflows (backward compat)
    "market-research": _RESEARCH_HANDLERS,
    "product-planning": _PLANNING_HANDLERS,
    "design-generation": _DESIGN_HANDLERS,
    "iterative-development": {
        "planner": dev_planner_handler,
        "coder": dev_coder_handler,
        "reviewer": dev_reviewer_handler,
    },
}

# Monkey-patch register_workflow_project to auto-attach handlers for legacy demo workflows.
_original_register = route_store.register_workflow_project

def _patched_register(workflow_id, project, *, tenant_id="default"):
    result = _original_register(workflow_id, project, tenant_id=tenant_id)
    project_name = result.name if hasattr(result, "name") else ""
    if project_name in WORKFLOW_NODE_HANDLERS:
        handlers = WORKFLOW_NODE_HANDLERS[project_name]
        route_store.control_plane_store.set_handlers(
            workflow_id,
            node_handlers=handlers,
        )
        print(f"[lifecycle] Auto-attached {len(handlers)} node handlers for '{project_name}' (workflow: {workflow_id})")
    return result

route_store.register_workflow_project = _patched_register

print(f"Workflow handlers ready: {list(WORKFLOW_NODE_HANDLERS.keys())}")

# ── Mission Control API Endpoints ─────────────────────
from pylon.api.server import Request, Response, _Route, _compile_path
import time as _time

_cps = route_store.control_plane_store

# -- Workflow → Task Board bridge --

def _track_task(*, task_id: str, title: str, description: str, status: str,
                assignee: str, priority: str = "medium", phase: str = "",
                run_id: str = "", node_id: str = ""):
    """Create or update a task record linked to a workflow execution."""
    now = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    existing = _cps.get_queue_task_record(task_id)
    if existing:
        existing["status"] = status
        existing["updated_at"] = now
        if description:
            existing["description"] = description
        _cps.put_queue_task_record(existing)
        return existing
    record = {
        "id": task_id,
        "name": title,
        "title": title,
        "description": description,
        "status": status,
        "priority": priority,
        "assignee": assignee,
        "assigneeType": "ai",
        "payload": {"phase": phase, "run_id": run_id, "node_id": node_id},
        "created_at": now,
        "updated_at": now,
    }
    _cps.put_queue_task_record(record)
    return record


# -- Tasks CRUD (backed by queue_task_records) --

def _list_tasks(request: Request) -> Response:
    status = None
    if "?" in request.path:
        qs = request.path.split("?", 1)[1]
        for part in qs.split("&"):
            if part.startswith("status="):
                status = part.split("=", 1)[1]
    tasks = _cps.list_queue_task_records(status=status if status else None)
    return Response(body=tasks)

def _create_task(request: Request) -> Response:
    body = request.body or {}
    task_id = body.get("id") or f"task_{uuid.uuid4().hex[:8]}"
    now = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    record = {
        "id": task_id,
        "name": body.get("title", body.get("name", "")),
        "title": body.get("title", body.get("name", "")),
        "description": body.get("description", ""),
        "status": body.get("status", "backlog"),
        "priority": body.get("priority", "medium"),
        "assignee": body.get("assignee", ""),
        "assigneeType": body.get("assigneeType", "human"),
        "payload": body.get("payload", {}),
        "created_at": body.get("createdAt", now),
        "updated_at": now,
    }
    _cps.put_queue_task_record(record)
    return Response(status_code=201, body=record)

def _get_task(request: Request) -> Response:
    task_id = request.path_params.get("task_id", "")
    record = _cps.get_queue_task_record(task_id)
    if record is None:
        return Response(status_code=404, body={"error": "Task not found"})
    return Response(body=record)

def _update_task(request: Request) -> Response:
    task_id = request.path_params.get("task_id", "")
    existing = _cps.get_queue_task_record(task_id)
    if existing is None:
        return Response(status_code=404, body={"error": "Task not found"})
    body = request.body or {}
    now = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    for key in ("title", "name", "description", "status", "priority", "assignee", "assigneeType", "payload"):
        if key in body:
            existing[key] = body[key]
    if "title" in body:
        existing["name"] = body["title"]
    existing["updated_at"] = now
    _cps.put_queue_task_record(existing)
    return Response(body=existing)

def _delete_task(request: Request) -> Response:
    task_id = request.path_params.get("task_id", "")
    deleted = _cps.delete_queue_task_record(task_id)
    if not deleted:
        return Response(status_code=404, body={"error": "Task not found"})
    return Response(status_code=204)

http_server.api_server.add_route("GET", "/api/v1/tasks", _list_tasks)
http_server.api_server.add_route("POST", "/api/v1/tasks", _create_task)
http_server.api_server.add_route("GET", "/api/v1/tasks/{task_id}", _get_task)
http_server.api_server.add_route("PUT", "/api/v1/tasks/{task_id}", _update_task)
http_server.api_server.add_route("PATCH", "/api/v1/tasks/{task_id}", _update_task)
http_server.api_server.add_route("DELETE", "/api/v1/tasks/{task_id}", _delete_task)
print("API: /api/v1/tasks CRUD registered")

# -- Memory CRUD (backed by audit_records) --

_memory_counter = 0

def _list_memories(request: Request) -> Response:
    event_type = None
    if "?" in request.path:
        qs = request.path.split("?", 1)[1]
        for part in qs.split("&"):
            if part.startswith("event_type="):
                event_type = part.split("=", 1)[1]
    records = _cps.list_audit_records(
        tenant_id=None,
        event_type=event_type if event_type else "memory",
        limit=200,
        offset=0,
    )
    return Response(body=records)

def _create_memory(request: Request) -> Response:
    global _memory_counter
    body = request.body or {}
    _memory_counter += 1
    entry_id = body.get("id", int(_time.time() * 1000) + _memory_counter)
    now = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    record = {
        "id": int(entry_id),
        "entry_id": int(entry_id),
        "tenant_id": "default",
        "event_type": "memory",
        "actor": body.get("actor", "system"),
        "category": body.get("category", "general"),
        "title": body.get("title", ""),
        "content": body.get("content", ""),
        "details": body.get("details", body),
        "timestamp": body.get("timestamp", now),
    }
    _cps.put_audit_record(record)
    return Response(status_code=201, body=record)

def _delete_memory(request: Request) -> Response:
    entry_id = request.path_params.get("entry_id", "")
    existing = _cps.get_audit_record(int(entry_id))
    if existing is None:
        return Response(status_code=404, body={"error": "Memory not found"})
    # No delete method for audit records; mark as deleted
    existing["event_type"] = "memory_deleted"
    _cps.put_audit_record(existing)
    return Response(status_code=204)

http_server.api_server.add_route("GET", "/api/v1/memories", _list_memories)
http_server.api_server.add_route("POST", "/api/v1/memories", _create_memory)
http_server.api_server.add_route("DELETE", "/api/v1/memories/{entry_id}", _delete_memory)
print("API: /api/v1/memories CRUD registered")

# -- Agent activity (extends existing /agents with status) --

def _list_agents_activity(request: Request) -> Response:
    agents_list = []
    for agent_id, agent in route_store.agents.items():
        agents_list.append({
            **agent,
            "current_task": None,
            "uptime_seconds": int(_time.time()) % 86400,
        })
    return Response(body=agents_list)

def _get_agent_activity(request: Request) -> Response:
    agent_id = request.path_params.get("agent_id", "")
    agent = route_store.agents.get(agent_id)
    if agent is None:
        return Response(status_code=404, body={"error": "Agent not found"})
    # Check if agent has active tasks
    all_tasks = _cps.list_queue_task_records(status="in_progress")
    current_task = None
    for t in all_tasks:
        if t.get("assignee") == agent.get("name"):
            current_task = t
            break
    return Response(body={
        **agent,
        "current_task": current_task,
        "uptime_seconds": int(_time.time()) % 86400,
    })

http_server.api_server.add_route("GET", "/api/v1/agents/activity", _list_agents_activity)
http_server.api_server.add_route("GET", "/api/v1/agents/{agent_id}/activity", _get_agent_activity)
print("API: /api/v1/agents/activity registered")

# -- Agent CRUD --

def _create_agent(request: Request) -> Response:
    body = request.body or {}
    agent_id = uuid.uuid4().hex[:12]
    name = body["name"]
    agent = {
        "id": agent_id,
        "name": name,
        "model": body.get("model", f"anthropic/{MODEL}"),
        "role": body.get("role", ""),
        "autonomy": body.get("autonomy", "A2"),
        "tools": body.get("tools", []),
        "sandbox": body.get("sandbox", "gvisor"),
        "status": "ready",
        "tenant_id": "default",
        "team": body.get("team", ""),
        "skills": body.get("skills", _AGENT_DEFAULT_SKILLS.get(name, [])),
    }
    route_store.agents[agent_id] = agent
    return Response(status_code=201, body=agent)

def _update_agent(request: Request) -> Response:
    agent_id = request.path_params.get("agent_id", "")
    agent = route_store.agents.get(agent_id)
    if not agent:
        return Response(status_code=404, body={"error": "Agent not found"})
    body = request.body or {}
    for key in ["name", "model", "role", "autonomy", "tools", "sandbox", "status", "team", "skills"]:
        if key in body:
            agent[key] = body[key]
    return Response(body=agent)

def _delete_agent(request: Request) -> Response:
    agent_id = request.path_params.get("agent_id", "")
    if agent_id not in route_store.agents:
        return Response(status_code=404, body={"error": "Agent not found"})
    del route_store.agents[agent_id]
    return Response(status_code=204)

def _list_agents(request: Request) -> Response:
    agents = list(route_store.agents.values())
    return Response(body={"agents": agents, "count": len(agents)})

def _get_agent(request: Request) -> Response:
    agent_id = request.path_params.get("agent_id", "")
    agent = route_store.agents.get(agent_id)
    if not agent:
        return Response(status_code=404, body={"error": "Agent not found"})
    return Response(body=agent)

http_server.api_server.add_route("GET", "/api/v1/agents", _list_agents)
http_server.api_server.add_route("GET", "/api/v1/agents/{agent_id}", _get_agent)
http_server.api_server.add_route("POST", "/api/v1/agents", _create_agent)
http_server.api_server.add_route("PATCH", "/api/v1/agents/{agent_id}", _update_agent)
http_server.api_server.add_route("DELETE", "/api/v1/agents/{agent_id}", _delete_agent)
print("API: /api/v1/agents CRUD registered")

# -- Agent Skills Management --

def _get_agent_skills(request: Request) -> Response:
    """GET /api/v1/agents/{agent_id}/skills — get agent's assigned skills with details."""
    agent_id = request.path_params.get("agent_id", "")
    agent = route_store.agents.get(agent_id)
    if not agent:
        return Response(status_code=404, body={"error": "Agent not found"})
    skill_details = []
    for skill_id in agent.get("skills", []):
        skill = _skill_registry.get(skill_id)
        if skill:
            skill_details.append({
                "id": skill["id"],
                "name": skill["name"],
                "description": skill["description"],
            })
        else:
            skill_details.append({"id": skill_id, "name": skill_id, "description": "(not found in registry)"})
    return Response(body={
        "agent_id": agent_id,
        "agent_name": agent["name"],
        "skills": skill_details,
    })

def _update_agent_skills(request: Request) -> Response:
    """PATCH /api/v1/agents/{agent_id}/skills — update agent's assigned skills."""
    agent_id = request.path_params.get("agent_id", "")
    agent = route_store.agents.get(agent_id)
    if not agent:
        return Response(status_code=404, body={"error": "Agent not found"})
    body = request.body or {}
    new_skills = body.get("skills")
    if new_skills is None or not isinstance(new_skills, list):
        return Response(status_code=400, body={"error": "'skills' must be a list of skill IDs"})
    # Validate all skill IDs exist in registry
    unknown = [s for s in new_skills if s not in _skill_registry]
    if unknown:
        return Response(status_code=400, body={"error": f"Unknown skill IDs: {unknown}", "available": list(_skill_registry.keys())})
    agent["skills"] = new_skills
    return Response(body={
        "id": agent_id,
        "name": agent["name"],
        "skills": new_skills,
    })

http_server.api_server.add_route("GET", "/api/v1/agents/{agent_id}/skills", _get_agent_skills)
http_server.api_server.add_route("PATCH", "/api/v1/agents/{agent_id}/skills", _update_agent_skills)
print("API: /api/v1/agents/{agent_id}/skills registered (2 endpoints)")

# -- Teams CRUD --

_teams: dict[str, dict] = {
    "development": {"id": "development", "name": "Engineering", "nameJa": "エンジニアリング", "icon": "Code2", "color": "text-blue-400", "bg": "bg-blue-600"},
    "design": {"id": "design", "name": "Design", "nameJa": "デザイン", "icon": "Palette", "color": "text-purple-400", "bg": "bg-pink-600"},
    "research": {"id": "research", "name": "Research & Writing", "nameJa": "リサーチ & ライティング", "icon": "PenTool", "color": "text-emerald-400", "bg": "bg-violet-600"},
    "data": {"id": "data", "name": "Data & AI", "nameJa": "データ & AI", "icon": "Zap", "color": "text-cyan-400", "bg": "bg-cyan-600"},
    "security": {"id": "security", "name": "Security", "nameJa": "セキュリティ", "icon": "Shield", "color": "text-red-400", "bg": "bg-red-600"},
    "product": {"id": "product", "name": "Product & Ops", "nameJa": "プロダクト & 運用", "icon": "Network", "color": "text-orange-400", "bg": "bg-orange-600"},
    "advertising": {"id": "advertising", "name": "Advertising", "nameJa": "広告運用", "icon": "Megaphone", "color": "text-amber-400", "bg": "bg-amber-600"},
}

def _list_teams(request: Request) -> Response:
    return Response(body=list(_teams.values()))

def _create_team(request: Request) -> Response:
    body = request.body or {}
    team_id = body.get("id") or uuid.uuid4().hex[:8]
    team = {
        "id": team_id,
        "name": body["name"],
        "nameJa": body.get("nameJa", body["name"]),
        "icon": body.get("icon", "Users"),
        "color": body.get("color", "text-gray-400"),
        "bg": body.get("bg", "bg-gray-600"),
    }
    _teams[team_id] = team
    return Response(status_code=201, body=team)

def _team_path_param(request: Request) -> str:
    return request.path_params.get("team_id", "") or request.path_params.get("id", "")

def _update_team(request: Request) -> Response:
    team_id = _team_path_param(request)
    team = _teams.get(team_id)
    if not team:
        return Response(status_code=404, body={"error": "Team not found"})
    body = request.body or {}
    for key in ["name", "nameJa", "icon", "color", "bg"]:
        if key in body:
            team[key] = body[key]
    return Response(body=team)

def _delete_team(request: Request) -> Response:
    team_id = _team_path_param(request)
    if team_id not in _teams:
        return Response(status_code=404, body={"error": "Team not found"})
    del _teams[team_id]
    return Response(status_code=204)

http_server.api_server.add_route("GET", "/api/v1/teams", _list_teams)
http_server.api_server.add_route("POST", "/api/v1/teams", _create_team)
http_server.api_server.add_route("PATCH", "/api/v1/teams/{team_id}", _update_team)
http_server.api_server.add_route("DELETE", "/api/v1/teams/{team_id}", _delete_team)
print("API: /api/v1/teams CRUD registered")

# -- Costs API (real-time LLM call tracking) --
# Pylon framework provides /api/v1/costs/summary but only for completed runs.
# This endpoint tracks ALL _call_llm invocations in real-time.

def _costs_realtime(request: Request) -> Response:
    period = "mtd"
    qs = getattr(request, "query_string", "") or ""
    if "period=" in qs:
        period = qs.split("period=")[1].split("&")[0]

    now = _time_mod.time()
    if period == "7d":
        cutoff = now - 7 * 86400
    elif period == "30d":
        cutoff = now - 30 * 86400
    elif period == "ytd":
        import datetime as _dt
        cutoff = _dt.datetime(_dt.datetime.now().year, 1, 1).timestamp()
    elif period == "all":
        cutoff = 0
    else:  # mtd
        import datetime as _dt
        d = _dt.datetime.now()
        cutoff = _dt.datetime(d.year, d.month, 1).timestamp()

    entries = [e for e in _cost_log if e["timestamp"] >= cutoff]
    total = sum(e["cost_usd"] for e in entries)
    total_in = sum(e["tokens_in"] for e in entries)
    total_out = sum(e["tokens_out"] for e in entries)
    by_provider: dict[str, float] = {}
    by_model: dict[str, float] = {}
    for e in entries:
        by_provider[e["provider"]] = by_provider.get(e["provider"], 0) + e["cost_usd"]
        by_model[e["model"]] = by_model.get(e["model"], 0) + e["cost_usd"]

    return Response(body={
        "total_usd": round(total, 6),
        "budget_usd": 100.0,
        "run_count": len(entries),
        "total_tokens_in": total_in,
        "total_tokens_out": total_out,
        "by_provider": {k: round(v, 6) for k, v in by_provider.items()},
        "by_model": {k: round(v, 6) for k, v in by_model.items()},
    })

http_server.api_server.add_route("GET", "/api/v1/costs/realtime", _costs_realtime)
print("API: /api/v1/costs/realtime registered")

# -- Scheduled Events (in-memory store) --

_scheduled_events: dict[str, dict] = {}

def _list_events(request: Request) -> Response:
    events = sorted(_scheduled_events.values(), key=lambda e: e.get("start", ""))
    return Response(body=events)

def _create_event(request: Request) -> Response:
    body = request.body or {}
    event_id = body.get("id") or f"evt_{uuid.uuid4().hex[:8]}"
    now = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    event = {
        "id": event_id,
        "title": body.get("title", ""),
        "description": body.get("description", ""),
        "start": body.get("start", now),
        "end": body.get("end", ""),
        "type": body.get("type", "task"),
        "agentId": body.get("agentId", ""),
        "created_at": now,
    }
    _scheduled_events[event_id] = event
    return Response(status_code=201, body=event)

def _delete_event(request: Request) -> Response:
    event_id = request.path_params.get("event_id", "")
    if event_id not in _scheduled_events:
        return Response(status_code=404, body={"error": "Event not found"})
    del _scheduled_events[event_id]
    return Response(status_code=204)

http_server.api_server.add_route("GET", "/api/v1/events", _list_events)
http_server.api_server.add_route("POST", "/api/v1/events", _create_event)
http_server.api_server.add_route("DELETE", "/api/v1/events/{event_id}", _delete_event)
print("API: /api/v1/events CRUD registered")

# -- Content Pipeline (in-memory store) --

_content_items: dict[str, dict] = {}

def _list_content(request: Request) -> Response:
    items = sorted(_content_items.values(), key=lambda c: c.get("created_at", ""))
    return Response(body=items)

def _create_content(request: Request) -> Response:
    body = request.body or {}
    content_id = body.get("id") or f"cnt_{uuid.uuid4().hex[:8]}"
    now = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    item = {
        "id": content_id,
        "title": body.get("title", ""),
        "description": body.get("description", ""),
        "type": body.get("type", "article"),
        "stage": body.get("stage", "ideation"),
        "assignee": body.get("assignee", ""),
        "assigneeType": body.get("assigneeType", "ai"),
        "created_at": now,
        "updated_at": now,
    }
    _content_items[content_id] = item
    return Response(status_code=201, body=item)

def _update_content(request: Request) -> Response:
    content_id = request.path_params.get("content_id", "")
    if content_id not in _content_items:
        return Response(status_code=404, body={"error": "Content not found"})
    body = request.body or {}
    now = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    item = _content_items[content_id]
    for key in ("title", "description", "type", "stage", "assignee", "assigneeType"):
        if key in body:
            item[key] = body[key]
    item["updated_at"] = now
    _content_items[content_id] = item
    return Response(body=item)

def _delete_content(request: Request) -> Response:
    content_id = request.path_params.get("content_id", "")
    if content_id not in _content_items:
        return Response(status_code=404, body={"error": "Content not found"})
    del _content_items[content_id]
    return Response(status_code=204)

http_server.api_server.add_route("GET", "/api/v1/content", _list_content)
http_server.api_server.add_route("POST", "/api/v1/content", _create_content)
http_server.api_server.add_route("PUT", "/api/v1/content/{content_id}", _update_content)
http_server.api_server.add_route("PATCH", "/api/v1/content/{content_id}", _update_content)
http_server.api_server.add_route("DELETE", "/api/v1/content/{content_id}", _delete_content)
print("API: /api/v1/content CRUD registered")

# ── Ads Audit API ──────────────────────────────────
import threading as _threading

_ads_reports: dict[str, dict] = {}  # report_id -> AggregateReport
_ads_runs: dict[str, dict] = {}     # run_id -> {status, progress, report_id}

# Import reference data
try:
    from ads_reference_data import (
        SEVERITY_MULTIPLIERS, GRADE_THRESHOLDS, PLATFORM_CATEGORY_WEIGHTS,
        PLATFORM_CHECK_COUNTS, INDUSTRY_TEMPLATES, PLATFORM_BENCHMARKS,
        AUDIT_AGENT_PROMPTS,
    )
    print("Ads: reference data loaded")
except ImportError:
    SEVERITY_MULTIPLIERS = {"critical": 5.0, "high": 3.0, "medium": 1.5, "low": 0.5}
    GRADE_THRESHOLDS = [(90, "A"), (75, "B"), (60, "C"), (40, "D"), (0, "F")]
    PLATFORM_CATEGORY_WEIGHTS = {}
    PLATFORM_CHECK_COUNTS = {"google": 74, "meta": 46, "linkedin": 25, "tiktok": 25, "microsoft": 20}
    INDUSTRY_TEMPLATES = {}
    PLATFORM_BENCHMARKS = {}
    AUDIT_AGENT_PROMPTS = {}
    print("Ads: reference data not found, using defaults")

def _score_to_grade(score: float) -> str:
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"

def _run_audit_agent(run_id: str, agent_name: str, platform: str, config: dict):
    """Run a single audit agent in a background thread."""
    try:
        _ads_runs[run_id]["progress"][agent_name] = "running"
        prompt_template = AUDIT_AGENT_PROMPTS.get(agent_name, "")
        prompt = (
            f"{prompt_template}\n\n"
            f"Industry: {config.get('industry_type', 'generic')}\n"
            f"Monthly Budget: ${config.get('monthly_budget', 'unknown')}\n"
            f"Account Data:\n{config.get('account_data', {}).get(platform, 'No data provided - generate realistic sample audit results.')}\n\n"
            f"Output ONLY a valid JSON array of check results."
        )
        provider = "anthropic"
        model = MODEL
        if agent_name in ("audit-creative", "audit-tracking", "audit-budget", "audit-compliance"):
            model = HAIKU_MODEL
        text, tin, tout = _call_llm(model, prompt, max_tokens=4096, provider=provider)
        try:
            checks = _json.loads(_strip_json_fences(text))
        except Exception:
            checks = []
        _ads_runs[run_id]["results"][agent_name] = checks
        _ads_runs[run_id]["progress"][agent_name] = "completed"
        print(f"[ads:{agent_name}] Done. {len(checks)} checks, {tin}in/{tout}out")
    except Exception as e:
        _ads_runs[run_id]["progress"][agent_name] = "failed"
        _ads_runs[run_id]["results"][agent_name] = []
        print(f"[ads:{agent_name}] Error: {e}")

def _synthesize_audit(run_id: str, config: dict):
    """Wait for all agents then synthesize the report."""
    agents = list(_ads_runs[run_id]["threads"].values())
    for t in agents:
        t.join(timeout=120)

    results = _ads_runs[run_id]["results"]
    all_checks = []
    platform_scores = {}

    for agent_name, checks in results.items():
        for check in checks:
            # Normalize result/severity to lowercase
            check["result"] = check.get("result", "fail").lower()
            check["severity"] = check.get("severity", "medium").lower()
            check.setdefault("is_quick_win", check.get("estimated_fix_time_min", 999) <= 15 and check["severity"] in ("critical", "high"))
            all_checks.append(check)

    # Group checks by platform (handle MS prefix for Microsoft before M for Meta)
    platform_checks: dict[str, list] = {}
    for check in all_checks:
        cid = check.get("id", "X")
        if cid[:2] == "MS":
            platform = "microsoft"
        else:
            plat_map = {"G": "google", "M": "meta", "L": "linkedin", "T": "tiktok", "B": "microsoft"}
            platform = plat_map.get(cid[0], "google")
        platform_checks.setdefault(platform, []).append(check)

    for platform, checks in platform_checks.items():
        total = len(checks)
        passed = sum(1 for c in checks if c.get("result") == "pass")
        score = (passed / total * 100) if total > 0 else 0
        cat_scores: dict[str, float] = {}
        cats: dict[str, list] = {}
        for c in checks:
            cat = c.get("category", "Other")
            cats.setdefault(cat, []).append(c)
        for cat, cat_checks in cats.items():
            cat_passed = sum(1 for c in cat_checks if c.get("result") == "pass")
            cat_scores[cat] = (cat_passed / len(cat_checks) * 100) if cat_checks else 0

        platform_scores[platform] = {
            "platform": platform,
            "score": round(score, 1),
            "grade": _score_to_grade(score),
            "budget_share": 1.0 / max(len(platform_checks), 1),
            "checks": checks,
            "category_scores": {k: round(v, 1) for k, v in cat_scores.items()},
        }

    agg_score = sum(ps["score"] for ps in platform_scores.values()) / max(len(platform_scores), 1)
    report_id = f"rpt_{uuid.uuid4().hex[:8]}"
    now = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())

    report = {
        "id": report_id,
        "created_at": now,
        "industry_type": config.get("industry_type", "generic"),
        "aggregate_score": round(agg_score, 1),
        "aggregate_grade": _score_to_grade(agg_score),
        "platforms": list(platform_scores.values()),
        "quick_wins": [c for c in all_checks if c.get("is_quick_win")],
        "critical_issues": [c for c in all_checks if c.get("severity") == "critical" and c.get("result") == "fail"],
        "cross_platform": {
            "budget_assessment": "Analyzed",
            "tracking_consistency": "Reviewed",
            "creative_consistency": "Assessed",
            "attribution_overlap": "Checked",
        },
        "total_checks": len(all_checks),
        "passed_checks": sum(1 for c in all_checks if c.get("result") == "pass"),
        "warning_checks": sum(1 for c in all_checks if c.get("result") == "warning"),
        "failed_checks": sum(1 for c in all_checks if c.get("result") == "fail"),
    }
    _ads_reports[report_id] = report
    _ads_runs[run_id]["status"] = "completed"
    _ads_runs[run_id]["report_id"] = report_id
    print(f"[ads:synthesizer] Report {report_id} ready. Score: {agg_score:.1f} ({_score_to_grade(agg_score)})")

def _ads_run_audit(request: Request) -> Response:
    body = request.body or {}
    platforms = body.get("platforms", ["google", "meta"])
    config = {
        "industry_type": body.get("industry_type", "generic"),
        "monthly_budget": body.get("monthly_budget", 5000),
        "account_data": body.get("account_data", {}),
    }
    run_id = f"ads_{uuid.uuid4().hex[:8]}"
    agent_map = {
        "google": "audit-google", "meta": "audit-meta",
    }
    # Always run creative, tracking, budget, compliance
    agent_names = list(set(
        [agent_map.get(p, f"audit-{p}") for p in platforms]
        + ["audit-creative", "audit-tracking", "audit-budget", "audit-compliance"]
    ))
    _ads_runs[run_id] = {
        "status": "running",
        "progress": {a: "pending" for a in agent_names},
        "results": {},
        "threads": {},
        "report_id": None,
    }
    # Start agent threads
    for agent_name in agent_names:
        platform = agent_name.replace("audit-", "")
        t = _threading.Thread(target=_run_audit_agent, args=(run_id, agent_name, platform, config), daemon=True)
        _ads_runs[run_id]["threads"][agent_name] = t
        t.start()
    # Start synthesizer thread
    _threading.Thread(target=_synthesize_audit, args=(run_id, config), daemon=True).start()
    return Response(status_code=201, body={"run_id": run_id})

def _ads_get_audit_status(request: Request) -> Response:
    run_id = request.path_params.get("run_id", "")
    run = _ads_runs.get(run_id)
    if not run:
        return Response(status_code=404, body={"error": "Run not found"})
    result: dict = {
        "status": run["status"],
        "progress": {k: v for k, v in run["progress"].items()},
    }
    if run["status"] == "completed" and run["report_id"]:
        result["report"] = _ads_reports.get(run["report_id"])
    return Response(body=result)

def _ads_list_reports(request: Request) -> Response:
    reports = sorted(_ads_reports.values(), key=lambda r: r["created_at"], reverse=True)
    return Response(body=reports)

def _ads_get_report(request: Request) -> Response:
    report_id = request.path_params.get("report_id", "")
    report = _ads_reports.get(report_id)
    if not report:
        return Response(status_code=404, body={"error": "Report not found"})
    return Response(body=report)

def _ads_generate_plan(request: Request) -> Response:
    body = request.body or {}
    industry_type = body.get("industry_type", "generic")
    monthly_budget = body.get("monthly_budget", 5000)
    template = INDUSTRY_TEMPLATES.get(industry_type, INDUSTRY_TEMPLATES.get("generic", {}))
    prompt = (
        f"You are an advertising strategist. Create a detailed ad campaign plan.\n"
        f"Industry: {industry_type}\nMonthly Budget: ${monthly_budget}\n"
        f"Template data: {_json.dumps(template)}\n\n"
        f"Output JSON with keys: industry_type, recommended_platforms (array), "
        f"campaign_architecture (array of {{platform, campaign_name, objective, budget_share, targeting_summary, creative_requirements[]}}), "
        f"monthly_budget_min, primary_kpi, time_to_profit.\n"
        f"Output ONLY valid JSON."
    )
    text, tin, tout = _call_llm(MODEL, prompt, max_tokens=4096, provider="anthropic")
    try:
        plan = _json.loads(_strip_json_fences(text))
    except Exception:
        plan = {"industry_type": industry_type, "recommended_platforms": list((template or {}).get("platforms", {}).keys()), "campaign_architecture": [], "monthly_budget_min": monthly_budget, "primary_kpi": "ROAS", "time_to_profit": "3-6 months"}
    return Response(body=plan)

def _ads_optimize_budget(request: Request) -> Response:
    body = request.body or {}
    current_spend = body.get("current_spend", {})
    target_mer = body.get("target_mer", 3.0)
    total = sum(current_spend.values()) or 5000
    prompt = (
        f"You are a media budget optimizer. Optimize this ad budget allocation.\n"
        f"Current spend: {_json.dumps(current_spend)}\nTarget MER: {target_mer}\n"
        f"Apply the 70/20/10 framework (proven/growth/experiment).\n\n"
        f"Output JSON: {{proven: number, growth: number, experiment: number, "
        f"platform_mix: {{google: 0.X, meta: 0.X, ...}}, monthly_budget: number, mer_target: number}}\n"
        f"Output ONLY valid JSON."
    )
    text, tin, tout = _call_llm(HAIKU_MODEL, prompt, max_tokens=2048, provider="anthropic")
    try:
        result = _json.loads(_strip_json_fences(text))
    except Exception:
        result = {"proven": total * 0.7, "growth": total * 0.2, "experiment": total * 0.1, "platform_mix": current_spend, "monthly_budget": total, "mer_target": target_mer}
    return Response(body=result)

def _ads_get_benchmarks(request: Request) -> Response:
    platform = request.path_params.get("platform", "google")
    benchmarks = PLATFORM_BENCHMARKS.get(platform, {})
    return Response(body=benchmarks)

def _ads_get_templates(request: Request) -> Response:
    templates = []
    for tid, tdata in INDUSTRY_TEMPLATES.items():
        templates.append({
            "id": tid,
            "name": tdata.get("name", tid),
            "platforms": tdata.get("platforms", {}),
            "min_monthly": tdata.get("min_monthly", 3000),
            "primary_kpi": tdata.get("primary_kpi", ""),
            "time_to_profit": tdata.get("time_to_profit", ""),
            "description": tdata.get("description", ""),
        })
    return Response(body=templates)

http_server.api_server.add_route("POST", "/api/v1/ads/audit", _ads_run_audit)
http_server.api_server.add_route("GET", "/api/v1/ads/audit/{run_id}", _ads_get_audit_status)
http_server.api_server.add_route("GET", "/api/v1/ads/reports", _ads_list_reports)
http_server.api_server.add_route("GET", "/api/v1/ads/reports/{report_id}", _ads_get_report)
http_server.api_server.add_route("POST", "/api/v1/ads/plan", _ads_generate_plan)
http_server.api_server.add_route("POST", "/api/v1/ads/budget/optimize", _ads_optimize_budget)
http_server.api_server.add_route("GET", "/api/v1/ads/benchmarks/{platform}", _ads_get_benchmarks)
http_server.api_server.add_route("GET", "/api/v1/ads/templates", _ads_get_templates)
print("API: /api/v1/ads/* registered (8 endpoints)")

# ── Model Management API Endpoints ───────────────────

import concurrent.futures as _futures


def _models_list(request: Request) -> Response:
    """GET /api/v1/models — list all available models grouped by provider."""
    providers_out: dict[str, dict] = {}
    for prov in ("anthropic", "openai", "gemini", "moonshot", "zhipu"):
        models = _model_registry.get(prov) or _fetch_provider_models(prov)
        pol = _model_policies.get(prov, {"policy": "auto", "pin": None})
        has_client = prov == "anthropic" or _get_provider_client(prov) is not None
        providers_out[prov] = {
            "models": [
                {"id": m["id"], "name": m["name"], "policy": pol["policy"]}
                for m in models
            ],
            "status": "available" if has_client else "not_configured",
            "default_model": DEFAULT_MODELS.get(prov, ""),
        }
    return Response(body={
        "providers": providers_out,
        "fallback_chain": FALLBACK_CHAIN,
        "policies": {k: v for k, v in _model_policies.items()},
    })


def _models_policy(request: Request) -> Response:
    """POST /api/v1/models/policy — update model selection policy for a provider."""
    body = request.body or {}
    provider = body.get("provider", "")
    policy = body.get("policy", "auto")
    pin = body.get("pin")

    if provider not in _model_policies:
        return Response(status=400, body={"error": f"Unknown provider: {provider}"})
    if policy not in ("auto", "stable", "pinned"):
        return Response(status=400, body={"error": f"Invalid policy: {policy}. Must be auto, stable, or pinned."})
    if policy == "pinned" and not pin:
        return Response(status=400, body={"error": "pin field required when policy is 'pinned'"})

    _model_policies[provider] = {"policy": policy, "pin": pin}
    selected = _select_best_model(provider, policy)
    return Response(body={
        "provider": provider,
        "policy": policy,
        "pin": pin,
        "selected_model": selected,
    })


def _models_refresh(request: Request) -> Response:
    """POST /api/v1/models/refresh — force-refresh model cache from all providers."""
    # Invalidate cache
    try:
        if _MODEL_CACHE_PATH.exists():
            _MODEL_CACHE_PATH.unlink()
    except Exception:
        pass
    _model_registry.clear()

    refreshed: dict[str, int] = {}
    for prov in ("anthropic", "openai", "gemini", "moonshot", "zhipu"):
        models = _fetch_provider_models(prov)
        refreshed[prov] = len(models)

    return Response(body={
        "status": "refreshed",
        "providers": refreshed,
        "total_models": sum(refreshed.values()),
    })


def _check_provider_health(prov: str) -> dict:
    """Check a single provider's connectivity and latency."""
    import time as _t
    client = _get_provider_client(prov)
    if prov != "anthropic" and client is None:
        return {"status": "not_configured", "latency_ms": -1, "model": DEFAULT_MODELS.get(prov, "")}

    model = _select_best_model(prov)
    start = _t.monotonic()
    try:
        if prov == "anthropic":
            resp = client_anthropic.messages.create(
                model=model, max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
        else:
            client.chat.completions.create(
                model=model, max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
        latency = int((_t.monotonic() - start) * 1000)
        return {"status": "ok", "latency_ms": latency, "model": model}
    except Exception as exc:
        latency = int((_t.monotonic() - start) * 1000)
        return {"status": "error", "latency_ms": latency, "model": model, "error": str(exc)}


def _models_health(request: Request) -> Response:
    """GET /api/v1/models/health — check connectivity to each provider (parallel)."""
    providers = ["anthropic", "openai", "gemini", "moonshot", "zhipu"]
    results: dict[str, dict] = {}
    with _futures.ThreadPoolExecutor(max_workers=len(providers)) as pool:
        future_map = {pool.submit(_check_provider_health, p): p for p in providers}
        for fut in _futures.as_completed(future_map):
            prov = future_map[fut]
            try:
                results[prov] = fut.result()
            except Exception as exc:
                results[prov] = {"status": "error", "latency_ms": -1, "model": "", "error": str(exc)}
    return Response(body=results)


http_server.api_server.add_route("GET", "/api/v1/models", _models_list)
http_server.api_server.add_route("POST", "/api/v1/models/policy", _models_policy)
http_server.api_server.add_route("POST", "/api/v1/models/refresh", _models_refresh)
http_server.api_server.add_route("GET", "/api/v1/models/health", _models_health)
print("API: /api/v1/models/* registered (4 endpoints)")

# ── Skills Management System ──────────────────────────

SKILL_DIRS = [
    Path.home() / ".claude" / "skills",
    Path(__file__).parent / "skills",
]

_skill_registry: dict[str, dict] = {}

_builtin_skills: dict[str, dict] = {
    "code-review": {
        "id": "code-review",
        "name": "コードレビュー",
        "description": "コード品質、セキュリティ、パフォーマンスの包括的レビュー",
        "category": "development",
        "risk": "safe",
        "source": "builtin",
        "tags": ["review", "quality"],
    },
    "security-scan": {
        "id": "security-scan",
        "name": "セキュリティスキャン",
        "description": "OWASP Top 10に基づくセキュリティ脆弱性の検出",
        "category": "security",
        "risk": "safe",
        "source": "builtin",
        "tags": ["security", "owasp"],
    },
    "test-generator": {
        "id": "test-generator",
        "name": "テスト生成",
        "description": "コードからユニットテストを自動生成",
        "category": "development",
        "risk": "safe",
        "source": "builtin",
        "tags": ["testing", "tdd"],
    },
    "refactor-advisor": {
        "id": "refactor-advisor",
        "name": "リファクタリング提案",
        "description": "コードの改善ポイントと具体的なリファクタリング手順を提案",
        "category": "development",
        "risk": "safe",
        "source": "builtin",
        "tags": ["refactoring", "clean-code"],
    },
    "api-designer": {
        "id": "api-designer",
        "name": "API設計",
        "description": "RESTful/GraphQL APIの設計とドキュメント生成",
        "category": "development",
        "risk": "safe",
        "source": "builtin",
        "tags": ["api", "design"],
    },
    "performance-profiler": {
        "id": "performance-profiler",
        "name": "パフォーマンス分析",
        "description": "ボトルネック検出と最適化提案",
        "category": "devops",
        "risk": "safe",
        "source": "builtin",
        "tags": ["performance", "optimization"],
    },
    "doc-generator": {
        "id": "doc-generator",
        "name": "ドキュメント生成",
        "description": "コードからAPI仕様書やREADMEを自動生成",
        "category": "documentation",
        "risk": "safe",
        "source": "builtin",
        "tags": ["documentation", "readme"],
    },
    "deployment-helper": {
        "id": "deployment-helper",
        "name": "デプロイアシスタント",
        "description": "CI/CDパイプラインの構築とデプロイ自動化",
        "category": "devops",
        "risk": "unknown",
        "source": "builtin",
        "tags": ["deploy", "cicd"],
    },
}

_BUILTIN_SKILL_PROMPTS: dict[str, str] = {
    "code-review": (
        "You are an expert code reviewer. Analyze the provided code for correctness, "
        "readability, security vulnerabilities, and performance issues. Provide specific, "
        "actionable feedback organized by severity (critical, warning, suggestion). "
        "Include line references where applicable and suggest concrete fixes."
    ),
    "security-scan": (
        "You are a security expert specializing in application security. Scan the provided "
        "code for OWASP Top 10 vulnerabilities including injection, broken authentication, "
        "sensitive data exposure, and insecure deserialization. Rate each finding by severity "
        "(critical/high/medium/low) and provide remediation steps."
    ),
    "test-generator": (
        "You are a testing specialist. Generate comprehensive unit tests for the provided code "
        "using appropriate testing frameworks. Cover happy paths, edge cases, error conditions, "
        "and boundary values. Use descriptive test names and include setup/teardown where needed. "
        "Follow the Arrange-Act-Assert pattern."
    ),
    "refactor-advisor": (
        "You are a refactoring expert. Analyze the provided code for code smells, duplicated "
        "logic, overly complex methods, and violations of SOLID principles. Propose specific "
        "refactoring steps with before/after examples. Prioritize changes by impact and risk."
    ),
    "api-designer": (
        "You are an API design specialist. Design clean, consistent, and well-documented APIs "
        "following REST best practices or GraphQL schema design patterns. Include endpoint "
        "definitions, request/response schemas, error codes, authentication requirements, "
        "and versioning strategy."
    ),
    "performance-profiler": (
        "You are a performance engineering expert. Analyze the provided code or system for "
        "bottlenecks, memory leaks, N+1 queries, unnecessary allocations, and algorithmic "
        "inefficiencies. Provide concrete optimization recommendations with expected impact "
        "estimates and tradeoff analysis."
    ),
    "doc-generator": (
        "You are a technical documentation specialist. Generate clear, comprehensive documentation "
        "from the provided code including API references, usage examples, parameter descriptions, "
        "and architectural overviews. Use appropriate formatting (Markdown) and maintain a "
        "consistent style throughout."
    ),
    "deployment-helper": (
        "You are a DevOps specialist focused on deployment automation. Help design and implement "
        "CI/CD pipelines, Dockerfiles, Kubernetes manifests, and infrastructure-as-code. Consider "
        "security best practices, rollback strategies, health checks, and monitoring integration."
    ),
}


def _parse_skill_md(skill_dir: Path) -> dict | None:
    """Parse SKILL.md file, extract YAML frontmatter and content."""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None
    try:
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    # Parse YAML frontmatter between --- markers
    fm_match = _re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, _re.DOTALL)
    if not fm_match:
        # No frontmatter; treat entire file as content with minimal metadata
        return {
            "id": skill_dir.name,
            "name": skill_dir.name,
            "description": "",
            "category": "other",
            "risk": "unknown",
            "source": "local" if "skills" in str(skill_dir) else "community",
            "tags": [],
            "path": str(skill_dir),
            "has_scripts": any(skill_dir.glob("*.sh")) or any(skill_dir.glob("*.py")),
            "content_preview": text[:200].strip(),
            "installed_at": _datetime.datetime.fromtimestamp(
                skill_file.stat().st_mtime, tz=_datetime.timezone.utc
            ).isoformat(),
        }

    yaml_text = fm_match.group(1)
    content_text = fm_match.group(2)

    # Simple regex-based YAML parser (no pyyaml dependency)
    def _yaml_val(key: str, default=""):
        m = _re.search(rf"^{key}\s*:\s*(.+)$", yaml_text, _re.MULTILINE)
        return m.group(1).strip().strip("\"'") if m else default

    def _yaml_list(key: str) -> list[str]:
        m = _re.search(rf"^{key}\s*:\s*\[(.+?)\]", yaml_text, _re.MULTILINE)
        if m:
            return [t.strip().strip("\"'") for t in m.group(1).split(",")]
        # Multi-line list
        items: list[str] = []
        in_list = False
        for line in yaml_text.splitlines():
            if _re.match(rf"^{key}\s*:", line):
                in_list = True
                continue
            if in_list:
                lm = _re.match(r"^\s+-\s+(.+)$", line)
                if lm:
                    items.append(lm.group(1).strip().strip("\"'"))
                else:
                    break
        return items

    skill_id = _yaml_val("id", skill_dir.name)
    return {
        "id": skill_id,
        "name": _yaml_val("name", skill_id),
        "description": _yaml_val("description"),
        "category": _yaml_val("category", "other"),
        "risk": _yaml_val("risk", "unknown"),
        "source": _yaml_val("source", "community"),
        "tags": _yaml_list("tags"),
        "path": str(skill_dir),
        "has_scripts": any(skill_dir.glob("*.sh")) or any(skill_dir.glob("*.py")),
        "content_preview": content_text[:200].strip(),
        "installed_at": _datetime.datetime.fromtimestamp(
            skill_file.stat().st_mtime, tz=_datetime.timezone.utc
        ).isoformat(),
    }


def _scan_skills() -> dict[str, dict]:
    """Scan all skill directories and build registry."""
    registry: dict[str, dict] = {}

    # Add builtin skills first
    now = _datetime.datetime.now(_datetime.timezone.utc).isoformat()
    for sid, meta in _builtin_skills.items():
        registry[sid] = {
            **meta,
            "path": "",
            "has_scripts": False,
            "content_preview": meta["description"],
            "installed_at": now,
        }

    # Scan filesystem skill directories
    for skill_base in SKILL_DIRS:
        if not skill_base.is_dir():
            continue
        for child in sorted(skill_base.iterdir()):
            if not child.is_dir():
                continue
            parsed = _parse_skill_md(child)
            if parsed and parsed["id"] not in registry:
                registry[parsed["id"]] = parsed

    return registry


# Initialize skill registry at startup
_skill_registry = _scan_skills()
print(f"Skills: {len(_skill_registry)} discovered ({sum(1 for s in _skill_registry.values() if s['source'] == 'builtin')} builtin)")


def _get_skill_content(skill: dict) -> str:
    """Return the full content for a skill (prompt for builtin, SKILL.md for file-based)."""
    if skill["source"] == "builtin":
        return _BUILTIN_SKILL_PROMPTS.get(skill["id"], skill["description"])
    skill_path = skill.get("path", "")
    if not skill_path:
        return skill["description"]
    skill_file = Path(skill_path) / "SKILL.md"
    if skill_file.exists():
        try:
            return skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return skill["description"]
    return skill["description"]


def _execute_skill(
    skill_id: str,
    user_input: str,
    context: dict | None = None,
    *,
    provider: str = "anthropic",
    model: str | None = None,
) -> dict:
    """Execute a skill using the specified provider/model (defaults to anthropic)."""
    skill = _skill_registry.get(skill_id)
    if not skill:
        return {"error": f"Skill '{skill_id}' not found"}

    # Resolve model: explicit > policy-based > default
    if model is None:
        model = _select_best_model(provider)
    use_model = model or DEFAULT_MODELS.get(provider, MODEL)

    skill_content = _get_skill_content(skill)

    prompt = f"[Skill: {skill['name']}]\n\n{skill_content}\n\n---\nUser Input:\n{user_input}"
    if context:
        prompt += f"\n\nContext:\n{_json_mod.dumps(context, ensure_ascii=False)}"

    try:
        text, tokens_in, tokens_out = _call_llm(
            use_model, prompt, max_tokens=4096, provider=provider, fallback=True,
        )
    except Exception as exc:
        return {"error": f"LLM call failed: {exc}", "skill_id": skill_id}

    return {
        "skill_id": skill_id,
        "result": text,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "model": use_model,
        "provider": provider,
    }


def _parse_qs(path: str) -> dict[str, str]:
    """Parse query string from request path into a dict."""
    if "?" not in path:
        return {}
    qs = path.split("?", 1)[1]
    params: dict[str, str] = {}
    for part in qs.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k] = v
    return params


def _skills_list(request: Request) -> Response:
    """GET /api/v1/skills - List all available skills."""
    qs = _parse_qs(request.path)
    category_filter = qs.get("category")
    source_filter = qs.get("source")
    search_filter = qs.get("search", "").lower()

    skills = list(_skill_registry.values())

    if category_filter:
        skills = [s for s in skills if s["category"] == category_filter]
    if source_filter:
        skills = [s for s in skills if s["source"] == source_filter]
    if search_filter:
        skills = [
            s for s in skills
            if search_filter in s["name"].lower()
            or search_filter in s["description"].lower()
            or search_filter in s["id"].lower()
            or any(search_filter in t.lower() for t in s.get("tags", []))
        ]

    categories: dict[str, int] = {}
    sources: dict[str, int] = {}
    for s in _skill_registry.values():
        categories[s["category"]] = categories.get(s["category"], 0) + 1
        sources[s["source"]] = sources.get(s["source"], 0) + 1

    return Response(body={
        "skills": skills,
        "total": len(skills),
        "categories": categories,
        "sources": sources,
    })


def _skills_get(request: Request) -> Response:
    """GET /api/v1/skills/{skill_id} - Get full skill details."""
    skill_id = request.path_params.get("skill_id", "")
    skill = _skill_registry.get(skill_id)
    if not skill:
        return Response(status_code=404, body={"error": f"Skill '{skill_id}' not found"})
    result = {**skill, "content": _get_skill_content(skill)}
    return Response(body=result)


def _skills_execute(request: Request) -> Response:
    """POST /api/v1/skills/{skill_id}/execute - Execute a skill.

    Body: {"input": "...", "context": {...}, "provider": "anthropic", "model": "claude-sonnet-4-6"}
    provider/model are optional; defaults to anthropic + policy-selected model.
    """
    skill_id = request.path_params.get("skill_id", "")
    body = request.body or {}
    user_input = body.get("input", "")
    if not user_input:
        return Response(status_code=400, body={"error": "'input' field is required"})
    context = body.get("context")
    provider = body.get("provider", "anthropic")
    model = body.get("model")  # None → auto-select
    if provider not in DEFAULT_MODELS:
        return Response(status_code=400, body={"error": f"Unknown provider: {provider}. Available: {list(DEFAULT_MODELS.keys())}"})
    result = _execute_skill(skill_id, user_input, context, provider=provider, model=model)
    if "error" in result:
        status = 404 if "not found" in result["error"] else 500
        return Response(status_code=status, body=result)
    return Response(body=result)


def _skills_scan(request: Request) -> Response:
    """POST /api/v1/skills/scan - Force rescan of skill directories."""
    global _skill_registry
    old_ids = set(_skill_registry.keys())
    _skill_registry = _scan_skills()
    new_ids = set(_skill_registry.keys())
    return Response(body={
        "total": len(_skill_registry),
        "new": len(new_ids - old_ids),
        "removed": len(old_ids - new_ids),
    })


def _skills_categories(request: Request) -> Response:
    """GET /api/v1/skills/categories - List all categories with counts."""
    categories: dict[str, int] = {}
    for s in _skill_registry.values():
        categories[s["category"]] = categories.get(s["category"], 0) + 1
    return Response(body={"categories": categories, "total": len(_skill_registry)})


# Register skill routes (order matters: specific paths before parameterized)
http_server.api_server.add_route("GET", "/api/v1/skills/categories", _skills_categories)
http_server.api_server.add_route("POST", "/api/v1/skills/scan", _skills_scan)
http_server.api_server.add_route("GET", "/api/v1/skills", _skills_list)
http_server.api_server.add_route("GET", "/api/v1/skills/{skill_id}", _skills_get)
http_server.api_server.add_route("POST", "/api/v1/skills/{skill_id}/execute", _skills_execute)
print("API: /api/v1/skills/* registered (5 endpoints)")

print(f"Routes: {len(route_store.list_workflow_projects(tenant_id='default'))} workflows ready")

# ── Async Workflow Run (override pylon's inline-blocking route) ──────────
import logging

from pylon.api.async_runs import (
    AsyncWorkflowRunManager,
    reconcile_lifecycle_projects_for_terminal_runs,
    sync_lifecycle_project_for_run,
)
from pylon.api.schemas import WORKFLOW_RUN_SCHEMA, validate


def _configure_async_run_logging() -> logging.Logger:
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        log_dir = project_root / ".pylon" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s"
        )
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        file_handler = logging.FileHandler(log_dir / "ui-dev-backend.log")
        file_handler.setFormatter(formatter)
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(stream_handler)
        root_logger.addHandler(file_handler)
    return logging.getLogger("ui.start_backend.async_runs")


_async_run_logger = _configure_async_run_logging()


def _sync_async_lifecycle_project(run_record: dict[str, object], workflow_id: str, tenant_id: str) -> None:
    sync_lifecycle_project_for_run(
        route_store.control_plane_store,
        run_record=run_record,
        workflow_id=workflow_id,
        tenant_id=tenant_id,
        logger_=_async_run_logger,
    )


_async_run_manager = AsyncWorkflowRunManager(
    route_store.control_plane_store,
    provider_registry=provider_registry,
    on_terminal_run=_sync_async_lifecycle_project,
    logger_=_async_run_logger,
)
_reconciled_async_runs = _async_run_manager.reconcile_orphaned_runs()
if _reconciled_async_runs:
    print(f"API: reconciled {_reconciled_async_runs} orphaned async workflow run(s)")
_backfilled_lifecycle_projects = reconcile_lifecycle_projects_for_terminal_runs(
    route_store.control_plane_store,
    logger_=_async_run_logger,
)
if _backfilled_lifecycle_projects:
    print(
        "API: backfilled "
        f"{_backfilled_lifecycle_projects} lifecycle project(s) from terminal async runs"
    )


def _replace_route(method: str, path: str, handler) -> None:
    api_server = http_server.api_server
    normalized_method = method.upper()
    api_server._routes = [
        route
        for route in api_server._routes
        if not (route.method == normalized_method and route.path_template == path)
    ]
    pattern, param_names = _compile_path(path)
    api_server._routes.insert(
        0,
        _Route(
            method=normalized_method,
            pattern=pattern,
            param_names=param_names,
            path_template=path,
            handler=handler,
        ),
    )


_replace_route("GET", "/api/v1/teams", _list_teams)
_replace_route("POST", "/api/v1/teams", _create_team)
_replace_route("PATCH", "/api/v1/teams/{id}", _update_team)
_replace_route("DELETE", "/api/v1/teams/{id}", _delete_team)

def _async_start_workflow_run(request: Request) -> Response:
    """Start a workflow run in a background thread, return immediately."""
    tenant_id = request.headers.get("x-tenant-id", "default")
    workflow_id = request.path_params.get("id", "")
    if route_store.get_workflow_project(workflow_id, tenant_id=tenant_id) is None:
        return Response(status_code=404, body={"error": f"Workflow not found: {workflow_id}"})
    body = request.body or {}
    valid, errors = validate(body, WORKFLOW_RUN_SCHEMA)
    if not valid:
        return Response(status_code=422, body={"errors": errors})
    raw_input = body.get("input")
    try:
        run_record = _async_run_manager.start_run(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            input_data=raw_input,
            parameters=body.get("parameters", {}),
            idempotency_key=body.get("idempotency_key"),
            correlation_id=str(request.context.get("correlation_id", "")) or None,
            trace_id=str(request.context.get("trace_id", "")) or None,
        )
    except Exception as exc:
        _async_run_logger.exception(
            "async_workflow_run_start_request_failed workflow_id=%s tenant_id=%s",
            workflow_id,
            tenant_id,
        )
        return Response(status_code=500, body={"error": str(exc)})

    return Response(
        status_code=202,
        headers={
            "content-type": "application/json",
            "location": f"/api/v1/runs/{run_record['id']}",
        },
        body=run_record,
    )

def _get_async_workflow_run(request: Request) -> Response:
    """Get a workflow run by ID while reconciling orphaned async workers."""
    run_id = request.path_params.get("run_id", "")
    tenant_id = request.headers.get("x-tenant-id", "default")
    existing = route_store.control_plane_store.get_run_record(run_id)
    if existing is None:
        return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
    if existing.get("tenant_id") != tenant_id:
        return Response(status_code=403, body={"error": "Forbidden"})
    record = _async_run_manager.get_run(run_id, tenant_id=tenant_id)
    if record is not None:
        return Response(body=record)
    return Response(status_code=404, body={"error": f"Run not found: {run_id}"})


def _get_async_workflow_run_for_workflow(request: Request) -> Response:
    """Get a workflow-scoped run by ID while enforcing workflow and tenant match."""
    run_id = request.path_params.get("run_id", "")
    workflow_id = request.path_params.get("id", "")
    tenant_id = request.headers.get("x-tenant-id", "default")
    existing = route_store.control_plane_store.get_run_record(run_id)
    if existing is None:
        return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
    if existing.get("tenant_id") != tenant_id:
        return Response(status_code=403, body={"error": "Forbidden"})
    if str(existing.get("workflow_id", existing.get("workflow", ""))) != workflow_id:
        return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
    record = _async_run_manager.get_run(run_id, tenant_id=tenant_id)
    if record is not None:
        return Response(body=record)
    return Response(status_code=404, body={"error": f"Run not found: {run_id}"})


def _list_async_workflow_runs(request: Request) -> Response:
    """List workflow runs while reconciling stale async workers."""
    tenant_id = request.headers.get("x-tenant-id", "default")
    workflow_id = request.path_params.get("id", "")
    if route_store.get_workflow_project(workflow_id, tenant_id=tenant_id) is None:
        return Response(status_code=404, body={"error": f"Workflow not found: {workflow_id}"})
    runs = _async_run_manager.list_runs(tenant_id=tenant_id, workflow_id=workflow_id)
    return Response(body={"runs": runs, "count": len(runs)})


def _list_async_runs(request: Request) -> Response:
    """List all runs while reconciling stale async workers."""
    tenant_id = request.headers.get("x-tenant-id", "default")
    runs = _async_run_manager.list_runs(tenant_id=tenant_id)
    return Response(body={"runs": runs, "count": len(runs)})

# Replace the default inline routes so the lifecycle UI uses background execution too.
for route_path in (
    "/v1/workflows/{id}/runs",
    "/api/v1/workflows/{id}/runs",
):
    _replace_route("GET", route_path, _list_async_workflow_runs)
for route_path in (
    "/workflows/{id}/run",
    "/v1/workflows/{id}/runs",
    "/api/v1/workflows/{id}/runs",
):
    _replace_route("POST", route_path, _async_start_workflow_run)
for route_path in (
    "/v1/workflows/{id}/runs/{run_id}",
    "/api/v1/workflows/{id}/runs/{run_id}",
):
    _replace_route("GET", route_path, _get_async_workflow_run_for_workflow)
for route_path in (
    "/v1/runs/{run_id}",
    "/api/v1/runs/{run_id}",
    "/api/v1/workflow-runs/{run_id}",
):
    _replace_route("GET", route_path, _get_async_workflow_run)
for route_path in (
    "/v1/runs",
    "/api/v1/workflow-runs",
):
    _replace_route("GET", route_path, _list_async_runs)
print("API: async workflow execution routes replaced for UI lifecycle runs")

# ── Feature manifest (enables lifecycle UI) ──────────
def _get_features(request):
    return Response(body={
        "contract_version": "1.0",
        "canonical_prefix": "/api/v1",
        "legacy_aliases_enabled": True,
        "surfaces": {
            "admin": {
                "dashboard": True,
                "workflows": True,
                "agents": True,
                "costs": True,
                "providers": True,
                "models": True,
                "skills": True,
                "settings": True,
            },
            "project": {
                "runs": True,
                "approvals": True,
                "studio": False,
                "lifecycle": True,
                "tasks": True,
                "team": True,
                "memory": True,
                "calendar": False,
                "content": True,
                "ads": True,
                "issues": False,
                "pulls": False,
            },
        },
    })

http_server.api_server.add_route("GET", "/v1/features", _get_features)
http_server.api_server.add_route("GET", "/api/v1/features", _get_features)
print("API: /api/v1/features registered (override)")

print("=" * 50)

try:
    http_server.serve_forever()
except KeyboardInterrupt:
    print("\nShutting down.")
    http_server.shutdown()
