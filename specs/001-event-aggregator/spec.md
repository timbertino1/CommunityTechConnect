# Feature Specification: Nebraska Tech Event Aggregator

**Feature Branch**: `001-event-aggregator`

**Created**: 2026-10-16

**Status**: Draft (clarifications resolved 2026-10-16)

**Input**: User description: "Automatically discover community tech events across Nebraska (with Omaha and Lincoln as the focus) and show upcoming and past events in a list view and a calendar view, with each event linking to its original event page. Examples of Categories of tech events should include but not limited to networking coding programming information security AI etc."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Browse upcoming tech events in a list (Priority: P1)

A member of the Nebraska tech community visits NETechConnect to find out what is happening
soon. They see a chronological list of upcoming community tech events that were discovered
automatically from public event sources. Each entry shows the essentials (title, date and time,
location or "Online", organizer, categories) and a clear link that takes them to the event's
original page, where they can read full details and register.

**Why this priority**: This is the core value of the product — one place to see what is coming
up, with a path to the real event page. Without it, nothing else matters.

**Independent Test**: With discovery running against a set of known sources, open the site and
confirm upcoming events appear in date order, each with its essentials and a working link to
the original event page.

**Acceptance Scenarios**:

1. **Given** discovery has found upcoming events, **When** a visitor opens the site, **Then**
   they see upcoming events sorted soonest first, each showing title, date/time in Central Time,
   location (or "Online"), organizer, and categories.
2. **Given** a visitor is viewing an event, **When** they select its link, **Then** they are
   taken to the original event page on the organizer's or host platform's site.
3. **Given** a new event is published on a monitored source, **When** the next discovery cycle
   completes, **Then** the event appears in the list without any manual action.
4. **Given** the same event is listed on two different sources, **When** a visitor views the
   list, **Then** the event appears only once.
5. **Given** there are no upcoming events matching the current view, **When** the visitor
   opens it, **Then** they see a clear "no events found" message rather than an empty page.

---

### User Story 2 - Automatically find events from groups the system doesn't know yet (Priority: P2)

A core promise of NETechConnect is that it finds tech events on its own, so the site owner does
not have to track down groups and figure out where they post events. On a regular schedule, the
system goes looking for events and groups it has never seen before, across many kinds of public
places — not just event platforms: organization and company websites, universities and their
departments, libraries, coworking spaces and incubators, professional associations, conference
websites, web search results, local tech newsletters and mailing lists, local tech news and
blogs, and links from pages of organizers, sponsors, venues, and speakers it already knows. When
it finds a relevant new group or event, it adds it automatically (on probation) and keeps
collecting from it from then on. It also notices when coverage may be slipping — for example,
a group that normally meets monthly with nothing upcoming — and goes looking for where that
group now posts.

**Why this priority**: This is what makes the service comprehensive and keeps it from becoming
manual work for the owner. The list view (P1) can be demonstrated with a starting set of
sources, but the product's value depends on this capability.

**Independent Test**: Start with a small set of known sources. Run the discovery cycle and
confirm it finds relevant Nebraska tech groups and events that were not in the starting set,
from at least three different kinds of channels (e.g., an event platform, an organization
website, and a newsletter), adds them on probation, and does not add irrelevant or out-of-state
groups.

**Acceptance Scenarios**:

1. **Given** a Nebraska tech meetup group exists on a public event platform but is not yet a
   source, **When** the next discovery cycle runs, **Then** it is added as a probationary source
   and its events are collected.
2. **Given** a Nebraska organization's own website lists tech events but is not on any event
   platform, **When** discovery finds the site through search or a link, **Then** the site is
   added as a probationary source and its events are collected.
3. **Given** a local tech newsletter received by the system mentions an event the system does not
   know, **When** the newsletter is processed, **Then** the event is identified, its original
   event page is located, and the event and its host are added for review.
4. **Given** a known event lists a co-host, sponsor, or venue organization that is not yet a
   source, **When** discovery runs, **Then** that organization is evaluated as a candidate source.
5. **Given** a candidate whose events are mostly non-tech or outside Nebraska, **When** discovery
   evaluates it, **Then** it is not added.
6. **Given** a group that usually holds monthly events has had no upcoming event for two
   expected cycles, **When** discovery runs, **Then** the group is flagged as possibly moved and
   the system searches for its new event location.
