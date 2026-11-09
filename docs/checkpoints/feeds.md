# Checkpoint: Event feeds (feature 002)

**Date:** 2026-11-09 (America/Chicago)
**Task:** T031 (`specs/002-event-feeds/quickstart.md` §2–§4)
**Deployed:** PR #179, `main` at 41e2fc3, Deploy site run 42636485522
**Result:** **Passed**, with one observation still to make: the first new event published
after launch should appear exactly once (below).

Owner decision (2026-11-09): check typical feed readers only; classic Outlook and Slack are not
part of this checkpoint. The feeds page still mentions them as options.

## Before deploy (§1–§2)

- `uv run pytest -q`: 1515 passed (353 security). Playwright: 102 passed.
- Build from real `data/` into two directories: 12 feeds (`all.xml` + 11 categories, largest
  5.5 KB) and `feeds/index.html`; the two builds' feed files were **byte-identical** (SC-007).

## Live (§3–§4)

| Check | Expected | Got |
|---|---|---|
| `curl -sI https://netechconnect.com/feeds/all.xml` | 200, Atom content type (R6) | **200**, `Content-Type: application/atom+xml; charset=utf-8` (the `_headers` rule wins over Pages' default, so no deviation) |
| Security headers on the feed | Site-wide CSP, HSTS, `nosniff`, Referrer-Policy | **All present**, same values as every page |
| Caching | Readers can revalidate | `Cache-Control: public, max-age=0, must-revalidate` + `ETag` |
| All 12 feed addresses | 200 | **12 × 200** |
| W3C Feed Validation Service, `all.xml` and `security.xml` (empty) | Valid Atom 1.0 | **Valid**, 0 errors, 0 warnings |
| `feedparser` on live `all.xml`, `software-dev.xml`, `security.xml` | `bozo` false; entries = upcoming events | **bozo false**; all: 5 entries (newest-listed first, each linking to the organizer's page), Software Development: 1, Information Security: 0 (valid, empty) |
| Autodiscovery on `https://netechconnect.com/` | `<link rel="alternate" type="application/atom+xml" … href="/feeds/all.xml">` | **Present** (FR-010) |
| Home page → `/feeds/` | ≤ 2 clicks (SC-004) | **1 click**: "Follow new events" in the hero, and "Follow" in every footer; `/feeds/` returns 200 |

## Still to observe

- **First new item.** The next discovery run that publishes a new event should add exactly one
  entry, and a refresh with no event changes should add none (SC-001, SC-007). The bytes check
  above already shows unchanged data gives an unchanged file; this confirms it on live data.
  Note: events published before feature 002 have no `published_at`, so their entries use
  `first_seen` as the listed time; new events and approvals record `published_at` from #175 on.
- **A reader app.** Paste `https://netechconnect.com/` into any feed reader (Feedly, Inoreader,
  NetNewsWire, Thunderbird…) to confirm it offers "NETechConnect: all events". Optional; the
  validator and `feedparser` results above are what readers rely on.
