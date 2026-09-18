#!/usr/bin/env bash
#
# Apply the repository policies of sbml2cellml: the merge settings of the
# repository, the rulesets in this directory and the branch which may deploy
# the documentation. The script is idempotent, i.e., a ruleset which already
# exists is updated instead of added a second time, so it can be run again
# after every change of the json files.
#
# The file name of a ruleset has to match the "name" in the json. A ruleset which
# is removed from this directory stays on the repository, delete it with
# `gh api -X DELETE repos/<owner>/<repo>/rulesets/<id>`.
#
# Requires the github cli (https://cli.github.com) authenticated as a user with
# admin permission on the repository:
#
#   gh auth login
#   .github/rulesets/apply.sh [owner/repo]
#
set -euo pipefail

REPO="${1:-matthiaskoenig/sbml2cellml}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "repository settings of ${REPO}"
gh api -X PATCH "repos/${REPO}" \
  -F allow_auto_merge=true \
  -F delete_branch_on_merge=true \
  -F allow_update_branch=true \
  -F allow_squash_merge=true \
  -F allow_rebase_merge=true \
  -F allow_merge_commit=false \
  --silent

for path in "${DIR}"/*.json; do
  name="$(basename "${path}" .json)"
  id="$(gh api "repos/${REPO}/rulesets" --jq "map(select(.name == \"${name}\")) | .[0].id // empty")"
  if [[ -n "${id}" ]]; then
    gh api -X PUT "repos/${REPO}/rulesets/${id}" --input "${path}" --silent
    echo "ruleset ${name} updated (${id})"
  else
    id="$(gh api -X POST "repos/${REPO}/rulesets" --input "${path}" --jq .id)"
    echo "ruleset ${name} created (${id})"
  fi
done

# The documentation workflow deploys from develop. Enabling GitHub Pages creates
# the github-pages environment with a deployment policy for the default branch
# of that moment (main here), which rejects every deployment from develop.
echo "deployment branches of the github-pages environment"
gh api -X PUT "repos/${REPO}/environments/github-pages" --silent --input - <<'JSON'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
JSON
policies="$(gh api "repos/${REPO}/environments/github-pages/deployment-branch-policies" \
  --jq '.branch_policies[].name')"
if grep -qx develop <<<"${policies}"; then
  echo "develop may deploy"
else
  gh api -X POST "repos/${REPO}/environments/github-pages/deployment-branch-policies" \
    -f name=develop -f type=branch --silent
  echo "develop may deploy (added)"
fi
