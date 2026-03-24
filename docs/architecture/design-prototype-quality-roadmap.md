# Design Prototype Quality Roadmap

## Goal

Pylon の design 成果物を「比較用 HTML モック」から「実際に触れて評価できる高精度プロトタイプ」へ引き上げる。
目標は 3 つ。

1. デザインの審美品質を明確に上げる
2. 実装 fidelity を上げて、承認と開発の判断精度を上げる
3. 評価ループを本物にして、品質を継続的に改善できるようにする

## Current Ceiling

現状の品質上限は、モデル品質より生成方式で決まっている。

- design variant は最終的に `preview_html` という 1 枚の HTML 文字列で保存される  
  参照: `/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/lifecycle/orchestrator.py:3818`
- design の中核データは `screens`, `flows`, `interaction_principles` 程度で、状態遷移、データモデル、コンポーネント階層、イベント契約がない  
  参照: `/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/lifecycle/orchestrator.py:2644`
- preview は固定テンプレートに design payload を流し込む方式で、表現の自由度が低い  
  参照: `/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/lifecycle/orchestrator.py:10128`
- design score は実測ではなく初期値ベースで入っている  
  参照: `/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/lifecycle/orchestrator.py:3765`
- design phase の LLM 出力契約は JSON metadata であって、実 UI コードではない  
  参照: `/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/lifecycle/orchestrator.py:8168`
- development phase の frontend bundle も `sections`, `feature_cards`, `css_tokens` などの軽量 plan に留まる  
  参照: `/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/lifecycle/orchestrator.py:8637`
- development integrator でも最終成果物は single-file HTML で、Next.js や React app ではない  
  参照: `/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/lifecycle/orchestrator.py:8862`
- build quality 判定も、審美性や interaction 品質ではなく、CSS/JS/ARIA/viewport の有無に近い  
  参照: `/Users/noriyuki.nakano/Documents/99_work/pylon/ui/src/pages/lifecycle/DevelopmentPhase.tsx:50`
- design desk は iframe で `preview_html` を見せているだけで、状態比較や interaction diff の可視化は弱い  
  参照: `/Users/noriyuki.nakano/Documents/99_work/pylon/ui/src/pages/lifecycle/DesignPhase.tsx:775`

結論として、今の pipeline は「いい prompt を当てれば少し良くなる」構造ではなく、「どれだけ頑張っても HTML mock 以上に伸びにくい」構造になっている。

## Why It Still Feels Low Quality

### 1. Artifact Type が弱い

静的 HTML preview は最終的に screenshot 向けの artifact であって、アプリ体験の artifact ではない。
そのため以下が表現できない。

- フロー間の状態遷移
- optimistic update / loading / empty / error / success
- フィルタ、ソート、検索、inline edit
- 実データに近い密度
- mobile と desktop で異なる interaction rhythm
- keyboard/focus/sheet/dialog まで含む挙動品質

### 2. Design Direction が浅い

いまの variant 差分は主に次の軸に寄りやすい。

- 色
- density
- nav layout
- screen label

これでは「direction が違う」のではなく「同じ骨格の skin 違い」になりやすい。

### 3. Visual Language の拘束が弱い

`visual_style`, `display_font`, `body_font` はあるが、以下の制約がない。

- type scale
- spacing rhythm
- corner / border language
- motion grammar
- shadow model
- iconography rules
- image / illustration system
- card anatomy
- empty state / form state / table state の設計規則

### 4. Copy と Data が仮想的すぎる

モジュールやフロー名が product-specific になっても、中身のデータ密度と語彙はまだ generic になりやすい。
高品質 UI は layout よりも、画面内の情報密度、情報の真実味、action の切迫感で決まる。

### 5. 評価ループが弱い

「良いかどうか」を判定する evidence が弱い。
今必要なのは、見た目のレビューコメントではなく、artifact を複数の軸で自動採点する仕組み。

## Highest-Leverage Improvements

### A. HTML Mock をやめて Runnable App を第一級 artifact にする

最重要。
v0.app 的な品質に近づけるには、design phase でも最終 artifact を次のどちらかに変えるべき。

1. 実行可能な Next.js app
2. 実行可能な React/Vite app

推奨は Next.js。理由は以下。

- route / layout / data fetching / server action まで含む app shape を持てる
- app router ベースで screen 単位の fidelity が上がる
- v0.app 的な mental model と近い
- 将来の production handoff で再利用しやすい

必要な変更:

