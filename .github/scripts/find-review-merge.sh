#!/usr/bin/env bash
# Is the pushed commit the merge of a review PR? (contracts/workflows-and-review.md, "Review PR")
#
# Looks up the PR merged as COMMIT_SHA. If it came from branch review/open, saves the three
# GitHub API responses `netc apply-review` checks (the PR, the merger's permission, and when
# the description was last edited) to OUT and sets the step output `number`. Otherwise it
# exits quietly, which is the case for almost every push to main.
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN (the GitHub App token) is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${COMMIT_SHA:?COMMIT_SHA is required}"
: "${OUT:?OUT (a directory for the API responses) is required}"
mkdir -p "$OUT"

number="$(gh api "repos/${GITHUB_REPOSITORY}/commits/${COMMIT_SHA}/pulls" --jq \
  "[.[] | select(.head.ref == \"review/open\" and .merged_at != null and .merge_commit_sha == \"${COMMIT_SHA}\")][0].number // empty")"
if [ -z "$number" ]; then
  echo "This push is not the merge of a review PR; nothing to apply."
  exit 0
fi

gh api "repos/${GITHUB_REPOSITORY}/pulls/${number}" > "$OUT/pr.json"
merger="$(jq -r '.merged_by.login // empty' "$OUT/pr.json")"
if [ -z "$merger" ]; then
  echo "::error::Review PR #${number} does not say who merged it."
  exit 1
fi
gh api "repos/${GITHUB_REPOSITORY}/collaborators/${merger}/permission" > "$OUT/permission.json"
gh api graphql \
  -f query='query($owner: String!, $name: String!, $number: Int!) {
    repository(owner: $owner, name: $name) { pullRequest(number: $number) { lastEditedAt } }
  }' \
  -f owner="${GITHUB_REPOSITORY%%/*}" -f name="${GITHUB_REPOSITORY#*/}" -F number="$number" \
  > "$OUT/edits.json"

echo "Found review PR #${number}, merged by ${merger}."
echo "number=${number}" >> "${GITHUB_OUTPUT:-/dev/null}"
