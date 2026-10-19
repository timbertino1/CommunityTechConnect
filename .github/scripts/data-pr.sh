#!/usr/bin/env bash
# Open or update a data PR (contracts/workflows-and-review.md, "Daily data PR").
#
# Run from the repository root after a netc command changed data/. Commits only files under
# data/ (never data/review/open.json, which belongs to the review PR), refuses to continue if
# anything else changed, pushes the branch with the GitHub App token in GH_TOKEN, opens the PR
# if needed, and turns on auto-merge. If REPORT_FILE names a Markdown report (from
# `netc discover-events --report` or `netc apply-review --report`), it is added to the PR
# description.
#
# Defaults are for the daily discovery PR; the apply-review workflow sets BRANCH, TITLE, INTRO
# and COMMIT_MESSAGE. A new daily PR closes older daily PRs that never merged (for example
# after a conflict), since it starts from the latest main and replaces them.
#
#   CHECK_ONLY=1 .github/scripts/data-pr.sh   # only run the path checks
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
if printf '%s\n' "$paths" | grep -qx 'data/review/open.json'; then
  echo "::error::Refusing to open a data PR: data/review/open.json changed (only the review PR may change it)."
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
branch="${BRANCH:-bot/data-${today}}"
title="${TITLE:-Data update ${today}}"
intro="${INTRO:-Automatic update from the scheduled discovery run (${stamp}). Changes only files under \`data/\`; it merges by itself once every check passes.}"
message="${COMMIT_MESSAGE:-data: discovery run ${stamp}}"
bot_login="${BOT_SLUG}[bot]"
bot_id="$(gh api "/users/${BOT_SLUG}%5Bbot%5D" --jq .id)"

git config user.name "$bot_login"
git config user.email "${bot_id}+${bot_login}@users.noreply.github.com"
git checkout -B "$branch"
git add -- data
git commit --quiet -m "$message"
git push --force --quiet "https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" "HEAD:refs/heads/${branch}"

body="$(mktemp)"
{
  echo "$intro"
  if [ -n "${REPORT_FILE:-}" ] && [ -s "$REPORT_FILE" ]; then
    echo
    cat "$REPORT_FILE"
  fi
} > "$body"

if gh pr view "$branch" --json state --jq .state 2>/dev/null | grep -q OPEN; then
  gh pr edit "$branch" --body-file "$body"
  echo "Updated the open data PR on ${branch}."
else
  gh pr create --base main --head "$branch" --title "$title" --body-file "$body"
fi
gh pr merge "$branch" --auto --squash

if [[ "$branch" == bot/data-* ]]; then
  gh pr list --state open --author "app/${BOT_SLUG}" --json number,headRefName \
    --jq ".[] | select(.headRefName | startswith(\"bot/data-\")) | select(.headRefName != \"${branch}\") | .number" |
    while read -r number; do
      gh pr close "$number" --delete-branch \
        --comment "Replaced by the data PR on \`${branch}\`, which starts from the latest main."
    done
fi