- `DesignVariant` に `preview_html` だけでなく `prototype_app` を追加する
- `prototype_app` は `framework`, `files`, `entry_routes`, `dependencies`, `mock_api`, `run_command` を持つ
- preview は `srcDoc` ではなく、sandbox で起動した app URL を iframe する
- 生成後に `npm install && next build` まで通す

### B. Design Output を App Schema に拡張する

現行の `screens` / `flows` では浅い。最低でも次が必要。

- route map
- layout regions
- component tree
- state matrix
- mock data fixtures
- interaction map
- async events
- empty/loading/error/success variants
- responsive adaptation rules
- design tokens v2

推奨 schema:

```json
{
  "routes": [],
  "screens": [],
  "components": [],
  "design_tokens": {},
  "mock_data": {},
  "state_matrix": {},
  "interaction_map": [],
  "acceptance_flows": [],
  "quality_targets": {}
}
```

モデルはまずこの schema を返し、その後 generator が Next.js app に変換する方が安定する。

### C. Generator を 2 段化する

1 回の LLM に app 全体を直接書かせるより、以下の 2 段構成が良い。

1. Product design planner
   - 情報設計
   - screen structure
   - visual direction
   - interaction model
2. App generator
   - Next.js files
   - components
   - mock API
   - test seeds

理由:

- 失敗が局所化する
- critique が差し戻ししやすい
- UI の審美性と実装整合性を別々に改善できる

### D. Design System を内蔵する

生成品質を上げるなら、自由生成を増やすより「強い部品」を持つ方が効く。

必要な資産:

- 5-8 個の art direction packs
- 3-4 個の domain-specific shell families
- typography pair library
- motion recipes
- data-heavy component recipes
- form / table / dashboard / kanban / detail pane / composer / sheet / timeline templates

重要なのは generic component library ではなく、次のような意味を持つ UI family。

- decision studio
- ops cockpit
- family planner
- editorial workspace
- field console
- concierge planner

各 family に対して以下を固定する。

- typography
- spacing scale
- container radius
- elevation model
- table density
- accent usage
- chart / icon style
- motion tone

### E. Mock Data を本物に近づける

高品質に見えるプロトタイプは、ほぼ例外なくデータが強い。
必要なのは lorem ipsum ではなく、domain-specific な realism。

追加するべきもの:

- persona-aware sample records
- realistic timestamps
- realistic quantities / statuses / priorities
- conflicting states
- long labels / short labels の混在
- edge-case rows
- notification / history / activity feed

`uchi-menu` のような consumer product なら、以下が必要。

- 実在感のある献立データ
- 在庫切れ、賞味期限、家族ごとの好み
- 「今日いま困ること」が表面化した状態
- 買い物リストの partial completion
- 朝昼夜で違う時間帯状態

### F. State Coverage を artifact に含める

1 画面 1 状態では評価不能。
最低限、各主要 screen について以下が必要。

- default
- empty
- loading
- error
- success
- dense data
- mobile collapsed

さらに、主要フローは click-through で動くべき。

### G. 評価を Screenshot + Flow + Vision で回す

質を 100 倍にするには prompt 改善ではなく quality gate の改善が必要。

推奨評価パイプライン:

1. desktop / tablet / mobile screenshot capture
2. Lighthouse accessibility / best-practices
3. Playwright critical flow tests
4. visual density checks
5. copy lint
6. vision critique
7. diff-based improvement loop

vision critique で見るべき項目:

- hierarchy clarity
- contrast
- spacing rhythm
- aesthetic conviction
- component consistency
- affordance clarity
- real-app fidelity
- mobile safety
- information scent
- domain realism

### H. Design Judge を本物にする

いまの design score は初期値ベースで、judge も metadata を見ている比率が高い。
judge が見るべき対象を変える。

judge input:

- rendered screenshots
- interactive flow capture
- component inventory
- mock data sample
- generated code structure
- accessibility/perf report

judge output:

- selected variant
- blocking issues
- fix plan
- scorecard with evidence

### I. DesignPhase UI 自体も強化する

比較画面が artifact の価値を引き出せていない。
追加すべきもの:

- 3 device 同時比較
- flow replay
- state matrix browser
- screen-to-screen diff
- token inspector
- component inventory
- evidence rail
- “why this is better” auto-annotation

### J. Development Handoff を code-first に変える

今は design から development へ入ると、selected design を元に single-file HTML を再合成している。
これでは design で高品質 app を作っても潰れる。

必要な変更:

