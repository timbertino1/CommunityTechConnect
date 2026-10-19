# Checkpoint: US6 (Phase 8), owner review and data quality

**Date:** 2026-10-19 (America/Chicago; times below are UTC)
**Task:** T128
**Result:** The offline scenario passed. The live review PR end to end is **still open**: nothing
has been held for review since the review PR shipped. Every current UNL event is filtered out
by rules, and every other active source is trusted. The first held event will exercise it.

## Quickstart scenario 6 (offline)

Ran through the real commands (`netc review-pr`, `netc apply-review`, `netc validate-data`,
`netc build-site`) at `--now 2026-10-19T11:00:00Z`. There were two probationary sources:
"Campus computing" with 4 held events and "Venue calendar" with 3. The GitHub API responses
were saved JSON, as in `tests/security/test_apply_review.py`.

| Expected | Result |
|---|---|
| Review PR body in the contract's format | `Review: 7 items (events)`; 7 ids in `data/review/open.json` |
| "approve" ticked → approved | Campus talks 3, 4, 5 and Venue social 7 published |
| "reject" ticked → rejected | Venue socials 8 and 9 rejected, not on the site |
| Undecided stays pending | Campus talk 6 still pending: "1 left waiting for the next review PR" |
| 3 approvals and 0 rejections promote a source | Campus computing: probationary → trusted |
| A mostly rejected source is paused | Venue calendar: 1 approved, 2 rejected → paused |
| Only an admin's merge is applied | The same apply with `permission: write` exited 1: "does not have the admin role" |
| An override hides an event | `visibility: hidden` on Campus talk 3: validate-data OK, gone from the built site |
| The override survives a re-run | `test_an_override_survives_a_re_run`: `discover-events --force` twice; still hidden, categories and area kept |

The quickstart named `discover-sources --emit-review-pr-body`, which doesn't exist; the review PR
is built by `netc review-pr`. It's corrected.

## Live pieces

| Step | Result |
|---|---|
| Review PR job in Discover events (PR #23) | Runs each time; nothing pending, so no PR was opened |
| Apply review workflow | Runs on every push to main and stops after one lookup (no review PR merged yet) |
| Discovery health issue (PR #25) | #29 opened by the bot on the manual run at 22:50, pinned, "Nothing needs attention" |
| Due-window fix (PR #27) | The 17:17 run had read nothing; after the fix, the manual run read all 7 active sources and data PR #28 merged itself |
| Overrides (T125–T126) | `data/overrides.yaml` is empty. Applied at the end of `discover-events` and `apply-review`, and in `build-site` |
| Admin guide (T127) | `docs/admin-guide.md` |

## Still to do for T128

When the first review PR appears:

1. Tick at least one approve (and a reject, if one fits), then merge.
2. Confirm that **Apply review** finds the merge and opens `Apply review #N`, that the
   follow-up PR merges itself, and that approved events appear on the site.
3. Record the result here and mark T128 done.
