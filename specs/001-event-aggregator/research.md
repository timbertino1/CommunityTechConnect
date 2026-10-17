# Research: Nebraska Tech Event Aggregator

**Feature**: `001-event-aggregator` | **Date**: 2026-10-16 | **Plan**: [plan.md](./plan.md)

This document resolves the open technical questions in the plan's Technical Context. Findings
come from web research done on 2026-10-16. Third-party pricing and terms change often, and
several findings came from secondary sources; each item marked **VERIFY** is a gate that MUST be
re-checked against the provider's own current documentation/terms before the matching task is
implemented (see "Validation gates" at the end).

---

## R1. Hosting and runtime: static site + scheduled jobs

**Decision**: Generate the public site as static files from versioned data in the repo. Run all
discovery in scheduled GitHub Actions workflows on GitHub-hosted runners. Deploy the static
output to Cloudflare Pages. Use Cloudflare Workers only for the two inbound endpoints that need
to be "always on": the source-suggestion form and the newsletter inbox.

**Rationale**:

- Public repositories using standard GitHub-hosted runners have free Actions usage (the
  per-account minute quotas apply to private repositories) — [GitHub billing docs][gh-billing].
- Cloudflare Pages Free: 500 builds/month, 1 concurrent build, 20-minute build timeout, 20,000
  files per site, unlimited static requests and bandwidth — [Pages limits][cf-pages-limits].
  Daily deploys (~31/month) plus PR previews stay far below 500.
- Cloudflare Workers Free: 100,000 requests/day, 10 ms CPU per request (network wait time not
  counted), 128 MB memory, 50 subrequests — [Workers limits][cf-workers-limits]. The suggestion
  form and email handler are tiny and fit.
- No always-on server, database, or login page exists to attack or patch (Constitution I, VII).

**Important constraint discovered**: In a public repository, scheduled workflows are
automatically disabled after 60 days with no repository activity — [GitHub docs][gh-disable].
The daily data-update PR (R9) creates activity, so this should not trigger; as a safeguard, the
health workflow also checks that schedules are still enabled and opens an issue if not.

**Alternatives considered**:

- Django/managed host (~$7–25/month, unverified): rejected for cost and server upkeep.
- Small VPS (~$4–6/month, unverified): rejected; self-managed patching conflicts with the
  security-first, low-effort goals.
- GitHub Pages instead of Cloudflare Pages: viable fallback; Cloudflare chosen because Pages,
  Workers, Turnstile, Email Routing, and KV live in one free account and Pages supports custom
  security headers via a `_headers` file.

---

## R2. Language, libraries, and tooling

**Decision**:

- **Discovery + site generator**: Python 3.13, managed with `uv` (lockfile with hashes).
  - HTTP: `httpx` wrapped by our own `safe_fetch` (R12).
  - Calendar feeds: `icalendar` + `recurring-ical-events` (expands recurring series).
  - RSS/Atom: `feedparser`.
  - HTML parsing / JSON-LD and microdata extraction: `selectolax` + standard `json`.
  - Sanitization: `nh3` (Rust "ammonia" bindings) for any HTML-derived text; output is plain text.
  - Models/validation: `pydantic` v2. Templates: `jinja2` with autoescape on.
  - robots.txt: `protego`. Fuzzy matching for de-duplication: `rapidfuzz`.
  - AI: official `openai` Python SDK.
- **Workers**: TypeScript, `wrangler`, `vitest`; `postal-mime` for parsing email.
- **Front end**: Hand-written, framework-free JavaScript (ES modules) and CSS, self-hosted. No
  third-party scripts or CDNs.
- **Quality**: `pytest`, `respx` (mock HTTP), `ruff` (lint/format), `mypy --strict`, `pip-audit`,
  `npm audit`, `gitleaks` (secret scanning), GitHub secret scanning + push protection,
  Dependabot, `axe-core` via Playwright for accessibility checks.

**Rationale**: Python has the most mature libraries for feeds, structured data, and HTML. One
language for discovery and site generation keeps the system small. Each library is widely used
and narrowly scoped.

**Alternatives considered**: Node/TypeScript for everything (fewer feed and calendar libraries);
`bleach` (deprecated, replaced by `nh3`); `extruct` (heavier dependency tree than needed).

---

## R3. Calendar view: generated HTML vs. FullCalendar

