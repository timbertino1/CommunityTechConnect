# Self security review

**Date:** 2026-10-24
**Task:** T139 (before the independent review, T140)
**Scope:** everything in this repository and what it runs: the discovery pipeline
(`discovery/`), the static site and its headers (`web/`, Cloudflare Pages), the two Workers
(`workers/`), the GitHub workflows and repository settings, at `main` after #105.
**Reviewer:** the builder (Claude, for the owner). This is a self-review: its job is to give the
independent reviewer a map, not to replace them.

**Result: no critical or high findings.** One medium and two low findings, listed at the end,
with what to do about each. All three were resolved on 2026-10-24.

## Automated checks

| Check | Result |
|---|---|
| `pytest -m security` (`discovery/tests/security/`: SSRF, fetch limits, sanitizing, AI injection, newsletter links, site output, apply-review, API client) | 340 passed |
| `pip-audit --strict` on the locked requirements (the CI command) | No known vulnerabilities |
| `npm audit` in `web/` and in `workers/` | 0 vulnerabilities in each |
| gitleaks | Runs on every PR and push to `main` in CI (full checkout, `fetch-depth: 0`), passing; GitHub secret scanning with push protection is also on. Not installed locally, so a full-history search for this project's secret formats (OpenAI, Tavily, GitHub, Cloudflare tokens, private keys, bearer headers) was run over all 242 commits: no secrets (two false matches inside a news article URL). |
| Workflows: actions pinned to a full commit SHA | All of them |
| Workflows: `pull_request_target` | Not used (only mentioned in a comment saying so) |
| Workflows: least permissions | Every workflow defaults to `contents: read`; only `deploy.yml` adds `deployments: write`. Writes to the repository go through the GitHub App's token, created per job with only `contents` and `pull-requests` write. The repository's default workflow token is read-only and can't approve PRs. |
| Secrets | None at repository level. `discovery` environment: bot App id and key, Cloudflare KV token, Eventbrite, OpenAI, search API key, and the newsletters KV id. `production`: Cloudflare account id and Pages token. Both environments accept deployments from `main` only. |
| `main` ruleset | Active, no bypass actors: no deletion, no force-push, PRs required, and required checks (Python, Web, Workers, gitleaks, "Bot PRs change only data/"; "Site (browser tests)" added after this review, see M1). Outside contributors need approval before their workflows run. |
| Live headers (`curl -I` on `/`, a month, `/past/`, `/suggest/`, `/data/upcoming.json`, a 404) | All carry the contract CSP, HSTS (2 years, subdomains), `nosniff`, `strict-origin-when-cross-origin` and the Permissions-Policy. `/suggest/` alone has the Turnstile CSP, and only one CSP. No `Set-Cookie` anywhere. |

## The threat summary, item by item

From `specs/001-event-aggregator/plan.md`, "Threat summary".

