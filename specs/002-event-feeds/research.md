# Research: Event Feeds

Decisions for `plan.md`. Each: decision, rationale, alternatives considered.

## R1. Feed format: Atom 1.0 (RFC 4287), plain-text content

- **Decision**: Publish Atom 1.0. Every text construct from event data (`title`, `summary`,
  category labels) uses `type="text"`. No `content` element, no HTML anywhere in the feed.
- **Rationale**: Atom's `type="text"` tells every reader "show this as plain text", so text from
  a source is escaped once (XML) and can never be read back as markup. RSS 2.0's `description`
  is treated by readers as HTML by convention: plain text has to be HTML-escaped *and* XML-escaped,
  and readers differ in how many times they decode it, which is the classic feed-injection bug.
  Atom also requires a stable `id` and `updated` per entry, which is what FR-004 needs. Atom is
  read by all common readers (Feedly, Inoreader, NetNewsWire, Thunderbird), Slack's `/feed`, and
  feed-to-email services.
- **Alternatives**: RSS 2.0 (wider legacy support; rejected for the escaping ambiguity above);
  JSON Feed (simple, but weaker support in Outlook/Slack); publishing both (twice the surface and
  tests for little gain).

## R2. Outlook and Teams

- **Decision**: Name "classic Outlook" as the Outlook target; check it by hand at the
  checkpoint. Don't promise Teams on the feeds page beyond "apps that can follow a feed".
- **Rationale**: Classic Outlook for Windows has an RSS Subscriptions folder; the new Outlook
  for Windows and Outlook on the web have no feed support. Microsoft retired the Office 365
  connectors Teams used for RSS; Teams now needs a Power Automate/Workflows flow, which works
  with any standard feed but isn't a one-step "paste the address". The feeds page lists feed
  readers, Slack and feed-to-email services as the plain ways, and Outlook (classic) as one more.
- **Alternatives**: Guarantee new Outlook (impossible: no feed support).

## R3. Generating the XML: Python standard library, no new dependency

- **Decision**: Build each feed with `xml.etree.ElementTree` in a new module
  `discovery/src/netc/site/feeds.py`, serialize as UTF-8 with an XML declaration. Before
  serializing, every text value passes a defensive filter that drops characters XML 1.0 forbids
  (C0 controls except tab/newline/CR, U+FFFE/U+FFFF, lone surrogates), although event text is
  already validated as plain text by the model (`_plain`).
- **Rationale**: ElementTree escapes `&`, `<`, `>` and quotes in text and attributes; we only
  write, never parse untrusted XML, so XXE/billion-laughs don't apply. Jinja templates for XML
  were rejected: HTML autoescaping is not XML escaping, and a missed `|e` is an injection.
  Constitution VII: no new dependency.
- **Alternatives**: `feedgen` (new dependency, more than needed); Jinja `feed.xml` template
  (escaping risk above).
- **Testing**: `feedparser` is already a runtime dependency (the iCal/RSS connectors use it).
  Tests parse every generated feed with it, as readers do, and assert `bozo == 0`. Hostile
  fixtures go through the full build in `tests/security/`.

## R4. When an event was "listed", and when it "changed": two new optional event fields

- **Decision**: Add two optional fields to `Event`:
  - `published_at`: when the event first became public. Set to the run time when a new event is
    created as `published` (trusted source) and when a review approval publishes it.
  - `changed_at`: when a detail a follower cares about last changed: title, start, end, all-day,
    location, or status (cancelled). Set in the lifecycle update when any of these differ from
    the stored event.

  Both are `null` on existing events and fall back to `first_seen` (published) and
  `published_at`/`first_seen` (updated). No migration.
- **Rationale**: The site build runs from `data/` in the deploy workflow and can't keep state
  between builds, so the feed can't detect changes itself. `first_seen` alone is wrong for
  probationary sources (an event discovered Monday and approved Thursday was *listed* Thursday),
  and `last_verified` changes every run, which would make the "updated" time churn and break
  SC-007. The summary is excluded from `changed_at`: small wording edits at the source aren't
  worth a follower's attention and would churn too.
