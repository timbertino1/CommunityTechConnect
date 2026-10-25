# Quarterly security review

When the independent pre-launch review (T140) was withdrawn on 2026-10-25, the owner asked for
constant internal review instead. Day to day, that's the automated checks on every pull request
and the security pass Claude Code does on every code change. Every quarter, this review steps
back and checks the whole system again.

**When:** the first week of January, April, July and October. The Discovery health issue
reminds the owner (the `security-review` item) and comments once.
**Who:** Claude Code runs it ("run the quarterly security review"); the owner checks two
dashboards (step 6). It takes about an hour.
**Record:** each review goes in `docs/reviews/security-<YYYY>-Q<n>.md` and gets a line in the log
at the end of this file. The first full review is [security-review.md](security-review.md)
(T139, Oct 2026), and its list of good places to start still applies.

## The checklist

Each step says what to run or look at, and what counts as a pass. A failure is a finding:
rate it critical, high, medium, low or info, as in T139. Fix critical and high ones before
anything else; agree the rest with the owner.

### 1. Automated checks, on `main`

```bash
cd discovery && uv sync --locked && uv run pytest -m security && uv run pip-audit
cd ../workers && npm ci && npx vitest run && npm audit --audit-level=high
cd ../web && npm ci && npm audit --audit-level=high
gh run list --workflow ci.yml --branch main -L1      # gitleaks and the rest, on the latest commit
gh api repos/timbertino1/CommunityTechConnect/dependabot/alerts --jq '[.[]|select(.state=="open")]|length'
gh api repos/timbertino1/CommunityTechConnect/secret-scanning/alerts --jq '[.[]|select(.state=="open")]|length'
```

Pass: every test passes, no audit finds a high or critical advisory, CI on `main` is green, and
both alert counts are 0.

### 2. What changed since the last review

```bash
git log --oneline <last review's commit>..main -- discovery/src workers .github web/_headers web/js
```

Read each change against the threat summary in
[plan.md](../../specs/001-event-aggregator/plan.md) and the contracts in
`specs/001-event-aggregator/contracts/`. Look hardest at:
- anything that fetches a URL (`discovery/src/netc/fetch/`, finders, connectors): it must go
  through `SafeHttp` or `SafeApi`;
- anything that puts outside text into a page (`pipeline/sanitize.py`, `site/build.py`,
  templates): no `|safe`, and no new inline script;
- the Workers (`workers/suggest/`, `workers/inbox/`): every check still in front of every write;
- workflows: permissions still `contents: read` by default, actions pinned to a full SHA, and
  secrets only in the jobs that need them.

Pass: no change weakens a control, or each one that does is a finding.

### 3. Dependencies and pins

- `discovery/pyproject.toml`: each `exclude-newer-package` exception (a package allowed newer than
  the 14-day rule, for a security fix) is still needed. Remove any whose date is now past 14 days.
- `.github/workflows/*.yml`: each action is pinned to a full commit SHA, with the version in a
  comment. Dependabot proposes updates; check that none is waiting more than a month.
- `web/package.json` and `workers/package.json`: exact versions, no package that nothing uses.

### 4. The live site and Workers

```bash
curl -sI https://netechconnect.com/            # and /suggest/ and an event page
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://www.netechconnect.com/
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Origin: https://netechconnect.com' \
  -H 'Content-Type: application/json' --data '{"url":"https://example.org/"}' \
  https://netc-suggest.tim-bertino.workers.dev/suggest
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Origin: https://evil.example' \
  -H 'Content-Type: application/json' --data '{"url":"https://example.org/"}' \
  https://netc-suggest.tim-bertino.workers.dev/suggest
```

Pass: the headers match
[contracts/site-urls.md](../../specs/001-event-aggregator/contracts/site-urls.md) exactly
(Turnstile allowed only on `/suggest/`); `www` answers 301 to the main address; the suggest
Worker answers 400 without a Turnstile token and 403 for a foreign origin.

### 5. GitHub settings

```bash
R=repos/timbertino1/CommunityTechConnect
gh api $R --jq '{visibility, sa: .security_and_analysis}'
gh api $R/actions/permissions/workflow
gh api $R/actions/permissions/selected-actions
gh api $R/environments --jq '[.environments[].name]'
gh api $R/rulesets/$(gh api $R/rulesets --jq '.[0].id') --jq '{enforcement, bypass: (.bypass_actors|length), rules: [.rules[].type]}'
gh secret list; gh secret list --env discovery; gh secret list --env production; gh variable list
```

Pass: Dependabot security updates, secret scanning and push protection on; workflows read-only
by default and unable to approve PRs; only GitHub's actions plus the named ones allowed; the
`main` ruleset active with no bypass, requiring all six checks; and every secret listed in
[operations.md](../operations.md#secrets-what-they-are-and-how-to-rotate-them), with nothing
extra.

### 6. Two dashboards (the owner)

1. **Cloudflare:** <https://dash.cloudflare.com/profile/api-tokens>. Pass: only the tokens
   operations.md lists, each with only its listed permissions, none you don't recognise. Delete
   anything unknown, then tell Claude Code.
2. **GitHub:** <https://github.com/settings/security> and
   <https://github.com/settings/tokens>. Pass: two-factor authentication is on, no session you
   don't recognise, and no personal access token you don't use.

### 7. Write it up

Record each step's result, the findings and what was done about them in
`docs/reviews/security-<YYYY>-Q<n>.md`, add a line to the log below, and open a PR.

## Log

| Quarter | Record | Result |
|---|---|---|
| 2026 Q4 | [security-review.md](security-review.md) (T139) and [final checkpoint](../checkpoints/final.md) (T149) | No critical or high findings; one medium fixed |