**Decision**: Generate month and week calendar pages as static, semantic HTML tables (one page
per month and per week, plus upcoming/past list pages) and add a small amount of our own
JavaScript for filtering and search. Do **not** use FullCalendar.

**Rationale**:

- Static tables are readable without JavaScript and work with screen readers and keyboards by
  construction, which makes WCAG 2.2 AA (FR-050) easier to prove than with a JS widget.
- No third-party script makes a strict Content Security Policy (`script-src 'self'`) simple.
- Month/week navigation becomes ordinary links, so URLs are shareable (FR-038) for free.

**Alternatives considered**: FullCalendar (capable, but adds a large dependency, JS-only
rendering, and extra accessibility testing); a hybrid of both was rejected as unnecessary.

---

## R4. Event platforms

### Meetup

**Findings**:

- The official API is GraphQL at `api.meetup.com/gql`. Meetup's help center lists an active
  **Pro subscription** plus OAuth as prerequisites for API work; third-party guides disagree on
  whether free accounts can do read-only search — [Meetup help][meetup-help],
  [third-party guide][meetup-3p]. **VERIFY**.
- `meetup.com/robots.txt` (fetched 2026-10-16) disallows `/api`, `/gql*`, `*/events/rss/*`,
  `*/events/atom/*`, `*/events/xml/*`, and `/find` URLs that use location/keyword query
  parameters. It does not disallow group event pages or `*/events/ical/*`, and it blocks the
  `GPTBot` user agent entirely.
- Group iCal feeds have historically been at `meetup.com/<group>/events/ical/`; a user report
  says these may now require being logged in — [WordPress support thread][meetup-ical]. **VERIFY**.

**Decision**: Treat Meetup as **"collect only if allowed."**

1. Before any Meetup connector is built, review Meetup's current Terms of Service and API
   license (gate V1).
2. If public group iCal feeds are reachable without login and the terms permit automated
   access, use them (generic iCal connector; no Meetup-specific code).
3. Otherwise, fall back to reading the `Event` JSON-LD on individual public group event pages
   only if the terms allow it; if they do not, Meetup groups are still **discovered** (via web
   search) and listed as known groups that link to their Meetup page, but their events are not
   collected. This would reduce coverage materially, so the decision will be reported to the
   owner.
4. Never use `/find` search URLs, `/gql`, or `/api` (robots-disallowed), and never log in.

### Eventbrite

**Findings**: Public event search (`GET /v3/events/search/`) was removed in late 2019/early
2020. Supported endpoints list events by ID, by venue, or by organization
(`/v3/organizations/{id}/events/`) — [GitHub issue][eb-search], [Eventbrite docs][eb-orgs].
No cross-platform search exists.

**Decision**: Eventbrite organizers are found through web search and link-following (R6). Once
known, collect their events through the organization events endpoint (free private API token)
if the API terms permit this use (gate V2), otherwise via `Event` JSON-LD on public event pages.

### Luma

**Findings**: Public Luma calendars and city Discover pages offer an "Add iCal Subscription" live
feed — [Luma help][luma-ical]. The official API key is scoped to a calendar you own. An
undocumented Discover API exists but is unofficial.

**Decision**: Use public Luma calendar iCal feeds through the generic iCal connector. Do not use
undocumented endpoints. Check whether Luma has a Discover page covering Omaha/Lincoln (gate V3).

### Universities and organization calendars (UNO, UNL, Creighton, chambers, libraries, etc.)

**Decision**: No platform-specific connectors up front. University and municipal calendars
commonly run on calendar products that expose iCal or RSS; the generic iCal, RSS, and JSON-LD
connectors (R5) cover them. Department-level pages (e.g., computer science, IS&T, cyber
programs) are added as sources so campus-wide calendars do not flood classification.

---

## R5. Generic connectors and automatic feed detection (FR-012)

**Decision**: Build a small set of generic connectors, chosen automatically per source:

| Connector | Detects | Notes |
|---|---|---|
| `ical` | `.ics` links, `webcal://`, `<link rel="alternate" type="text/calendar">` | Expands recurrences; keeps source time zone |
| `rss` | `<link rel="alternate" type="application/rss+xml|atom+xml">` | Items become *candidate mentions*, not events, unless they carry event data |
| `jsonld` | `<script type="application/ld+json">` with `Event` (incl. `@graph`) | Also handles microdata `itemtype=schema.org/Event` |
| `eventbrite_org` | Eventbrite organizer URL | Only if gate V2 passes |
| `html_rules` | Last resort, per-site extraction rules in a data file (CSS selectors) | Requires review; never auto-created |

