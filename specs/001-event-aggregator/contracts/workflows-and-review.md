# Contract: Scheduled Workflows and the Review Pull Request

## Workflows (`.github/workflows/`)

| Workflow | Trigger | Permissions | Secrets (Environment `discovery`) | Does |
|---|---|---|---|---|
| `ci.yml` | `pull_request`, `push` to `main` | `contents: read` | none | Tests, lint, type check, schema validation of `data/`, `pip-audit`, `npm audit`, gitleaks, accessibility check on built site |
| `discover-events.yml` | `schedule` twice daily (11:00 and 23:00 UTC) + manual | `contents: read` (writes via App token) | OpenAI, Cloudflare KV token, GitHub App key | Pull suggestions/newsletters from KV, run connectors, classify, de-dupe, update data; open/update the **daily data PR** (auto-merge) |
| `discover-sources.yml` | `schedule` weekly + manual | same | + search API key | Run finders, evaluate candidates, resolve mentions, gap checks; open/update the **review PR**; update the health issue |
| `apply-review.yml` | `push` to `main` | `contents: read` (writes via App token) | GitHub App key | Look up the merged PR for the pushed commit; if it is the `review/open` PR authored by the App and merged by an admin, apply its decisions; otherwise exit |
| `deploy.yml` | `push` to `main` | `contents: read`, `deployments: write` | Cloudflare Pages token | Build static site and deploy |
| `deploy-workers.yml` | `push` to `main` changing `workers/**` | `contents: read` | Cloudflare Workers token (Environment `production`) | Test and deploy both Workers |

Rules: all third-party actions pinned to full commit SHA; no `pull_request_target`; fork PR
workflows require approval; scheduled jobs use `concurrency` groups so runs never overlap; each
job has a timeout (discovery ≤ 60 min).

## Daily data PR

- Branch `bot/data-<date>`, created and updated by the GitHub App.
- Contains only machine-written files under `data/` (CI rejects bot PRs that touch anything else).
- Auto-merges after CI passes. No human action needed. This is allowed by the constitution
  v1.1.0 exception for bot PRs that change only `data/`.
- `discover-events.yml` runs twice daily (11:00 and 23:00 UTC) so a delayed or skipped
  scheduled run still keeps every source within 24 hours (FR-002).

## Review PR

- Branch `review/open`, title `Review: N items (events, sources, suggestions)`. Created or
  updated by either discovery workflow whenever items are pending (at most daily); no PR when
  nothing is pending. Visitor notes never appear in it.
- Body has one block per item, each with an approve and a reject checkbox:

```markdown
**Event** · Omaha AI Night — Thu Nov 12, 6:00 PM CT · Omaha · AI & ML · `rev_ab12cd`
Held: probationary source "Example Coworking" · [original page](https://…)
- [ ] approve
- [ ] reject

**Source** · Lincoln Rust Users (https://…) · found via web search · detected: iCal · `rev_ef34gh`
Held: new source · sample events: 3
- [ ] approve
- [ ] reject
```

- At merge: **approve** ticked → approved; **reject** ticked → rejected; neither or both ticked →
  stays pending and reappears in the next review PR. Closing without merge leaves everything
  pending.
- `apply-review.yml` (on `push` to `main`, so it can use the `main`-only Environment) finds the
  merged PR for the commit and validates: PR head branch is `review/open`, PR author is the App,
  merger has admin role, each `rev_` id exists and is pending. It then updates `review/queue.json`, event `review_state`, source
  counts, and applies promotion/pausing rules (FR-018), committing via a follow-up data PR.

## Health issue

- One pinned issue titled `Discovery health`, edited in place weekly (and daily if failures).
- Sections: failing sources, quiet groups, unresolved mentions, new sources this week by
  channel, AI and search spend vs. budget, schedule status.
- Includes a **Sources** table listing every source: name, status, trust, how it was found,
  last successful check, events found last run, consecutive failures (FR-042).
- When something needs action, posts a **new comment** mentioning the owner (comments notify;
  issue edits do not), at most one per day (FR-044, SC-010).