7. **Given** an annual conference's past edition is known, **When** next year's edition is
   announced publicly, **Then** discovery finds it.
8. **Given** a probationary source has had several of its events approved and none rejected,
   **When** it reaches the promotion threshold, **Then** it becomes trusted automatically and its
   future events publish without review.

---

### User Story 3 - View events on a calendar (Priority: P3)

A visitor wants to see how events are spread across the month to plan their schedule. They
switch to a calendar view that shows events on the days they occur and can move between months
and weeks. Selecting an event shows its essentials and the link to the original event page.

**Why this priority**: The calendar is the second explicitly requested way to browse and helps
people plan, but the list alone already lets people find events.

**Independent Test**: Switch to the calendar view and confirm events appear on the correct
days, navigation between periods works, and each event links to its original page.

**Acceptance Scenarios**:

1. **Given** events exist in the current month, **When** a visitor opens the calendar view,
   **Then** each event appears on the correct day based on its Central Time start.
2. **Given** a visitor is on the calendar, **When** they navigate to the next or previous month
   or week, **Then** the events for that period are shown.
3. **Given** a multi-day event (e.g., a two-day conference), **When** it is shown on the
   calendar, **Then** it appears across each day it spans.
4. **Given** a visitor selects an event on the calendar, **When** its summary opens, **Then** it
   includes the link to the original event page.

---

### User Story 4 - Filter events by location and category (Priority: P4)

A visitor only cares about events near them or about a certain topic, such as information
security in Lincoln. They filter the list or calendar by location (Omaha, Lincoln, Other
Nebraska, Online) and by one or more categories (e.g., AI, information security, programming,
networking) and see only matching events.

**Why this priority**: Filtering makes a growing list useful, but the product works without it
when event volume is modest.

**Independent Test**: Apply each location and category filter and confirm only matching events
are shown in both the list and calendar views.

**Acceptance Scenarios**:

1. **Given** events in several locations, **When** a visitor filters to "Lincoln", **Then** only
   Lincoln-area events are shown.
2. **Given** events in several categories, **When** a visitor selects "Information Security"
   and "AI & Machine Learning", **Then** events in either category are shown.
3. **Given** filters are applied, **When** the visitor switches between list and calendar views,
   **Then** the same filters remain applied.
4. **Given** a visitor has applied filters, **When** they share or bookmark the page address,
   **Then** opening that address shows the same filtered view.

---

### User Story 5 - Browse past events (Priority: P5)

A visitor wants to see what happened recently — to find a group's past talks, see how active a
meetup is, or locate a recording. They switch to past events and browse them most recent first,
with the same filters and links to the original event pages.

**Why this priority**: Past events are explicitly in scope and add archival value, but upcoming
events are the primary need.

**Independent Test**: After events pass their end time, confirm they move from upcoming to past,
remain viewable in list and calendar views, and still link to the original page.

**Acceptance Scenarios**:

1. **Given** an event's end time has passed, **When** a visitor views upcoming events, **Then**
   that event no longer appears there, and it appears under past events.
2. **Given** a visitor views past events, **When** the list loads, **Then** events are sorted
   most recent first and remain filterable by location and category.
3. **Given** a past event's original page no longer exists, **When** a visitor views it,
   **Then** the listing indicates the original page may no longer be available.

---

### User Story 6 - Administrator manages event sources and data quality (Priority: P6)

A site administrator keeps discovery accurate. They add, pause, or remove event sources; see
whether each source is working (last successful check, events found, errors); and hide events
that are not community tech events or were misclassified.

**Why this priority**: Needed to keep the service accurate over time, but the initial set of
sources can be configured before launch without a management interface.

**Independent Test**: Sign in as an administrator, add a new source, confirm its events are
discovered on the next cycle, then hide one event and confirm it disappears from public views.

**Acceptance Scenarios**:

1. **Given** an administrator signs in with multi-factor authentication, **When** they open the
   source list, **Then** they see each source's status, trust level, last successful check, and
   recent errors.
2. **Given** events from probationary sources are awaiting review, **When** the administrator
   opens the review queue, **Then** they can approve or reject each event in a single action,
   and the queue shows why each item is held.
3. **Given** an administrator adds a new source, **When** the next discovery cycle runs,
   **Then** events from that source are discovered and listed.
