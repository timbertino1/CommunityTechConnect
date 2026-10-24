# Operations

The runbook: what runs when, the secrets and how to rotate them, how to pause things, and how
NETechConnect is backed up and restored. Day-to-day admin (reviews, overrides, sources) is in
[`admin-guide.md`](admin-guide.md). The monthly and quarterly checks are in
[`operations/metrics.md`](operations/metrics.md) and [`coverage/`](coverage/README.md).

## What runs when

All times are UTC (Central Time is 5 hours behind in summer, 6 in winter). GitHub can start a
scheduled run several minutes late, sometimes more.

| Workflow | When | What it does |
|---|---|---|
| **Discover events** (`discover-events.yml`) | 11:00 and 23:00 daily | Reads every due source and updates `data/` through a bot PR that merges itself once CI passes. Updates the Discovery health issue. On the 1st of the month it also checks past events' original pages (T118). |
| **Deploy site** (`deploy.yml`) | 11:30 and 23:30 daily, on every push to `main`, and by hand | Validates `data/`, builds the site and deploys it to Cloudflare Pages. The timed runs move ended events to Past even when no data changed. |
| **Discover sources** (`discover-sources.yml`) | Mondays 12:00 | The weekly hunt for new groups (web search, links, news, newsletters, gap checks, visitor suggestions). New sources start on probation. |
| **Review PR** (`review-pr.yml`) | When the review queue on `main` changes, and by hand | Opens or refreshes the review PR (branch `review/open`). |
| **Apply review** (`apply-review.yml`) | When the review PR is merged | Applies your approve and reject ticks through a bot PR. |
| **CI** (`ci.yml`) | Every PR and push to `main` | The six required checks. |

To run one now: **Actions → the workflow → Run workflow** (for the ones that allow it).

## Secrets: what they are, and how to rotate them

Values live only at the providers and in GitHub's encrypted secrets; this file names them and
nothing more.

**When to rotate a secret:** right away if it may have leaked (for example, after a GitHub secret
scanning alert), when someone who had access no longer should, and otherwise about once a year.

**How, for a GitHub secret:**
1. Create the new value at the provider.
2. Go to **Settings → Environments → the environment → the secret → Update**.
3. Check that the next run works.
4. Only then revoke the old value at the provider.

| Secret | Where | What it's for | To rotate | If it's missing |
|---|---|---|---|---|
| `OPENAI_API_KEY` | `discovery` | The AI second opinion for undecided events, and reading newsletters | platform.openai.com → API keys → create a key for the project, update the secret, then revoke the old key | No AI: undecided events wait for review, and newsletters aren't read |
| `SEARCH_API_KEY` | `discovery` | Tavily web search in the weekly hunt | app.tavily.com → API keys | The web-search channel is skipped |
| `EVENTBRITE_TOKEN` | `discovery` | Eventbrite's API, for Eventbrite organizer sources | Eventbrite → Account settings → Developer links → API keys → regenerate the private token | Eventbrite sources fail, and the health issue says so |
| `CLOUDFLARE_KV_TOKEN` | `discovery` | Reading and clearing the newsletter and suggestion inboxes | Cloudflare → My Profile → API Tokens → this token → **Roll** | Newsletters and suggestions wait in KV (up to 30 days); the run report says it couldn't read them |
| `BOT_APP_PRIVATE_KEY` | `discovery` | The bot's GitHub App: data PRs, the review PR, the health issue | GitHub → Settings → Developer settings → GitHub Apps → the app → **Generate a private key**. Paste the whole `.pem` file into the secret, then delete the old key there | No data PRs, no review PR, no health issue updates |
| `BOT_APP_ID` | `discovery` | The App's id (not secret, but kept with its key) | Doesn't change | As above |
| `KV_NEWSLETTERS_ID` | `discovery` | The `NEWSLETTERS` namespace id (not secret) | Only if the namespace is recreated | Newsletters aren't read |
| `CLOUDFLARE_ACCOUNT_ID` | `discovery` (a variable) and `production` | Which Cloudflare account (not secret) | Doesn't change | Nothing on Cloudflare can be reached |
| `CLOUDFLARE_API_TOKEN` | `production` | Deploying the site to Cloudflare Pages | Cloudflare → My Profile → API Tokens → this token → **Roll** | The site stays as last deployed |
| `TURNSTILE_SECRET` | Suggest Worker | Checking the form's Turnstile tokens | Cloudflare → Turnstile → the widget → rotate the secret key, then `npx wrangler secret put TURNSTILE_SECRET --env suggest` | Every suggestion is refused ("That didn't go through") |
| `IP_HASH_SALT` | Suggest Worker | Salting the hourly rate-limit counters | Any new long random value: `npx wrangler secret put IP_HASH_SALT --env suggest` (the counters simply start over) | Rate limits rely on a predictable hash; set it |
| `OWNER_FORWARD_ADDRESS` | Inbox Worker | Where subscription-confirmation emails go | `npx wrangler secret put OWNER_FORWARD_ADDRESS --env inbox` | Confirmation emails are dropped |

`KV_SUGGESTIONS_ID` in `discovery` is unused (the workflow passes the public id) and can be
deleted.

Worker secrets are set from `workers/`, in your own terminal. Until T147/T148 add a deploy
token, Worker deploys also run from there: `npx wrangler deploy --env <suggest|inbox>`.

## Pausing things

