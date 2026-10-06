# Outfit Visual Evaluation Implementation Plan

> **For agentic workers:** Use subagent-driven-development for the independent data/protocol tasks, then review their integration. Keep other worktree changes intact.

**Goal:** Freeze the confirmed desktop clothing inputs and prepare a reproducible attributes versus attributes-plus-photos outfit comparison.

**Architecture:** Standalone `backend/eval/outfits_v2` reuses production outfit rules without loading app settings or changing production behavior. A confirmed inventory and frozen candidate bundle feed identical model requests with optional images. Default runs use local caches only and report missing coverage honestly.

**Tech Stack:** Python 3, existing Pillow/httpx/pytest, JSON and Markdown artifacts.

## 1. Record confirmed inputs

- [x] Create `backend/eval/outfits_v2/dataset/desktop-2026-10-05/confirmation.json` and `garments.json` from the existing 47-image AI package.
- [x] Bind user confirmation text/date and source file hash; include all 75 stable mappings and preserve nulls. Do not modify source annotations or fabricate independent review.
- [x] Inspect the initial 18 single-object crops; remove c005/c012 for model/inner-layer and UI residue, freezing the 16 verified inputs specified in the design.
- [x] Keep source images and all generated crop files ignored in Git.

## 2. Matched requests and guarded replay

Files: `backend/eval/outfits_v2/{__init__,protocol,runner}.py`, `backend/tests/v2/test_outfit_eval_protocol.py`, `backend/tests/v2/test_outfit_eval_runner.py`.

- [x] Start with tests for identical text blocks, picture-only arm difference, exact display-pool membership, duplicate/unknown IDs, no-candidate stop and null-to-unknown handling.
- [x] Run failing tests before implementing the corresponding behavior.
- [x] Implement `safe_payload(case)`, `validate_selection(case,result)` and `run_one(case,spec,image_root,cache_dir,arm,run_index=0,offline=True,budget=None,http_client=None)`.
- [x] Reuse public ModelSpec/CallBudget types from recognition evaluation; do not reuse recognition response caches.
- [x] Require safe relative JPEG/PNG paths and expected hashes for referenced visual assets; fail before networking on image mutation.
- [x] Default offline; enforce explicit live call budget, no automatic retry, success/error cache identity, safe errors and usage fields.
- [x] Use httpx MockTransport to verify actual request bodies and error replay without a network call.

Example protocol expectation:

```python
assert validate_selection(case, {'garment_ids': case['combinations'][0], 'reason': '配色协调'})['valid']
assert not validate_selection(case, {'garment_ids': ['999999'], 'reason': '示例'})['valid']
```

## 3. Freeze cases and expose a local CLI

Files: `backend/eval/outfits_v2/{prepare,report,__main__}.py`, `backend/tests/v2/test_outfit_eval_prepare.py`, `backend/tests/v2/test_outfit_eval_report.py`.

- [x] Test that input unknown fields remain unknown, 4 preferences × 3 contexts produce 12 cases, both arms share candidate IDs/order and display pools remain ≤20.
- [x] Create rule-input copies with ready/fit explicitly documented as synthetic assumptions. Freeze candidate IDs, attributes, baseline and crop hashes.
- [x] Evaluate separate no-shoes, washing, fit-unknown, fixed/excluded and occupied boundary cases locally; deduplicate 12 scenarios into 8 unique model inputs.
- [x] CLI accepts frozen cases, model configuration, image directory, cache, output, and optional `--live --max-calls`; offline needs no secrets. Protect existing/nonempty output and input directories from accidental overwrite.
- [x] Report rules baseline and arm coverage/statuses. Offline missing responses never rank arms or manufacture a win rate.
- [x] Provide a local baseline contact sheet and a manual pairwise-review template; do not claim templates contain real model comparisons.

## 4. Verify and deliver

- [x] Independently review code/spec compliance and data provenance.
- [x] Run focused new tests plus existing recognition evaluation tests and relevant pure outfit rule tests.
- [x] Run real 12-case preparation and offline comparison, verify all source/crop hashes, all candidate legality and boundary stop results.
- [x] Document commands and actual results in `backend/eval/outfits_v2/README.md`; update the data README with confirmation and scope without overwriting historical AI drafts.
- [x] Open the baseline artifact and deliver links; identify model configuration and blind ratings as remaining inputs. No deployment, database mutation or live model call in offline preparation.

## Verified outcome — 2026-10-05

200 focused evaluation/rule checks passed with one pre-existing anyio deprecation warning. Independent final review closed both identified P1 issues and reran 63 outfit-tool checks. The final offline run produced 12 scenarios, 8 distinct request groups, 0 completed model pairs and 0 live calls. All 24 pairwise-rating records are explicitly unrated placeholders. The native preview open request was queued; the file is available locally. Live model configuration and actual blind ratings remain follow-up inputs, outside offline preparation. No production/config/database changes or live model calls were performed.