4. **Given** an administrator hides an event, **When** a visitor loads any public view, **Then**
   the event does not appear, and the action is recorded in an audit log.
5. **Given** someone who is not an administrator, **When** they try to reach an administrative
   function, **Then** access is denied.

---

### User Story 7 - Visitor suggests an event source (Priority: P7)

A visitor knows of a Nebraska tech group that is missing. They use a short suggestion form to
submit the group's public event page address and an optional note. The suggestion is checked
automatically; if it looks relevant it is added on probation like any other discovered source,
otherwise it waits for administrator review.

**Why this priority**: Helps fill coverage gaps that automatic discovery misses, but is not
required for the core experience.

**Independent Test**: Submit a valid suggestion and confirm it becomes a probationary source or
enters the review queue; submit many suggestions rapidly and confirm they are rate limited.

**Acceptance Scenarios**:

1. **Given** a visitor submits the public event page of a Nebraska tech group, **When** the
   suggestion is evaluated, **Then** it is added as a probationary source or placed in the
   review queue, and the visitor sees a confirmation.
2. **Given** a visitor submits an address that is not a public web page, points to a private or
   internal network location, or is clearly unrelated, **When** it is evaluated, **Then** it is
   rejected without being fetched and the visitor sees a neutral message.
3. **Given** the same visitor or automated client submits many suggestions in a short time,
   **When** the limit is exceeded, **Then** further submissions are refused for a period.
4. **Given** a visitor submits a suggestion, **When** it is stored, **Then** no personal
   information is required, and nothing beyond the address and optional note is kept.

---

### Edge Cases

- An event is cancelled or removed at its source: the listing is marked cancelled (or removed
  from upcoming) after the next discovery cycle rather than shown as active.
- An event's date, time, or location changes at the source: the listing reflects the change after
  the next discovery cycle.
- A source is unreachable, slow, or returns malformed data: other sources and the public site
  continue working; previously discovered events from that source remain, marked with their
  last-verified time, and the failure is visible to administrators.
- A source returns content containing scripts, markup, or links to unsafe locations: the content
  is neutralized and never executed or rendered as active content.
- An event has no clear location, or a location just outside Nebraska (e.g., Council Bluffs,
  IA): it is included only if hosted by a Nebraska-based group or explicitly targeting
  Nebraska; otherwise excluded.
- An online-only event: included when hosted by a Nebraska-based group or targeting a Nebraska
  audience, and labeled "Online".
- An event crosses midnight or spans multiple days: it appears on every day it covers in the
  calendar and stays "upcoming" until it ends.
- An event's source time zone differs from Central Time or is missing: times are converted to
  Central Time; if the zone is missing, Central Time is assumed and the assumption is recorded.
- A recurring event series (e.g., a monthly meetup): each occurrence is listed as its own event
  linked to its own page where one exists.
- An event that is not tech-related or is a purely commercial sales pitch is found on a general
  source: it is excluded or hidden from public views.
- Daylight saving time transitions: event times remain correct across the change.
- An event is found in a newsletter, news article, or search result rather than on its own
  page: the system looks for the event's original page; if none can be found, the event is not
  published (it may be held for review with the place it was mentioned).
- The same new event is found through several channels at once (e.g., a newsletter and a
  search result): it is recorded once, with each place it was found noted.
- A discovered website forbids automated access in its access rules or terms: it is not
  collected from, and is recorded so it is not re-evaluated repeatedly.

## Clarifications

### Session 2026-10-16

- Q: Can the public suggest sources or submit events? → A: Visitors can suggest event sources
  (reviewed/evaluated before use); individual event submissions are not accepted.
- Q: Are discovered events published automatically or held for approval? → A: Events from
  trusted sources publish automatically; events from new/probationary sources are held for
  review until the source earns trust.
- Discovery of sources MUST itself be automatic so the site owner has no routine manual work.
- Finding events from groups the system doesn't already know is a core capability (raised to
  P2): it must search well beyond event platforms — organization websites, web search,
  newsletters, news/blogs, and links from known pages — and detect coverage gaps on its own.
  The owner may occasionally add sources by hand but must not need to.

## Requirements *(mandatory)*

### Functional Requirements

**Discovery**

- **FR-001**: System MUST automatically discover community tech events from a configured set of
  public event sources on a recurring schedule, with no manual entry required per event.
