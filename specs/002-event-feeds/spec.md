# Feature Specification: Event Feeds

**Feature Branch**: `002-event-feeds`

**Created**: 2026-11-07

**Status**: Draft

**Input**: User description: "Event feeds: publish Atom/RSS feeds so people can follow new NETechConnect events in a feed reader, Outlook, Slack/Teams, or a feed-to-email service of their choice. One feed for all events (/feeds/all.xml) and one feed per category (one for each of the 11 categories in data/categories.yaml, e.g. /feeds/ai-ml.xml). No per-area/city feeds for now. Each entry carries only what a listing card already shows (title, date/time in Central time, place, organizer, short plain-text description, link to the organizer's original event page as the primary link, plus the NETechConnect event page). Feeds are static files rebuilt on every site build; no sign-up, no forms, no Workers, no storage, and no personal data of any kind. Feed text from sources must be escaped as plain text (no HTML) so source content cannot inject markup into readers. Make feeds discoverable: a "Follow" / feed link per category on the site and an autodiscovery link tag. Constitution Principle II bans calendar subscriptions and reminders; feeds are not calendar subscriptions, so the constitution needs a one-line clarification that new-event feeds are allowed while iCal/calendar subscriptions remain banned. Owner wants this low-risk, near-zero admin."

## Context

NETechConnect (feature 001) lists Nebraska tech events on a static site. Visitors asked, through
the owner, for a way to hear about new events without checking the site. The owner wants this
with **no personal data**: the site must never collect, store or process anyone's email address
or other identifying details. A web feed meets that: the visitor's own app (feed reader, Outlook,
Slack, Teams, or a feed-to-email service they choose) fetches a public file and tells them what
is new. Any sign-up happens with that app, never with NETechConnect.

Email alerts sent by NETechConnect itself, per-area feeds, and calendar subscriptions are out of
scope (see Out of Scope).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Follow every new event (Priority: P1)

