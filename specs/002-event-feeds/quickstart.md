# Quickstart: validating Event Feeds

Run from the repository root on a machine set up for feature 001 (uv, Node). Windows: build into
a short directory (MAX_PATH), e.g. `%TEMP%\feeds`.

## 1. Automated checks

```sh
cd discovery
uv run pytest -q                 # unit, contract, integration (feeds included)
uv run pytest -q -m security     # hostile-text feed tests among them
cd ../web && npx playwright test # feeds page, footer link, axe at 320/360/1280, light/dark
```

Expected: all pass. Feed tests cover contract rules 1–10 in `contracts/feeds.md`.

## 2. Build on real data and inspect

```sh
cd discovery
uv run netc build-site --data ../data --out "$TEMP/feeds" --web ../web
ls "$TEMP/feeds/feeds"           # all.xml, 11 <category>.xml, index.html
uv run python -c "import feedparser,sys; d=feedparser.parse(sys.argv[1]); print(d.bozo, d.feed.title, len(d.entries)); [print(e.published, e.title, e.link) for e in d.entries[:5]]" "$TEMP/feeds/feeds/all.xml"
```

Expected: `0 NETechConnect: all events <n>` where n = number of upcoming events on the home
page (≤ 100); newest-listed first; each `link` is the organizer's page.

Stability (SC-007): build again into a second directory with the same data and compare:

```sh
uv run netc build-site --data ../data --out "$TEMP/feeds2" --web ../web
diff -r "$TEMP/feeds/feeds" "$TEMP/feeds2/feeds" -x index.html && echo identical
```

Expected: `identical` (the feeds page itself may differ only in the footer's "Updated" time).

## 3. Validator

Paste `all.xml` and one category feed into the W3C Feed Validation Service (validator.w3.org/feed,
"Validate by Direct Input"). Expected: valid Atom 1.0; warnings about `tag:` ids are acceptable.

## 4. Live checks (after deploy)

1. `curl -sI https://netechconnect.com/feeds/all.xml` → 200, `content-type: application/atom+xml`
   (R6: `application/xml`/`text/xml` is a recorded deviation, not a failure), CSP, HSTS,
   `x-content-type-options: nosniff`.
2. Home page → footer **Follow** → `/feeds/` lists 12 feeds (SC-004: ≤ 2 clicks, < 1 minute).
3. Give a feed reader (e.g. Feedly or Inoreader) only `https://netechconnect.com/`: it offers
   the all-events feed (FR-010).
4. Subscribe to one category feed in Slack (`/feed subscribe https://netechconnect.com/feeds/<id>.xml`)
   and in classic Outlook (RSS Subscriptions → Add), if available. Both show the current
   entries with working organizer links (FR-009).
5. After the next discovery run that publishes a new event, the reader shows exactly that event
   as new, and nothing already seen comes back as new (SC-001, SC-007).

Record results in `docs/checkpoints/feeds.md`.
