#!/bin/sh
# Keep a server's copies of Studios in step with the PC's. Run it from cron once a minute, as the clones' owner:
#
#   * * * * *  flock -n /tmp/studio-sync.lock /path/to/home/tool/deploy/sync.sh studio-app [/path/to/another/home ...] >> /var/log/studio-sync.log 2>&1
#
# For this home and each other one named, it commits what was changed on the phone, takes the PC's commits and
# pushes. When the commits it took change the tool itself (this home's tool/), it restarts the page's container
# (named by the first argument, several with commas between; "" for none) so the page runs the new code.
set -u
home=$(cd "$(dirname "$0")/../.." && pwd)
container=${1:-}
[ $# -gt 0 ] && shift
before=$(git -C "$home" rev-parse HEAD:tool 2>/dev/null)
for one in "$home" "$@"; do
  said=$(python3 "$home/tool/studio.py" --home "$one" sync --commit always 2>&1)
  [ "$said" = "Already in step." ] || echo "$(date -u +%FT%TZ) $(basename "$one"): $said"
done
after=$(git -C "$home" rev-parse HEAD:tool 2>/dev/null)
if [ -n "$container" ] && [ "$before" != "$after" ]; then
  for one in $(echo "$container" | tr ',' ' '); do  # the page's container, and the share server's after a comma
    docker restart "$one" >/dev/null && echo "$(date -u +%FT%TZ) the tool changed: restarted $one"
  done
fi
