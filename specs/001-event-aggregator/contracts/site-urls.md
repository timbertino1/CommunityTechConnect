# Contract: Public Site URLs and Data Files

The public site is static. These paths and query parameters are a stable contract: shared and
bookmarked links (FR-038) must keep working.

## Pages

| Path | Content | Works without JS |
|---|---|---|
| `/` | Upcoming events list, soonest first (FR-032) | Yes |
| `/past/` | Past events, most recent first (FR-034, FR-040); paginated `/past/page/<n>/` | Yes |
| `/calendar/<YYYY>/<MM>/` | Month view; `/calendar/` redirects to the current month (FR-033) | Yes |
| `/calendar/<YYYY>/week/<WW>/` | ISO week view | Yes |
| `/events/<slug>/` | Event detail: essentials + **primary link to original page** (FR-024, FR-025) | Yes |
| `/suggest/` | Source suggestion form (FR-020) — posts to the Worker | Needs JS for Turnstile |
| `/about/` | About, bot identity/contact for site owners, how events are found, privacy note | Yes |

Every event card and detail page links to `original_url` with visible text such as
"View and register on <host>" — this is the primary call to action. No page offers calendar
downloads, invites, reminders, or RSVP (FR-026).

## Query parameters (list and calendar pages)

| Param | Values | Default |
|---|---|---|
| `area` | comma list of `omaha`, `lincoln`, `other_ne`, `online` | all |
| `cat` | comma list of category ids | all |
| `from`, `to` | `YYYY-MM-DD` (Central Time dates) | none |
| `q` | keyword, ≤ 100 chars, matched against title, organizer, summary (FR-037) | none |

Filters are applied in the browser and preserved when switching list ↔ calendar and when
navigating months/weeks (FR-036, FR-038). Unknown or invalid values are ignored. Without JS, all
events are shown and a notice explains filters need JavaScript.

## Public data files (read by the site's own JS; also usable by anyone)

| Path | Content |
|---|---|
| `/data/upcoming.json` | All publicly visible upcoming events (public fields only) |
| `/data/past/<YYYY>.json` | Publicly visible past events for a year |
| `/data/meta.json` | Categories, areas, `generated_at` |
| `/data/map.json` | For the home page header map: `towns` (every `{name, lat, lon}` in `data/areas.yaml` `points`) and `pins` (`{city, lat, lon, events}` for each city with upcoming in-person, not cancelled events; a city not in `points` gets no pin) |

Public event fields: `id, slug, title, start, end, all_day, area, location, organizer,
summary, categories, original_url, status, last_verified, inferred, original_unavailable`. Internal fields
(`listings`, `review_state`, hashes) are not published in these files.

## Security headers (via Cloudflare Pages `_headers`)

All paths:

`Content-Security-Policy: default-src 'self'; script-src 'self'; connect-src 'self';
img-src 'self' data:; style-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self';
frame-ancestors 'none'`,
`Strict-Transport-Security: max-age=63072000; includeSubDomains`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
`Permissions-Policy: camera=(), microphone=(), geolocation=()`.

`/suggest/*` only (overrides the CSP above):

`Content-Security-Policy: default-src 'self'; script-src 'self' https://challenges.cloudflare.com;
frame-src https://challenges.cloudflare.com; connect-src 'self' https://<worker-host>;
img-src 'self' data:; style-src 'self'; object-src 'none'; base-uri 'none';
form-action https://<worker-host>; frame-ancestors 'none'`

## Privacy

Public pages set no cookies, ask for no personal information, and make no requests to other
hosts. The only exception is Turnstile on `/suggest/` (FR-039).
