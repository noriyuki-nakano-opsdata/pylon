# Design Phase P0/P1 Issues

P0/P1 を、そのまま pylon のマルチエージェント基盤へ割り当てられる 10 本の issue に分解した。
owner は既存の agent lane を前提にしている。

1. `DES-001` Preview HTML persistence contract
owner: `backend-integrator`
scope: `designVariants[*].preview_html` を compact storage で保持し、LLM preview を消さない。
status: implemented

2. `DES-002` Preview hydrate preservation and fallback
owner: `backend-integrator`
scope: GET hydrate 時に valid preview を保持し、欠落/短すぎる/壊れた preview のみ template fallback する。
status: implemented

3. `DES-003` Preview validation metadata
owner: `design-critic`
scope: `preview_meta` に source, extraction, validation, fallback reason, interactive features を付与する。
status: implemented

4. `DES-004` Structured design artifact contract
owner: `backend-integrator`
scope: `scorecard`, `primary_workflows`, `screen_specs`, `artifact_completeness` を variant payload に追加する。
status: implemented

5. `DES-005` Design freshness and provenance
owner: `product-orchestrator`
scope: current decision fingerprint と variant fingerprint を比較して `freshness` を計算する。
status: implemented

6. `DES-006` Phase contract completeness for design
owner: `quality-lab`
scope: design phase contract に completeness, preview source, freshness を反映する。
status: implemented

7. `DES-007` Approval handoff guardrail
owner: `frontend-builder`
scope: stale / incomplete な selected design では approval handoff を無効化する。
status: implemented

8. `DES-008` Selected vs inspected separation in review UI
owner: `ux-architect`
scope: 比較中の案と承認へ渡す案を UI 上で分離し、混線を防ぐ。
status: implemented

9. `DES-009` Preview quality and readiness surfacing
owner: `design-critic`
scope: selected packet と preview panel に freshness/completeness/preview source を表示する。
status: implemented

10. `DES-010` Regression coverage
owner: `quality-lab`
scope: backend pytest と frontend vitest で preview persistence, contract enrichment, stale gating を固定する。
status: implemented
