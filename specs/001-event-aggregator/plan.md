# Implementation Plan: Nebraska Tech Event Aggregator

**Branch**: `001-event-aggregator` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-event-aggregator/spec.md`

## Summary

NETechConnect automatically finds community tech events across Nebraska (Omaha and Lincoln
first), including from groups it has never seen, and shows upcoming and past events in list and
calendar views that always link to the organizer's original event page.

Technical approach: a **near-$0/month static architecture**. Python discovery jobs run on a
schedule in GitHub Actions (public repo). They collect events from known sources through generic
iCal, JSON-LD and RSS connectors. They also find new groups weekly through web search,
link-following, a newsletter inbox, local news RSS, platform calendars and gap detection.
Events are classified with rules first and an OpenAI nano-tier model only for unclear cases.
The jobs store everything as versioned data files and build a static site deployed to
Cloudflare Pages. Two tiny Cloudflare Workers accept source suggestions and newsletter
email. Administration happens in GitHub: a daily data PR auto-merges, and a review PR (updated at most daily when items are held)
is a checklist the owner ticks. GitHub 2FA provides MFA, and git history is the audit log.
See [research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.13 (discovery, site generator); TypeScript 5.x (Cloudflare
Workers); framework-free ES2022 JavaScript and CSS (front end), plus three.js for one
decorative home-page header only (R15)

**Primary Dependencies**: httpx, icalendar, recurring-ical-events, feedparser, selectolax, nh3,
pydantic v2, jinja2, protego, rapidfuzz, openai (Python); wrangler, postal-mime (Workers); three
(front end, self-hosted and pinned, home header only)

**Storage**: Versioned JSON/YAML files in the repo under `data/` ([data-model.md](./data-model.md));
Cloudflare Workers KV only as a short-lived inbox (TTL 30 days) for suggestions and newsletters

**Testing**: pytest + respx (recorded fixtures, no live network in CI), mypy --strict, ruff;
vitest (Workers); Playwright + axe-core (accessibility); JSON Schema validation of `data/`

**Target Platform**: GitHub Actions `ubuntu-latest` runners (scheduled jobs); Cloudflare Pages
(static hosting); Cloudflare Workers free plan; modern desktop and mobile browsers

**Project Type**: Static web application + scheduled data pipeline + two edge functions

**Performance Goals**: Pages show main content in ≤ 2 s for 95% of visits on 4G (SC-006); daily
discovery run ≤ 30 min; new/changed events visible within 24 h (SC-003)

**Constraints**: ≤ ~$5/month total running cost, target ≈ $1 (AI) + optional domain; free tiers
of GitHub Actions, Cloudflare Pages (500 builds/mo), Workers (100k req/day, 10 ms CPU); strict CSP
with no third-party scripts except Turnstile on `/suggest/`; WCAG 2.2 AA; honor robots.txt and
terms; HTTPS only; no personal data; admin effort ≤ 15 min/week (SC-010)

**Scale/Scope**: ~50–200 sources, ~100–400 events/month, archive grows ~3–5k events/year; ~40
search queries/week; ~20–40 newsletters/month; low thousands of visitors/month; single admin

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Pre-research | Post-design |
|---|---|---|---|
| **I. Security by Default** | Untrusted input sanitized and output encoded; SSRF protection; least privilege; no secrets in repo; HTTPS + CSP/security headers; minimal personal data; dependency scanning blocks critical/high | ✅ Planned | ✅ `safe_fetch` (R12); nh3 + Jinja autoescape, plain-text storage; Workers hold no GitHub creds and never fetch public URLs; secrets in protected Environment; strict `_headers`; no accounts; pip-audit/npm audit/gitleaks/Dependabot in CI; public-repo hardening (R13) |
| **II. Aggregator, Not Organizer** | Every event links to original page as primary CTA; no invites/.ics/reminders/RSVP/ticketing; short summaries only | ✅ Planned | ✅ `original_url` required and HTTPS (schema); mention-only events unpublished until resolved (FR-014); summary ≤ 500 chars; site contract forbids calendar export. Reading iCal **feeds** is allowed (input only) |
| **III. Nebraska Community Scope** | Statewide, Omaha/Lincoln prioritized, commercial/non-tech excluded, past events retained | ✅ Planned | ✅ Area enum + gazetteer; seed list and queries weighted to Omaha/Lincoln (R14, R6); exclusion rules (R10); `/past/` archive with yearly data files |
| **IV. Accurate, Attributed Event Data** | Source recorded and linked; UTC + source TZ, Central display; de-dup; last-verified; cancelled/unverified flagged; inferred data distinguishable | ✅ Planned | ✅ `listings[]`, `source_tz`, `last_verified`, `status`, `inferred[]` in schema; de-dup rules (R11) |
| **V. Responsible & Resilient Discovery** | APIs/feeds before scraping; robots.txt/terms; honest UA; rate limits; isolated adapters; observability; source content never treated as instructions | ✅ Planned | ✅ Connector priority ical→jsonld→rss, `html_rules` last resort (R5); `protego` + per-host delays; terms gates V1–V7; per-source error isolation and `source_status.json`; health issue; AI has no tools and schema-only output (R10) |
| **VI. Test-First Quality** | Tests before code; fixture tests incl. malicious payloads; security-control tests; discovery→storage→views integration tests; CI gates | ✅ Planned | ✅ Test layout below; security suite in quickstart; CI required for merge |
| **VII. Accessible, Simple Presentation** | List + calendar; filters (date, area, past/upcoming); WCAG 2.2 AA; mobile; links out; YAGNI | ✅ Planned | ✅ Static semantic calendar tables instead of a JS widget (R3); axe-core checks; no server, DB, or framework; one justified dependency, three.js for a decorative home header within fixed limits (R15, Complexity Tracking) |
| **Security Requirements** | Threat analysis for new sources/inputs; admin MFA + audit log; public input rate limited and moderated; backups tested | ✅ Planned | ✅ Threat summary below; GitHub 2FA + PR history; Turnstile + rate limits + review; git is the backup (restore = checkout; tested in quickstart) |
| **Workflow & Quality Gates** | PR-only to `main`; human review except bot data-only PRs (v1.1.0); security review for auth/input/fetch/secrets; CI gates | ✅ Planned | ✅ Branch ruleset requires PRs + CI; the owner reviews and merges every code PR; bot PRs auto-merge only when CI confirms they change nothing outside `data/` |

**Result**: PASS. One added dependency (three.js, owner decision 2026-10-20) is justified under
Complexity Tracking, as Principle VII requires.

### Threat summary (Security Requirements: threat analysis)

| Asset / entry point | Threat | Mitigation |
|---|---|---|
| Fetched source content (pages, feeds, emails) | XSS/HTML injection into site; malformed data crashes | Plain-text extraction (nh3), Jinja autoescape, schema validation, strict CSP, per-source isolation |
| Outbound fetches from runners | SSRF to cloud metadata/internal hosts | `safe_fetch` IP vetting on every hop, HTTPS/443 only, size/time limits |
| AI calls | Prompt injection changing decisions; cost blow-up | Delimited data, no tools, schema output, AI cannot publish probationary items or change trust; caching + hard monthly budget |
| Suggestion endpoint | Spam, abuse, SSRF via submitted URL, stored PII | Turnstile, Origin check, IP-hash rate limit, syntactic URL validation, Worker never fetches, note scrubbed and limited, public-data notice |
| Newsletter inbox | Junk/hostile mail, oversized mail; public links that can manage the subscription | Sender allow-list, 1 MiB cap, raw-only storage, parsing in Python with same untrusted-data rules; query strings and unsubscribe/tracking links stripped before storage |
| Suggestion notes | Personal data published in the public repo | Notes stay in private KV (30-day TTL) and are used only in memory; never written to `data/`, PRs, or issues |
| GitHub repo & Actions (public) | Malicious fork PRs, compromised actions, secret leaks | No `pull_request_target`, approval for outside contributors, SHA-pinned actions, read-only default token, protected Environment, secret scanning + push protection |
| Admin actions | Account takeover; unauthorized approvals | Required 2FA, admin-only merge on review branches, `apply-review` verifies author/merger, full history |
| Deployed site | Defacement via bad data | Data PRs gated by schema + CI; deploy only from `main` |

**Ongoing review (added 2026-10-25, with SC-008's change):** the threats above are rechecked
every quarter with the checklist in `docs/reviews/quarterly-security.md` (automated checks,
changes since the last review, pins, the live site and Workers, GitHub settings, and the owner's
Cloudflare and GitHub token dashboards). `netc health-issue` raises a `security-review` attention
item in the first week of January, April, July and October (Central Time) and comments once.

## Project Structure

### Documentation (this feature)

```text
specs/001-event-aggregator/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── event.schema.json
│   ├── source.schema.json
│   ├── site-urls.md
│   ├── workers.md
│   ├── connectors-and-finders.md
│   └── workflows-and-review.md
├── checklists/requirements.md
└── tasks.md             # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
discovery/                          # Python package "netc" (uv project)
├── pyproject.toml / uv.lock
├── src/netc/
│   ├── cli.py                      # netc discover-events | discover-sources | apply-review | build-site
│   ├── models.py                   # pydantic models mirroring contracts/*.schema.json
│   ├── storage.py                  # deterministic read/write of data/
│   ├── fetch/                      # safe_fetch, robots, rate limiting (CODEOWNERS-protected)
│   ├── connectors/                 # ical.py, rss.py, jsonld.py, eventbrite_org.py, html_rules.py, detect.py
│   ├── finders/                    # web_search.py, link_graph.py, newsletter.py, news.py, platform.py, gaps.py, config.yaml
│   ├── search/                     # SearchProvider implementations (tavily.py, ...)
│   ├── pipeline/                   # normalize.py, sanitize.py, classify.py, ai.py, dedupe.py, trust.py, evaluate.py, review.py, overrides.py
│   ├── inbox/                      # KV client for suggestions and newsletters
│   ├── github/                     # App-token PR creation, health issue
│   └── site/                       # build.py, templates/ (Jinja), calendar.py
└── tests/
    ├── unit/
    ├── contract/                   # connectors vs. recorded fixtures; schemas
    ├── integration/                # discovery → data/ → built site
    ├── security/                   # SSRF, sanitization, prompt-injection, header checks
    └── fixtures/                   # recorded feeds, pages, emails, search results (incl. malicious)

