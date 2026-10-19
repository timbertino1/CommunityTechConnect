#!/usr/bin/env bash
# Create or update the pinned Discovery health issue (contracts/workflows-and-review.md,
# "Health issue").
#
# Run from the repository root after `netc discover-events`, so the issue shows this run.
# PREVIOUS_STATUS, if set, is main's data/state/source_status.json from before the run, used to
# tell whether earlier runs' data reached main. `netc health-issue` writes the description and,
# when the owner needs to act and hasn't been told recently, an alert comment; this script only
# talks to GitHub, with the App token in GH_TOKEN (issues: write).
#
# Only the bot's own issue and the bot's own comments are read: anyone can open an issue with
# the same title or post a comment with the same marker.
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN (the GitHub App token) is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${BOT_SLUG:?BOT_SLUG (the App slug) is required}"
: "${OWNER:?OWNER (the GitHub login to mention) is required}"
export GH_REPO="$GITHUB_REPOSITORY"

title="Discovery health"
bot_login="${BOT_SLUG}[bot]"
out="${RUNNER_TEMP:-$(mktemp -d)}/health-issue"
rm -rf "$out"
mkdir -p "$out"

number="$(gh api "repos/${GITHUB_REPOSITORY}/issues?state=open&creator=${BOT_SLUG}%5Bbot%5D&per_page=100" \
  --jq "[.[] | select(.pull_request == null and .title == \"${title}\")][0].number // empty")"

: > "$out/last-alert.json"
if [ -n "$number" ]; then
  gh api --paginate "repos/${GITHUB_REPOSITORY}/issues/${number}/comments?per_page=100" \
    --jq ".[] | select(.user.login == \"${bot_login}\" and (.body | contains(\"<!-- netc-health-alert:\"))) | {created_at, body} | tojson" \
    | tail -n 1 > "$out/last-alert.json"
fi

args=(--data-dir ../data --out "$out" --owner "$OWNER" --last-alert "$out/last-alert.json")
if [ -n "${PREVIOUS_STATUS:-}" ]; then
  args+=(--previous-status "$PREVIOUS_STATUS")
fi
(cd discovery && uv run netc health-issue "${args[@]}")

if [ -z "$number" ]; then
  url="$(gh issue create --title "$title" --body-file "$out/body.md")"
  number="${url##*/}"
  echo "Opened the health issue #${number}."
  gh issue pin "$number" || echo "::warning::Couldn't pin issue #${number}; pin it by hand."
else
  gh issue edit "$number" --body-file "$out/body.md" > /dev/null
  echo "Updated the health issue #${number}."
fi

if [ -f "$out/comment.md" ]; then
  gh issue comment "$number" --body-file "$out/comment.md" > /dev/null
  echo "Posted an alert on issue #${number}."
fi
