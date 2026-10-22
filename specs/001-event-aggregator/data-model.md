# Data Model: Nebraska Tech Event Aggregator

**Feature**: `001-event-aggregator` | **Date**: 2026-10-16 | **Plan**: [plan.md](./plan.md)

All data is stored as versioned files in the public repository under `data/` (see
[research.md](./research.md) R1, R9). Everything stored is public information; nothing personal
or secret is stored. JSON Schemas for the two central entities are in
[contracts/event.schema.json](./contracts/event.schema.json) and
[contracts/source.schema.json](./contracts/source.schema.json).

## Storage layout

```text
data/
├── categories.yaml              # Category list (admin-extendable, FR-028)
├── areas.yaml                   # Location areas + Nebraska gazetteer (cities, ZIPs, venues, map points)
├── known_groups.yaml            # Known groups/organizations, with or without a working source
├── overrides.yaml               # Admin corrections (visibility, categories, area) applied last
├── organizers.yaml              # Organizer records
├── sources/<source_id>.yaml     # One file per Event Source (human-editable)
├── events/<YYYY>/<YYYY-MM>.json # Events grouped by start month (machine-written)
├── candidates.json              # Candidate sources and their evaluation history
├── mentions.json                # Event mentions awaiting resolution to an original page
├── review/queue.json            # Items held for administrator review
├── review/open.json             # Snapshot of rev_ ids in the open review PR (written only by it)
├── state/source_status.json     # Per-source run health (last success, errors, counts)
└── cache/ai/<YYYY-MM>.jsonl     # AI results keyed by content hash (cost control)
```

Machine-written files are written deterministically (sorted keys, stable ordering) so that
daily diffs are small and reviewable.

## Entities

### Event

One event occurrence, possibly merged from several Source Listings.

| Field | Type | Rules |
|---|---|---|
| `id` | string | `evt_` + first 12 hex chars of SHA-256 of the canonical original URL of the first listing; never changes |
| `slug` | string | URL-safe, from title + date; unique |
| `title` | string | 1–200 chars, plain text (sanitized) |
| `start` | datetime (UTC, ISO 8601) | Required |
| `end` | datetime (UTC) \| null | ≥ `start` when present |
| `source_tz` | IANA zone | From source; `America/Chicago` assumed if missing, with `tz_assumed: true` |
| `all_day` | bool | |
| `location` | object | `{venue?, address?, city?, state?, online: bool}` |
| `area` | enum | `omaha` \| `lincoln` \| `other_ne` \| `online` (FR-036) |
| `organizer_id` | string \| null | → Organizer |
| `summary` | string | Plain text, ≤ 500 chars (FR-031) |
| `categories` | list[enum] | ≥ 1, values from `categories.yaml` (FR-028) |
| `original_url` | string | **HTTPS only**, preferred organizer page (FR-025, FR-048) |
| `status` | enum | `scheduled` \| `cancelled` \| `unverified` (FR-007) |
| `review_state` | enum | `published` \| `pending_review` \| `rejected` |
| `visibility` | enum | `shown` \| `hidden` (admin override, FR-019, FR-045) |
| `inferred` | list[string] | Names of fields set by rules/AI rather than the source (FR-029) |
| `listings` | list[SourceListing] | ≥ 1 |
| `series_key` | string \| null | Groups recurring/annual occurrences (R7) |
| `first_seen` | datetime (UTC) | |
| `last_verified` | datetime (UTC) | Updated whenever any listing is re-read successfully (FR-030) |
| `original_unavailable` | bool | Default `false`; set by the monthly link check when the original page returns 404/410 |

**Derived (not stored)**: `is_upcoming` = now < (`end` or `start`) (FR-035); display times in
`America/Chicago` (FR-027). An event is publicly visible only when `review_state = published`
and `visibility = shown`.

**State transitions**:

```text
review_state:  [discovered] ──trusted source──▶ published
               [discovered] ──probationary────▶ pending_review ──approve──▶ published
                                                               └─reject───▶ rejected
status:        scheduled ◀──▶ unverified   (missing from source on 2 consecutive runs → unverified;
               scheduled ───▶ cancelled      reappears → scheduled; source says cancelled → cancelled)
visibility:    shown ◀──admin──▶ hidden
```

### SourceListing (embedded in Event)

| Field | Type | Rules |
|---|---|---|
| `source_id` | string | → Event Source |
| `url` | string | Listing URL on that source (HTTPS) |
| `external_id` | string \| null | UID/ID from the source (iCal `UID`, JSON-LD `@id`, etc.) |
| `content_hash` | string | Hash of normalized listing content; used for change detection and AI cache |
| `last_seen` | datetime (UTC) | |
| `missing_runs` | int | Consecutive runs not seen; drives `unverified` |

### Event Source

A place events are collected from. One YAML file per source so the owner can edit by PR.

