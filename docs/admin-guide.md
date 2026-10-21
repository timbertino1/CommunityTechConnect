# NETechConnect admin guide

Everything the owner does happens on GitHub, through pull requests and one pinned issue. There
is no admin website and no separate login. The bot does the routine work twice a day. You only
step in when GitHub notifies you, which should take less than 15 minutes a week (SC-010).

| You get notified about | What to do | Section |
|---|---|---|
| A **Review** pull request | Tick approve or reject under each item, then merge | [Reviewing](#reviewing-held-items) |
| A comment on the **Discovery health** issue | Read the list; usually fix or pause a source | [Health issue](#reading-the-health-issue) |
| A wrong, duplicate or spam event on the site | Add an override by PR | [Overrides](#hiding-an-event-or-fixing-its-details) |

Never edit the month files under `data/events/` by hand. The next run rewrites them, so the
edit would be lost. Use `data/overrides.yaml` instead.

## Reviewing held items

Some events wait for you before they go on the site: new events from a **probationary** source,
and events the rules couldn't decide on. The bot lists them in one pull request on branch
`review/open`, titled like `Review: 3 items (events)`.

1. Open the PR and read each item: title, date and time, area, topics, why it was held, which
   source it came from, and a link to the original page.
2. Under each item, tick **approve** or **reject**.
   - **Approve** publishes the event on the site.
   - **Reject** keeps it off the site for good.
   - Leave both unticked (or tick both) to decide later. The item comes back in the next
     review PR.
3. **Merge** the PR. A minute later the bot opens a small follow-up PR, `Apply review #N`, that
   applies your decisions and merges itself.

Things to know:

- Only the ticks are read. Don't edit the description in any other way: if it was edited after
  the merge, the bot refuses to apply anything.
- Only a merge by an admin counts, and only for the bot's own `review/open` PR. Closing the PR
  without merging changes nothing.
- The bot refreshes the PR at most once a day, and never once you've ticked a box, so you can
  review in more than one sitting.
- Your decisions also count for the source. A probationary source becomes **trusted** after 3
  approved events and no rejected ones; after that, its events publish without review. A
  probationary source is **paused** once at least 3 of its events have been reviewed and most were
  rejected (so one early rejection doesn't pause a new source).
- Event titles are shown in `code`, because they come from other websites. A title that looks
  like a checkbox or an id is just text.

## Hiding an event or fixing its details

Add an entry to `data/overrides.yaml` in a pull request. When it merges, the change appears at
the next deploy (a couple of minutes), and every later run keeps it.

```yaml
- event_id: evt_0123456789ab
  visibility: hidden
  reason: duplicate of the Meetup listing
- event_id: evt_abcdef012345
  categories: [ai-ml, data-analytics]
  area: lincoln
  reason: Lincoln event, mostly about AI
```

- **`event_id`** (required): find it in the site's `/data/upcoming.json`, or in
  `data/events/<year>/<year-month>.json`, next to the event's title.
- **`visibility`**: `hidden` takes the event off the site. To bring it back, delete the entry
  (or set `shown`).
- **`categories`**: one or more ids from `data/categories.yaml`. They replace the guessed
  topics.
- **`area`**: `omaha`, `lincoln`, `other_ne` or `online`.
- **`reason`** (required): a short note. It's public, so don't include anyone's personal
  details.

An entry has to set at least one of `visibility`, `categories` or `area`.

What an override can't do: change the event's link to the original page, publish an event that
is waiting for review (approve it in the review PR instead), or change a source's trust.
`netc validate-data` (run by CI on every PR) fails if an entry names an event that doesn't
exist or a category that isn't defined.

If you delete a categories or area entry, upcoming events go back to the guessed values at the
next run. Past events are no longer read, so they keep the old values; set them explicitly if
you need to.

## Managing sources

Each source is one file in `data/sources/`. Change sources with a normal pull request; CI
checks the file.

- **Add:** copy a similar source file (for a Meetup group, `src_ai-omaha.yaml`) and change
  `id`, `name`, `url` and the `follow_links` path. Set `origin: admin` and today's `added_at`.
  Choose `trust`:
  - `trusted`: events go straight on the site. Use this for established community groups
    whose events are public and on-topic.
  - `probationary`: each event waits in the review PR until the source earns trust.
  Meetup sources keep `rate_limit_seconds: 10` (the Meetup terms decision).
- **Pause:** set `status: paused`. The source isn't read, and its existing events stay as
  they are.
- **Demote:** set `trust: probationary`. New events then wait for review again. Only you can
  demote a source; review results never demote a trusted one.
- **Remove:** set `status: paused` and say why in `notes`. Keep the file: the archive keeps the
  source's past events, and `validate-data` fails if an event's source file is missing. Its
  upcoming events stay on the site until they happen; hide them with overrides if they
  shouldn't. You can delete a file only if no stored event lists that source.

Before adding a source the pipeline can't obviously read, try it in a dry run (as was done for
AI Omaha on Oct 19, 2026):

```sh
cd discovery
uv run netc discover-events --data-dir <copy of data with only the new source> --dry-run --force --report report.md
```

## The weekly hunt for new groups

Every Monday at 12:00 UTC, **Discover sources** looks for groups nobody told the site about:
about 40 web searches, the links on known organizers' pages, local news feeds
(`discovery/src/netc/finders/config.yaml`), and targeted searches for groups that went quiet,
annual events not yet listed, and known groups with no working source. It opens its own data
PR, `New sources <date>`, which merges by itself; the description lists what was added and what
was looked at and turned down.

- A relevant site is added as a **probationary** source. Its events reach you in the review PR
  from the next daily run, and three approvals make it trusted.
- A site whose events are outside Nebraska, or not about tech, is rejected and looked at again
  after a month.
- A site it can't read automatically (no calendar feed or event data) is listed under
  **Candidates needing a look** in the health issue. If it's worth having, add it by hand.
- A newsletter or news mention is never published itself. Once the bot finds the organizer's
  page, that site becomes a candidate like any other.

Web search uses at most 400 of Tavily's 1,000 free monthly searches; the AI shares the $1.00
monthly budget with the daily runs. Both totals are in the health issue.

## Reading the health issue

The pinned issue **Discovery health** is rewritten after every run. Editing it is pointless, and
the edit doesn't notify anyone. It shows:

- **Sources:** every source with its status, trust, how it was found, last successful check,
  events found last run, and failures in a row.
- **Failing sources:** each one with its last error. One failure is usually a blip (a site
  timing out). If a source keeps failing, open its page to see whether it moved or changed,
  then fix the URL or pause the source.
- **Waiting for review:** the number of items in the review PR.
- **Quiet groups:** groups with nothing upcoming whose last event is more than twice their
  usual gap ago. They may have moved to another site.
- **Unresolved mentions, new sources this week, AI and search spend:** used by automatic
  discovery (Phase 4).
- **Schedule:** when this run happened, and how old `main`'s data was before it. Data more
  than 36 hours old means the bot's data PRs aren't merging. Check the latest `Data update`
  PR for failed checks.

The bot adds a **comment** mentioning you when something needs action: a source failing 2
runs in a row, items waiting for review, or stale data on `main`. You get at most one comment
a day. A problem it has already reported comes up again only after a week; a new problem is
reported at the next run.

## Access

- Only the owner (`@timbertino1`) holds admin or write access to the repository. Two-factor
  authentication is required on that account (T001).
- The bot is a GitHub App. It may only write files under `data/`, open pull requests, and open
  and update issues. CI fails any bot PR that changes anything outside `data/`, and only an
  admin's merge of the review PR is applied.
- Before anyone else gets access as a future maintainer, they must show that two-factor
  authentication is enabled on their GitHub account.
- The App's permissions are **Contents**, **Pull requests** and **Issues**, all read and write,
  plus the read-only **Metadata** permission GitHub gives every App. If GitHub asks you to
  approve new permissions for it, check that they are only these.
