# Tasks: Event Feeds

**Input**: Design documents from `specs/002-event-feeds/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/feeds.md, quickstart.md

**Tests**: Included. Constitution Principle VI requires test-first work; each test task MUST be
written and seen failing before the implementation task that satisfies it.

**Organization**: Tasks are grouped by user story so each story can be built and checked on its
own. Commands run from `discovery/` (`uv run pytest …`) or `web/` (`npx playwright test …`).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 (all-events feed), US2 (category feeds), US3 (finding the feeds)

## Path Conventions

Existing feature 001 layout: Python package `discovery/src/netc/`, tests `discovery/tests/`,
templates `discovery/src/netc/site/templates/`, static assets and browser tests `web/`.

---

## Phase 1: Setup (Constitution amendment — own PR, merged first)

**Purpose**: FR-014 / research R8. The code PRs are checked against the amended text.

- [X] T001 Amend `.specify/memory/constitution.md` to 1.1.1 (PATCH): add to Principle II the bullet "Read-only web feeds (e.g. Atom) of listed events are permitted: they carry only the listing summary and link each event to its original page. They are not calendar subscriptions." Leave the prohibition bullet unchanged; put the Sync Impact Report (version 1.1.0 → 1.1.1, rationale: clarification, no change in meaning; templates needing updates: none) in the PR description, as the 1.1.0 amendment did; set **Last Amended**. Open as its own PR (`docs/constitution-feeds`) and merge before T004.

**Checkpoint**: Constitution 1.1.1 on `main`.

---

## Phase 2: Foundational (event timestamps — own PR, blocks all stories)

**Purpose**: research R4, data-model.md "Event: new optional fields". Entry order and `updated`
for every feed depend on these. Merging this early lets live events start recording real times.

### Tests (write first, must fail)

- [X] T002 [P] Unit tests for the new Event fields in `discovery/tests/unit/test_event_timestamps.py`: `published_at` and `changed_at` are optional ("datetime (UTC) or null"), default null, and serialize as UTC `Z` strings; validator rejects `published_at` < `first_seen` and `changed_at` < `published_at` when both set; an event JSON with the fields passes `discovery/src/netc/schemas/event.schema.json`, and one with an unknown extra field still fails (`additionalProperties: false`).
- [X] T003 [P] Lifecycle/review/merge tests in `discovery/tests/unit/test_lifecycle_timestamps.py`: (a) new event from a trusted source → `published_at = now`; new probationary event → `published_at` null while `pending_review`; (b) approving a review item → `published_at = now` "(if null)", and a second approval/republish never moves it; (c) a run update changing any of `title`, `start`, `end`, `all_day`, `location`, `status` sets `changed_at = now`; (d) changes only to `summary`, `categories`, listings or `last_verified` keep `changed_at` unchanged; (e) dedupe merge "keeps the earliest `published_at` and the latest `changed_at`"; (f) `published_at` is "never changed afterward, including by later edits".

### Implementation

- [X] T004 Add `published_at: UtcDatetime | None = None` and `changed_at: UtcDatetime | None = None` to `Event` in `discovery/src/netc/models.py`, extending the existing `model_validator` with the ordering rules from T002.
- [X] T005 [P] Add both fields as nullable `date-time` strings to `discovery/src/netc/schemas/event.schema.json` and mirror them in `specs/001-event-aggregator/contracts/event.schema.json`; keep `additionalProperties: false`.
- [X] T006 Set `published_at = now` for events created as `published` and set/keep `changed_at` in `_update` (compare stored vs fresh `title`, `start`, `end`, `all_day`, `location`, `status`) in `discovery/src/netc/pipeline/lifecycle.py`.
- [X] T007 [P] Set `published_at = now` when an approval publishes an event and it is null, in `discovery/src/netc/pipeline/review.py` (where `state = "published"` is decided).
- [X] T008 [P] In `merge` in `discovery/src/netc/pipeline/dedupe.py`, keep the earliest non-null `published_at` and the latest non-null `changed_at`.
- [X] T009 Add the two fields to the Event table in `specs/001-event-aggregator/data-model.md` with a link to `specs/002-event-feeds/data-model.md`; run the full suite (`uv run pytest -q`, `ruff check --no-cache`, `mypy`) and `uv run netc validate-data --data ../data` on real data (existing events have null fields and stay valid). Open the timestamps PR with a security note (data-only fields, no new input).

**Checkpoint**: Timestamps PR merged and deployed; the next discovery runs record `published_at`/`changed_at`.

---

## Phase 3: User Story 1 - Follow every new event (Priority: P1) 🎯 MVP

**Goal**: `/feeds/all.xml` lists every public upcoming event per `contracts/feeds.md`.

**Independent Test**: Build the site; `feedparser` reads `all.xml` with `bozo == 0`; entries = the home page's upcoming events (≤ 100), newest-listed first, each linking to the organizer page; a second build with the same data gives identical bytes; quickstart §2–§3.

### Tests for User Story 1 (write first, must fail)

- [X] T010 [P] [US1] Unit tests for `discovery/src/netc/site/feeds.py` in `discovery/tests/unit/test_feeds.py`: entry fields per data-model.md "Feed entry" (id `tag:netechconnect.com,2026:event/<event id>`; title with `Cancelled: ` prefix when `status == "cancelled"`; `published` = `published_at` or else `first_seen`; `updated` = "the latest of `published` and `changed_at`"; first link `rel="alternate"` = `original_url`; `rel="related"` = `https://<site_domain>/events/<slug>/`; author omitted when no organizer; one `category` per event category with its label; summary = when · where line, `Organizer: <name>` line if known, blank line, event summary); feed `updated` = newest entry `updated`, or `2026-11-01T00:00:00Z` when empty; order `published` desc then event id; cap 100; identical input → identical bytes.
- [X] T011 [P] [US1] Contract tests in `discovery/tests/contract/test_feeds_contract.py` for `contracts/feeds.md` rules 1–10 on a built fixture site: parse with `feedparser` (`bozo == 0`), Atom namespace only, all text constructs `type="text"`, no `content` element, no query strings in any link, feed `id`/`title`/`self` link per the contract.
- [X] T012 [P] [US1] Security tests in `discovery/tests/security/test_feed_output.py` (marked `security`): event text containing `<script>`, `</summary><entry>`, `]]>`, `&amp;`-style entities, quotes, U+FFFE, and overlong text produces a well-formed feed where the text round-trips as literal plain text through `feedparser` and no element or attribute is injected; strings with XML-forbidden characters (bypassing model validation via `model_construct`) have them removed; held (`pending_review`), `rejected`, `hidden` and ended events never appear.
- [X] T013 [P] [US1] Integration test in `discovery/tests/integration/test_build_site_feeds.py`: `build_site` on the sample data writes `feeds/all.xml`; its entries match `data/upcoming.json`'s events (same ids, ≤ 100); two builds with different `now` but no event ending in between produce byte-identical `all.xml`; `_headers` in the output contains the `/feeds/*.xml` rule.