- development input を `selected_design.prototype_app` にする
- frontend bundle は plan ではなく file tree 差分ベースにする
- integrator は HTML builder ではなく app merger にする
- review は lint/test/build/screenshot evidence で行う

## v0-Style Target Architecture

### Target Flow

1. planning phase が product scope と design tokens seed を作る
2. design phase が `prototype_spec` を生成する
3. app generator が Next.js app を生成する
4. sandbox で app を起動する
5. screenshot / flow / a11y / perf を収集する
6. design critic が実 render を見て改善指示を返す
7. app generator が差分修正する
8. design judge が evidence ベースで採用案を決める
9. development phase はその app を土台に本実装へ進む

### Recommended Artifact Model

`DesignVariant` に追加するもの:

- `prototype_spec`
- `prototype_app`
- `mock_data`
- `state_matrix`
- `screenshots`
- `flow_recordings`
- `quality_report`
- `component_inventory`
- `evaluation_evidence`

### Recommended Runtime Model

- app workspace: `/tmp/pylon-prototypes/<project>/<variant>/`
- framework: Next.js 15 + TypeScript + Tailwind
- component base: shadcn/ui or internal kit
- mock backend: route handlers + fixture JSON
- validation: `next build`, Playwright, Lighthouse

## Concrete Implementation Workstreams

### Workstream 1: Upgrade the Contract

変更対象:

- `/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/lifecycle/orchestrator.py`
- `/Users/noriyuki.nakano/Documents/99_work/pylon/ui/src/types/lifecycle.ts`
- `/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/api/routes.py`

やること:

- `DesignVariant` schema 拡張
- `prototype_spec` serializer 追加
- `preview_html` を optional fallback に格下げ

### Workstream 2: Build a Prototype Generator

新規追加候補:

- `src/pylon/prototyping/generator.py`
- `src/pylon/prototyping/templates/next-app/`
- `src/pylon/prototyping/runtime.py`
- `src/pylon/prototyping/evaluator.py`

やること:

- schema -> Next.js file tree generator
- mock data writer
- app runner
- screenshot capture

### Workstream 3: Add a Design Evidence Loop

やること:

- Playwright flow capture
- desktop/tablet/mobile screenshots
- a11y audit
- vision critique prompt
- regression storage

### Workstream 4: Strengthen Visual Direction Packs

新規追加候補:

- `src/pylon/prototyping/art_direction/`
- `src/pylon/prototyping/component_families/`

やること:

- domain-specific art directions
- typography presets
- motion recipes
- shell families

### Workstream 5: Replace Development HTML Builder

変更対象:

- `/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/lifecycle/orchestrator.py`

やること:

- `_development_frontend_handler` を file-plan aware にする
- `_development_integrator_handler` を app-aware にする
- quality snapshot を real evidence ベースにする

## Priority Order

最短で効果が大きい順に並べるとこうなる。

1. `preview_html` 中心設計をやめる
2. `prototype_spec` を追加する
3. Next.js prototype generator を作る
4. screenshot / Playwright / vision critique を回す
5. design system packs を増やす
6. design desk の比較 UI を強化する
7. development を app-first に接続する

## What Not To Do

以下は労力の割に効きにくい。

- prompt に「もっと美しく」と足すだけ
- 色や font の候補だけ増やす
- 単一 HTML template の CSS を肥大化させる
- judge score の数値だけ調整する
- design desk の表層 UI だけ先に豪華にする

これらはすべて、artifact 自体の fidelity が低いままだと頭打ちになる。

## Immediate Next Steps

次の順で着手するのが妥当。

1. `DesignVariant` に `prototype_spec` と `prototype_app` を追加する
2. Next.js prototype generator の最小版を 1 variant だけで動かす
3. `uchi-menu` を最初の golden project にして、desktop/tablet/mobile の screenshot suite を固定する
4. design judge を metadata judge から evidence judge に切り替える
5. development phase が generated app を引き継ぐようにする

## Success Criteria

改善が効いたと言える条件を先に固定する。

- design artifact が static HTML ではなく runnable app である
- 主要 3 フローが click-through で動く
- desktop/tablet/mobile すべてで review 可能
- empty/loading/error/success が揃う
- screenshot だけ見ても domain realism が高い
- design judge の根拠が screenshot / flow / audit に紐づく
- development phase が design artifact を再生成せず継承できる

この方向に切り替えると、Pylon の design phase は「比較用モック生成」ではなく「実装に近い product prototyping engine」になる。
