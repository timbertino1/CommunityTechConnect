# Data Model: Event Feeds

The feature adds **no new stored entity**. It adds two optional fields to the existing Event
(`specs/001-event-aggregator/data-model.md`) and defines two derived, unstored structures
(Feed, Feed entry) that the site build computes from `data/`.

## Event: new optional fields

| Field | Type | Rules |
|---|---|---|
| `published_at` | datetime (UTC) or null | When the event first became public. Set once: at creation if published (trusted source), or when a review approval publishes it. Never changed afterward, including by later edits. Null on events stored before this feature. |
| `changed_at` | datetime (UTC) or null | When a follower-relevant detail last changed: `title`, `start`, `end`, `all_day`, `location`, or `status`. Set in the lifecycle update when any of these differ from the stored event; otherwise kept. Not moved by `summary`, `categories`, listings, `last_verified`, or overrides. Null until the first such change. |

Validation:
- Both optional; JSON Schema (`discovery/src/netc/schemas/event.schema.json`, mirrored in
  `specs/001-event-aggregator/contracts/event.schema.json`) adds them as nullable `date-time`
  strings; the schema stays `additionalProperties: false`.
- `published_at` ≥ `first_seen` when both set; `changed_at` ≥ `published_at` when both set
  (validator; a violation is a data error reported by `validate-data`).
- De-duplication merge keeps the earliest `published_at` and the latest `changed_at` of the
  merged events.

State transitions (additions to 001's lifecycle):

```text
new event, trusted source  ── create ──▶ published      published_at = now
pending_review ── approve ──▶ published                   published_at = now (if null)
pending_review ── reject  ──▶ rejected                    (no change)
published ── run update with changed title/start/end/all_day/location/status ──▶ changed_at = now
```

## Feed (derived, not stored)

| Attribute | Value |
|---|---|
| kind | `all`, or one category id from `data/categories.yaml` |
| path | `/feeds/all.xml` or `/feeds/<category-id>.xml` |
| title | `NETechConnect: all events` or `NETechConnect: <category label>` |
| id | `tag:netechconnect.com,2026:feed/all` or `…:feed/<category-id>` |
| updated | newest entry `updated`; `2026-11-01T00:00:00Z` when empty |
| entries | public (`is_public`), upcoming (`now < end or start`) events — for a category feed, those whose `categories` include it — sorted by entry `published` desc then event id; first 100 |

## Feed entry (derived, not stored)

| Atom element | Source |
|---|---|
| `id` | `tag:netechconnect.com,2026:event/<event.id>` |
| `title` (text) | `event.title`, prefixed `Cancelled: ` when `status == "cancelled"` |
| `published` | `published_at` or else `first_seen` |
| `updated` | the latest of `published` and `changed_at` |
| `link rel="alternate"` | `event.original_url` (the organizer's page; primary link) |
| `link rel="related"` | `https://<site_domain>/events/<slug>/` |
| `author/name` | organizer name (same rule as the site: organizer, else first source name); omitted if none, the feed-level author `NETechConnect` then applies |
| `category` (term, label) | each of the event's category ids with its label |
| `summary` (text) | `<when> · <where>` line, then `Organizer: <name>` if known, then a blank line and `event.summary` — the same strings the event card shows (`_view`'s `when`, `where`) |

No other event data (listings, sources, inferred fields, verification dates) appears in feeds.