| To pause | Do this | To resume |
|---|---|---|
| **All discovery** (the site stays up) | **Actions → Discover events → ⋯ → Disable workflow**, and the same for **Discover sources** | **Enable workflow** on each. While they're off, the health issue isn't updated; once they're back, it notes how old the data was. The site keeps deploying twice a day, so ended events still move to Past. |
| **Only the weekly hunt for new groups** | Disable **Discover sources** | Enable it |
| **One source** | Set `status: paused` in its file in `data/sources/`, by PR ([admin guide](admin-guide.md#managing-sources)) | Set it back to `active` |
| **The AI** | Delete `OPENAI_API_KEY` from the `discovery` environment | Add a key again |
| **Newsletter intake** | Set `ALLOWED_SENDERS = ""` in `workers/wrangler.toml` and redeploy the inbox Worker; all mail is then dropped | Restore the list and redeploy |
| **The suggestion form** | Set `SUGGEST_ENDPOINT` to `None` in `discovery/src/netc/site/build.py`, by PR. The page, its links and its header block are gone at the next deploy | Set the Worker's URL again |
| **The whole site** (a last resort) | Cloudflare → Workers & Pages → `netechconnect` → disable or delete the deployment | Run **Deploy site** (it recreates the project if needed) |

If you disable a discovery workflow by hand and leave the other one running, the health issue
shows the disabled one as switched off by hand (T145).

## What is backed up, and where

**The GitHub repository is the backup.** Everything the site is made from is in git, with its
full history: the code, every event, source, candidate, review decision and override (`data/`),
the site's templates, styles and fonts (`web/`), the Workers' code and configuration
(`workers/`), and the workflows. Every clone is a complete copy, so keep one on your own computer
up to date (`git pull` on `main` now and then) as an off-GitHub copy.

**Not in git, on purpose:**

| What | Where it lives | If it's lost |
|---|---|---|
| Secrets (API keys, tokens, the bot's private key) | GitHub environments `discovery` and `production`; Cloudflare Worker secrets | Create new ones at each provider and set them again (names below). |
| Newsletters waiting to be read | Workers KV `NEWSLETTERS`, 30-day expiry | Nothing to restore: newer newsletters keep coming. |
| Visitors' suggestions waiting to be read | Workers KV `SUGGESTIONS`, 30-day expiry | Nothing to restore; notes are private and short-lived by design. |
| The Turnstile widget (site key in `discovery/src/netc/site/build.py`) | Cloudflare dashboard | Create a widget again (hostnames below), then update the site key and the Worker's `TURNSTILE_SECRET`. |
| Repository settings: the "Protect main" ruleset, environments, the bot's GitHub App | GitHub | Recreate them as described in `docs/reviews/security-review.md` ("Automated checks"). |

The secrets to set again after a loss are listed above, under "Secrets".

## Restoring

**The site looks wrong, or a bad data change was merged.** Revert the PR on GitHub (the PR's
**Revert** button opens a new PR; merge it). The Deploy workflow then rebuilds the site from `main`.
To redeploy without any change: **Actions → Deploy site → Run workflow**.

**The Cloudflare Pages project is gone.** Run **Deploy site** again: it creates the
`netechconnect` project if it doesn't exist, then deploys. After launch, reconnect the custom
domain (T156).

**A Worker is gone or broken.** From `workers/`, run `npx wrangler deploy --env suggest` and
`npx wrangler deploy --env inbox`. If a Worker had to be recreated, set its secrets again with
`npx wrangler secret put <NAME> --env <suggest|inbox>`. The KV namespace ids are in
`workers/wrangler.toml`. If a namespace itself is gone, create it with
`npx wrangler kv namespace create <NAME>` and put the new id in `wrangler.toml` (and, for
newsletters, in the `KV_NEWSLETTERS_ID` secret).

**The Turnstile widget is gone.** Create it again (Cloudflare → Turnstile → Add widget, mode
Managed) with the hostnames `netechconnect.pages.dev`, `netechconnect.com` and
`www.netechconnect.com`. Put its site key in `TURNSTILE_SITE_KEY` in
`discovery/src/netc/site/build.py`, and its secret key in the suggest Worker's `TURNSTILE_SECRET`.

**The GitHub repository is gone.** From your up-to-date clone:
1. Create an empty repository and push `main` to it (`git remote set-url origin <new URL>`, then `git push -u origin main`).
2. Recreate the `discovery` and `production` environments, each limited to the `main` branch, with the secrets above.
3. Recreate the "Protect main" ruleset: require PRs and the six status checks, and block deletion and force-pushes.
4. Install the bot's GitHub App on the new repository.
5. Run **Deploy site**.

## Rebuilding the site from a clone (and checking it)

This is how T141 checked the backup. The same steps rebuild the site anywhere.

```sh
git clone https://github.com/timbertino1/CommunityTechConnect.git netc && cd netc
cd discovery && uv sync --locked && uv run netc validate-data --data-dir ../data
cd ../web && npm ci && npm run build:vendor
cd ../discovery && NETC_SITE_DOMAIN=netechconnect.pages.dev \
  uv run netc build-site --data ../data --out ../dist --web ../web --now <time>
```

`--now` is the build's clock. To reproduce a deploy exactly, use its `generated_at` from
`/data/meta.json`. On Windows, clone into a short path (e.g. `C:\Users\you\AppData\Local\Temp\r`):
some event page paths are long enough to hit the 260-character limit.

### Test record: 2026-10-24 (T141)

- **What:** a fresh clone of the public repository at `634a46e` (the deployed commit), built with
  `--now 2026-10-24T17:55:14Z` (the live site's `generated_at`).
- **`netc validate-data`:** 40 files valid.
- **Build:** 151 pages, 172 files.
- **Compared with the live site, byte for byte:** **all 171 served files identical** (every page,
  stylesheet, script, font and data file). The 172nd, `_headers`, isn't served as a file; the live
  security headers matched it (5 of 5 on `/`, 5 of 5 on `/suggest/`).
- **Result: the deployed site can be rebuilt exactly from the repository alone.**
