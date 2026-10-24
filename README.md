# NETechConnect

NETechConnect (aka CommunityTechConnect) automatically discovers community technology events
across Nebraska — with Omaha and Lincoln first — and shows upcoming and past events in list and
calendar views.

**NETechConnect is an aggregator, not an organizer.** Every event links to its original event
page, which is always the place to get details and register. The site never creates calendar
invites or calendar files, sends reminders, or handles registration, RSVP, tickets, or payments
(constitution, Principle II).

## How it works

- **Discovery** (`discovery/`, Python): scheduled GitHub Actions jobs collect events from known
  sources (iCal feeds, structured event data, RSS) and look for new groups across event
  platforms, organization websites, web search, newsletters, and local tech news.
- **Data** (`data/`): everything is stored as versioned, public data files in this repository.
- **Website** (`web/` + generated pages): a static site deployed to Cloudflare Pages.
- **Workers** (`workers/`): two small Cloudflare Workers for source suggestions and the
  newsletter inbox.
- **Administration** happens in GitHub: a daily data pull request merges automatically after
  checks pass, and held items appear in a review pull request with approve/reject checkboxes.

## Repository layout

```text
discovery/   Python discovery pipeline and site generator (package "netc")
web/         Static front-end assets, security headers, accessibility tests
workers/     Cloudflare Workers (TypeScript)
data/        Versioned event, source, and review data
docs/        Operations, reviews, and coverage checks
specs/       Spec-driven development artifacts (spec, plan, tasks)
```

## Running it

- [`docs/operations.md`](docs/operations.md): the runbook. It covers what runs when, the secrets
  and how to rotate them, how to pause discovery, and backup and restore.
- [`docs/admin-guide.md`](docs/admin-guide.md): reviewing held events, overrides, managing
  sources, and reading the Discovery health issue.
- [`docs/operations/metrics.md`](docs/operations/metrics.md) (monthly) and
  [`docs/coverage/`](docs/coverage/README.md) (quarterly): checking that the site does its job.
- [`docs/reviews/`](docs/reviews/): the security, accessibility and performance reviews.

## Getting started

See the validation guide in
[`specs/001-event-aggregator/quickstart.md`](specs/001-event-aggregator/quickstart.md) for
prerequisites, run modes, and how to verify each user story.

## Security

Please report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
