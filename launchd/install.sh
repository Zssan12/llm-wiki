#!/bin/sh
# Fill the placeholders in the three LaunchAgent templates and write them to ~/Library/LaunchAgents
# (or the directory given as $1). Loading them is left to you: the commands are printed at the end.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
wiki=$(dirname "$here")
dest=${1:-"$HOME/Library/LaunchAgents"}
# claude (and codex/agy if you use them) must be on this PATH; launchd starts jobs with a minimal one
path="$HOME/.local/bin:$(dirname "$(command -v claude 2>/dev/null || echo /usr/bin/claude)"):/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "$dest"
for f in "$here"/*.plist; do
  sed -e "s|__WIKI__|$wiki|g" -e "s|__HOME__|$HOME|g" -e "s|__PATH__|$path|g" -e "s|__USER__|$(id -un)|g" \
    "$f" > "$dest/$(basename "$f")"
  echo "wrote $dest/$(basename "$f")"
done
echo
echo "Load them with:"
for f in "$here"/*.plist; do
  echo "  launchctl bootstrap gui/\$(id -u) $dest/$(basename "$f")"
done
