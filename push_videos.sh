#!/usr/bin/env bash
# Put new reels on the "videos" branch (public links) and keep only the last 14 days.
set -e
SRC="$GITHUB_WORKSPACE/out/videos"
[ -d "$SRC" ] && [ -n "$(ls -A "$SRC" 2>/dev/null)" ] || { echo "no new videos"; exit 0; }
W=$(mktemp -d) && cd "$W"
git init -q
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
git config user.name "jannah-agent"
git config user.email "jannah-agent@users.noreply.github.com"
git config push.negotiate false
if git fetch -q --depth 1 origin videos 2>/dev/null; then git checkout -q FETCH_HEAD; fi
cp "$SRC"/*.mp4 .
cutoff=$(date -d '14 days ago' +%Y%m%d)
for f in *.mp4; do
  d="${f%%-*}"
  if [ "$d" -lt "$cutoff" ] 2>/dev/null; then rm -f "$f"; fi
done
git checkout -q --orphan fresh
git add -A
git commit -qm "videos $(date +%F)"
git push -qf origin fresh:videos
echo "videos branch updated"