When discovery finds a new website, the **feed detector** fetches the page once, looks for the
above signals in priority order (ical → jsonld → rss), and records the chosen connector on the
source. Sites with no detectable signal become *candidate sources needing review* rather than
getting custom code.

**Rationale**: Covers most sites with no per-site code (Constitution V: official feeds and
structured data first) and keeps each source isolated.

---

## R6. Discovering unknown groups and events (User Story 2; FR-010–FR-014)

**Decision**: A weekly `discover-sources` workflow runs these *finders*, each producing
**candidate sources** and **event mentions**:

1. **Web search finder** — runs a query set of `{topic} × {place}` templates (e.g., "meetup",
   "user group", "conference", "workshop", "hackathon" × "Omaha", "Lincoln", "Nebraska", plus
   topic words: AI, cybersecurity, programming, cloud, data, networking, DevOps, etc.). About
   40 queries/week (~175/month).
2. **Link-graph finder** — from pages of known organizers, sponsors, venues, and speakers,
   follows outbound links (one hop, same-page only, no crawling of whole sites) and keeps links
   that look like groups, event pages, or calendars.
3. **Newsletter finder** — processes emails received since the last run (R8).
4. **News/blog finder** — reads RSS feeds of local tech news and community blogs.
5. **Platform finder** — checks Luma public calendars/Discover pages; Meetup only per gate V1.
6. **Gap finder** — see R7.

Each candidate goes through **evaluation**: robots/terms check → feed detection (R5) → relevance
scoring (R10) → result: *added as probationary*, *rejected* (not re-evaluated for 30 days,
FR-015), or *needs review*. Event mentions (from newsletters, news, search snippets) are never
published directly; the system tries to resolve each to an original event page (FR-014) and, if
found, adds that page's host as a candidate source.

**Rationale**: Many channels, each simple; all output flows through the same trust/review rules.

### Web search provider

**Findings**: Brave Search API appears to have replaced its free tier for new sign-ups with
about $5/month in credits (~1,000 queries) at about $5 per 1,000 requests; sources conflict and
one lists a free 2,000-query tier — [costbench][brave-cost], [apicostcalc][brave-calc]. **VERIFY**.

**Decision**: Use a pluggable `SearchProvider` interface; default to **Brave Search API**,
whose monthly credit is expected to cover ~175 queries/month (gate V4). Results are cached by
query for 7 days. If the free credit disappears or Brave's terms forbid storing results, switch
providers via configuration only.

**Alternatives considered**: Google Programmable Search JSON API, Bing Web Search API, other
search APIs — availability and terms for new customers to be checked in gate V4; scraping search
engine result pages is rejected (terms violations).

---

## R7. Coverage measurement and gap detection (FR-013; SC-002, SC-011)

**Decision**:

- **Quiet group detection**: for each source, compute typical cadence from its last 6 months of
  events; if no upcoming event is known after 2× the median gap, flag "possibly moved" and run
  targeted searches for the organizer name.
- **Annual events**: for events marked as an annual series (same organizer, similar title, ~1
  year apart), search for the next edition 10 months after the last one.
- **Known-groups list**: a maintained file `data/known_groups.yaml` (seeded in R14, extended
  automatically by every finder) lists groups/organizations even if no source works yet. Groups
  with no working source are re-searched monthly.
- **Coverage report**: the weekly run writes a coverage summary (sources by channel type, new
  groups found, quiet groups, unresolved mentions) into the health issue (R9).
- **Quarterly coverage check (SC-002)**: a documented manual procedure in `quickstart.md`.

---

## R8. Newsletter inbox

**Findings**: Cloudflare Email Routing on the free plan has unlimited inbound mail, 25 MiB message
cap, 200 rules/addresses; Email Workers on free can hit CPU limits on large or complex messages;
forwarding to verified destination addresses is free — [Email Routing limits][cf-email-limits],
[Email pricing][cf-email-pricing].

**Decision**:

- A dedicated address (e.g., `events@<domain>`) routes to an **Email Worker**.
- The Worker accepts mail only from an **allow-list of newsletter senders** stored in config;
  everything else is dropped. Subscription-confirmation emails are forwarded to the owner's
  verified address so they can click "confirm" once.
