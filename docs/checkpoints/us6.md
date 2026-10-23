# Checkpoint: US6 (Phase 8), owner review and data quality

**Date:** 2026-10-19, live part 2026-10-22 (America/Chicago; times below are UTC)
**Task:** T128
**Result:** **Passed.** The offline scenario passed on Oct 19, and on Oct 22 the first real review
PR went end to end: 14 held events, 1 approved and 13 rejected, applied by a follow-up PR that
merged itself, with the approved event live on the site and a mostly rejected source paused.

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

## The first real review PR (Oct 22)

The first held events came from two probationary sources found by `discover-sources`. The
review PR job opened the review PR; the owner ticked boxes and merged it; **Apply review** did
the rest.

| Step | Result |
|---|---|
| Review PR opened by the bot | #52, `Review: 14 items (events)`, branch `review/open`, opened 22:56 by `netechconnect-bot` |
| Owner ticks and merges | 1 approve, 13 reject; merged 23:12:09 by the owner (admin) as `733d6f4` |
| Apply review finds the merge | Run 39870217398 at 23:12:11: "Found review PR #52, merged by timbertino1", then `netc apply-review` (which checks the branch, the bot author, the merge commit, the merger's admin role, and that the description wasn't edited after the merge): "1 approved, 13 rejected, 0 left waiting for the next review PR." |
| Follow-up PR merges itself | #54, `Apply review #52`, opened 23:12:29, every check green, auto-merged 23:13:15 as `d46e337`. It changes only `data/`: the events, the review queue and the two sources |
| Approved event on the site | **INTERFACE Omaha 2026** (Nov 5) published; the deploy of `d46e337` succeeded at 23:13, and the live home page lists it |
| Rejected events kept off | All 13 (trivia nights, mahjong, a generic "Networking" and the like) are rejected and not on the site |
| Source counts and trust | "Meetups in Lincoln" (allevents.in): 0 approved, 13 rejected, so **paused** automatically. INTERFACE (infosec-conferences.com): 1 approved, so it stays probationary (3 are needed to be trusted) |

## Found along the way

- **Aggregators make poor sources.** The paused source is allevents.in, a general event
  aggregator: 13 of its 14 held events weren't tech events. The review rule handled it as
  designed (paused, nothing published), but candidate evaluation should be stricter about
  aggregator listing pages, as already noted after the first T105 attempt.
- **Source names from page titles.** The approved event's source is named "INTERFACE Omaha
  2026, Omaha, United States | Cyber Event", the page title of a single conference listing, and
  the site shows that as the organizer. Rename it in
  `data/sources/src_infosec-conferences-com.yaml` (or give the event an organizer record), and
  discovery should name new sources better.
