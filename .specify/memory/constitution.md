# NETechConnect (CommunityTechConnect) Constitution

## Core Principles

### I. Security by Default (NON-NEGOTIABLE)

Security is the highest-priority quality attribute of NETechConnect and overrides convenience,
speed of delivery, and feature scope when they conflict.

- All untrusted input — including every byte fetched from third-party event sources — MUST be
  validated and sanitized server-side, and all output MUST be context-encoded to prevent XSS,
  injection, and HTML/script smuggling from scraped content.
- The system MUST follow least privilege: discovery workers, the web app, and data stores run
  with separate, minimally scoped credentials; no component holds credentials it does not need.
- Secrets MUST never be committed to the repository, logged, or exposed to the client; they are
  supplied via a secrets manager or environment configuration and are rotatable.
- All traffic MUST use HTTPS/TLS; responses MUST ship a strict Content Security Policy and
  standard security headers (HSTS, X-Content-Type-Options, frame-ancestors, Referrer-Policy).
- Outbound fetching MUST be protected against SSRF (allow-listed schemes, no private/loopback/
  metadata address ranges, size and time limits on responses).
- Personal data collection MUST be minimized; the public site MUST function without accounts.
  Any feature that stores personal data requires an explicit justification in its plan.
- Dependencies MUST be pinned, scanned for known vulnerabilities in CI, and patched promptly;
  a known critical/high vulnerability blocks release.

Rationale: The service ingests content from many uncontrolled sources and publishes it to the
public, making it an attractive vector for injection, SSRF, and supply-chain attacks.

### II. Aggregator, Not Organizer (NON-NEGOTIABLE)

NETechConnect is an event aggregator. It discovers events and points people to the organizer's
own event page; it is never the system of record for an event.

- Every displayed event MUST link to its original event page, and that link MUST be the primary
  call to action for details, registration, and RSVP.
- The service MUST NOT create calendar invites, generate iCal/.ics files or calendar
  subscriptions, send event reminders, or handle registration, RSVP, ticketing, or payments.
- The service MUST NOT host or author event content beyond the summary needed for listing
  (title, date/time, location, organizer, short description, source link).
- Where the original event page and NETechConnect disagree, the original page is authoritative
  and the listing MUST direct users there.

Rationale: Keeping organizers as the source of truth avoids stale or conflicting copies of
event details, keeps the system small, and reduces the security and privacy surface.

### III. Nebraska Community Scope

- The service MUST cover community technology events held in, or explicitly targeting, the
  state of Nebraska, including virtual events hosted by Nebraska-based groups.
- Omaha and Lincoln are the primary focus: discovery sources for these metros MUST be
  prioritized and their coverage measured; other Nebraska locations MUST still be included.
- "Community tech event" means meetups, user groups, conferences, hackathons, workshops, and
  similar gatherings centered on technology. Purely commercial sales events and non-tech events
  MUST be excluded or clearly filterable.
- Both upcoming and past events MUST remain viewable; past events are retained as a historical
  archive rather than deleted.

Rationale: A focused, well-defined scope keeps the event list relevant and trustworthy for the
Nebraska tech community.

### IV. Accurate, Attributed Event Data

- Every event MUST record its source (origin URL and source name) and link back to the original
  listing so users can verify details with the organizer.
- Event times MUST be stored in UTC with the source time zone retained, and displayed in
  America/Chicago (Central Time) unless the user chooses otherwise.
- Duplicate listings of the same event from multiple sources MUST be detected and merged into a
  single displayed event.
- Each event MUST carry a last-verified timestamp; events whose source changes or disappears
  MUST be updated or flagged (e.g., cancelled/unverified) rather than silently shown as current.
- Automatically derived data (e.g., classification, location inference) MUST be distinguishable
  from source-provided data.

Rationale: Users rely on the service to decide where to spend their time; stale, duplicated, or
unattributed data erodes trust.

### V. Responsible & Resilient Discovery

- Discovery MUST prefer official APIs, iCal/RSS feeds, and structured data over HTML scraping.
- Discovery MUST honor each source's terms of service and robots.txt, identify itself with an
  honest User-Agent, and apply per-source rate limits with backoff.
