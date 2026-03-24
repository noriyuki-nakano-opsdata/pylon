# Design Runtime Telemetry Investigation Request

## Summary

`design` phase の成果物品質自体は改善済みです。`opp-smoke` で design workflow を再実行した結果、selected design は `preview-validation` gate を通過し、`previewSource=repaired`、`previewValidationOk=true`、`artifactCompletenessStatus=complete`、`freshnessStatus=fresh` まで回復しています。

一方で、UI の「協調ランタイム」パネルは terminal run 完了後も実態を正しく投影していません。2026-03-17 の再現では、backend 上は `completed` run と `5 checkpoints` を確認できるのに、画面上では `完了ノード 0` と `最新のフォーカスはありません` のままでした。

この依頼の目的は、**design runtime telemetry の表示経路が completed run の実データを取りこぼしている本当の原因を特定し、修正案まで提示すること**です。

## Priority

- Severity: `P1`
- Affected area: lifecycle `design` phase runtime panel
- Environment: local dev
- Date observed: `2026-03-17`
- Project: `opp-smoke`
- Workflow: `lifecycle-design-opp-smoke`

## Investigation Goal

以下を明確にしてください。

1. backend で保持している completed run / checkpoints / latest workflow run のどのデータが UI 側へ届いていないのか
2. 問題が backend projection なのか、frontend selection/aggregation なのか
3. completed run の runtime panel が何を source of truth にすべきか
4. 再発防止のための最小修正案とテスト追加案

## Confirmed Facts

### 1. Design workflow は新 graph で完了している

- Prepare endpoint:
  - `POST /api/v1/lifecycle/projects/opp-smoke/phases/design/prepare`
  - team に以下 5 node が含まれていました
    - `claude-designer`
    - `gemini-designer`
    - `claude-preview-validator`
    - `gemini-preview-validator`
    - `design-evaluator`

### 2. 実行した run

- Async wrapper run id: `run_async_4c8464accb3c482c9928ac0301adef1c`
- Workflow id: `lifecycle-design-opp-smoke`
- Started at: `2026-03-16T21:00:54.669184+00:00`
- Completed at: `2026-03-16T21:07:06.700176+00:00`
  - JST では `2026-03-17 06:07:06`

### 3. Backend log 上は checkpoints 付きで sync 完了している

`/tmp/pylon-backend-rootfix.log` で以下を確認済みです。

- `2026-03-17 06:07:06,846`
  - `async_workflow_run_synced_lifecycle_project`
  - `workflow_id=lifecycle-design-opp-smoke`
  - `project_id=opp-smoke`
  - `phase=design`
  - `run_id=run_async_4c8464accb3c482c9928ac0301adef1c`
  - `status=completed`
  - `checkpoints=5`

- `2026-03-17 06:07:06,871`
  - `async_workflow_run_finished`
  - `events=5`
  - `checkpoints=5`
  - `duration_ms=372030`

### 4. Run payload 自体も validator node 完了を返している

`GET /api/v1/runs/run_async_4c8464accb3c482c9928ac0301adef1c`

observed logs:

- `run:run_f2fc3e9be08345ffbdf0a647703a87f0 workflow:lifecycle-design-opp-smoke`
- `node:claude-designer status:ok attempt:1`
- `node:gemini-designer status:ok attempt:1`
- `node:claude-preview-validator status:ok attempt:1`
- `node:gemini-preview-validator status:ok attempt:1`
- `node:design-evaluator status:ok attempt:1`

注意点:

- wrapper run id は `run_async_...`
- logs 内には別の inner run id `run_f2fc3e9be08345ffbdf0a647703a87f0` が出ています
- ただし `src/pylon/api/async_runs.py` では checkpoint 保存時に `run_id=async wrapper run id` を再設定しています

### 5. Checkpoint endpoint は現在 5 件返している

`GET /api/v1/runs/run_async_4c8464accb3c482c9928ac0301adef1c/checkpoints`

observed result:

- `count = 5`
- checkpoint payload に design variant artifacts が含まれる

つまり、**現時点では checkpoint が存在しないわけではありません**。

### 6. Lifecycle project contract も正常化している

`GET /api/v1/lifecycle/projects/opp-smoke`

observed design contract:

- `selectedDesignId = claude-designer`
- `previewSource = repaired`
- `previewValidationOk = true`
- `previewValidationIssueCount = 0`
- `artifactCompletenessStatus = complete`
- `freshnessStatus = fresh`
- `preview-validation` quality gate = `passed: true`
- `phaseStatuses`
  - `design = completed`
  - `approval = available`

### 7. それでも UI の runtime panel は completed state を正しく出していない

URL:

- `http://127.0.0.1:5176/p/opp-smoke/lifecycle/design`

2026-03-17 の hard reload 後も、画面上で以下を確認しました。

- `実行状態: 完了`
- `対象フェーズ: デザイン`
- `完了ノード: 0`
- `現在のフォーカス: 最新のフォーカスはありません`
- `現在はデザイン実行のライブイベントがありません。`

同じ画面で確認できた正常情報:

- `修復済みプレビュー`
- `検証: 適合`
- `この方向で承認へ` ボタンは enabled
- iframe preview は表示されている

