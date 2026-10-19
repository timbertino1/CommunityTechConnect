#!/usr/bin/env bash
# Open, update or close the review PR (contracts/workflows-and-review.md, "Review PR").
#
# Run from the repository root on a fresh checkout of main, so every item it lists is already
# in main's queue. `netc review-pr` writes the title, the description and the snapshot
# data/review/open.json; this script commits only that file to branch review/open and opens or
# updates the PR with the GitHub App token in GH_TOKEN. It never turns on auto-merge: only the
# owner merges a review PR.
#
# An open review PR is left alone once any box is ticked (rewriting it would lose the ticks),
# and is otherwise refreshed at most once a day. With nothing pending, an open one is closed.
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN (the GitHub App token) is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${BOT_SLUG:?BOT_SLUG (the App slug) is required}"

branch="review/open"
snapshot="data/review/open.json"
min_hours="${MIN_HOURS_BETWEEN_UPDATES:-20}"
out="${RUNNER_TEMP:-$(mktemp -d)}/review-pr"
rm -rf "$out"
mkdir -p "$out"

state="$(gh pr view "$branch" --json state --jq .state 2>/dev/null || true)"
current=()
if [ "$state" = "OPEN" ]; then
  gh pr view "$branch" --json body --jq .body > "$out/current.md"
  current=(--current-body "$out/current.md")
fi

(cd discovery && uv run netc review-pr --data-dir ../data --out "$out" "${current[@]}")

case "$(cat "$out/status")" in
  kept)
    exit 0
    ;;
  none)
    if [ "$state" = "OPEN" ]; then
      gh pr close "$branch" --delete-branch --comment "Nothing is waiting for review any more."
    fi
    exit 0
    ;;
  ready) ;;
  *)
    echo "::error::netc review-pr wrote an unexpected status"
    exit 1
    ;;
esac

normalized() { tr -d '\r' < "$1" | sed -e 's/[[:space:]]*$//' -e '/./,$!d'; }
if [ "$state" = "OPEN" ]; then
  if diff -q <(normalized "$out/current.md") <(normalized "$out/body.md") > /dev/null; then
    echo "The open review PR is already up to date."
    exit 0
  fi
  last="$(gh api "repos/${GITHUB_REPOSITORY}/commits/${branch}" --jq .commit.committer.date)"
  age_hours=$(( ($(date -u +%s) - $(date -u -d "$last" +%s)) / 3600 ))
  if [ "$age_hours" -lt "$min_hours" ]; then
    echo "The review PR was updated ${age_hours}h ago; it is refreshed at most once a day."
    exit 0
  fi
fi

# The snapshot must be the only change.
other="$(git status --porcelain=v1 --untracked-files=all | cut -c4- | grep -vx "$snapshot" || true)"
if [ -n "$other" ]; then
  echo "::error::Refusing to update the review PR: files other than ${snapshot} changed:"
  printf '%s\n' "$other"
  exit 1
fi

title="$(cat "$out/title.txt")"
bot_login="${BOT_SLUG}[bot]"
bot_id="$(gh api "/users/${BOT_SLUG}%5Bbot%5D" --jq .id)"
git config user.name "$bot_login"
git config user.email "${bot_id}+${bot_login}@users.noreply.github.com"
git checkout -B "$branch"
git add -- "$snapshot"
# Empty when main already holds the same snapshot (a review PR merged with nothing ticked).
git commit --quiet --allow-empty -m "review: ${title}"
git push --force --quiet "https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" "HEAD:refs/heads/${branch}"

if [ "$state" = "OPEN" ]; then
  gh pr edit "$branch" --title "$title" --body-file "$out/body.md"
  echo "Updated the review PR: ${title}"
else
  gh pr create --base main --head "$branch" --title "$title" --body-file "$out/body.md"
fi