- Each source MUST be implemented as an isolated adapter: a failure, timeout, or malformed
  response from one source MUST NOT break discovery from other sources or the public site.
- Discovery runs MUST be observable: structured logs and per-source metrics (events found,
  errors, last success) MUST exist so coverage gaps and broken sources are detected.
- Source content MUST be treated as untrusted data, never as instructions or executable code
  (see Principle I).

Rationale: Automatic discovery is the core value of the product and must be sustainable,
respectful of event organizers, and robust to sources that change without notice.

### VI. Test-First Quality

- Tests MUST be written before or alongside implementation and MUST fail before the code that
  satisfies them is written.
- Every source adapter MUST have tests against recorded fixtures, including malformed and
  malicious payloads (script injection, oversized responses, invalid dates).
- Security controls (sanitization, SSRF protection, headers, authorization) MUST have explicit
  automated tests.
- Integration tests MUST cover the path from discovery → storage → public listing and calendar
  views.
- CI MUST pass (tests, linting, type checks, dependency and secret scanning) before merge.

Rationale: The system depends on many external sources that change unpredictably; automated
tests are the only reliable guard against regressions and security holes.

### VII. Accessible, Simple Presentation

- The public site MUST provide both a list view and a calendar view of events, with filtering
  by date range, location (at minimum Omaha, Lincoln, and Other Nebraska), and past/upcoming.
- The UI MUST meet WCAG 2.2 Level AA and MUST be usable on mobile devices.
- Each event in both views MUST link out to its original event page (see Principle II).
- Designs MUST start with the simplest solution that satisfies the requirement (YAGNI); added
  complexity, new services, or new dependencies MUST be justified in the feature plan.

Rationale: The service exists for the whole community; it must be easy for anyone to use, and a
small, simple system is easier to secure and maintain.

## Security Requirements

- Threat modeling: every feature plan that introduces a new data source, external integration,
  user input, or stored data MUST include a brief threat analysis (assets, entry points, and
  mitigations) aligned with the OWASP Top 10.
- Administrative functions (source management, moderation, manual event edits) MUST require
  strong authentication (MFA) and authorization checks on every request, and MUST be
  audit-logged.
- Any public input (e.g., event submissions, reports) MUST be rate limited and protected against
  abuse and spam, and submitted content MUST be moderated or validated before publication.
- Logs MUST NOT contain secrets or unnecessary personal data.
- Backups of event data MUST exist and restores MUST be tested.
- Security issues found in production are fixed before new feature work proceeds.

## Development Workflow & Quality Gates

- Work follows the Spec Kit flow: specify → clarify → plan → tasks → implement. Each plan MUST
  pass a Constitution Check against Principles I–VII before implementation begins.
- All changes land through pull requests; direct commits to `main` are not permitted once CI is
  established.
- Every pull request MUST be reviewed for correctness and security; changes touching
  authentication, input handling, fetching, or secrets require explicit security review.
- Required CI gates: automated tests, linting/formatting, type checking (where applicable),
  dependency vulnerability scanning, and secret scanning.
- Deviations from a principle MUST be documented in the plan's Complexity Tracking section with
  a justification and the simpler alternative that was rejected.

## Governance

- This constitution supersedes all other development practices and guidance for NETechConnect.
  Where another document conflicts with it, the constitution wins.
- Amendments are made via pull request that updates this file, includes a Sync Impact Report,
  states the version bump rationale, and describes any migration needed for existing work.
- Versioning follows semantic versioning:
  - MAJOR: removal or backward-incompatible redefinition of a principle or governance rule.
  - MINOR: a new principle or section, or materially expanded guidance.
  - PATCH: clarifications, wording, and typo fixes with no change in meaning.
- Compliance is verified at plan time (Constitution Check), at review time (every PR), and
  through a periodic review of the constitution at least once per year.

**Version**: 1.0.0 | **Ratified**: 2026-10-16 | **Last Amended**: 2026-10-16
