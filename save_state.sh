#!/usr/bin/env bash
# Commit the agent's memory (data/*.json) back to the repo.
set -e
git config user.name "jannah-agent"
git config user.email "jannah-agent@users.noreply.github.com"
git add data
git diff --cached --quiet && exit 0
git commit -qm "agent: $1"
for i in 1 2 3; do
  git pull -q --rebase && git push -q && exit 0
  sleep 5
done
exit 1
