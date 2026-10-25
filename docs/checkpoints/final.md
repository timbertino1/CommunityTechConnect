# Checkpoint: final end-to-end run

**Date:** 2026-10-25 (America/Chicago)
**Task:** T149 (every quickstart.md scenario, plus the security, accessibility and operational
checks)
**Code:** `main` at `8e58e67`. **Live site:** https://netechconnect.pages.dev
**Result:** **Passed.** Every scenario and check passed. Two places where the quickstart's wording
didn't match the site were fixed in the quickstart; nothing in the site needed to change.

## Test suites and audits

| Check | Result |
|---|---|
| Python tests (`uv run pytest`) | 1431 passed |
| Security tests (`pytest -m security`) | 340 passed |
| Integration tests (`tests/integration`) | 137 passed |
| Workers: `tsc`, `vitest` | types OK; 47 passed |
| `pip-audit` | no known vulnerabilities |
| `npm audit --audit-level=high` (`workers/`, `web/`) | 0 vulnerabilities in each |
| gitleaks | passed in CI on `8e58e67` |
| GitHub: Dependabot and secret-scanning alerts | 0 open |

## Scenarios

| # | Story | How | Result |
|---|---|---|---|
| 1 | US1 list | Integration tests (offline discover-events and build); live home page in Edge | **Pass.** 9 events, soonest first, every time labeled CT; no duplicates; event pages link to their HTTPS originals; a filter with no matches says "No events match these filters." |
| 2 | US2 discovery | The documented command, run by `test_the_command_runs_offline` on its prepared data | **Pass.** New probationary sources from web search, links on known pages and news; an out-of-state and a non-tech candidate rejected; an unresolved newsletter mention not published; a quiet group flagged |
| 3 | US3 calendar | Live: `/calendar/` to this month, previous month, a week page | **Pass.** Month and week pages load; previous and next links name their month and work; events sit on their CT day. Keyboard use was covered by T137 |
| 4 | US4 filters | Live: `/?area=lincoln&cat=security`, then the calendar, then reload | **Pass.** Only matching events ("Showing 1 of 9 events." with two topics); the filters stay in the address on the calendar; a reload restores both the area and the topic |
| 5 | US5 past | Site rebuilt with `--now 2027-01-01T12:00:00Z` and served locally | **Pass.** Ended events moved to `/past/` (1 upcoming, 10 past), most recent first; filters work there ("Showing 3 of 10 events.") |
| 6 | US6 review | `test_review_pr_command.py`, `tests/security/test_apply_review.py`; live since Oct 22 | **Pass.** Offline: the checklist, approve, reject, undecided, promotion at 3 approvals, pausing, and overrides surviving a re-run. Live: the first real review (Oct 22) approved one event and paused a source after 13 rejections |
| 7 | US7 suggest | Worker tests (36); requests to the live Worker | **Pass.** Tests: 202 for a valid address; 400 for `http://`, IP literals, `localhost`, `.internal` and more; 429 on the 6th in an hour; 400 without Turnstile. Live: no Turnstile token, an `http://` address, an IP literal and a 6 KB body each got 400; a foreign Origin got 403 |

## Security

Live response headers on `/`, an event page and `/suggest/` match
[contracts/site-urls.md](../../specs/001-event-aggregator/contracts/site-urls.md) exactly: the
strict Content-Security-Policy (with Turnstile allowed only on `/suggest/`), HSTS for two years,
`nosniff`, the referrer policy and the permissions policy. The pre-launch review for SC-008 is
[docs/reviews/security-review.md](../reviews/security-review.md) (T139; the independent review,
T140, was withdrawn by the owner on Oct 25).

## Accessibility and performance

- Automated: axe-core on 7 pages × 3 widths × 2 themes runs on every pull request (T136).
- By hand: [docs/reviews/accessibility-2026.md](../reviews/accessibility-2026.md) (T137): screen
  reader, keyboard only and 200% zoom, no findings.
- Speed: [docs/reviews/performance.md](../reviews/performance.md) (T138): main content in
  1.83 s on a simulated slow phone, against a 2 s target.

## Operations

| Check | Result |
|---|---|
| Data freshness (SC-003: under 26 h) | `generated_at` 2026-10-25T14:10Z, checked at 14:18Z. The last events run (00:36Z) found no changes |
| Events runs | The last 4 succeeded. Today's 11:00Z run was still queued at 14:18Z: GitHub delays scheduled runs (yesterday's 11:00Z run started at 14:11Z), and the health issue warns if runs stop |
| Bot data PRs | Merge themselves (latest #126, Oct 25) |
| Health issue | #29, updated by the run at 13:44Z |
| Spend | The cost check is T142, after two weeks of live runs (about Nov 7). This month's search budget is used up (400 of 400) and resets Nov 1 |

## Fixed in the quickstart

- **Scenario 1:** "No events found" is the page's text when there are no events at all; a
  filter that matches nothing says "No events match these filters." The expected result now
  names both.
- **Scenario 2:** the command needs the small data folder the integration test prepares, not a
  copy of `data/` (whose known sources and candidates leave nothing new to add). The quickstart
  now says so, as it already did for scenario 1.
