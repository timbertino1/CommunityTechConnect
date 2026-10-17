# Contract: Scheduled Workflows and the Review Pull Request

## Workflows (`.github/workflows/`)

| Workflow | Trigger | Permissions | Secrets (Environment `discovery`) | Does |
|---|---|---|---|---|
| `ci.yml` | `pull_request`, `push` to `main` | `contents: read` | none | Tests, lint, type check, schema validation of `data/`, `pip-audit`, `npm audit`, gitleaks, accessibility check on built site |
| `discover-events.yml` | `schedule` daily (~06:00 CT) + manual | `contents: read` (writes via App token) | OpenAI, Cloudflare KV token, GitHub App key | Pull suggestions/newsletters from KV, run connectors, classify, de-dupe, update data; open/update the **daily data PR** (auto-merge) |
| `discover-sources.yml` | `schedule` weekly + manual | same | + search API key | Run finders, evaluate candidates, resolve mentions, gap checks; open/update the **review PR**; update the health issue |
| `apply-review.yml` | `pull_request: closed` on `review/*` branches | `contents: read` (writes via App token) | GitHub App key | If merged by an admin and authored by the App: apply ticked/unticked decisions |
| `deploy.yml` | `push` to `main` | `contents: read`, `deployments: write` | Cloudflare Pages token | Build static site and deploy |

Rules: all third-party actions pinned to full commit SHA; no `pull_request_target`; fork PR
workflows require approval; scheduled jobs use `concurrency` groups so runs never overlap; each
job has a timeout (discovery ≤ 60 min).

## Daily data PR

- Branch `bot/data-<date>`, created and updated by the GitHub App.
- Contains only machine-written files under `data/` (CI rejects bot PRs that touch anything else).
- Auto-merges after CI passes. No human action needed.

## Review PR

- Branch `review/<date>`, title `Review: N items (events, sources, suggestions)`.
- Body is a checklist, one line per item:

```markdown
- [ ] **Event** · Omaha AI Night — Thu Nov 12, 6:00 PM CT · Omaha · AI & ML
      Held: probationary source "Example Coworking" · [original page](https://…) · `rev_ab12cd`
- [ ] **Source** · Lincoln Rust Users (https://…) · found via web search · detected: iCal
      Held: new source · sample events: 3 · `rev_ef34gh`
```

- Ticked at merge = **approve**; unticked at merge = **reject**. Closing without merge = leave
  pending (items reappear in the next review PR).
- `apply-review.yml` validates: PR author is the App, merger has admin role, each `rev_` id
  exists and is pending. It then updates `review/queue.json`, event `review_state`, source
  counts, and applies promotion/pausing rules (FR-018), committing via a follow-up data PR.

## Health issue

- One pinned issue titled `Discovery health`, edited in place weekly (and daily if failures).
- Sections: failing sources, quiet groups, unresolved mentions, new sources this week by
  channel, AI and search spend vs. budget, schedule status.
- Mentions the owner only when something needs action (FR-044, SC-010).
