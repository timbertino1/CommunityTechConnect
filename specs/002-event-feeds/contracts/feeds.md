# Contract: Event feeds and the feeds page

Public interface added to the static site (`specs/001-event-aggregator/contracts/site-urls.md`
gets these rows when the feature lands). Addresses are stable: changing one is a breaking change
for every follower.

## URLs

| Path | What | Content type |
|---|---|---|
| `/feeds/all.xml` | Atom feed: all public upcoming events | `application/atom+xml; charset=utf-8` (R6) |
| `/feeds/<category-id>.xml` | Atom feed: public upcoming events tagged with that category; one per category in `data/categories.yaml` (11 today: `ai-ml`, `security`, `software-dev`, `networking-infra`, `cloud-devops`, `data-analytics`, `web-mobile`, `product-design-ux`, `career-networking`, `hardware-iot-makers`, `general-tech`) | same |
| `/feeds/` | HTML page listing every feed and how to use one | `text/html` |

A category removed from `categories.yaml` loses its feed file at the next build (404 after that).

## Feed document

```xml
<?xml version='1.0' encoding='utf-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>tag:netechconnect.com,2026:feed/security</id>
  <title type="text">NETechConnect: Security</title>
  <subtitle type="text">New community tech events in Nebraska. Each links to the organizer's own page.</subtitle>
  <updated>2026-11-07T16:46:00Z</updated>
  <author><name>NETechConnect</name></author>
  <link rel="self" type="application/atom+xml" href="https://netechconnect.com/feeds/security.xml"/>
  <link rel="alternate" type="text/html" href="https://netechconnect.com/"/>
  <entry>
    <id>tag:netechconnect.com,2026:event/evt_…</id>
    <title type="text">Nebraska Public Sector Cybersecurity &amp; AI Summit</title>
    <published>2026-11-02T20:41:00Z</published>
    <updated>2026-11-02T20:41:00Z</updated>
    <link rel="alternate" type="text/html" href="https://organizer.example/event"/>
    <link rel="related" type="text/html" href="https://netechconnect.com/events/…/"/>
    <author><name>Organizer name</name></author>
    <category term="security" label="Security"/>
    <summary type="text">Tue, Nov 17, 2026, 5:00 PM – 7:00 PM CT · Omaha
Organizer: Organizer name

Short plain-text summary.</summary>
  </entry>
</feed>
```

Rules (each has a test):

1. Well-formed XML 1.0, UTF-8, Atom 1.0 valid; `feedparser` parses it with `bozo == 0`.
2. All text constructs are `type="text"`; there is no `content` element and no element or
   attribute outside the Atom namespace.
3. Entries: only `is_public` events that haven't ended at build time; category feeds only events
   tagged with that category; ≤ 100 entries; order `published` desc, then event id.
4. Entry `id` = `tag:netechconnect.com,2026:event/<event id>`, independent of the build domain.
5. The first `link` of an entry (`rel="alternate"`) is the organizer's original page; the
   NETechConnect page is `rel="related"`.
6. `published` = `published_at` or `first_seen`; `updated` = max(`published`, `changed_at`).
   Admin overrides do not change `updated`.
7. Cancelled events keep their entry with `Cancelled: ` before the title.
8. Feed `updated` = newest entry `updated`, or `2026-11-01T00:00:00Z` when there are no entries.
   Two builds from the same data at different times produce byte-identical feeds unless an event
   ended between them.
9. No query strings, tracking parameters, cookies, or per-request variation; links are exactly
   the event's `original_url` and the site's event page.
10. No text from a source can produce markup: `<`, `>`, `&` and quotes are escaped; characters
    not allowed in XML 1.0 are removed.

## Feeds page and discovery

- Every HTML page's `<head>` contains
  `<link rel="alternate" type="application/atom+xml" title="NETechConnect: all events" href="/feeds/all.xml">`.
- `/feeds/` additionally has one `rel="alternate"` link per category feed.
- Every page's footer nav has a **Follow** link to `/feeds/`; the home page has a "Follow new
  events" link to `/feeds/` near the event count.
- `/feeds/` lists the all-events feed first, then each category in `categories.yaml` order, each
  as its label plus the full absolute address as a link. Works without JavaScript. WCAG 2.2 AA,
  no sideways scroll at 320 px (long addresses wrap), light and dark themes.

## Headers

`web/_headers` adds:

```text
/feeds/*.xml
  Content-Type: application/atom+xml; charset=utf-8
```

The global `/*` security headers (CSP, HSTS, nosniff, Referrer-Policy, Permissions-Policy) apply
to feeds and the feeds page unchanged.
