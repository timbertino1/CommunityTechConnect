# Performance check

**Date:** 2026-10-24
**Task:** T138 (SC-006: main content in ≤ 2 s on a phone on slow 4G)
**Tool:** Lighthouse 13.5.0, default mobile settings (simulated slow 4G and a 4× slower CPU,
Moto G-sized screen), in Microsoft Edge (headless), 3 runs per page.
**Result:** **Passes, with almost no margin.** One regression was found and fixed: the calendar's
layout shift. The main-content time (LCP) is about 1.97 s on both pages, against the 2 s target.
What it would take to buy more margin is under "Options" below.

## Live site, before the fix (`main` at `c4c0f10`)

| Page | Run | Perf | FCP | LCP | TBT | CLS | Weight |
|---|--:|--:|--:|--:|--:|--:|--:|
| `/` | 1 | 94 | 1.46 s | 1.98 s | 256 ms | 0.007 | 273 KB |
| `/` | 2 | 94 | 1.54 s | 1.98 s | 253 ms | 0.007 | 273 KB |
| `/` | 3 | 93 | 1.50 s | 1.98 s | 269 ms | 0.000 | 273 KB |
| `/calendar/2026/10/` | 1 | 85 | 1.41 s | 1.93 s | 0 ms | **0.279** | 122 KB |
| `/calendar/2026/10/` | 2 | 85 | 1.38 s | 2.00 s | 0 ms | **0.279** | 122 KB |
| `/calendar/2026/10/` | 3 | 84 | 1.41 s | **2.07 s** | 0 ms | **0.279** | 122 KB |

Accessibility 100 and best practices 100 on both pages. The only failed audit was "valid source
maps" on the home page; the bundled three.js ships without one, and no change is needed.

**Compared with Oct 22** (`docs/reviews/design-b.md`): the home page's LCP went from 1.7 s to
2.0 s, and its FCP from 1.3 s to 1.5 s. Since then the site gained the filter bar and its two
scripts, the Past page, more events, and the Suggest link.

## The regression: the calendar jumped as it loaded

**Cause:** the filter bar was in the HTML but `hidden` until `filters.js` ran, so visitors without
JavaScript wouldn't see controls that can't work. When the script showed it, the calendar table
moved down: a layout shift of **0.279**. Google calls anything over 0.25 "poor".

**Fix:** the bar is now shown from the first paint. A stylesheet loaded only inside `<noscript>`
(`web/css/nojs.css`, allowed by the CSP as one of the site's own files) hides it when JavaScript
is off, and the "Filters need JavaScript" notice still shows. A build test and the existing
"with JavaScript off" browser test cover both cases.

**After the fix** (today's data built locally, served without throttling, same Lighthouse
settings):

| Page | Perf | FCP | LCP | TBT | CLS |
|---|--:|--:|--:|--:|--:|
| `/` (3 runs) | 95 | 1.67-1.69 s | 1.97-1.98 s | 198-200 ms | 0.007 |
| `/calendar/2026/10/` (3 runs) | **99** | 1.25-1.38 s | 1.97 s | 0 ms | **0.000** |

## Where the main-content time goes

On both pages the largest paint is text: the intro paragraph on `/`, an event title on the
calendar. The page itself is small (4-5 KB of HTML, 7 KB of CSS, 3 KB of filter script, and data
files of 9 KB and 4 KB, far under the 200 KB at which the task says to split `upcoming.json`).
The cost is the web fonts: Inter (48 KB) and Archivo (35 KB) are preloaded, and JetBrains Mono
(22 KB) follows. Measured variants, each 2-3 runs on the same local build:

| Variant | `/` LCP | Calendar LCP |
|---|--:|--:|
| **As shipped:** Inter and Archivo preloaded, `font-display: swap` | 1.97-1.98 s | 1.97 s |
| No Archivo preload | 1.97-2.12 s | 1.97-2.13 s |
| No font preloads at all | 2.12-2.13 s | 1.99-2.14 s |
| Inter with `font-display: optional` | 1.97 s | 1.97-2.00 s |
| *Diagnostic only:* no web fonts (system fonts) | 1.44-1.45 s | 1.38 s |

So the fonts cost about half a second on a slow phone, and the shipped setup is already the
fastest way of loading them. The three.js header map doesn't affect LCP: it starts after the
content is shown and accounts for most of the home page's 200 ms of blocking time.

## Options for more margin (owner's call)

1. **Leave it.** It passes, and real phones on 4G or better are usually faster than this simulation.
2. **Smaller font files.** Keep the same fonts, but cut each to the weights the site uses (for
   example Inter at 400-700 instead of its full range) and to the characters it needs. Likely
   20-40 KB less to download, without changing how the site looks. Needs a one-time font tool
   step, with the results checked into `web/fonts/`.
3. **System fonts for body text, web fonts for headings only.** Saves about half of what the
   fonts cost, but changes the look of design B.

## Not measured

`/past/`, event pages and `/suggest/` use the same template, CSS and fonts as the pages above,
with less script than the home page.