| Asset / entry point | Planned mitigation | What the implementation does (evidence) | Status |
|---|---|---|---|
| **Fetched source content** (pages, feeds, emails): XSS, crashes | Plain text, autoescape, schema validation, strict CSP, per-source isolation | Every text field goes through `pipeline/sanitize.py` (`to_plain_text`, nh3, cleaned until stable). Jinja runs with `autoescape=True` and `StrictUndefined`. Every write is validated against the pydantic models and JSON schemas, and CI validates `data/`. The site has no inline script or style (tested), and the CSP allows only `'self'`. `runner.py` runs each source with a timeout and catches its failure; discover-sources isolates each finder, candidate and mention. Tests: `test_sanitize.py`, `test_site_output.py` (a hostile JSON-LD page through the real pipeline). | ✅ |
| **Outbound fetches**: SSRF | IP vetting on every hop, HTTPS/443, size and time limits | `fetch/urls.py` `vet_url`: https on 443 only (http on 80 is upgraded), no user info, no IP literals or localhost. `safe_fetch.py` resolves and vets the address on every redirect hop and pins the connection to it (`VettedBackend`), with no redirects followed automatically, size caps per kind, timeouts, robots.txt, per-host rate limit and budget. Tests: `test_safe_fetch_ssrf.py`, `test_safe_fetch_limits.py`. | ✅ |
| **AI calls**: prompt injection, cost | Delimited data, no tools, schema output, no authority, caching, monthly budget | `pipeline/ai.py`: Structured Outputs with a strict JSON schema, no tools, untrusted text delimited. The AI only answers "relevant / category / area" for listings the rules can't decide. Publishing still follows trust (probationary sources' events always wait for review, `lifecycle.py`). Trust changes only through review counts (`trust.py`), never through the AI. Answers are cached by input hash, and the monthly budget stops calls when spent. Tests: `test_ai_injection.py`. | ✅ |
| **Suggestion endpoint**: spam, abuse, SSRF, PII | Turnstile, Origin check, IP-hash rate limit, URL validation, Worker never fetches, note scrubbed | `workers/suggest/index.ts`, in order: Origin, a 4 KB body cap, server-side Turnstile (its only outbound request), 5 an hour per salted IP hash (hash only, 1-hour TTL), then the https/public-host URL check. The note is cut to 280 characters with e-mail addresses and phones removed. Responses never echo input. Logs carry the outcome and failing check only. Tests: `workers/test/suggest.test.ts` (36). Checked live: T135, `docs/checkpoints/us7.md`. Python reads the suggested URL like any other untrusted candidate, through `safe_fetch`. | ✅ |
| **Newsletter inbox**: hostile or oversized mail, management links | Sender allow-list, 1 MiB cap, raw storage, Python parsing, links stripped | `workers/inbox/index.ts`: allow-list, 1 MiB cap, raw only (no parsing in the Worker), confirmations forwarded to the owner. `finders/newsletter.py` parses in Python under the same rules and strips query strings, fragments and unsubscribe/preference/tracking links before anything is stored. Tests: `inbox.test.ts`, `test_newsletter_links.py`. | ✅ |
| **Suggestion notes**: personal data in the public repo | Notes only in private KV and memory | `CandidateSource.note` is excluded from serialization. A test reads every file under `data/` and the review PR body after a run with a note and finds no trace of it. The evaluator doesn't use the note, so it never goes to the AI. KV holds it for at most 30 days, and discover-sources deletes it once read. | ✅ |
| **GitHub repo & Actions**: malicious forks, compromised actions, leaks | No `pull_request_target`, approval for outsiders, SHA pins, read-only token, protected Environment, secret scanning | All confirmed above (Automated checks). | ✅ |
| **Admin actions**: account takeover, unauthorized approvals | 2FA, admin-only merge of review PRs, apply-review checks, history | `apply-review.yml` runs on push to `main` only, and `apply_review` checks the PR's head branch, that the App opened it, that an admin merged it, and that the description wasn't edited after the merge; ids must be in the PR's snapshot and still pending. Tests: `test_apply_review.py`. Every change is a PR in git history. **2FA could not be confirmed from here** (finding L1). | ✅ (owner to confirm 2FA) |
| **Deployed site**: defacement via bad data | Data PRs gated by schema and CI; deploy only from `main` | Bot PRs auto-merge only when every required check passes, including "Bot PRs change only data/" and schema validation. `deploy.yml` deploys from `main` only, and the `production` environment accepts `main` only. **One gap: the browser tests aren't required** (finding M1). | ✅ with M1 |

## Findings

| # | Severity | Finding | Recommendation |
|---|---|---|---|
| M1 | Medium (**fixed 2026-10-24**) | **"Site (browser tests)" was not a required check** on `main`. The other five are. A PR, including an automatic data PR, could merge with failing browser, accessibility or Content-Security-Policy tests. The site build itself would still have to succeed to deploy. | **Done** with the owner's OK: "Protect main" now requires all six checks (Python, Web, Workers, gitleaks, "Bot PRs change only data/", "Site (browser tests)"), still with no bypass. |
| L1 | Low (**resolved 2026-10-24**) | **2FA on the owner's GitHub account couldn't be verified** with the CLI's token. The plan requires it. | **Done:** the owner confirmed two-factor authentication is on. |
| L2 | Low (**fixed 2026-10-24**) | **Workers were deployed from the owner's machine** with `wrangler`'s login, which can do much more than deploy these two Workers. | **Done:** T147/T148. `CLOUDFLARE_WORKERS_TOKEN` (Workers Scripts edit and Workers KV read, this account only) lives in the `production` environment and is used only by `deploy-workers.yml`. Its first run (40135156680) deployed both Workers, and the suggest Worker answered as before. The laptop's login is now needed only for setting Worker secrets. |
| I1 | Info | Cloudflare Pages sends `Access-Control-Allow-Origin: *` on every response. | No action: the site and its JSON are public and cookie-free, so other origins can read only what anyone can. |
| I2 | Info | `KV_SUGGESTIONS_ID` is an unused secret in the `discovery` environment; the workflow passes the public id directly. | Delete it to keep the inventory exact (T146). |
| I3 | Info | The `main` ruleset needs no approving review, and branches needn't be up to date before merging. | Fine for a single maintainer who merges every code PR. Revisit if more people get write access. |

## For the independent reviewer (T140)

Good places to start:
- `discovery/src/netc/fetch/` (SSRF and limits)
- `discovery/src/netc/pipeline/sanitize.py` and `site/build.py` (untrusted text into HTML)
- `workers/suggest/index.ts` (the only public write endpoint)
- `.github/workflows/` with `discovery/src/netc/pipeline/review.py` (who can change data, and how)
- `web/_headers` with the `/suggest/*` block that `build.py` appends

The contracts in `specs/001-event-aggregator/contracts/` say what each part is supposed to do.