- The Worker does minimal work (to stay within 10 ms CPU): it stores the raw message (≤ 1 MiB,
  larger dropped) in **Workers KV** with a 30-day TTL and returns. All parsing happens later in
  Python in the daily workflow, which reads and deletes processed items through the Cloudflare
  API with a token scoped to that one KV namespace.
- In Python, emails are converted to plain text, links extracted, and the AI extracts event
  mentions (R10). Each email is processed once (cached by message hash).
- Before any link is stored (all of it public), query strings and fragments are removed and
  unsubscribe, preference, "view in browser", and tracking/redirect links are dropped (matched
  against the `List-Unsubscribe` header and known link patterns), so nothing in the repo can be
  used to manage the inbox's subscriptions. Only the message hash is stored, never content.

**Alternatives considered**: a Gmail account with IMAP (requires storing a mailbox credential and
login; rejected); paid newsletter-to-RSS services (cost).

**VERIFY** (gate V5): KV free-tier limits (expected ~1,000 writes/day, 1 GB storage) and whether
Email Workers parse within free CPU limits when storing raw messages only.

---

## R9. Admin workflow on GitHub (FR-018, FR-041–FR-046)

**Decision**:

- **Daily data PR**: the `discover-events` workflow commits updated data on a bot branch and
  opens a PR using a **GitHub App** installation token (PRs created with the default
  `GITHUB_TOKEN` do not trigger CI). Changes that need no review (trusted sources, updates,
  cancellations) are in this PR, which is set to **auto-merge** once CI passes — permitted by the
  constitution v1.1.0 exception for bot PRs that change only `data/`.
- **Review PR**: held events, new probationary sources, and suggestions that need review go
  into a separate PR (branch `review/open`, updated at most daily while items are pending) whose
  description has an **approve** and a **reject** checkbox per item, with the reason it is held,
  the source, and a link. At merge, an `apply-review` workflow (triggered on `push` to `main`, so
  it can use the `main`-only Environment) applies ticked decisions, leaves undecided items
  pending, and updates source approve/reject counts (FR-018 promotion/pausing).
- **Audit log**: git history plus PR records (who ticked, who merged) satisfies FR-046.
- **MFA**: required on the owner's GitHub account; repository admin is the only role allowed to
  merge review PRs (branch protection + CODEOWNERS).
- **Summary (FR-044)**: GitHub notifications for the review PR; a single pinned "Discovery
  health" issue whose body shows current status (all sources, failing sources, quiet groups, AI
  spend, coverage). When something needs attention, the workflow posts a **new comment**
  mentioning the owner (issue edits do not send notifications), at most once per day.
- **Manual source edits (FR-042)**: sources are YAML files under `data/sources/`; adding, pausing,
  or removing a source is a normal PR.

**Rationale**: Uses GitHub's existing strong authentication, review UI, notifications, and
history at no cost; nothing custom to secure.

---

## R10. Relevance classification and AI usage

**Decision**:

1. **Rules first**: keyword and pattern scoring on title/organizer/description (tech terms,
   category vocabularies, Nebraska place names, exclusion terms like "webinar demo",
   "real estate"). Location resolution uses a gazetteer of Nebraska cities/ZIPs and venue names.
   Rules decide clear cases.
2. **AI only for ambiguous cases and extraction**: OpenAI API with **Structured Outputs** (JSON
   schema with enums for categories, location area, and a relevance label + confidence). AI is
   also used to extract event mentions from newsletters and news posts.
3. **Model**: the cheapest current OpenAI "nano"-tier model, set in config. Secondary sources
   list GPT-5 nano at about $0.05/$0.40 per million input/output tokens and GPT-5.4 nano at about
   $0.20/$1.25 — [anotherwrapper][oa-nano], [morphllm][oa-pricing]. **VERIFY** (gate V6).
4. **Cost controls**: results cached by content hash (an unchanged event is never re-sent);
   inputs truncated (e.g., 4,000 characters per event, 20,000 per email); a hard monthly
   budget enforced in code (stop calling AI and fall back to "needs review" when reached) in
   addition to the OpenAI dashboard spending limit. Estimated volume: a few hundred
   classifications plus ~20–40 emails per month, roughly 1–3 million tokens — expected to cost
   about $1/month or less at the prices above.
