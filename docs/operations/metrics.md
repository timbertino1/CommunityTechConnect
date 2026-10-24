# Monthly metrics

How NETechConnect is doing against the spec's outcome criteria (`specs/001-event-aggregator/spec.md`,
"Success Criteria"). In the **first week of each month**, add a row to each table below. The
Discovery health issue asks for it then (one comment a month), and its **Monthly check** section
shows the discovery count for SC-011.

About 15 minutes a month. The coverage check (SC-002) is quarterly and has its own log in
`docs/coverage/`.

## SC-004: duplicates and misclassified events (monthly spot check)

**Target:** fewer than 2% duplicates and fewer than 5% misclassified or out of scope. With 30
events, that's **0 duplicates** and **at most 1** misclassified.

**How:** this picks 30 published events at random, the same 30 for anyone running it in the same
month (or all of them, if there are fewer):

```sh
cd discovery
uv run python -c "import random,datetime; from pathlib import Path; from netc.storage import DataStore; ev=sorted((e for e in DataStore(Path('../data')).read_events() if e.is_public), key=lambda e: e.id); random.Random(datetime.date.today().strftime('%Y-%m')).shuffle(ev); [print(e.start.date(), e.area, ','.join(e.categories), e.title, '->', f'/events/{e.slug}/') for e in ev[:30]]"
```

For each event, open its page on the site and ask:
- **Duplicate:** is the same event listed twice?
- **Misclassified:** wrong area, or wrong topics?
- **Out of scope:** not a tech event, or not in Nebraska and not online from a Nebraska group?

Hide or correct anything wrong through `data/overrides.yaml` (`docs/admin-guide.md`).

| Month | Events checked | Duplicates | Misclassified / out of scope | Fixed | Notes |
|---|--:|--:|--:|---|---|
| | | | | | |

## SC-010: admin time

**Target:** at most **15 minutes a week** on average, after the first month. Count review PRs,
health-issue comments, overrides and source fixes; not building new features.

| Month | Minutes, average per week | What took the time |
|---|--:|---|
| | | |

## SC-011: groups added by discovery

**Target:** within **60 days of launch**, discovery adds **at least 10** relevant Nebraska groups
or organizations that weren't in the starting list, from **at least 3 kinds of channel**, with no
manual source research by the owner.

**How:** copy the counts from the health issue's **Monthly check** section. They count active
sources that discovery added or visitors suggested; paused and removed ones don't count.

| Date | Active sources added by discovery | Kinds of channel | By channel | Notes |
|---|--:|--:|---|---|
| 2026-10-24 (baseline, before launch) | 7 | 2 | web search 5, gap check 2 | Short of 3 channels, as in T105 (`docs/checkpoints/us2.md`) |

## SC-001: first-visit task (at launch, then yearly)

**Target:** a first-time visitor finds the next upcoming tech event in their chosen city and
reaches its original event page **within 30 seconds**.

**How:** ask 3 people who haven't used the site. Hand them a phone or laptop on the home page and
say: "Find the next tech event in [Omaha or Lincoln, their choice] and open its page." Time from
"go" until the organizer's page opens.

| Date | Person | Device | City | Seconds | Got there? | What slowed them down |
|---|---|---|---|--:|---|---|
| | | | | | | |
