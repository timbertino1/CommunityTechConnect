# Checkpoint: US7 (Phase 9), visitor suggestions

**Date:** 2026-10-24 (America/Chicago)
**Task:** T135
**Result:** **Passed.** Quickstart scenario 7 was run against the suggest Worker locally
(`wrangler dev`), every case as expected, and against the deployed Worker, where the owner
sent a real suggestion through the live form and it was received, stored, read by
discover-sources and cleared. Two setup problems and two gaps were found and fixed along the way
(below).

## Locally: `wrangler dev`

The suggest Worker ran with `wrangler dev --env suggest --local`, with Cloudflare's published
Turnstile **test** secret (`1x0000000000000000000000000000000AA`, which accepts any token), so
every rule after Turnstile could be exercised. The KV namespace was the local simulation;
nothing touched the real one. All requests came from one client, with the site's `Origin`.

| # | Request | Expected | Got | Logged reason |
|---|---|---|---|---|
| 1 | `https://technologynebraska.com/events/` | 202 | **202** | received |
| 2 | `http://example.org/` | 400 | **400** | `url` |
| 3 | `https://203.0.113.9/events` (IP literal) | 400 | **400** | `url` |
| 4 | `https://localhost/` | 400 | **400** | `url` |
| 5 | `https://wiki.corp.internal/` | 400 | **400** | `url` |
| 6 | a valid address, 6th request this hour | 429 | **429** | rate_limited |
| 7 | no Turnstile token | 400 | **400** | `no_token` |
| 8 | `Origin: https://evil.example` | 403 | **403** | `origin` |

Afterwards the local KV held one `suggestion:<uuid>` record and one `rate:<sha256>` counter (a
salted hash, not the IP). Requests 2-5 count toward the hourly limit because they passed
Turnstile first, which is the contract's order (Origin, Turnstile, rate limit, then the URL).

## Deployed: `https://netc-suggest.tim-bertino.workers.dev`

| Check | Result |
|---|---|
| Missing token / fake token | 400 / 400 |
| Wrong `Origin` | 403 |
| Preflight from `https://netechconnect.pages.dev` | 204, `Access-Control-Allow-Origin` set to it |
| `GET /suggest` | 405 |
| `/suggest/` page | 200; one CSP, allowing Turnstile and the Worker on that page only |
| **The owner's real suggestion** through the live form | "Thanks! We'll take a look…"; the Worker logged `received`; one `suggestion:` key in KV |
| discover-sources run 40058592923 (2026-10-24) | "Visitor suggestions: 1 read, 0 sent to review, 1 cleared from KV" |

The deployed checks can't pass Turnstile from a script, so the valid, rate-limit and URL rules
on the live Worker are covered by the owner's real submission and the local run above.

## Problems found and fixed

1. **Turnstile error 110200, "Unable to connect to website".** The widget's hostname list
   didn't include `netechconnect.pages.dev`. Fixed in the Turnstile dashboard (Hostname
   management); no code change.
2. **"That didn't go through" for a valid address.** The Worker refused at the Turnstile check:
   the `TURNSTILE_SECRET` value was wrong. Re-entered with `wrangler secret put`. Since the logs
   then said only "invalid", each refusal now logs which check failed and Turnstile's own error
   codes, never anything the visitor sent (#96).
3. **A suggestion for a site already in doubt was dropped.** The owner's suggestion had been
   found by web search on Oct 21 and left "needs review: no upcoming events to judge it by", so
   discover-sources counted the suggestion as a duplicate. Such suggestions now go to the
   review queue with the earlier verdict as the reason (#99).
4. **`wrangler dev` refused to start the Worker.** The Workers runtime treats every named export
   of a Worker's main module as an entry point, and both Workers exported constants. Production
   accepted them, but the constants now live in `suggest/limits.ts` and `inbox/limits.ts`, and a
   test checks each main module exports only its handler (this PR).

## Privacy

- The note is kept only in KV (30 days, and deleted once discover-sources has read it) and in
  memory during evaluation. `tests/integration/test_discover_sources.py` reads every file under
  `data/` and the review PR body after a run and finds no trace of it; the evaluator doesn't use
  it, so it never goes to the AI.
- The Worker keeps only a salted hash of the IP, for an hour, and logs no submitted content.
- Turnstile's script loads only on `/suggest/`; every other page keeps the strict CSP.

## Not covered

- Approving a "suggestion" review item records the decision but doesn't add a source; the
  owner adds it (or discover-sources re-evaluates it later). Worth automating if suggestions
  become common.