- **FR-002**: System MUST check each active source at least once every 24 hours.
- **FR-003**: System MUST include events held in Nebraska, and online events hosted by
  Nebraska-based groups or explicitly targeting a Nebraska audience, and MUST exclude other
  events.
- **FR-004**: System MUST prioritize coverage of the Omaha and Lincoln metro areas while still
  including events elsewhere in Nebraska.
- **FR-005**: System MUST exclude events that are not technology-focused, and purely commercial
  sales events, from public views.
- **FR-006**: System MUST detect when the same event appears on multiple sources and display it
  once.
- **FR-007**: System MUST update an event's details when they change at the source, and MUST
  mark events as cancelled or unverified when the source indicates cancellation or no longer
  lists them.
- **FR-008**: System MUST continue discovering from all other sources when any single source
  fails, and MUST record each failure for administrators.
- **FR-009**: System MUST respect each source's published access rules and terms of use, and
  MUST limit how often it requests content from each source.
- **FR-010**: System MUST, on a recurring schedule (at least weekly) and without administrator
  action, look for events and groups it does not already know about. Identifying, evaluating,
  and adding candidates MUST be fully automatic; administrators only approve or reject held
  items.
- **FR-011**: Discovery of unknown groups and events MUST use multiple kinds of public channels,
  including at least: public event platforms; organization and company websites (including
  universities and departments, libraries, coworking spaces, incubators, professional
  associations, and conference websites); web search; local tech newsletters and mailing lists
  the system subscribes to; local tech news and blogs; and links from pages of known organizers,
  sponsors, venues, and speakers. Public community announcement channels MAY be used only where
  their terms allow automated access.
- **FR-012**: System MUST automatically detect standard event information and calendar feeds
  published on discovered websites, so that a new website can become a source without
  hand-written setup for that site whenever such information is available.
- **FR-013**: System MUST detect likely coverage gaps — recurring groups with no upcoming event
  when one is expected, annual events whose next edition is not yet listed, and known Nebraska
  tech groups or organizations with no working source — and MUST automatically search for the
  missing information.
- **FR-014**: An event found only as a mention (in a newsletter, article, or search result) MUST
  NOT be published until its original event page is identified, so that every listing links to
  the organizer's page.
- **FR-015**: System MUST evaluate each candidate source for relevance (technology focus and
  Nebraska connection) and MUST add relevant candidates automatically as probationary sources;
  irrelevant candidates MUST NOT be added and MUST NOT be re-evaluated more than once per month.
- **FR-016**: Every source MUST have a trust level: trusted or probationary. Sources configured
  before launch or added by an administrator start as trusted; automatically discovered and
  visitor-suggested sources start as probationary.
- **FR-017**: Events from trusted sources MUST be published automatically when discovered.
  Events from probationary sources MUST be held for administrator review before appearing
  publicly.
- **FR-018**: A probationary source MUST be promoted to trusted automatically once at least 3 of
  its events have been approved and none rejected; a source with rejected events MUST stay
  probationary, and a source with a majority of its reviewed events rejected MUST be paused
  automatically.
- **FR-019**: Administrators MUST be able to hide any published event, including events from
  trusted sources, and to demote a trusted source to probationary.
- **FR-020**: Visitors MUST be able to suggest a new event source by submitting a public web
  address and an optional note, without creating an account or providing personal information.
  The optional note is used only for automatic evaluation and is never published or stored in
  the public repository.
- **FR-021**: Suggested sources MUST be evaluated automatically like any other candidate; those
  passing evaluation become probationary sources, and those that cannot be evaluated
  automatically go to the administrator review queue.
- **FR-022**: Source suggestions MUST be rate limited per visitor, protected against automated
  abuse, and validated so that only public web addresses are accepted; addresses pointing to
  private, internal, or non-web locations MUST be rejected without being fetched.
- **FR-023**: Visitors MUST NOT be able to submit individual events; events come only from
  sources.

**Event information**

- **FR-024**: Each event MUST display title, start date and time, end date and time (when
  provided), location (venue and city) or "Online", organizer or group name, categories, a short
  description, and the source it was found on.
- **FR-025**: Each event MUST include a link to its original event page, and that link MUST be
  the primary way for visitors to get full details and register.
