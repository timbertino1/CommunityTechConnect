# Operations

How NETechConnect is backed up and how to restore it. (T146 adds the rest of the runbook:
schedules, rotating secrets, pausing discovery.)

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

**Secret names**, never the values:
- **`discovery` environment:** `BOT_APP_ID`, `BOT_APP_PRIVATE_KEY`, `CLOUDFLARE_KV_TOKEN`, `EVENTBRITE_TOKEN`, `KV_NEWSLETTERS_ID`, `OPENAI_API_KEY`, `SEARCH_API_KEY`, and the variable `CLOUDFLARE_ACCOUNT_ID`. (`KV_SUGGESTIONS_ID` is unused and can be deleted.)
- **`production` environment:** `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`.
- **Suggest Worker:** `TURNSTILE_SECRET`, `IP_HASH_SALT`.
- **Inbox Worker:** `OWNER_FORWARD_ADDRESS`.

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