| Field | Type | Rules |
|---|---|---|
| `id` | string | `src_` + slug; unique |
| `name` | string | |
| `url` | string | HTTPS page or feed URL |
| `connector` | enum | `ical` \| `rss` \| `jsonld` \| `eventbrite_org` \| `html_rules` (R5) |
| `feed_url` | string \| null | Detected feed (when different from `url`) |
| `trust` | enum | `trusted` \| `probationary` (FR-016) |
| `origin` | enum | `preconfigured` \| `admin` \| `discovered` \| `suggested` |
| `found_via` | enum \| null | `web_search` \| `link_graph` \| `newsletter` \| `news` \| `platform` \| `gap` \| `suggestion` |
| `status` | enum | `active` \| `paused` \| `blocked_by_terms` |
| `organizer_id` | string \| null | |
| `default_area` | enum \| null | Used when events lack a location |
| `approved_count` / `rejected_count` | int | Review outcomes (FR-018) |
| `check_interval_hours` | int | Default 24; ≤ 24 (FR-002). A run reads the source when skipping it until the next twice-daily run would exceed this (with 1 h for late starts), so a 24 h source is read at every run 11 h or more after the last |
| `rate_limit_seconds` | int | Minimum delay between requests to this host; default 5 |
| `html_rules` | object \| null | Only for `html_rules` connector |
| `added_at` / `updated_at` | date | |

Run health lives separately in `state/source_status.json`: `last_attempt`, `last_success`,
`last_error` (sanitized message), `consecutive_failures`, `events_found_last_run`.

**State transitions** (FR-016–FR-019):

```text
trust:   probationary ──approved ≥ 3 AND rejected = 0──▶ trusted
         trusted ──admin demote──▶ probationary
status:  active ──rejected > approved (≥ 3 reviewed)──▶ paused   (automatic)
         active ◀──admin──▶ paused
         any ──robots/terms forbid──▶ blocked_by_terms
```

### Candidate Source

| Field | Type | Rules |
|---|---|---|
| `url` | string | Normalized HTTPS URL (key) |
| `found_via` | enum | as above |
| `evidence` | list | Where it was seen (query, referring page, email hash) |
| `result` | enum | `pending` \| `added` \| `rejected` \| `needs_review` \| `blocked_by_terms` |
| `reason` | string | Short reason for the result |
| `last_evaluated` | datetime | Re-evaluation not before `last_evaluated + 30 days` when rejected (FR-015) |

**Privacy**: visitor suggestion notes are **never** stored in `data/` or shown in PRs or
issues. They stay only in the private KV inbox (30-day TTL) and are passed in memory to
evaluation (FR-020).

### Event Mention

An event seen only as a mention (newsletter, news post, search snippet) — never published
directly (FR-014).

| Field | Type | Rules |
|---|---|---|
| `id` | string | Hash of channel + title + date |
| `channel` | enum | `newsletter` \| `news` \| `web_search` |
| `title`, `date_hint`, `place_hint`, `organizer_hint` | string | Extracted (inferred) |
| `links` | list[string] | Candidate URLs found with the mention; query strings and fragments removed; unsubscribe, preference, "view in browser", and tracking/redirect links dropped |
| `resolution` | enum | `unresolved` \| `resolved` \| `held` \| `discarded` |
| `event_id` | string \| null | Set when resolved to an Event |
| `attempts` | int | Resolution attempts; discarded after 4 weekly attempts or after the date passes |

### Review Item

| Field | Type | Rules |
|---|---|---|
| `id` | string | `rev_` + hash |
| `kind` | enum | `event` \| `source` \| `suggestion` \| `mention` |
| `ref` | string | Event id, source id, or candidate URL |
| `reason` | string | Why it is held (e.g., "probationary source", "low confidence: location") |
| `created` | datetime | |
| `decision` | enum | `pending` \| `approved` \| `rejected` |
| `decided_in_pr` | int \| null | PR number (audit trail, FR-046) |

### Override

Admin corrections that must survive pipeline re-runs (FR-019, FR-045). Stored in
`data/overrides.yaml`, applied after every pipeline run and before site build.

| Field | Type | Rules |
|---|---|---|
| `event_id` | string | Must match an existing Event `id` (validation fails otherwise) |
| `visibility` | enum \| absent | `shown` \| `hidden` |
| `categories` | list[enum] \| absent | ≥ 1, values from `categories.yaml` |
| `area` | enum \| absent | `omaha` \| `lincoln` \| `other_ne` \| `online` |
| `reason` | string | Short admin note (public; no personal data) |

Overrides MUST NOT change `original_url`, `review_state`, or trust, and MUST NOT publish an event
from a probationary source. Overridden fields are removed from the event's `inferred` list.

### Organizer

`id`, `name`, `home_city`, `url` (HTTPS), `aliases` (for de-duplication and quiet-group search).

### Category

`id` (slug), `label`, `keywords` (rules vocabulary). Seed list per FR-028: `ai-ml`,
`security`, `software-dev`, `networking-infra`, `cloud-devops`, `data-analytics`, `web-mobile`,
`product-design-ux`, `career-networking`, `hardware-iot-makers`, `general-tech`.

### Known Group

`name`, `aliases`, `area`, `links` (any known pages), `source_ids` (working sources, may be
empty), `last_searched`, `cadence_days` (computed), `status` (`active` \| `quiet` \| `defunct`).

### Administrator and Audit Log Entry

Not stored in `data/`. Administrators are GitHub users with admin role on the repository
(MFA required). The audit log is git history plus review PRs (who ticked, who merged).

## Validation rules (applied on every write, enforced in CI)

- All files validate against their schema; CI fails otherwise.
- Every `url`, `original_url`, and `feed_url` is HTTPS and has a public hostname (FR-048).
- All text fields are plain text after sanitization; no HTML is stored (FR-047).
- Times are stored in UTC with `source_tz` retained (Constitution IV).
- `summary` ≤ 500 chars; `title` ≤ 200 chars.
- No event may have `review_state: published` if its only listings come from a
  `probationary` source and there is no approved Review Item for it.