A local tech worker wants to know whenever a new Nebraska tech event is listed. They copy the
"all events" feed address from the site into their feed reader (or Outlook's RSS folder). From
then on, each event that appears on the site shows up in their reader as a new item with its
title, date and time, place, organizer and a short description. Opening the item takes them to
the organizer's event page.

**Why this priority**: This is the whole feature in its simplest form, useful on its own, and
the base the category feeds reuse.

**Independent Test**: Add the all-events feed to a standard feed reader, publish a new event
(through a normal discovery run or an approved review item), rebuild the site, refresh the
reader: the new event appears once, with correct details and a working link to the original page.

**Acceptance Scenarios**:

1. **Given** the site is built with published upcoming events, **When** a feed reader fetches
   the all-events feed, **Then** it shows one item per published upcoming event, newest-listed
   first, each with title, date and time (Central), place (or "Online"), organizer, short
   description, and a link to the organizer's original event page.
2. **Given** a reader already showed an event, **When** the site is rebuilt and nothing about
   that event changed, **Then** the reader does not show it as new again.
3. **Given** a new event is published on the site, **When** the site is next built, **Then** the
   event appears in the all-events feed in the same build that puts it on the site.
4. **Given** an event is held for review, hidden by the administrator, or rejected, **When** the
   site is built, **Then** it does not appear in any feed.

---

### User Story 2 - Follow one topic only (Priority: P2)

A security engineer only cares about security events. On the site they find the list of feeds,
copy the "Security" feed address, and add it to a Slack channel for their user group. The channel
gets a message for each new security-tagged event and nothing else.

**Why this priority**: Category feeds make the feature useful to groups and specialists who
don't want every event, but they depend on P1's entry format.

**Independent Test**: Subscribe to one category feed; publish one event in that category and one
outside it; after the rebuild, only the first appears in that feed, and both appear in the
all-events feed.

**Acceptance Scenarios**:

1. **Given** the site's 11 categories, **When** the site is built, **Then** there is one feed per
   category, each containing exactly the published upcoming events tagged with that category.
2. **Given** an event tagged with two categories, **When** the site is built, **Then** it appears
   in both category feeds and once in the all-events feed.
3. **Given** a category with no upcoming events, **When** a reader fetches its feed, **Then** the
   feed is valid and simply has no items.

---

### User Story 3 - Find the feeds without knowing what a feed is (Priority: P3)

A visitor who has never used a feed reader sees a "Follow" link, lands on a short page that
explains in plain words what a feed is and lists every feed (all events, then each category)
with an address they can copy, plus two or three examples of where to paste it (a feed reader,
Outlook, Slack/Teams, or an email service that turns feeds into emails). Browsers and feed
readers that look for a site's feed find the all-events feed automatically from any page.

**Why this priority**: The feeds work without this page for people who already know feeds; the
page widens the audience.

**Independent Test**: From the home page, reach the feeds page in one step, copy a category
feed address, and paste it into a feed reader; separately, give a feed reader just the site's
home page address and confirm it finds the all-events feed.

**Acceptance Scenarios**:

1. **Given** any page of the site, **When** a visitor uses the "Follow" link, **Then** they reach
   the feeds page listing the all-events feed and all 11 category feeds by category name.
2. **Given** a feed reader is given the site's home page address, **When** it looks for feeds,
   **Then** it finds the all-events feed.
3. **Given** the feeds page, **When** it is read with a screen reader or on a 320 px wide phone,
   **Then** every feed address can be reached and copied, and the page meets the same
   accessibility standard as the rest of the site.

---

### Edge Cases

- **Event details change** (new time, place or title): the existing item is updated in place
  (same identity, newer "updated" time); it is not added as a second item.
- **Event cancelled**: the item stays while the event would still be upcoming, its title is
  marked "Cancelled", and its "updated" time changes, so followers learn of it.
- **Event passes**: it drops out of the feeds after it ends (feeds list upcoming events only);
  readers keep what they already showed.
- **Event hidden or removed by the administrator after appearing**: it drops out of every feed
  at the next build.
- **Many events at once** (e.g. a big source added): each feed lists at most a fixed number of
  the most recently listed upcoming events (default 100), so files stay small.
- **Hostile text from a source** (markup, script, control characters, very long text): appears
  in readers as harmless plain text, never as formatting or active content; long text is cut
  to the same length the site uses.
- **Category added or renamed later** by the administrator: the next build creates its feed;
  a removed category's feed is no longer published.
- **Online events**: place reads "Online"; no fake address.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The site MUST publish one all-events feed and one feed per event category (one for
  each category the site defines; 11 today), at stable addresses that do not change between
  builds.
- **FR-002**: Each feed MUST contain only events that are public on the site (published and not
  hidden) and upcoming (not yet ended), at most 100 items, ordered newest-listed first.
- **FR-003**: Each item MUST contain only what an event card already shows: title, start (and
  end when known) in Central time, place or "Online", organizer name when known, the short
  summary, the event's categories, a primary link to the organizer's original event page, and a
  link to the event's NETechConnect page.
- **FR-004**: Each item MUST keep the same identity across builds, so readers show an event
  once; a change to the event's details MUST update the item's "updated" time rather than create
  a new item.
- **FR-005**: A cancelled event MUST stay in the feeds while upcoming, with "Cancelled" in its
  title.
- **FR-006**: All text taken from event sources MUST be delivered as plain text, never as markup:
  no source-provided HTML, scripts, styles, images or embedded content may reach a reader, and
  the result MUST be a well-formed feed for any input text.
- **FR-007**: Feeds MUST be generated as part of every normal site build, from the same data as
  the site's pages, with no extra service, storage, scheduled job, or administrator step.
- **FR-008**: The feature MUST NOT collect, store, log or process any personal data: no sign-up,
  form, subscriber list, cookies, tracking parameters in links, or per-reader content. Every
  reader receives the same file.
- **FR-009**: Feeds MUST validate against the feed format's standard and open in widely used
  feed readers, classic Outlook's RSS feature, and Slack's feed integration.
- **FR-010**: Every page of the site MUST advertise the all-events feed for automatic discovery
  by browsers and feed readers.
- **FR-011**: The site MUST have a feeds page, reachable in one step from every page (a "Follow"
  link), that explains feeds in plain language, lists every feed by name with a copyable
  address, and names a few ways to use them (feed reader, Outlook, Slack/Teams, a feed-to-email
  service of the visitor's choice) without endorsing a specific commercial service.
- **FR-012**: The feeds page MUST meet the site's existing accessibility standard (WCAG 2.2 AA,
  320 px width, light and dark themes) and its existing security headers and content policy.
- **FR-013**: Feed files MUST be served with the correct feed content type and the site's usual
  security headers, and MUST be cacheable by readers in the same way as the site's pages.
- **FR-014**: The project constitution MUST be clarified (Principle II) to state that read-only
  feeds of newly listed events are permitted, while calendar invites, iCal/.ics files, calendar
  subscriptions and reminders remain prohibited.

### Key Entities

- **Feed**: a public file listing events; one for all events and one per category. Has a title
  ("NETechConnect: all events", "NETechConnect: Security"), a stable address, and an updated
  time.
- **Feed item**: one event as it appears in a feed; a read-only view of an existing published
  event (no new event data is created). Has a stable identity tied to the event.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of published upcoming events appear in the all-events feed and in the feed of
  every category they are tagged with, within the same build that lists them on the site.
- **SC-002**: 0 items appear in any feed for events that are held, rejected, hidden or ended.
- **SC-003**: Every feed passes a standard feed validator with no errors on every build, including
  builds fed deliberately hostile event text (markup, scripts, control characters, overlong text).
- **SC-004**: A visitor can go from the home page to a copied feed address in under 1 minute and
  2 clicks or fewer.
- **SC-005**: The feature adds no personal data to the system: a review of the change finds no
  new input, storage, cookie, form or per-visitor behavior.
- **SC-006**: The feature adds 0 minutes of routine administration per month and no new
  running cost.
- **SC-007**: Refreshing a reader after a rebuild with no event changes shows 0 new items.

## Assumptions

- "Newest-listed first" means ordered by when the event first became public on the site; the
  plan decides how that time is derived from existing event data.
- Feeds list upcoming events only, matching the site's main list; past events stay on the site's
  past-events pages.
- 100 items per feed is enough for this site's volume (a handful of new events a week).
- Category names and order come from the site's existing category list; adding a category in
  that list is enough to add its feed.
- Feeds are free to fetch with no rate limits beyond the hosting provider's normal protection;
  reader polling is a negligible load on the free hosting plan.
- The format follows the widely used Atom standard; the plan confirms it and the exact addresses
  (for example `/feeds/all.xml`, `/feeds/<category>.xml`).
- Visitors who want email use a third-party feed-to-email service of their choice; that service's
  handling of their address is between them and that service.

## Out of Scope

- Email alerts sent by NETechConnect, subscriber lists, or any sign-up (owner decision
  2026-11-07: no personal data).
- Per-area or per-city feeds (owner: not now; can be added later the same way).
- Calendar invites, iCal/.ics files and calendar subscriptions (constitution Principle II).
- Feeds of past events, search results, or custom filter combinations.
- Analytics on who or how many follow the feeds.

## Dependencies

- Feature 001's site build, event data, categories and security headers.
- A constitution amendment (FR-014), made before or with the implementation, with the version
  bump and Sync Impact Report the constitution's governance section requires.
