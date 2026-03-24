"""Generate runnable prototype artifacts from lifecycle design blueprints."""

# ruff: noqa: E501

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from textwrap import dedent
from typing import Any

_NEXT_VERSION = "16.1.6"
_REACT_VERSION = "19.2.4"
_TAILWIND_VERSION = "4.2.1"
_TYPESCRIPT_VERSION = "5.9.3"


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _slug(value: str, *, prefix: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "")).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned[:48] or prefix


def _screen_routes(screens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for index, screen in enumerate(screens):
        screen_id = str(screen.get("id") or _slug(screen.get("title") or f"screen-{index + 1}", prefix=f"screen-{index + 1}"))
        segment = _slug(screen.get("title") or screen_id, prefix=f"screen-{index + 1}")
        routes.append(
            {
                "id": f"route-{index + 1}",
                "screen_id": screen_id,
                "path": "/" if index == 0 else f"/{segment}",
                "segment": "" if index == 0 else segment,
                "title": str(screen.get("title") or f"Screen {index + 1}"),
                "headline": str(screen.get("headline") or screen.get("title") or ""),
                "layout": str(screen.get("layout") or "workspace"),
                "primary_actions": [str(item) for item in _as_list(screen.get("primary_actions")) if str(item).strip()][:3],
                "states": ["default", "loading", "empty", "error", "success"],
            }
        )
    return routes


def build_prototype_spec(
    *,
    title: str,
    subtitle: str,
    primary: str,
    accent: str,
    features: list[str],
    prototype: dict[str, Any] | None = None,
    design_tokens: dict[str, Any] | None = None,
    decision_scope: dict[str, Any] | None = None,
    quality_focus: list[str] | None = None,
) -> dict[str, Any]:
    prototype_payload = _as_dict(prototype)
    design_tokens_payload = _as_dict(design_tokens)
    shell = _as_dict(prototype_payload.get("app_shell"))
    screens = [dict(item) for item in _as_list(prototype_payload.get("screens")) if isinstance(item, dict)]
    if not screens:
        screens = [
            {
                "id": "workspace",
                "title": str(title or "Workspace"),
                "purpose": str(subtitle or "Review the primary product workflow."),
                "layout": "workspace",
                "headline": str(title or "Workspace"),
                "supporting_text": str(subtitle or ""),
                "primary_actions": [str(item) for item in features[:3] if str(item).strip()],
                "modules": [],
                "success_state": "Move the workflow forward with a clear next action.",
            }
        ]
    flows = [dict(item) for item in _as_list(prototype_payload.get("flows")) if isinstance(item, dict)]
    routes = _screen_routes(screens)
    colors = _as_dict(design_tokens_payload.get("colors"))
    typography = _as_dict(design_tokens_payload.get("typography"))
    state_matrix: dict[str, list[dict[str, str]]] = {}
    components: list[dict[str, Any]] = []
    interaction_map: list[dict[str, Any]] = []
    mock_data: dict[str, Any] = {
        "activity_feed": [
            {"time": "07:10", "label": "Morning check", "detail": "Open the highest-friction task first."},
            {"time": "12:05", "label": "Midday sync", "detail": "Refresh decisions with the latest context."},
            {"time": "18:40", "label": "Evening review", "detail": "Prepare the next handoff before closing the loop."},
        ],
    }

    for index, screen in enumerate(screens):
        screen_id = str(screen.get("id") or f"screen-{index + 1}")
        screen_title = str(screen.get("title") or f"Screen {index + 1}")
        modules = [dict(item) for item in _as_list(screen.get("modules")) if isinstance(item, dict)]
        state_matrix[screen_id] = [
            {
                "state": "default",
                "trigger": "Initial visit",
                "summary": str(screen.get("supporting_text") or screen.get("purpose") or f"{screen_title} is ready for execution."),
            },
            {
                "state": "loading",
                "trigger": "Refreshing context",
                "summary": f"{screen_title} is synchronizing the latest records and decision context.",
            },
            {
                "state": "empty",
                "trigger": "No records yet",
                "summary": f"{screen_title} starts with a guided empty state that nudges the first meaningful action.",
            },
            {
                "state": "error",
                "trigger": "Sync conflict",
                "summary": f"{screen_title} surfaces a recoverable issue with the exact next step.",
            },
            {
                "state": "success",
                "trigger": "Primary action complete",
                "summary": str(screen.get("success_state") or f"{screen_title} confirms the completed step and points to the next move."),
            },
        ]
        components.append(
            {
                "id": f"{screen_id}-hero",
                "screen_id": screen_id,
                "kind": "hero-panel",
                "title": screen_title,
                "purpose": str(screen.get("purpose") or ""),
                "data_keys": ["headline", "supporting_text", "primary_actions"],
            }
        )
        for module_index, module in enumerate(modules):
            module_name = str(module.get("name") or f"Module {module_index + 1}")
            components.append(
                {
                    "id": f"{screen_id}-module-{module_index + 1}",
                    "screen_id": screen_id,
                    "kind": str(module.get("type") or "panel"),
                    "title": module_name,
                    "purpose": f"{screen_title} module for {module_name}.",
                    "data_keys": [str(item) for item in _as_list(module.get("items")) if str(item).strip()][:4],
                }
            )
        interaction_map.extend(
            {
                "screen_id": screen_id,
                "action": action,
                "result": f"Updates {screen_title} and keeps the user in flow.",
            }
            for action in [str(item) for item in _as_list(screen.get("primary_actions")) if str(item).strip()][:3]
        )
        mock_data[screen_id] = {
            "highlights": [
                str(screen.get("headline") or screen_title),
                str(screen.get("purpose") or "Clarify the next best move."),
                str(screen.get("success_state") or "Keep the workflow moving."),
            ],
            "modules": [
                {
                    "name": str(module.get("name") or f"Module {module_index + 1}"),
                    "items": [str(item) for item in _as_list(module.get("items")) if str(item).strip()][:4],
                }
                for module_index, module in enumerate(modules)
            ],
        }

    acceptance_flows = [
        {
            "id": str(flow.get("id") or f"flow-{index + 1}"),
            "name": str(flow.get("name") or f"Flow {index + 1}"),
            "goal": str(flow.get("goal") or ""),
            "steps": [str(item) for item in _as_list(flow.get("steps")) if str(item).strip()][:6],
        }
        for index, flow in enumerate(flows)
    ]

    return {
        "schema_version": "1.0",
        "framework_target": "nextjs-app-router",
        "title": str(title or "Prototype"),
        "subtitle": str(subtitle or ""),
        "shell": {
            "kind": str(prototype_payload.get("kind") or "product-workspace"),
            "layout": str(shell.get("layout") or "sidebar"),
            "density": str(shell.get("density") or "medium"),
            "status_badges": [str(item) for item in _as_list(shell.get("status_badges")) if str(item).strip()][:4],
            "primary_navigation": [
                {
                    "id": str(item.get("id") or _slug(item.get("label") or "nav", prefix="nav")),
                    "label": str(item.get("label") or "Section"),
                    "priority": str(item.get("priority") or "primary"),
                }
                for item in _as_list(shell.get("primary_navigation"))
                if isinstance(item, dict)
            ][:6],
        },
        "theme": {
            "primary": str(primary or "#2563eb"),
            "accent": str(accent or "#f59e0b"),
            "background": str(colors.get("background") or "#0b1020"),
            "surface": str(colors.get("surface") or "#111827"),
            "text": str(colors.get("text") or "#f8fafc"),
            "heading_font": str(typography.get("heading") or "IBM Plex Sans"),
            "body_font": str(typography.get("body") or "Noto Sans JP"),
        },
        "selected_features": [str(item) for item in features if str(item).strip()][:6],
        "screens": screens,
        "routes": routes,
        "components": components,
        "mock_data": mock_data,
        "state_matrix": state_matrix,
        "interaction_map": interaction_map,
        "acceptance_flows": acceptance_flows,
        "quality_targets": [str(item) for item in quality_focus or [] if str(item).strip()] or [
            "distinctive visual direction",
            "mobile resilience",
            "clear next action",
            "accessible contrast floor",
        ],
        "decision_scope": _as_dict(decision_scope),
    }


def _prototype_data_file(prototype_spec: dict[str, Any]) -> str:
    payload = json.dumps(prototype_spec, ensure_ascii=False, indent=2)
    return dedent(
        f"""\
        export const prototypeSpec = {payload} as const;
        """
    )


def _prototype_shell_component(title: str) -> str:
    escaped_title = json.dumps(title, ensure_ascii=False)
    return dedent(
        f"""\
        "use client";

        import Link from "next/link";
        import {{ useMemo, useState }} from "react";
        import {{ prototypeSpec }} from "../lib/prototype-data";

        type RouteRecord = {{
          readonly id: string;
          readonly screen_id: string;
          readonly path: string;
          readonly layout: string;
          readonly title: string;
        }};
        type ModuleRecord = {{ readonly name: string; readonly type: string; readonly items: readonly string[] }};
        type ScreenRecord = {{
          readonly id: string;
          readonly title: string;
          readonly headline: string;
          readonly purpose: string;
          readonly supporting_text?: string;
          readonly primary_actions: readonly string[];
          readonly modules: ReadonlyArray<ModuleRecord>;
        }};
        type FlowRecord = {{ readonly id: string; readonly name: string; readonly goal: string; readonly steps: readonly string[] }};
        type StateRecord = {{ readonly state: string; readonly trigger: string; readonly summary: string }};
        type ScreenData = {{
          readonly highlights?: readonly string[];
          readonly modules?: ReadonlyArray<{{ readonly name: string; readonly items: readonly string[] }}>;
        }};

        export function PrototypeShell({{ screenId }}: {{ screenId: string }}) {{
          const screens = prototypeSpec.screens as unknown as readonly ScreenRecord[];
          const routeMap = prototypeSpec.routes as unknown as readonly RouteRecord[];
          const flows = prototypeSpec.acceptance_flows as unknown as readonly FlowRecord[];
          const screen = useMemo(
            () => screens.find((item) => item.id === screenId) ?? screens[0],
            [screenId, screens],
          );
          const stateMatrix = prototypeSpec.state_matrix as unknown as Record<string, readonly StateRecord[]>;
          const mockData = prototypeSpec.mock_data as unknown as Record<string, ScreenData>;
          const states = stateMatrix[screen.id] ?? [];
          const [activeState, setActiveState] = useState(states[0]?.state ?? "default");
          const currentState = states.find((item) => item.state === activeState) ?? states[0];
          const currentData = mockData[screen.id] ?? {{}};
          const relevantFlows = flows.filter((flow) =>
            flow.steps.some((step) => step.includes(screen.title) || step.includes(screen.headline || "")),
          );

          return (
            <main className="prototype-shell">
              <aside className="shell-rail">
                <div className="brand-mark">
                  <span className="brand-dot" aria-hidden="true" />
                  <div>
                    <p className="eyebrow">Runnable prototype</p>
                    <h1>{escaped_title}</h1>
                  </div>
                </div>
                <p className="shell-note">{{prototypeSpec.subtitle}}</p>
                <div className="feature-pills">
                  {{prototypeSpec.selected_features.map((feature) => (
                    <span key={{feature}} className="pill">
                      {{feature}}
                    </span>
                  ))}}
                </div>
                <nav aria-label="Prototype routes">
                  <ul className="nav-list">
                    {{routeMap.map((route) => (
                      <li key={{route.id}}>
                        <Link
                          href={{route.path}}
                          className={{route.screen_id === screen.id ? "nav-link active" : "nav-link"}}
                        >
                          <span>{{route.title}}</span>
                          <small>{{route.layout}}</small>
                        </Link>
                      </li>
                    ))}}
                  </ul>
                </nav>
              </aside>

              <section className="canvas">
                <header className="panel hero-panel">
                  <div>
                    <p className="eyebrow">Active screen</p>
                    <h2>{{screen.headline || screen.title}}</h2>
                    <p className="lede">{{screen.purpose}}</p>
                  </div>
                  <div className="action-row">
                    {{screen.primary_actions.slice(0, 3).map((action) => (
                      <button key={{action}} type="button" className="action-button">
                        {{action}}
                      </button>
                    ))}}
                  </div>
                </header>

                <section className="panel">
                  <div className="panel-head">
                    <div>
                      <p className="eyebrow">State coverage</p>
                      <h3>Review the full interaction envelope</h3>
                    </div>
                    <p className="caption">{{currentState?.summary}}</p>
                  </div>
                  <div className="state-row">
                    {{states.map((state) => (
                      <button
                        key={{state.state}}
                        type="button"
                        className={{state.state === activeState ? "state-pill active" : "state-pill"}}
                        onClick={{() => setActiveState(state.state)}}
                      >
                        <span>{{state.state}}</span>
                        <small>{{state.trigger}}</small>
                      </button>
                    ))}}
                  </div>
                </section>

                <div className="content-grid">
                  <section className="panel">
                    <div className="panel-head">
                      <div>
                        <p className="eyebrow">Modules</p>
                        <h3>Screen composition</h3>
                      </div>
                      <p className="caption">{{screen.supporting_text}}</p>
                    </div>
                    <div className="module-grid">
                      {{screen.modules.map((module) => (
                        <article key={{module.name}} className="module-card">
                          <p className="module-type">{{module.type}}</p>
                          <h4>{{module.name}}</h4>
                          <ul>
                            {{module.items.slice(0, 4).map((item) => (
                              <li key={{item}}>{{item}}</li>
                            ))}}
                          </ul>
                        </article>
                      ))}}
                    </div>
                  </section>

                  <section className="panel">
                    <div className="panel-head">
                      <div>
                        <p className="eyebrow">Mock data</p>
                        <h3>Domain realism</h3>
                      </div>
                      <p className="caption">Generated from the design contract, ready for iteration.</p>
                    </div>
                    <div className="stack">
                      {{(currentData.highlights ?? []).map((item) => (
                        <div key={{item}} className="data-card">
                          {{item}}
                        </div>
                      ))}}
                      {{(currentData.modules ?? []).map((module) => (
                        <article key={{module.name}} className="data-group">
                          <strong>{{module.name}}</strong>
                          <div className="data-tags">
                            {{module.items.map((item) => (
                              <span key={{item}} className="tag">
                                {{item}}
                              </span>
                            ))}}
                          </div>
                        </article>
                      ))}}
                    </div>
                  </section>
                </div>

                <div className="content-grid">
                  <section className="panel">
                    <div className="panel-head">
                      <div>
                        <p className="eyebrow">Acceptance flows</p>
                        <h3>Click-through storyline</h3>
                      </div>
                    </div>
                    <div className="flow-stack">
                      {{(relevantFlows.length > 0 ? relevantFlows : flows).map((flow) => (
                        <article key={{flow.id}} className="flow-card">
                          <div className="flow-head">
                            <h4>{{flow.name}}</h4>
                            <span>{{flow.goal}}</span>
                          </div>
                          <ol>
                            {{flow.steps.map((step) => (
                              <li key={{step}}>{{step}}</li>
                            ))}}
                          </ol>
                        </article>
                      ))}}
                    </div>
                  </section>

                  <section className="panel">
                    <div className="panel-head">
                      <div>
                        <p className="eyebrow">Activity rail</p>
                        <h3>Operational cadence</h3>
                      </div>
                    </div>
                    <div className="activity-stack">
                      {{(prototypeSpec.mock_data.activity_feed ?? []).map((item) => (
                        <article key={{`${{item.time}}-${{item.label}}`}} className="activity-item">
                          <div className="activity-time">{{item.time}}</div>
                          <div>
                            <strong>{{item.label}}</strong>
                            <p>{{item.detail}}</p>
                          </div>
                        </article>
                      ))}}
                    </div>
                  </section>
                </div>
              </section>
            </main>
          );
        }}
        """
    )


def _page_file(relative_import: str, screen_id: str) -> str:
    return dedent(
        f"""\
        import {{ PrototypeShell }} from "{relative_import}";

        export default function Page() {{
          return <PrototypeShell screenId={json.dumps(screen_id)} />;
        }}
        """
    )


def _globals_css(prototype_spec: dict[str, Any]) -> str:
    theme = _as_dict(prototype_spec.get("theme"))
    background = str(theme.get("background") or "#081121")
    primary = str(theme.get("primary") or "#2563eb")
    accent = str(theme.get("accent") or "#f59e0b")
    text = str(theme.get("text") or "#f8fafc")
    body_font = str(theme.get("body_font") or "Noto Sans JP")
    heading_font = str(theme.get("heading_font") or "IBM Plex Sans")
    return dedent(
        f"""\
        :root {{
          --bg: {background};
          --panel: rgba(15, 23, 42, 0.76);
          --panel-strong: rgba(15, 23, 42, 0.9);
          --surface: rgba(255, 255, 255, 0.06);
          --surface-strong: rgba(255, 255, 255, 0.12);
          --text: {text};
          --muted: color-mix(in srgb, {text} 64%, #94a3b8);
          --border: color-mix(in srgb, {text} 14%, transparent);
          --primary: {primary};
          --accent: {accent};
          --shadow: 0 24px 70px rgba(2, 8, 23, 0.35);
        }}

        * {{
          box-sizing: border-box;
        }}

        html, body {{
          margin: 0;
          min-height: 100%;
          background:
            radial-gradient(circle at 0% 0%, color-mix(in srgb, var(--accent) 18%, transparent), transparent 26%),
            radial-gradient(circle at 100% 10%, color-mix(in srgb, var(--primary) 22%, transparent), transparent 24%),
            linear-gradient(180deg, color-mix(in srgb, var(--bg) 78%, #020617), var(--bg));
          color: var(--text);
          font-family: "{body_font}", "Hiragino Sans", sans-serif;
        }}

        body {{
          padding: 28px;
        }}

        a {{
          color: inherit;
        }}

        h1, h2, h3, h4 {{
          margin: 0;
          font-family: "{heading_font}", "Hiragino Sans", sans-serif;
          letter-spacing: -0.02em;
        }}

        p {{
          margin: 0;
          line-height: 1.6;
          color: var(--muted);
        }}

        ul, ol {{
          margin: 0;
          padding-left: 18px;
        }}

        .prototype-shell {{
          display: grid;
          grid-template-columns: minmax(260px, 300px) minmax(0, 1fr);
          gap: 20px;
          max-width: 1480px;
          margin: 0 auto;
        }}

        .shell-rail,
        .panel {{
          border: 1px solid var(--border);
          border-radius: 28px;
          background: var(--panel);
          box-shadow: var(--shadow);
          backdrop-filter: blur(20px);
        }}

        .shell-rail {{
          position: sticky;
          top: 28px;
          align-self: start;
          padding: 24px;
        }}

        .brand-mark {{
          display: flex;
          gap: 14px;
          align-items: flex-start;
        }}

        .brand-dot {{
          width: 14px;
          height: 14px;
          border-radius: 999px;
          margin-top: 4px;
          background: linear-gradient(135deg, var(--accent), var(--primary));
          box-shadow: 0 0 28px color-mix(in srgb, var(--accent) 55%, transparent);
        }}

        .eyebrow {{
          text-transform: uppercase;
          letter-spacing: 0.18em;
          font-size: 0.72rem;
          color: color-mix(in srgb, var(--accent) 54%, var(--text));
        }}

        .shell-note {{
          margin-top: 16px;
          max-width: 28ch;
        }}

        .feature-pills,
        .data-tags,
        .action-row,
        .state-row {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
        }}

        .feature-pills {{
          margin-top: 18px;
        }}

        .pill,
        .tag {{
          display: inline-flex;
          align-items: center;
          padding: 7px 11px;
          border-radius: 999px;
          background: var(--surface);
          border: 1px solid var(--border);
          font-size: 0.78rem;
        }}

        .nav-list {{
          list-style: none;
          padding: 0;
          margin: 22px 0 0;
          display: grid;
          gap: 10px;
        }}

        .nav-link {{
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          padding: 14px 16px;
          border-radius: 18px;
          text-decoration: none;
          background: var(--surface);
          border: 1px solid transparent;
        }}

        .nav-link small {{
          color: var(--muted);
          text-transform: uppercase;
          letter-spacing: 0.14em;
          font-size: 0.64rem;
        }}

        .nav-link.active {{
          border-color: color-mix(in srgb, var(--accent) 45%, transparent);
          background: color-mix(in srgb, var(--accent) 12%, var(--surface));
        }}

        .canvas {{
          display: grid;
          gap: 18px;
        }}

        .panel {{
          padding: 24px;
        }}

        .hero-panel {{
          display: flex;
          justify-content: space-between;
          gap: 18px;
          align-items: flex-start;
          background: linear-gradient(
            180deg,
            color-mix(in srgb, var(--panel-strong) 82%, var(--accent) 3%),
            color-mix(in srgb, var(--panel) 88%, var(--primary) 3%)
          );
        }}

        .hero-panel h2 {{
          font-size: clamp(1.8rem, 3vw, 2.6rem);
          margin-top: 6px;
        }}

        .lede {{
          margin-top: 12px;
          max-width: 48ch;
          font-size: 0.98rem;
        }}

        .action-button {{
          appearance: none;
          border: 1px solid color-mix(in srgb, var(--primary) 55%, transparent);
          border-radius: 16px;
          background: color-mix(in srgb, var(--primary) 18%, var(--surface));
          color: var(--text);
          padding: 12px 14px;
          font: inherit;
          font-weight: 600;
        }}

        .panel-head {{
          display: flex;
          justify-content: space-between;
          gap: 16px;
          align-items: flex-start;
          margin-bottom: 18px;
        }}

        .panel-head h3 {{
          margin-top: 6px;
          font-size: 1.1rem;
        }}

        .caption {{
          max-width: 36ch;
          font-size: 0.84rem;
        }}

        .state-pill {{
          min-width: 122px;
          text-align: left;
          border-radius: 18px;
          border: 1px solid var(--border);
          background: var(--surface);
          color: var(--text);
          padding: 12px 14px;
          font: inherit;
          display: grid;
          gap: 4px;
        }}

        .state-pill small {{
          color: var(--muted);
        }}

        .state-pill.active {{
          border-color: color-mix(in srgb, var(--accent) 48%, transparent);
          background: color-mix(in srgb, var(--accent) 14%, var(--surface));
        }}

        .content-grid {{
          display: grid;
          gap: 18px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }}

        .module-grid,
        .flow-stack,
        .stack,
        .activity-stack {{
          display: grid;
          gap: 12px;
        }}

        .module-grid {{
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }}

        .module-card,
        .flow-card,
        .data-card,
        .data-group,
        .activity-item {{
          border-radius: 22px;
          border: 1px solid var(--border);
          background: color-mix(in srgb, var(--surface) 90%, transparent);
          padding: 16px;
        }}

        .module-type {{
          text-transform: uppercase;
          letter-spacing: 0.16em;
          font-size: 0.68rem;
          color: color-mix(in srgb, var(--accent) 48%, var(--muted));
        }}

        .module-card h4,
        .flow-card h4 {{
          margin-top: 6px;
          font-size: 1rem;
        }}

        .module-card ul,
        .flow-card ol {{
          margin-top: 12px;
          display: grid;
          gap: 8px;
        }}

        .flow-head {{
          display: flex;
          justify-content: space-between;
          gap: 12px;
          align-items: baseline;
        }}

        .flow-head span {{
          color: var(--muted);
          font-size: 0.82rem;
        }}

        .activity-item {{
          display: grid;
          grid-template-columns: 72px minmax(0, 1fr);
          gap: 14px;
        }}

        .activity-time {{
          color: color-mix(in srgb, var(--accent) 56%, var(--text));
          font-weight: 600;
        }}

        @media (max-width: 1080px) {{
          .prototype-shell,
          .content-grid,
          .module-grid {{
            grid-template-columns: 1fr;
          }}

          .shell-rail {{
            position: static;
          }}
        }}

        @media (max-width: 720px) {{
          body {{
            padding: 16px;
          }}

          .panel,
          .shell-rail {{
            border-radius: 22px;
            padding: 18px;
          }}

          .hero-panel,
          .panel-head {{
            grid-template-columns: 1fr;
            display: grid;
          }}
        }}
        """
    )


def build_nextjs_prototype_app(
    *,
    title: str,
    subtitle: str,
    primary: str,
    accent: str,
    prototype_spec: dict[str, Any],
) -> dict[str, Any]:
    routes = [dict(item) for item in _as_list(prototype_spec.get("routes")) if isinstance(item, dict)]
    if not routes:
        routes = [{"screen_id": "workspace", "path": "/", "segment": ""}]
    files: list[dict[str, str]] = []
    files.append(
        {
            "path": "package.json",
            "kind": "json",
            "content": json.dumps(
                {
                    "name": _slug(title, prefix="pylon-prototype"),
                    "private": True,
                    "scripts": {
                        "dev": "next dev",
                        "build": "next build",
                        "start": "next start",
                    },
                    "dependencies": {
                        "next": _NEXT_VERSION,
                        "react": _REACT_VERSION,
                        "react-dom": _REACT_VERSION,
                    },
                    "devDependencies": {
                        "typescript": _TYPESCRIPT_VERSION,
                        "tailwindcss": _TAILWIND_VERSION,
                        "@types/node": "^24.0.0",
                        "@types/react": "^19.0.0",
                        "@types/react-dom": "^19.0.0",
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        }
    )
    files.append(
        {
            "path": "tsconfig.json",
            "kind": "json",
            "content": json.dumps(
                {
                    "compilerOptions": {
                        "target": "ES2017",
                        "lib": ["dom", "dom.iterable", "esnext"],
                        "allowJs": False,
                        "skipLibCheck": True,
                        "strict": True,
                        "noEmit": True,
                        "esModuleInterop": True,
                        "module": "esnext",
                        "moduleResolution": "bundler",
                        "resolveJsonModule": True,
                        "isolatedModules": True,
                        "jsx": "preserve",
                        "incremental": True,
                        "plugins": [{"name": "next"}],
                    },
                    "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],
                    "exclude": ["node_modules"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        }
    )
    files.extend(
        [
            {
                "path": "next-env.d.ts",
                "kind": "ts",
                "content": '/// <reference types="next" />\n/// <reference types="next/image-types/global" />\n\n// This file is auto-generated by Next.js.\n',
            },
            {
                "path": "app/layout.tsx",
                "kind": "tsx",
                "content": dedent(
                    f"""\
                    import type {{ Metadata }} from "next";
                    import type {{ ReactNode }} from "react";
                    import "./globals.css";

                    export const metadata: Metadata = {{
                      title: {json.dumps(title, ensure_ascii=False)},
                      description: {json.dumps(subtitle, ensure_ascii=False)},
                    }};

                    export default function RootLayout({{ children }}: {{ children: ReactNode }}) {{
                      return (
                        <html lang="ja">
                          <body>{{children}}</body>
                        </html>
                      );
                    }}
                    """
                ),
            },
            {
                "path": "app/globals.css",
                "kind": "css",
                "content": _globals_css(prototype_spec),
            },
            {
                "path": "app/lib/prototype-data.ts",
                "kind": "ts",
                "content": _prototype_data_file(
                    {
                        **prototype_spec,
                        "theme": {
                            **_as_dict(prototype_spec.get("theme")),
                            "primary": primary,
                            "accent": accent,
                        },
                    }
                ),
            },
            {
                "path": "app/components/prototype-shell.tsx",
                "kind": "tsx",
                "content": _prototype_shell_component(title),
            },
            {
                "path": "app/page.tsx",
                "kind": "tsx",
                "content": _page_file("./components/prototype-shell", str(routes[0].get("screen_id") or "screen-1")),
            },
            {
                "path": "app/api/prototype/route.ts",
                "kind": "ts",
                "content": dedent(
                    """\
                    import { NextResponse } from "next/server";
                    import { prototypeSpec } from "../../lib/prototype-data";

                    export async function GET() {
                      return NextResponse.json(prototypeSpec);
                    }
                    """
                ),
            },
        ]
    )
    for route in routes[1:]:
        segment = str(route.get("segment") or "").strip("/")
        if not segment:
            continue
        files.append(
            {
                "path": f"app/{segment}/page.tsx",
                "kind": "tsx",
                "content": _page_file("../components/prototype-shell", str(route.get("screen_id") or "")),
            }
        )
    return {
        "artifact_kind": "runnable-prototype",
        "framework": "nextjs",
        "router": "app",
        "entry_routes": [str(route.get("path") or "") for route in routes if str(route.get("path") or "").strip()],
        "dependencies": {
            "next": _NEXT_VERSION,
            "react": _REACT_VERSION,
            "react-dom": _REACT_VERSION,
        },
        "dev_dependencies": {
            "typescript": _TYPESCRIPT_VERSION,
            "tailwindcss": _TAILWIND_VERSION,
            "@types/node": "^24.0.0",
            "@types/react": "^19.0.0",
            "@types/react-dom": "^19.0.0",
        },
        "install_command": "npm install",
        "dev_command": "npm run dev",
        "build_command": "npm run build",
        "mock_api": ["/api/prototype"],
        "files": files,
        "artifact_summary": {
            "screen_count": len([item for item in _as_list(prototype_spec.get("screens")) if isinstance(item, dict)]),
            "route_count": len(routes),
            "file_count": len(files),
        },
    }


def materialize_prototype_app(prototype_app: dict[str, Any], destination: str | Path) -> Path:
    destination_path = Path(destination)
    destination_path.mkdir(parents=True, exist_ok=True)
    for file_record in _as_list(prototype_app.get("files")):
        file_payload = _as_dict(file_record)
        path = destination_path / str(file_payload.get("path") or "").strip()
        if not path.name:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(file_payload.get("content") or ""), encoding="utf-8")
    return destination_path