要するに、**artifact quality / approval gate は正しいが、runtime panel だけが completed run を空表示している** 状態です。

## Reproduction Steps

### 1. Backend / frontend を起動

- backend: `http://127.0.0.1:8080`
- frontend: `http://127.0.0.1:5176`

### 2. Prepare

```bash
curl -sS -X POST \
  http://127.0.0.1:8080/api/v1/lifecycle/projects/opp-smoke/phases/design/prepare
```

### 3. Design input を作成して run 開始

```bash
curl -sS -o /tmp/opp-smoke-project-runtime.json \
  http://127.0.0.1:8080/api/v1/lifecycle/projects/opp-smoke

.venv/bin/python -c '
import json
from pylon.lifecycle import lifecycle_phase_input
project=json.load(open("/tmp/opp-smoke-project-runtime.json"))
json.dump({"input": lifecycle_phase_input(project, "design")}, open("/tmp/opp-smoke-design-run-body.json", "w"))
'

curl -sS -X POST \
  -H "content-type: application/json" \
  --data @/tmp/opp-smoke-design-run-body.json \
  -o /tmp/opp-smoke-design-run-response.json \
  http://127.0.0.1:8080/api/v1/workflows/lifecycle-design-opp-smoke/runs
```

### 4. Run 完了後の確認

```bash
curl -sS \
  http://127.0.0.1:8080/api/v1/runs/run_async_4c8464accb3c482c9928ac0301adef1c

curl -sS \
  http://127.0.0.1:8080/api/v1/runs/run_async_4c8464accb3c482c9928ac0301adef1c/checkpoints

curl -sS \
  http://127.0.0.1:8080/api/v1/lifecycle/projects/opp-smoke
```

### 5. UI 確認

- `http://127.0.0.1:5176/p/opp-smoke/lifecycle/design`
- ページを hard reload
- 「協調ランタイム」セクションを見る

## Likely Fault Domain

現時点の情報から、backend persistence より **frontend runtime projection / selection** が本命です。

### Backend で確認したい箇所

- [async_runs.py](/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/api/async_runs.py)
  - `_persist_artifacts()`
  - `sync_lifecycle_project_for_run()`
- [workflow_service.py](/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/control_plane/workflow_service.py)
  - `list_checkpoint_payloads()`
  - `get_run_payload()`
- [routes.py](/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/api/routes.py)
  - `list_run_checkpoints()`
  - lifecycle project sync path

### Frontend で確認したい箇所

- [DesignPhase.tsx](/Users/noriyuki.nakano/Documents/99_work/pylon/ui/src/pages/lifecycle/DesignPhase.tsx)
  - runtime panel 表示
- [pulseUtils.ts](/Users/noriyuki.nakano/Documents/99_work/pylon/ui/src/components/lifecycle/pulseUtils.ts)
  - `buildPhasePulseSnapshot()`
  - `resolvePhaseTelemetry()`
  - `resolvePhaseRuntimeSummary()`
- [selectors.ts](/Users/noriyuki.nakano/Documents/99_work/pylon/ui/src/lifecycle/selectors.ts)
  - completed node count の算出
- `ui/src/hooks/useWorkflowRun.ts`
  - terminal run の `agentProgress` / run payload hydration
- `ui/src/hooks/useLifecycleRuntimeStream.ts`
  - completed run 後の phase telemetry の扱い

## Working Hypotheses

### Hypothesis A

UI は `completed` run に対して `checkpoints` を source of truth にしておらず、live telemetry が消えた後に `completedNodeCount=0` へフォールバックしている。

### Hypothesis B

UI は workflow runs endpoint から latest completed run を取れているが、runtime panel の completed summary 生成で `runtimeSummary` か `runtimeLiveTelemetry` のどちらか一方しか見ておらず、terminal run の persisted state を無視している。

### Hypothesis C

`async wrapper run` と `inner run` の二層構造があり、どこかの selector が inner run ベースの進捗情報を期待しているため、completed 後の集約が空になる。

### Hypothesis D

`events?phase=design` の live stream が止まった時点で、UI が terminal summary を再構築せず、「ライブイベントなし = 完了ノードなし」とみなしている。

## What We Need Back

調査結果として以下を返してください。

1. 根本原因
2. どのレイヤーの不整合か
   - backend persistence
   - backend projection
   - frontend fetching
   - frontend selector / rendering
3. 最小修正案
4. 回帰防止テスト案
5. completed run と in-progress run での source of truth の整理

## Acceptance Criteria

以下を満たしたら完了です。

1. `design` completed run 後に UI の runtime panel が `完了ノード > 0` を表示する
2. `現在のフォーカス` が最後の meaningful node か action を表示する
3. `GET /api/v1/runs/{run_id}/checkpoints` の内容と UI 表示が説明可能になる
4. `in-progress` と `completed` の両ケースで回帰テストが追加される
5. 調査結果に「なぜ artifact は正しいのに runtime panel だけ空になるのか」が明確に書かれている

## Notes

- 今回の依頼は design artifact の品質調整ではありません。
- `preview-validation` や `approval gate` の修正は別件として概ね機能しています。
- 調査対象は、**runtime telemetry の最終表示整合性** に限定します。