web/                                # static assets copied into the build
├── js/                             # filters.js, search.js, suggest.js (ES modules, no deps);
│                                   #   header-map.js (the one module that imports three.js, R15)
├── vendor/                         # three.js, copied from the pinned npm package at build time
├── fonts/                          # Archivo, Inter, JetBrains Mono (self-hosted woff2, OFL)
├── css/
├── _headers                        # Cloudflare Pages security headers
├── package.json                    # Playwright + axe-core dev deps only
└── tests/a11y/

workers/                            # Cloudflare Workers (TypeScript)
├── suggest/                        # POST /suggest
├── inbox/                          # Email Worker
├── wrangler.toml
└── test/

data/                               # versioned data (see data-model.md), incl. overrides.yaml
docs/
├── admin-guide.md                  # how to review, hide/correct events, manage sources
├── operations.md                   # runbook, secrets inventory, restore steps
├── operations/                     # cost.md, metrics.md
├── checkpoints/                    # per-story validation records
├── reviews/                        # accessibility, performance, security reviews
└── coverage/                       # quarterly coverage checks (SC-002)
.github/
├── workflows/                      # ci, discover-events, discover-sources, apply-review, deploy, deploy-workers
├── CODEOWNERS
└── dependabot.yml
SECURITY.md
LICENSE
```

**Structure Decision**: Three small, independent parts: `discovery/` (Python pipeline and site
generator), `web/` (static front-end assets), and `workers/` (two edge functions). They share
only the `data/` files and the contracts. This is the minimum needed: Workers must be
TypeScript, and front-end assets are kept separate so they can be tested and linted on their own.

## Complexity Tracking

| Added complexity | Why it's needed | Simpler alternative and why it isn't enough | Limits that keep it in bounds |
|---|---|---|---|
| three.js (front end), for one decorative 3D map in the home-page header (R15) | Owner decision (2026-10-20): the site should look modern and professional, and the home page should be memorable | Direction A, the same design with no 3D. Kept as the fallback; the owner preferred B | Home header only; loads after the event list; ≤ 150 KB compressed (CI check); still under reduced motion; static image on Save-Data or low-power devices and without WebGL; paused off screen; `aria-hidden`; self-hosted and pinned; never needed to find an event |

## Open items carried into tasks

These are validation gates from [research.md](./research.md#validation-gates-must-pass-before-the-dependent-tasks)
that need human-readable terms or live accounts to confirm. Each becomes an early task that
blocks only its dependent work:

- **V1 Meetup terms and feed access**: highest coverage risk. If blocked, Meetup groups are
  discovered and listed as known groups, but their events are not collected.
- **V2 Eventbrite API terms.**
- **V3 Luma public feed terms.**
- **V4 Search API free credit/terms.**
- **V5 Cloudflare KV and Email Worker free limits.**
- **V6 OpenAI nano model and price.**
- **V7 Seed source verification.**
