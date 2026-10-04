# Phase A UI Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the native mini-program's Phase A pages and permission/error states into line with the reviewed visual companion, then complete code and UI review.

**Architecture:** Keep the existing `/v2` backend and native mini-program. Extend only page state and presentation: server-confirmed family/child context controls which actions appear; mutations remain versioned and scoped to stable IDs. Shared CSS in `app.wxss` establishes type, color, and surface tokens, while page CSS owns layout.

**Tech Stack:** Native WeChat WXML/WXSS/JS, existing `miniprogram-v2/services`, Node `node:test`; existing FastAPI `/v2` contract is unchanged.

**Reference:** `docs/design/phase-a-simplified-review/README.md` and the approved HTML screens under `.superpowers/brainstorm/77011-1790911188/content/`. The UI screens are design references, not runtime dependencies.

---

## Task 1: Homepage and Entry State

**Files:** `miniprogram-v2/services/entry.js`, `pages/home/home.{js,wxml,wxss}`, `tests/entry.test.js`, `tests/onboarding.test.js`, `tests/flows.test.js`.

- [x] Add failing tests: a family without children opens `home`; viewer empty state never offers add; weather is not requested without a selected child; tapping the homepage child selector opens a bottom sheet and selecting another child persists its stable ID.
- [x] Confirm `node --test tests/entry.test.js tests/onboarding.test.js tests/flows.test.js` fails for those behaviors.
- [x] Return `home` for a selected accessible family regardless of child count. Load current membership before enabling empty-state actions. Replace horizontal child chips with the approved compact current-child header and bottom sheet; show access-revoked and network retry states without exposing stale private content.
- [x] Run the focused tests and all existing Node tests. Expected: pass, including prior account/family isolation cases.

## Task 2: Child Profile, Archive, and First-Use Recovery

**Files:** `pages/onboarding/onboarding.{js,wxml,wxss}`, `pages/children/children.{js,wxml,wxss}`, `pages/child-edit/child-edit.{js,wxml,wxss}`, `pages/preferences/preferences.{wxml,wxss}`, `tests/flows.test.js`, `tests/onboarding.test.js`, `tests/pages.test.js`.

- [x] Add failing tests: login failure keeps first-child draft and displays retry within the login sheet; save conflict keeps child form and blocks another save until explicit reload confirmation; archive requires confirmation and picks a remaining active child or the role-appropriate empty state; viewer gets no create/archive action. Add markup assertions for monogram identity and absence of photo upload UI.
- [x] Run focused tests and confirm each fails for the missing behavior.
- [x] Reuse compact monogram identity on switch, edit, and preferences screens. Keep the existing forms and `/v2` payloads; use in-page status sheets for failed login, conflict, and archive confirmation. Do not add photo upload, inferred preferences, or a restore promise.
- [x] Run focused and all Node tests. Expected: pass without changing backend contracts.

## Task 3: Family List, Detail, and Access Confirmations

**Files:** `pages/families/families.{js,wxml,wxss}`, `pages/family-detail/family-detail.{js,wxml,wxss}`, `pages/my/my.{js,wxml,wxss}`, `tests/flows.test.js`, `tests/pages.test.js`.

- [x] Add failing tests: one family opens detail directly; multiple families present switch list; creation uses a separate form state and preserves other family data; viewer cannot manage members; downgrade/remove/leave actions require in-page confirmation; last admin is stopped before leave/downgrade; logout clears only local login state.
- [x] Run tests and confirm expected red failures.
- [x] Implement the approved B member cards and scoped action sheets. Keep existing invitation generation and sharing, moving it behind a clear admin entry. Preserve draft on failed save and guard concurrent mutations with `busy` and `family.version`.
- [x] Run focused and all Node tests. Expected: pass, with no writes available through viewer controls.

## Task 4: Location and Invitation Recovery

**Files:** `pages/location/location.{js,wxml,wxss}`, `pages/invitation/invitation.{js,wxml,wxss}`, `tests/flows.test.js`, `tests/pages.test.js`.

- [x] Add failing tests: city result selection does not navigate until explicit confirmation; a failed location request permits search and manual city; invitation 410 has no accept action and does not clear the account or other families; already-joined acceptance routes to the accessible family.
- [x] Run focused tests to see the missing-state failures.
- [x] Implement the approved city search/selection layout and unavailable invitation state. Preserve existing API path, token handling, and real-weather fallback policy.
- [x] Run focused and all Node tests. Expected: pass.

## Task 5: UI and Code Review

**Files:** Page WXSS/WXML above, `miniprogram-v2/app.wxss`, `docs/runbooks/zhida-phase-a-acceptance.md` if verification notes change.

- [x] Add static page checks for visible action ownership, defined handlers, valid page registration, and no unsupported photo/AI actions. Run `npm test`; expected all green.
- [x] Review the changed files for data isolation, authorization, loading/error honesty, and stale-response behavior. Fix any identified defects and rerun relevant tests.
- [ ] Capture and inspect native mini-program screens in WeChat Developer Tools. WXML/WXSS static review is complete; native inspection awaits an unlocked Mac and initialized IDE CLI.
- [x] Run syntax checks on changed JS, `git diff --check`, and final Node suite. Record test counts and unresolved external verification clearly.

## Scope Guard

No backend migrations, image upload, AI try-on, clothing management, weather mocks, or conversion of the visual companion into the app. Do not modify legacy `miniprogram/`. Preserve all pre-existing untracked work in this worktree.