### Implementation for User Story 1

- [X] T014 [US1] Create `discovery/src/netc/site/feeds.py` with pure functions: `entry_for(event, view, site_domain)` and `atom_feed(feed_id, title, self_url, site_url, entries) -> bytes`, using `xml.etree.ElementTree` (no Jinja), `type="text"` on every text construct, an XML 1.0 character filter applied to every text value, `FEED_LIMIT = 100`, `EMPTY_FEED_UPDATED = 2026-11-01T00:00:00Z`, UTF-8 with XML declaration; reuse `_view`'s `when`/`where`/`organizer` strings so feeds match the cards.
- [X] T015 [US1] Wire `/feeds/all.xml` into `build_site` in `discovery/src/netc/site/build.py`: same `public`/`upcoming` lists and `organizer_of` as the pages, absolute links from `site_domain`, write with `atomic_write`; report the feed count in `BuildReport` if it has a suitable field (else leave it).
- [X] T016 [P] [US1] Add to `web/_headers` the block `/feeds/*.xml` → `Content-Type: application/atom+xml; charset=utf-8` (research R6); global `/*` security headers stay as they are.

**Checkpoint**: US1 works alone: `all.xml` valid, stable, and safe.

---

## Phase 4: User Story 2 - Follow one topic only (Priority: P2)