5. **Prompt-injection safety**: source text is placed only in a clearly delimited data field;
   the system prompt states the text is untrusted data; the model has **no tools** and can only
   return the schema; outputs are validated, and AI results can never publish an event from a
   probationary source, change trust levels, or add a source as trusted. AI-derived fields are
   marked as inferred (FR-029).

**Alternatives considered**: AI for everything (cost, unpredictability); no AI (newsletter
extraction and ambiguous classification would need manual review, breaking SC-010).

---

## R11. De-duplication (FR-006)

**Decision**: Events are matched by (a) identical canonical original URL, else (b) same start
time within ±30 minutes, same day, and title similarity ≥ 85 (rapidfuzz token-set ratio) with
compatible location (same city or both online). Matched listings merge into one Event; the
preferred original link is the organizer's own page over aggregators. Every source listing is
kept so changes and cancellations can be tracked per source.

---

## R12. Safe fetching and SSRF protection (Constitution I; FR-022, FR-047)

**Decision**: All outbound HTTP goes through one `safe_fetch` function:

- HTTPS only (http allowed only to be upgraded); ports 443 only.
- Resolve DNS, reject private, loopback, link-local (incl. `169.254.169.254` cloud metadata),
  multicast, CGNAT, and IPv6 equivalents; connect to the vetted IP; re-check on every redirect
  (max 5).
- Timeouts (connect 10 s, total 30 s); response size cap (5 MB pages, 2 MB feeds); allowed
  content types per connector.
- Honest User-Agent (`NETechConnectBot/1.0 (+https://<domain>/about)`), robots.txt honored via
  `protego` with per-host crawl delay (default ≥ 5 s) and per-host request budgets.
- The Worker's suggestion endpoint performs the same syntactic URL checks but **never fetches**
  the URL; fetching happens later in `safe_fetch` (FR-022).

---

## R13. Public-repo and supply-chain hardening (Constitution I, workflow gates)

**Decision**: secret scanning + push protection; Dependabot (pip, npm, GitHub Actions);
branch protection on `main` (PR required, CI required, no force-push, CODEOWNERS review for
`/.github/`, `/workers/`, `/discovery/src/netc/fetch/`); default `GITHUB_TOKEN` read-only, with
per-job `permissions:`; "require approval for all outside collaborators" for fork PR workflows;
no `pull_request_target`; all actions pinned to full commit SHAs; secrets (OpenAI key, Brave key,
Cloudflare KV token, GitHub App key) stored in a protected **`discovery` Environment** limited to
`main` and the scheduled workflows; `SECURITY.md`; MIT license (owner may choose otherwise).
Pages security headers via `_headers`: strict CSP (`default-src 'self'; script-src 'self';
object-src 'none'; base-uri 'none'; frame-ancestors 'none'`), HSTS, `X-Content-Type-Options`,
`Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`.

---

## R14. Starting list of sources, organizations, and newsletters

Seed entries for `data/known_groups.yaml` and `data/sources/`. **All are unverified leads from
search results on 2026-10-16** (several listings were 2024–2025); each MUST be checked for an
active page, a usable feed or structured data, and terms before becoming a trusted source.