- **FR-026**: System MUST NOT create calendar invites or calendar files, send reminders, or
  handle registration, RSVP, ticketing, or payment for any event.
- **FR-027**: Event times MUST be displayed in Central Time (America/Chicago) and labeled as such.
- **FR-028**: Each event MUST be assigned one or more categories from a defined list that
  includes at least: AI & Machine Learning; Information Security / Cybersecurity; Software
  Development & Programming; Computer Networking & Infrastructure; Cloud & DevOps; Data &
  Analytics; Web & Mobile; Product, Design & UX; Career & Professional Networking; Hardware, IoT
  & Makers; and General Tech. The list MUST be extendable by administrators.
- **FR-029**: Categories, locations, or other details inferred by the system (rather than stated
  by the source) MUST be distinguishable from source-provided details.
- **FR-030**: Each event MUST record when it was last verified against its source.
- **FR-031**: Descriptions shown on NETechConnect MUST be limited to a short summary (no more than
  roughly 500 characters), with the full description left on the original event page.

**Browsing**

- **FR-032**: Visitors MUST be able to view upcoming events as a list sorted soonest first.
- **FR-033**: Visitors MUST be able to view events in a calendar with month and week views and
  navigate between periods.
- **FR-034**: Visitors MUST be able to switch between upcoming and past events in both views;
  past events are sorted most recent first in the list view.
- **FR-035**: An event MUST be treated as upcoming until its end time (or its start time when no
  end time is provided) has passed.
- **FR-036**: Visitors MUST be able to filter by location (Omaha area, Lincoln area, Other
  Nebraska, Online), by one or more categories, and by date range, in both views.
- **FR-037**: Visitors MUST be able to search events by keyword across title, organizer, and
  description.
- **FR-038**: The current view and filters MUST be reflected in the page address so it can be
  bookmarked or shared.
- **FR-039**: Visitors MUST NOT need an account or provide any personal information to browse.
- **FR-040**: Past events MUST be retained and remain viewable as a historical archive.

**Administration and security**

- **FR-041**: Administrators MUST sign in with multi-factor authentication to reach any
  administrative function; all other users MUST be denied access.
- **FR-042**: Administrators MUST be able to add, edit, pause, and remove event sources, and see
  each source's status, trust level, how it was found (pre-configured, discovered, suggested),
  last successful check, number of events found, and recent errors.
- **FR-043**: Administrators MUST have a single review queue showing held events and
  unevaluated source suggestions, with the reason each item is held, and MUST be able to approve
  or reject each item in one action.
- **FR-044**: System MUST send administrators a periodic summary (at most daily, and only when
  something needs attention) of items awaiting review and of sources that are failing, so that
  no routine monitoring is required.
- **FR-045**: Administrators MUST be able to hide or unhide an event and correct its categories
  or location.
- **FR-046**: Every administrative action MUST be recorded in an audit log showing who did what
  and when.
- **FR-047**: All content obtained from sources MUST be treated as untrusted and neutralized
  before display, so that no source can cause scripts or active content to run in a visitor's
  browser.
- **FR-048**: Links to original event pages MUST use only safe web addresses (secure web links);
  any other kind of link MUST be discarded.
- **FR-049**: The public site and administrative functions MUST be served only over encrypted
  connections.

**Accessibility**

- **FR-050**: List and calendar views MUST meet WCAG 2.2 Level AA, including full keyboard
  operation and screen-reader support for the calendar.
- **FR-051**: All public views MUST be usable on mobile phones as well as desktop browsers.
- **FR-052** *(owner decision, 2026-10-23)*: The site MUST NOT show what an event costs, on any
  view or in its public data: the organizer's own page, which every event links to, is the source
  of truth. (A "Free" label on some events would suggest the others cost money.)

### Key Entities

- **Event**: A single community tech event occurrence. Attributes: title, start and end time,
  source time zone, venue and city or online indicator, location area (Omaha, Lincoln, Other
  Nebraska, Online), organizer, short description, categories, original event page link,
  status (scheduled, cancelled, unverified), review state (published, pending review,
  rejected), visibility (shown or hidden), first discovered
  time, last verified time, and which details were inferred versus source-provided.