**Goal**: One feed per category in `data/categories.yaml`.

**Independent Test**: Build the site; there are 11 category feeds; an event tagged with two categories is in both and once in `all.xml`; an empty category's feed is valid with no entries.

### Tests for User Story 2 (write first, must fail)

- [X] T017 [P] [US2] Extend `discovery/tests/unit/test_feeds.py`: category feed `id` `tag:netechconnect.com,2026:feed/<category-id>`, title `NETechConnect: <category label>`, only events whose `categories` include it, a two-category event in both feeds, empty feed valid with `updated` `2026-11-01T00:00:00Z`.
- [X] T018 [P] [US2] Extend `discovery/tests/integration/test_build_site_feeds.py`: one `feeds/<id>.xml` per category in the sample `categories.yaml` and no others; adding a category to the sample data adds its feed; a stale feed file from a previous build in `out_dir` does not survive (`_prepare` clears the output).

### Implementation for User Story 2

- [X] T019 [US2] In `discovery/src/netc/site/build.py`, write one feed per category (in `categories.yaml` order) to `feeds/<category-id>.xml` with `feeds.atom_feed`, filtering `upcoming` by category.

**Checkpoint**: US1 and US2 both work; 12 feeds total on real data.

---

## Phase 5: User Story 3 - Find the feeds without knowing what a feed is (Priority: P3)

**Goal**: `/feeds/` page, footer **Follow** link, home "Follow new events" link, autodiscovery.

**Independent Test**: Home → Follow → `/feeds/` in ≤ 2 clicks; page lists 12 feeds; axe passes at 320/360/1280 in light and dark; a page's `<head>` advertises `/feeds/all.xml`.

### Tests for User Story 3 (write first, must fail)

- [X] T020 [P] [US3] Extend `discovery/tests/integration/test_build_site_feeds.py`: every generated HTML page has exactly one `<link rel="alternate" type="application/atom+xml" title="NETechConnect: all events" href="/feeds/all.xml">` and a footer link to `/feeds/`; `feeds/index.html` lists the all-events feed first then every category in `categories.yaml` order, each with its label and absolute address as a link, plus one `rel="alternate"` per category feed in its head; the home page has a "Follow new events" link to `/feeds/`.
- [X] T021 [P] [US3] Browser test `web/tests/feeds.spec.js`: from `/`, the footer **Follow** link reaches `/feeds/`; 12 feed links with addresses ending `.xml`; no horizontal scroll at 320 px; page works with JavaScript disabled.
- [X] T022 [P] [US3] Add `feeds: "/feeds/"` to the page list in `web/tests/a11y/pages.spec.js` so axe runs on it at all sizes and themes.

### Implementation for User Story 3

- [X] T023 [US3] Create `discovery/src/netc/site/templates/feeds.html` (extends `base.html`): title "Follow new events"; one plain-language paragraph on what a feed is and that no sign-up or email is collected; list of feeds (all events first, then categories) each as label + full address link; "Ways to use a feed": a feed reader, Slack (`/feed subscribe <address>`), classic Outlook (RSS Subscriptions), or a feed-to-email service of your choice — no named commercial service; `head` block adds one `rel="alternate"` per category feed.
- [X] T024 [US3] In `discovery/src/netc/site/build.py`, render `feeds/index.html` (`nav="feeds"`) with the feed list (label, absolute URL) and count it in `pages`.
- [X] T025 [P] [US3] In `discovery/src/netc/site/templates/base.html`, add the all-events autodiscovery `<link>` in `<head>` and a **Follow** item (with `aria-current` on `nav == "feeds"`) to the footer nav.
- [X] T026 [P] [US3] In `discovery/src/netc/site/templates/list.html`, add a "Follow new events" link to `/feeds/` near the upcoming-event count (home page only, not `/past/`).
- [X] T027 [P] [US3] In `web/css/site.css`, style the feeds list so long addresses wrap (`overflow-wrap: anywhere`) and match existing link and focus styles in both themes.

