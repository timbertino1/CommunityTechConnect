# Quarterly coverage check

Does NETechConnect find the events people would expect it to? Once a quarter, collect Nebraska
tech events **by hand, from places the system doesn't read**, and count how many are already on
the site (SC-002, `specs/001-event-aggregator/spec.md`; quickstart "Quarterly coverage check").

**Targets:**
- **At least 85%** of the hand-found events are on the site.
- **At least 95%** for Omaha and Lincoln groups the system already monitors (groups with a source
  in `data/sources/`).

About an hour a quarter. One file per quarter: `docs/coverage/<YYYY>-Q<n>.md`, starting with
`2027-Q1.md`. Copy the template at the end of this page for later quarters.

## When

In the first two weeks of January, April, July and October. Look at events from roughly the next
six weeks: far enough ahead that groups have posted them, near enough that they're real.

## 1. Collect at least 20 events by hand

Use places the system isn't configured to read. Good ones:
- **Ask people:** organizers at a meetup, the (NE)NUG or ISACA lists, a Slack or Discord you're in.
- **Campus pages** other than UNL Computing: UNO, Creighton, Bellevue University, the community colleges.
- **Library, coworking and chamber calendars:** Omaha Public Library, Lincoln City Libraries, Kiewit Luminarium, Nebraska Innovation Campus, Startup Collaborative.
- **Platforms, searched by hand:** Meetup and Luma searches for Omaha and Lincoln, Eventbrite's
  Nebraska tech listings, LinkedIn events.
- **Local news** event listings.

Don't use the site itself, its sources, or its review PRs, since those can only agree with it. Aim for a
mix: Omaha, Lincoln, the rest of Nebraska, online events by Nebraska groups, and both one-off
events and regular meetups.

For each event, note where you found it.

## 2. Check each one against the site

Search the site (the keyword box on the home page or calendar) and look at the calendar for its
date. Then mark it:
- **Yes:** it's on the site, with the right date and a link to the organizer's page.
- **No:** it isn't, or it's there with wrong details. Say which.
- **Monitored group?** Yes if its group already has a source in `data/sources/`. These count
  toward the 95% target.

Leave out events the site shouldn't list: outside Nebraska, not tech, or private or members-only.
Note them, but don't count them either way.

## 3. Act on the misses

For each event that wasn't on the site, decide why, and fix what you can:
- **Its group is new to us:** add it to `data/known_groups.yaml`, so the weekly gap check searches
  for it (and suggests a source when it finds one). A minimal entry:

  ```yaml
  - name: Omaha Rust Users
    aliases: [Omaha Rust]
    area: omaha
    links: [https://www.meetup.com/omaha-rust/]
  ```

  Or, quicker: suggest its events page through the site's **Suggest** form.
- **Its group has a source, but the event is missing:** look at the source's row in the Discovery
  health issue. It may be failing, paused, or reading the wrong page.
- **It's there, but with wrong details:** fix it with an override (`docs/admin-guide.md`).
- **It was held for review, or rejected:** check the review PR history. A wrong rejection is a
  sign to look at that source's trust.

## 4. Record the result

Fill in the totals at the top of the quarter's file, then copy the coverage percentages into the
quarter's notes in `docs/operations/metrics.md` if useful.

---

## Template

```markdown
# Coverage check: <YYYY> Q<n>

**Checked:** <date> by <name>
**Window:** events from <date> to <date>

| | Found by hand | On NETechConnect | Coverage | Target |
|---|--:|--:|--:|--:|
| All counted events | | | | 85% |
| Monitored Omaha and Lincoln groups | | | | 95% |

| # | Event | Date | Area | Where found by hand | Monitored group? | On NETechConnect | Action taken |
|--:|---|---|---|---|---|---|---|
| 1 | | | | | | | |

**Left out** (not counted: outside Nebraska, not tech, or private):

**Notes:**
```
