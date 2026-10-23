# Checkpoint: US2 (Phase 4), automatic discovery

**Date:** 2026-10-21 (America/Chicago evening; times below are UTC)
**Task:** T105
**Result:** Offline scenario passed (after one fix). The live run worked end to end but did **not**
meet the checkpoint: new sources came from two channel types, not three, and no candidate was
rejected. The main cause is a missing setting, not code: `OPENAI_API_KEY` was never added to the
`discovery` Environment (T073), so the AI has not run live. T105 stays open until a live run
with the key passes.

## Quickstart scenario 2 (offline)

The documented command, with the integration fixtures, at `--now 2026-10-20T12:00:00Z`.

| Expected | Result |
|---|---|
| ≥ 1 new probationary source from each of 3 channel types | Passed after a fix: 4 added, via web search (2), links on known pages (1) and news (1), all `probationary` and `discovered` |
| An out-of-state and a non-tech candidate rejected | `kccloud.example.org` ("its upcoming events are outside Nebraska"); `yoga.example.org` ("no tech events among 2 upcoming") |
| An unresolved mention is not published | "Cyber Night coming to The Mill" stays `unresolved` (1 attempt); the run writes no events |
| The data validates | `validate-data` passed |

### Finding: the documented command reached only two channels (fixed)

The CLI always read the real news feed list from `finders/config.yaml` (Silicon Prairie News),
which is not in the offline fixtures, so the news channel failed ("news feeds: errors 1"). The
integration test passed its fixture feed directly and never noticed. `discover-sources` now takes
`--news-feed URL` (repeatable) for offline runs; the quickstart command uses it, and the CLI test
pins all three channels (PR #45).

The newsletter channel can't run offline (it reads the KV inbox). Its parsing, link cleaning and
deletion rules are covered by `tests/unit/test_finder_newsletter.py` and
`tests/security/test_newsletter_links.py`; the inbox itself was tested live (below).

## Live run

`gh workflow run discover-sources.yml` on `main` at 00:34 (run 39700513844): success in 37 minutes;
data PR #46 merged by itself.

| | Result |
|---|---|
| Web search | 40 queries, 377 results; budget 54 used this month, 291 left (an earlier run had used some) |
| Links on known pages | 14 pages, 3 errors |
| Event platforms | nothing new to do |
| News feeds | 10 articles, **all skipped: no AI** |
| Newsletters | **skipped: no inbox** (`CLOUDFLARE_ACCOUNT_ID` not set yet, T100) |
| Gap checks | 14 targeted searches |
| Candidates | 80 new (web search 67, gap checks 12, links 1); 25 evaluated, the per-run cap |
| Evaluated | 3 added, 21 needs review, 1 blocked by terms (ISACA Omaha's robots.txt), **0 rejected** |
| Mentions | 15 new; 0 resolved, 27 still looking; none published |

| Checkpoint criterion | Live result |
|---|---|
| New probationary sources from ≥ 3 channel types | **Not met.** This run: web search (allevents.in) and gap checks (two event pages). Counting the earlier run's dev.events, still two channel types |
| Out-of-state and non-tech candidates rejected | **Not met.** No candidate has been rejected in any live run (52 evaluated: 43 needs review, 4 added, 3 blocked). When the rules can't decide, the AI's second opinion is what turns a candidate into a rejection; without it, it goes to a person |
| Unresolved mentions not published | Met. Discovery never writes events, and no mention resolved |

### What did work live

- **The trust rules.** dev.events (added on probation the day before) produced 10 events, 9 of
  them online events from elsewhere. After review #43 (1 approved, 9 rejected) the source was
  paused automatically (`rejected > approved` with ≥ 3 reviewed, T092).
- **The newsletter inbox.** `netc-inbox` is deployed and `events@netechconnect.com` routes to
  it; a test message from an unlisted sender was dropped (`unknown_sender`) using 0 ms of CPU.
  Silicon Prairie News is subscribed, but its sender isn't on the allow-list yet (see T100).

## Findings and follow-ups

1. **`OPENAI_API_KEY` is missing** from the `discovery` Environment (and the repository), though
   T073 is checked. Without it the AI never runs: news articles are skipped, undecided events and
   candidates go to review, and nothing is rejected. *Owner: add the key, then re-run this
   checkpoint.*
2. **Aggregators and single event pages pass evaluation too easily.** allevents.in ("Meetups in
   Lincoln") and dev.events list everything; infosec-conferences.com and events.govtech.com pages
   describe one event and will go quiet once it has passed. One Nebraska tech event in the sample
   is enough to be added. Probation and the trust rules contain the damage, but a follow-up
   should make evaluation stricter for these (e.g., require a share of the sample to be Nebraska
   tech, and treat a page with one event as a mention, not a source).
3. **Candidate backlog:** 199 pending against 25 evaluations a run, so about 8 weekly runs to
   clear, and it grows by ~80 a run. Many are noise (map links, product pages, job listings). A
   follow-up should filter obvious non-sources before they become candidates.
4. **Newsletter allow-list:** Silicon Prairie News uses single opt-in, so no confirmation email
   came; its envelope sender is still unknown. Find it from an SPN email's `Return-Path`, add it
   to `ALLOWED_SENDERS`, and redeploy (T100).
5. **Workflow note:** the run summary is only on the Actions page; the data PR body carries the
   same report, which is where to read it.

## Later attempts (Oct 22–23)

`OPENAI_API_KEY` and `CLOUDFLARE_ACCOUNT_ID` were added and SPN's sender allowed (T100 progress);
the AI's answers were made usable (#50). Each re-run then exposed the next bottleneck:

| Run (UTC) | Outcome | What it showed | Fix |
|---|---|---|---|
| Oct 22 22:55 (39868403415) | Cancelled at the 60-minute job timeout; nothing saved | Run times had grown 12 → 37 → 39 → 60+ min, with no progress logged | #59: 40-minute evaluation budget, per-stage and per-candidate timing log, samples of 8 events |
| Oct 23 00:11 (39876646399) | Finished in 58 min, but 0 candidates evaluated | Finders 5.4 min, **mention resolution 52.4 min**, evaluation 0 s (budget already spent) | #66: mentions get 10 minutes, at most 10 a run, 3 pages each |
| Oct 23 01:34 (39884807906) | Finished in 22 min; 25 evaluated: 1 added, 1 rejected, 2 blocked by terms, 21 need a look | Every stage got its turn (finders 5.1, mentions 12.0, evaluation 4.1 min), but candidates were evaluated in address order, so the 25 were mostly noise (gitlab.com, a Princeton help page, Lincoln Financial jobs). The one added, `cms.erepublic.com/.../add_event_to_calendar/144627`, is a one-event calendar link | This PR: see below |

**Did not pass:** one new source from one channel, one rejection (UNMC events, "no tech events
among 8 upcoming"); unresolved mentions stayed unpublished.

**Fix (this PR):** candidates that are obviously not sources (job boards, sign-in, account and
help pages, reference and vendor-documentation sites, other Lincolns, sites outside the US,
one-event calendar links, a platform's own home page) are rejected from their address alone,
with no fetch and without using the run's evaluations. The rest go most promising first:
Meetup, Luma and Eventbrite group pages naming a Nebraska place, then other pages naming one,
then other group pages, then everything else. The per-run limit rises from 25 to 75 (about
10 s each). On the Oct 23 backlog: 30 of 222 pending candidates are settled without a fetch,
and the first 18 to be evaluated are real Nebraska groups' pages (Lincoln AI, Lincoln Code,
Omaha SQL User Group, Nebraska UX, NEB-RUG and others). The erepublic source is paused.

## To pass

Run `discover-sources` once more and check the three criteria. Record that run here.
