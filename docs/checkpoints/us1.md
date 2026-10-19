# Checkpoint: US1 (Phase 3), the first live site

**Date:** 2026-10-18/19 (America/Chicago evening; times below are UTC)
**Task:** T072
**Site:** https://netechconnect.pages.dev (unannounced; no custom domain until T140)
**Result:** Passed. One finding (soft 404s) was fixed in the checkpoint PR.

## Quickstart scenario 1 (offline)

Ran `discover-events --offline` with `tests/fixtures/integration`, then `build-site`, at `--now 2026-10-18T12:00:00Z`. The data folder used three sources whose URLs match the fixture index.

| Expected | Result |
|---|---|
| Upcoming events, soonest first | 3 cards, in start order |
| Times labeled CT | Yes, on every card |
| Each card links to its HTTPS original page | 3 of 3 "View and register" links are https |
| An event listed on 2 sources appears once | "Industry in Residence: Nelnet" (UNL calendar and partner page) is stored and shown as one event |
| No events shows "No events found" | Covered by `test_empty_data_says_no_events_found` (filters arrive in US4) |

The quickstart's offline command named the wrong fixture folder (`tests/fixtures/sources` has no `index.json`). It's corrected.

## Pre-share security gate

| Check | Result |
|---|---|
| `uv run pytest -m security` | 247 passed |
| Full suite | 726 passed (725, plus the new 404 test) |
| `pip-audit --strict` | Passed in CI on main (run after PR #19). It can't run on the owner's PC because of TLS interception there. |
| `npm audit --audit-level=high` in `web/` | 0 vulnerabilities |
| `npm audit --audit-level=high` in `workers/` | 0 vulnerabilities |
| `curl -I` on `/`, an event page, and an unknown path | All five headers in contracts/site-urls.md are present and match exactly: CSP, HSTS (2 years, includeSubDomains), nosniff, Referrer-Policy and Permissions-Policy. Plain http gets a 301 to https. |

### Finding: unknown paths returned 200 (fixed)

Cloudflare Pages treats a site with no `404.html` as a single-page app, so it served the home page with a 200 for any path, such as `/does-not-exist` or `/feed.ics`. A mistyped or expired event link looked like a working page, and search engines could index junk URLs. `build-site` now writes a `404.html` page ("Page not found", with a link to upcoming events), and a test covers it.

To confirm after the checkpoint PR deploys, run `curl -I https://netechconnect.pages.dev/does-not-exist`. It should return `HTTP/1.1 404`.

## Live automation

| Step | Result |
|---|---|
| GitHub App `netechconnect-bot` (T065) | Installed on this repo only. Secrets are in the `discovery` environment (main only). |
| Cloudflare Pages `netechconnect` (T070) | Direct Upload project. The token can only edit Pages. Secrets are in the `production` environment (main only). |
| PR #18 merged, then Deploy site | Green, 22:39 |
| Scheduled discovery (23:00 slot; GitHub started it at 00:33) | Green. The bot opened PR #19 "Data update 2026-10-19", which changed only `data/` (2 event months and source status). |
| PR #19 | All checks passed, including "Bot PRs change only data/". It merged itself (squash) at 00:37. |
| Deploy after #19 | Green at 00:37 |
| Manual Discover events (00:52) | Green. Nothing had changed, so it opened no PR. |
| Live site lists real events | Drupal Nebraska (Oct 21) and the (NE)NUG Omaha Fall Event (Nov 12). UNL items wait in review (UNL is probationary). |
| Original links work | groups.drupal.org/node/537358 returns 200; usnua.com/live/nenug-omaha-fall-event-2026 returns 200 |

## Repository settings (owner)

- "Bot PRs change only data/" is a required check on main, so auto-merge waits for the path guard.
- Automatically delete head branches is on, so the bot's daily `bot/data-*` branches are removed after they merge.

## Still unannounced

Don't share the site publicly yet. The custom domain and announcement wait for T140 (see "Launch" in spec.md Assumptions).
