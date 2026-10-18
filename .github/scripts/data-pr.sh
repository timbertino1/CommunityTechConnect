#!/usr/bin/env bash
# Open or update the daily data PR (contracts/workflows-and-review.md, "Daily data PR").
#
# Run from the repository root after `netc discover-events`. Commits only files under data/,
# refuses to continue if anything else changed, pushes branch bot/data-<UTC date> with the
# GitHub App token in GH_TOKEN, opens the PR if needed, and turns on auto-merge.
#
#   CHECK_ONLY=1 .github/scripts/data-pr.sh   # only run the data/-only check
set -euo pipefail

changed="$(git status --porcelain=v1 --untracked-files=all)"
if [ -z "$changed" ]; then
  echo "No data changes; nothing to do."
  exit 0
fi

# Paths from porcelain v1 lines ("XY path" or "XY old -> new").
paths="$(printf '%s\n' "$changed" | cut -c4- | sed 's/^.* -> //; s/^"//; s/"$//')"
outside="$(printf '%s\n' "$paths" | grep -v '^data/' || true)"
if [ -n "$outside" ]; then
  echo "::error::Refusing to open a data PR: files outside data/ changed:"
  printf '%s\n' "$outside"
  exit 1
fi
echo "Changed files are all under data/:"
printf '%s\n' "$paths"

if [ "${CHECK_ONLY:-}" = "1" ]; then
  exit 0
fi

: "${GH_TOKEN:?GH_TOKEN (the GitHub App token) is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${BOT_SLUG:?BOT_SLUG (the App slug) is required}"

today="$(date -u +%Y-%m-%d)"
stamp="$(date -u +%Y-%m-%dT%H:%MZ)"
branch="bot/data-${today}"
bot_login="${BOT_SLUG}[bot]"
bot_id="$(gh api "/users/${BOT_SLUG}%5Bbot%5D" --jq .id)"

git config user.name "$bot_login"
git config user.email "${bot_id}+${bot_login}@users.noreply.github.com"
git checkout -B "$branch"
git add -- data
git commit --quiet -m "data: discovery run ${stamp}"
git push --force --quiet "https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" "HEAD:refs/heads/${branch}"

if gh pr view "$branch" --json state --jq .state 2>/dev/null | grep -q OPEN; then
  echo "Updated the open data PR on ${branch}."
else
  gh pr create --base main --head "$branch" \
    --title "Data update ${today}" \
    --body "Automatic update from the scheduled discovery run (${stamp}). Changes only files under \`data/\`; it merges by itself once every check passes."
fi
gh pr merge "$branch" --auto --squash
