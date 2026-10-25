# Accessibility pass

**Date:** 2026-10-25
**Task:** T137 (manual pass: keyboard only, a screen reader, 200% zoom)
**Site:** https://netechconnect.pages.dev (`main` at `3d9c00f`)
**Result:** **Passes.** No problems found, so no fixes were needed.

This pass adds to the automatic checks that run on every pull request: axe-core on 7 pages ×
3 widths (320, 360 and 1280 px) × light and dark themes (T136), and the no-JavaScript,
reduced-motion and no-WebGL checks of the home page map (T154).

## Screen reader

**Tester:** the owner. **Tool:** Windows Narrator in Microsoft Edge (Windows 11).

| Area | What was checked | Result |
|---|---|---|
| Home | Page title read on load; headings form an outline; landmarks (banner, navigation, main, footer); the map is silent; filters read their name and checked state; event links read the event's name; date, time and place read clearly | OK |
| Event page | First heading is the event's name; date, time and location read clearly; each link says where it goes | OK |
| Calendar | The day and its events can be told apart; previous and next links name their month | OK |
| Suggest | Each field reads its label and whether it is required; the Turnstile check doesn't get in the way; submitting empty reads an error that says what to fix | OK |

## Keyboard only

**Tool:** a Playwright script in Microsoft Edge at 1280 × 900. On each page it pressed Tab
through every stop and checked that the focused element has a visible focus style, is not hidden,
and is on screen.

| Page | Tab stops | First stops | Result |
|---|--:|---|---|
| `/` | 39 | Skip to main content > NETechConnect > Upcoming | OK |
| An event page | 12 | same | OK |
| `/past/` | 24 | same | OK |
| `/calendar/` | 39 | same | OK |
| `/suggest/` | 9 | same | OK |
| `/about/` | 13 | same | OK |

**Filters:** ticking a topic with Space narrowed the home page from 9 events to 6, and the status
message changed to "Showing 6 of 9 events." Its live region is what tells screen-reader users
the list changed.

## 200% zoom

200% zoom on a 1280 px window lays the page out at 640 CSS px. Each of the pages above was loaded
at that width and checked for sideways scrolling and for links, buttons, fields or headings cut
off at either edge. **None found.** The narrower 400% case (320 px, WCAG 2.2 "Reflow") is
covered by the automatic checks.