| Name | Area | Type / where found | Notes |
|---|---|---|---|
| AIM Institute (Heartland Developers Conference) | Omaha | Organization + annual conference | HDC 2026 listed Sep 30–Oct 1 — [SPN][spn-hdc], [Unleash CB][hdc-2026] |
| INTERFACE Omaha | Omaha | Annual IT/security conference | 2026 edition listed Nov 5, CHI Health Center — [luminik][interface] |
| ISACA Omaha Chapter | Omaha | Professional association | Monthly, 2nd Tuesday — [ISACA Omaha][isaca] |
| InfraGard Nebraska; NEbraskaCERT | Omaha | Security organizations | Sponsors of INTERFACE |
| OWASP Omaha | Omaha | Security chapter | Old wiki archived — [OWASP wiki][owasp]; find current page |
| BSides Omaha; WiCyS Nebraska; Nebraska Cybersecurity Conference; Great Plains Cybersecurity Conference | Nebraska | Security events | Named in a Nebraska list — [infosec-conferences][infosec]; also a candidate known-list for gap checks (terms to check) |
| Omaha Azure User Group | Omaha | Meetup group | Meetup (gate V1) |
| Omaha Red Hat User Group | Omaha | Meetup group | Meetup (gate V1) |
| AI Omaha; GCP Meetup – Omaha; Nebraska Women of Color in Tech; Nebraska Data and Analytics Forum; OMWEB | Omaha | Meetup groups | Seen in Meetup suggestions |
| Women in Technology of the Heartland | Omaha | Organization | Events seen 2025 |
| Salesforce Developer Group, Omaha | Omaha | Trailblazer Community group | [Trailblazer][sfdg] |
| Drupal Nebraska / Omaha Drupal Meetup | Omaha/Lincoln | groups.drupal.org | 2026 meetups listed — [Drupal Nebraska][drupal] |
| Nebraska Code Camp | Lincoln | Developer conference | Historic (UNL + Lincoln .NET UG); check if active |
| FUSE Coworking | Lincoln | Coworking / venue | Historic host of tech meetups |
| UNL School of Computing; UNO College of IS&T; Creighton; Bellevue University cybersecurity | Lincoln/Omaha | University calendars | Look for department-level iCal/RSS |
| Lincoln Chamber of Commerce; Greater Omaha Chamber | Lincoln/Omaha | Chamber calendars | Filter heavily for tech |
| Silicon Prairie News | Regional | Tech news (RSS) + newsletter | News/blog finder and newsletter candidate |

---

## Validation gates (must pass before the dependent tasks)

| Gate | Check | Blocks |
|---|---|---|
| V1 | Meetup Terms/API license: is automated reading of public group iCal feeds or event pages allowed without Pro? Are feeds reachable without login? | Collecting Meetup events |
| V2 | Eventbrite API terms allow listing a third-party organization's public events | `eventbrite_org` connector |
| V3 | Luma public calendar iCal feed terms; any Omaha/Lincoln Discover page | Luma sources |
| V4 | Search API provider: current free credit/tier, terms on caching/storing results | Web search finder |
| V5 | Cloudflare KV free limits; Email Worker within free CPU | Newsletter inbox |
| V6 | Current OpenAI nano model name, price, Structured Outputs support | AI classifier |
| V7 | Each seed source in R14: active, feed/structured data present, terms allow | Seeding trusted sources |

---

[gh-billing]: https://docs.github.com/en/billing/concepts/product-billing/github-actions
[gh-disable]: https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows
[cf-pages-limits]: https://developers.cloudflare.com/pages/platform/limits
[cf-workers-limits]: https://developers.cloudflare.com/workers/platform/limits
[cf-email-limits]: https://developers.cloudflare.com/email-routing/limits
[cf-email-pricing]: https://developers.cloudflare.com/email-service/platform/pricing/
[meetup-help]: https://help.meetup.com/hc/en-us/articles/41939051573133-I-want-to-create-a-large-number-of-groups-within-my-Meetup-network-Can-I-leverage-Meetup-s-API-to-do-that-in-bulk
[meetup-3p]: https://www.rapidevelopers.com/bolt-ai-integrations/meetup
[meetup-ical]: https://wordpress.org/support/?p=16607116
[eb-search]: https://github.com/Automattic/eventbrite-api/issues/83
[eb-orgs]: https://www.eventbrite.co/platform/docs/organizations
[luma-ical]: https://help.luma.com/p/ical-syncing
[brave-cost]: https://costbench.com/software/ai-search-apis/brave-search-api/
[brave-calc]: https://apicostcalc.com/brave-search.html
[oa-nano]: https://anotherwrapper.com/llm-pricing/gpt-5-nano-2025-08-07
[oa-pricing]: https://morphllm.com/openai-api-pricing
[spn-hdc]: https://siliconprairienews.com/tag/heartland-developers-conference
[hdc-2026]: https://www.unleashcb.com/events/heartland_developers_conference_hdc/2025-09-30/
[interface]: https://www.luminik.io/events/interface-omaha-nebraska/attendees/
[isaca]: https://engage.isaca.org/omahachapter/aboutchapter/about
[owasp]: https://wiki.owasp.org/index.php/Omaha
[infosec]: https://infosec-conferences.com/us-state/nebraska
[sfdg]: https://trailblazercommunitygroups.com/salesforce-developer-group-omaha-united-states
[drupal]: https://groups.drupal.org/nebraska