- **Alternatives**: A feed-state file written by the build (the deploy job doesn't commit data;
  would need a new write path); hashing displayed fields into `updated` (a hash isn't a time);
  using `first_seen` for everything (wrong order for reviewed events, no change signal).
- **Limit**: An administrator override (`data/overrides.yaml`) is applied at build time and does
  not move `changed_at`. Overrides mostly hide events (which drops them from feeds) or fix a
  category; that's acceptable and documented in the contract.

## R5. Addresses, identity, sizes

- **Decision**:
  - Feeds at `/feeds/all.xml` and `/feeds/<category-id>.xml`; the page at `/feeds/`.
  - Entry `id`: `tag:netechconnect.com,2026:event/<event id>` (RFC 4151). Event ids never change
    (they survive merges via the oldest event), so the entry identity is stable. It doesn't
    depend on the serving domain, so a preview or `pages.dev` build has the same ids.
  - Feed `id`: `tag:netechconnect.com,2026:feed/all` and `.../feed/<category-id>`.
  - Links are absolute, built from the build's `site_domain` (the deploy already passes it).
  - At most 100 entries per feed, ordered by `published` newest first, ties by event id.
  - Feed `updated` = the newest entry `updated`, so a build with no event changes produces a
    byte-identical file (SC-007; also lets readers' conditional requests hit). An empty feed
    uses a fixed time (`2026-11-01T00:00:00Z`, the feature's start) so it is stable too.
- **Rationale**: Stable bytes mean no false "new" items and no needless downloads. 100 entries at
  roughly 1 KB each keeps a feed around 100 KB uncompressed, far less over the wire.

## R6. Serving: content type and headers on Cloudflare Pages

- **Decision**: Add a `/feeds/*.xml` rule to `web/_headers` setting
  `Content-Type: application/atom+xml; charset=utf-8`; the global `/*` rule already adds CSP,
  HSTS, `nosniff`, Referrer-Policy and Permissions-Policy. Check the live response at the
  checkpoint; if Pages keeps its default (`application/xml` or `text/xml`) the feed still works
  in every reader tested, so that's a recorded deviation, not a blocker.
- **Rationale**: FR-013. `nosniff` plus an XML type stops a browser treating the file as HTML.
  The strict CSP applies to the XML too, so even a browser rendering it can't run anything.
- **Alternatives**: `.atom` extension (less familiar to people pasting addresses).

## R7. Finding the feeds (FR-010, FR-011)

- **Decision**:
  - `base.html` gets `<link rel="alternate" type="application/atom+xml" title="NETechConnect:
    all events" href="/feeds/all.xml">` on every page.
  - A **Follow** link in the footer nav of every page, and a short "Follow new events" line on
    the home page under the event count, both to `/feeds/`.
  - `/feeds/` page: one paragraph explaining feeds; the all-events feed first, then each category
    in the site's category order, each as its label and full address as a link; then "Ways to
    use a feed": a feed reader, Slack (`/feed subscribe <address>`), classic Outlook (RSS
    Subscriptions), or a feed-to-email service of your choice. No named commercial service, no
    JavaScript needed. Copying uses the browser's own "copy link".
- **Rationale**: Footer link meets "one step from every page" without crowding the phone
  header (already Brand + Suggest). SC-004 (≤ 2 clicks) holds: home → Follow → copy.
- **Alternatives**: Header nav item (no room on phones); a copy button (needs JS; YAGNI).

## R8. Constitution clarification (FR-014)

- **Decision**: PATCH amendment 1.1.0 → 1.1.1. Principle II gets one bullet: "Read-only web feeds
  (e.g. Atom) of listed events are permitted: they carry only the listing summary and link each
  event to its original page. They are not calendar subscriptions." The prohibition bullet is
  unchanged. Sync Impact Report at the top of the file, as the governance section requires.
- **Rationale**: Clarifies existing meaning (feeds were never in the prohibited list; they
  carry exactly the allowed listing summary), so PATCH under the versioning rules. It lands as
  its own PR before the feature code, so the code PR is checked against the amended text.
- **Alternatives**: MINOR (would signal a new permission; the owner's intent is that nothing
  about the banned items changes).

## R9. Threat analysis (constitution "Security Requirements")

The feature adds an **output**, not an input or stored data. Assets: visitors' readers/apps,
the site's reputation. Entry points: event text from sources (already untrusted).

| Threat | Mitigation |
|---|---|
| Markup/script injection into readers via event text | Atom `type="text"` only; ElementTree escaping; no HTML elements; hostile-fixture security tests |
| Malformed XML (control chars, surrogates) breaking feeds | Model validation (`_plain`) + defensive XML-char filter; `feedparser` `bozo == 0` on hostile input |
| Dangerous link schemes (`javascript:`) | `original_url` is a validated `HttpsUrl`; site links are built from the build domain |
| Browser renders feed as HTML | `nosniff` + XML content type + global CSP |
| Tracking / personal data | Static identical file; no query parameters, cookies, or per-visitor content; SC-005 review |
| Oversized feed / abuse | 100-entry cap; static files on Cloudflare's CDN |
| Hidden or held events leaking | Feeds use the same `is_public` + upcoming filter as the site; tests for each state |

No new secrets, permissions, workflows, or Workers.
