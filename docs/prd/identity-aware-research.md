# PRD: Identity-Aware Research

## Summary
Pylon の research は、プロダクト名の文字列一致ではなく、調査対象エンティティを固定したうえで evidence を収集・審査する。  
そのために project に `productIdentity` を追加し、UI で `会社名 / 自社プロダクト名 / 公式サイト / 別名 / 除外対象` を登録できるようにする。research はこの登録情報を query anchor、source quarantine、readiness 判定に使う。

## Problem
- 同名他社プロダクトが research に混入し、競合・ソース・主張台帳が汚染される。
- 現状の quality gate は structural で、`正しい対象についての根拠か` を見ていない。
- operator は research 後に誤混入へ気づくため、再実行コストが高い。

## Goals
- research 前に対象エンティティを固定する。
- same-name collision を UI と audit の両方で抑止する。
- trusted evidence のみで planning へ進める。
- operator が `誰の何を調べているか` を常に確認できる。

## Non-Goals
- 今回は tenant 横断の company master を作らない。
- 外部法人データベース連携は行わない。
- 完全自動の企業同定モデルは今回の範囲外とする。

## Users
- Product operator: 企画前提を入力し、research の精度を担保したい。
- Delivery lead: planning へ渡す論点が正しい対象に紐づくことを担保したい。
- Reviewer: source contamination を早い段階で見つけたい。

## User Journey
1. `/projects/new` で project を作成する。
2. 必要に応じて `運営会社と自社プロダクトを登録する` を開き、identity を入れる。
3. `/lifecycle/research` で identity lock を確認し、未入力なら会社名と自社プロダクト名を補う。
4. research 実行時に identity-aware anchor が backend に渡る。
5. review 画面では `調査対象のロック` と trusted / quarantined evidence を見ながら判断する。

## User Stories
- As a product operator, I want to register my company and product before research so that same-name products do not pollute the result.
- As a reviewer, I want quarantined same-name sources to be explicit so that I can trust what remains.
- As a planner, I want research readiness to fail when target identity is not fixed so that planning never starts from ambiguous evidence.

## Job Stories
- When a product name is shared by another company, I want Pylon to anchor research to my company and official domain so I can avoid false competitors.
- When research evidence comes from ambiguous sources, I want the system to quarantine them automatically so I can review only defensible inputs.

## JTBD
- Functional: identify the correct product entity and collect only relevant evidence.
- Emotional: reduce fear that research is confidently wrong.
- Social: allow operators to defend research provenance in front of stakeholders.

## KANO
- Must-be: company name, product name, official site registration before research.
- Must-be: same-company source is never shown as competitor.
- One-dimensional: more identity signals improve quarantine precision.
- Attractive: explicit excluded same-name entities and visible target lock in review UI.

## IA Impact
- `/projects/new`
  - Add a separate collapsible identity registration section.
- `/lifecycle/research`
  - Add mandatory identity lock block in pre-run state.
  - Add target lock summary in review state.
- Project persistence
  - `LifecycleProject.productIdentity`

## Requirements
### Functional
- Persist `productIdentity` on lifecycle project.
- Split identity input into:
  - required before research:
    - `companyName`
    - `productName`
  - optional with graceful fallback:
    - `officialWebsite`
    - `aliases`
    - `excludedEntityNames`
- Allow input of:
  - `companyName`
  - `productName`
  - `officialWebsite`
  - `aliases`
  - `excludedEntityNames`
- Require `companyName` and `productName` before research can start.
- If optional fields are blank, the system should still:
  - anchor search with company + product name
  - derive lightweight alias candidates
  - detect likely same-name collisions and quarantine them
- Pass `identity_profile` into research workflow input.
- Use identity in query anchor generation.
- Use identity in frontend research audit to quarantine same-name collisions.
- Mark research not ready if identity is not locked.

### UX
- Registration must be visibly separate from brief / GitHub settings.
- Required and optional identity fields must be visually separated, not only described in helper copy.
- Research start CTA must explain when identity lock is missing.
- Optional fields must explain that AI fills the gap when omitted.
- Review UI must show the currently locked target.
- Dynamic text areas and long entity names must wrap without breaking layout.

### Accessibility
- All new controls require visible labels.
- Error states need `aria-invalid` and readable helper text.
- Disabled CTA must have nearby explanatory copy.

## Success Metrics
- Accepted claims containing off-target same-name entities: `0`.
- Competitor entries on official target domains: `0`.
- Research runs started without company+product identity: `0`.
- Manual operator catches of same-name contamination: down by `80%+`.

## Acceptance Criteria
- Project identity is saved and restored across refresh.
- Research cannot start when `companyName` or `productName` is missing.
- `identity_profile` is present in research workflow input when registered.
- Review UI shows target lock summary.
- Same-name competitors or sources matching `excludedEntityNames` are quarantined.
- Changing `productIdentity` invalidates research and downstream lifecycle artifacts.

## Rollout
1. Add project-level identity persistence and UI.
2. Wire identity into research workflow input and query anchoring.
3. Enforce readiness / quarantine rules.
4. Expand backend quality gates in a follow-up to full entity-linked evaluation.