- **Event Source**: A public place events are discovered from (e.g., an event platform group,
  an organization's events page, a published event feed). Attributes: name, address, status
  (active or paused), trust level (trusted or probationary), origin (pre-configured, discovered,
  or suggested), approved and rejected event counts, check frequency, last successful check,
  recent errors, events found.
- **Candidate Source**: A possible source found by automatic source discovery or a visitor
  suggestion, with its evaluation result (added, rejected, needs review) and when it was last
  evaluated.
- **Review Item**: An event or source suggestion awaiting administrator decision, with the
  reason it is held and the eventual decision.
- **Source Listing**: The record of one event as it appears on one source; multiple listings can
  be merged into one Event. Links an Event to the Event Source(s) it was found on.
- **Organizer**: The group or organization hosting events (e.g., a meetup group or user group).
  Attributes: name, home city, link to its page.
- **Category**: A topic label for events (e.g., AI & Machine Learning, Information Security).
  An event has one or more categories.
- **Administrator**: A person permitted to manage sources and event visibility. Attributes:
  identity, multi-factor enrollment, role.
- **Audit Log Entry**: A record of an administrative action: who, what, when, and which item.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A first-time visitor can find the next upcoming tech event in their chosen city and
  reach its original event page within 30 seconds.
- **SC-002**: In a quarterly coverage check, at least 85% of Nebraska community tech events in an
  independently compiled sample (found by hand from sources not given to the system) already
  appear on NETechConnect, and at least 95% for Omaha and Lincoln groups the system monitors.
- **SC-003**: New or changed events from trusted sources are reflected on NETechConnect within
  24 hours; events held for review appear in the review queue within 24 hours.
- **SC-004**: Fewer than 2% of displayed events are duplicates, and fewer than 5% are
  misclassified or out of scope, measured by monthly spot check.
- **SC-005**: 100% of displayed events include a working link to their original event page at
  the time of their last verification.
- **SC-006**: Event lists and calendar views appear within 2 seconds for 95% of visits on a
  typical broadband or 4G connection.
- **SC-007**: A failure of any single source causes no outage of the public site and no loss of
  events from other sources.
- **SC-008**: A security review before launch (the builder's review of every item in the plan's
  threat summary, with the automated security checks) finds no critical or high-severity
  vulnerabilities, and no scripted content from any source can execute in visitors' browsers.
  *Changed 2026-10-25 by the owner: an independent review is no longer required. The site has
  no user accounts, logins or personal data; its only public input is the suggest form.*
- **SC-009**: An automated and manual accessibility audit of list and calendar views finds no
  WCAG 2.2 AA failures.
- **SC-010**: Ongoing administration (reviewing held items and responding to failing sources)
  takes no more than 15 minutes per week on average after the first month of operation.
- **SC-011**: Within 60 days of launch, automatic discovery adds at least 10 relevant Nebraska
  groups or organizations that were not in the initial source list, from at least 3 different
  kinds of channels, with no manual source research by the owner.

## Assumptions

- The audience is the general public interested in Nebraska technology events; no accounts are
  needed to browse.
- An initial set of sources (e.g., public event platform groups for Omaha and Lincoln tech
  meetups, university and user group event pages, and published event feeds) is identified and
  configured before launch.
- "Networking" in the request covers both computer networking topics and professional networking
  events for the tech community; these are separate categories.
- Omaha area includes surrounding Nebraska communities (e.g., Bellevue, Papillion, La Vista,
  Elkhorn); Lincoln area includes surrounding communities. Events across the river in Council
  Bluffs, IA are excluded unless hosted by a Nebraska-based group.
- Free and paid community events (e.g., paid regional conferences) are both in scope; vendor
  product pitches and sales webinars are not.
- Discovery uses only publicly available information and does not require logging into sources
  on behalf of users. Automatic discovery relies on public search features of event platforms, web
  search, newsletter subscriptions, and public websites; which specific services and methods are
  used is decided during planning, and some channels may be ruled out by their terms of use.
- "Launch" means the public announcement of NETechConnect (sharing it with the community and
  pointing the custom domain at it). Before launch the site may run unannounced at its default
  hosting address for testing.
- The site owner is the only administrator at launch and wants near-zero routine effort; the
  review queue and summary exist so attention is needed only when something is held or broken.
- Past events are kept indefinitely unless an administrator removes them.
- English-language event listings only for this feature.
- Calendar export, reminders, and registration are permanently out of scope per the project
  constitution (aggregator, not organizer).