**Checkpoint**: All three stories work; feeds PR ready.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T028 [P] Add `/feeds/`, `/feeds/all.xml` and `/feeds/<category-id>.xml` rows to `specs/001-event-aggregator/contracts/site-urls.md`, pointing to `specs/002-event-feeds/contracts/feeds.md`.
- [X] T029 [P] Add a short "Feeds" section to `docs/admin-guide.md`: feeds rebuild with the site, nothing to administer; a category added in `data/categories.yaml` gets a feed automatically; overrides don't move an entry's `updated` time.
- [X] T030 Security pass on the feeds PR diff (memory: ongoing security review): confirm research R9 mitigations are each covered by a test, no new input/storage/cookie/form (SC-005), CSP/headers unchanged except the feeds content type; run `uv run pytest -q -m security`, `npm audit`, `pip-audit`; write what was checked in the PR description. Open the feeds PR (US1–US3 + T028–T029).
- [ ] T031 Checkpoint on live after deploy, per `specs/002-event-feeds/quickstart.md` §2–§4: W3C validator, `curl -sI` headers (record the actual content type; R6 deviation allowed), reader autodiscovery from the home page, Slack `/feed subscribe`, classic Outlook if the owner has it, then after a discovery run that publishes an event: exactly one new item. Record in `docs/checkpoints/feeds.md`.
- [ ] T032 Update the build log `docs/journey/build-log.html` with a Feeds tab/section (stats, checklist with PR numbers, notes) and republish the artifact https://claude.ai/artifact/XFAsLsB9NCfo6eCKFAvnbb.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (T001)**: none; merge first.
- **Phase 2 (T002–T009)**: after T001 merges; blocks Phases 3–5.
- **Phase 3 US1 (T010–T016)**: after Phase 2.
- **Phase 4 US2 (T017–T019)**: after T014 (uses `atom_feed`); can overlap US1's T015–T016.
- **Phase 5 US3 (T020–T027)**: after Phase 2; independent of US1/US2 code, but the page links to feeds US1/US2 create, so ship together in the feeds PR.
- **Phase 6**: T028–T030 after US1–US3; T031 after the feeds PR deploys; T032 after T031.

### User Story Dependencies

- US1: needs Phase 2 only.
- US2: reuses US1's `feeds.py`.
- US3: needs Phase 2 only to build; meaningful once US1/US2 exist.

### Within Each User Story

- Tests first and failing → `feeds.py`/templates → `build.py` wiring → headers/CSS.

### Parallel Opportunities

- T002 ‖ T003; T005 ‖ T007 ‖ T008 (after T004).
- T010 ‖ T011 ‖ T012 ‖ T013; then T016 alongside T014–T015.
- T017 ‖ T018.
- T020 ‖ T021 ‖ T022; T025 ‖ T026 ‖ T027 alongside T023–T024.
- T028 ‖ T029.

---

## Parallel Example: User Story 1

```text
Write together (all fail first):
  T010 discovery/tests/unit/test_feeds.py
  T011 discovery/tests/contract/test_feeds_contract.py
  T012 discovery/tests/security/test_feed_output.py
  T013 discovery/tests/integration/test_build_site_feeds.py
Then: T014 feeds.py → T015 build.py; T016 web/_headers in parallel.
```

---

## Implementation Strategy

### MVP first

1. T001 constitution PR → merge.
2. Phase 2 timestamps PR → merge, deploy (events start recording times).
3. US1 → `all.xml` alone is a usable MVP (anyone who knows feeds can follow everything).

### Incremental delivery

4. US2 category feeds and US3 page/links complete the feature; ship US1–US3 as one feeds PR so
   the Follow link never points at missing feeds.
5. Polish, live checkpoint, build log.

### PRs

| PR | Tasks |
|---|---|
| Constitution 1.1.1 | T001 |
| Event timestamps | T002–T009 |
| Feeds | T010–T030 |
| Checkpoint + build log | T031–T032 |
