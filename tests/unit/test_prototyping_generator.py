"""Tests for runnable prototype artifact generation."""

# ruff: noqa: E501

from pathlib import Path

from pylon.prototyping import (
    build_nextjs_prototype_app,
    build_prototype_spec,
    materialize_prototype_app,
)


def _sample_prototype() -> dict[str, object]:
    return {
        "kind": "product-workspace",
        "app_shell": {
            "layout": "sidebar",
            "density": "medium",
            "primary_navigation": [
                {"id": "today", "label": "今日の献立", "priority": "primary"},
                {"id": "inventory", "label": "在庫登録", "priority": "primary"},
            ],
            "status_badges": ["3日分献立", "在庫登録"],
        },
        "screens": [
            {
                "id": "today",
                "title": "今日の献立",
                "purpose": "今日の夕食を5分で決める。",
                "layout": "workspace",
                "headline": "今夜の献立をすぐに決める",
                "supporting_text": "家族の好みと在庫を同時に見る。",
                "primary_actions": ["候補を見る", "在庫を更新する"],
                "modules": [
                    {"name": "おすすめ献立", "type": "panel", "items": ["鶏むね照り焼き", "副菜2品", "20分"]},
                    {"name": "在庫サマリー", "type": "panel", "items": ["鶏むね 1", "小松菜 1", "卵 4"]},
                ],
                "success_state": "今夜の献立と買い足しを確定する。",
            },
            {
                "id": "inventory",
                "title": "在庫登録",
                "purpose": "冷蔵庫の現状を3分で反映する。",
                "layout": "split-view",
                "headline": "写真から在庫を登録する",
                "supporting_text": "不足と期限切れ候補を一緒に確認する。",
                "primary_actions": ["写真で登録する", "手入力で追加する"],
                "modules": [
                    {"name": "登録候補", "type": "queue", "items": ["牛乳", "豆腐", "ピーマン"]},
                ],
                "success_state": "次の献立に必要な材料が見える。",
            },
        ],
        "flows": [
            {
                "id": "flow-1",
                "name": "今夜の献立の初回導線",
                "steps": ["今日の献立を開く", "候補を見る", "不足食材を買い物リストへ送る"],
                "goal": "迷わず夕食を決める。",
            }
        ],
    }


def test_nextjs_prototype_app_generation_and_materialization(tmp_path: Path):
    prototype_spec = build_prototype_spec(
        title="うちメニュー",
        subtitle="家族の夕食計画を助けるアプリ。",
        primary="#1d4ed8",
        accent="#ea580c",
        features=["在庫登録", "3日分献立", "買い物リスト"],
        prototype=_sample_prototype(),
        design_tokens={"colors": {"background": "#0b1020", "text": "#f8fafc"}},
        quality_focus=["mobile resilience", "clear next action"],
    )

    prototype_app = build_nextjs_prototype_app(
        title="うちメニュー",
        subtitle="家族の夕食計画を助けるアプリ。",
        primary="#1d4ed8",
        accent="#ea580c",
        prototype_spec=prototype_spec,
    )
    materialize_prototype_app(prototype_app, tmp_path)

    assert prototype_spec["framework_target"] == "nextjs-app-router"
    assert prototype_spec["routes"][0]["path"] == "/"
    assert prototype_app["framework"] == "nextjs"
    assert prototype_app["artifact_summary"]["file_count"] >= 7
    assert (tmp_path / "package.json").exists()
    assert (tmp_path / "app" / "page.tsx").exists()
    assert (tmp_path / "app" / "components" / "prototype-shell.tsx").read_text(encoding="utf-8").startswith('"use client";')
    second_route_segment = prototype_app["entry_routes"][1].strip("/")
    assert (tmp_path / "app" / second_route_segment / "page.tsx").exists()
