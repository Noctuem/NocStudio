#!/bin/sh
# Keep a server's copy of a Studio in step with the PC's. Run it from cron once a minute, as the clone's owner:
#
#   * * * * *  flock -n /tmp/studio-sync.lock /path/to/home/tool/deploy/sync.sh studio-app >> /var/log/studio-sync.log 2>&1
#
# It commits what was changed on the phone, takes the PC's commits and pushes. When the commits it took change the
# tool itself, it restarts the page's container (named by the first argument) so the page runs the new code.
set -u
home=$(cd "$(dirname "$0")/../.." && pwd)
container=${1:-}
before=$(git -C "$home" rev-parse HEAD:tool 2>/dev/null)
said=$(python3 "$home/tool/studio.py" --home "$home" sync --commit always 2>&1)
[ "$said" = "Already in step." ] || echo "$(date -u +%FT%TZ) $said"
after=$(git -C "$home" rev-parse HEAD:tool 2>/dev/null)
if [ -n "$container" ] && [ "$before" != "$after" ]; then
  docker restart "$container" >/dev/null && echo "$(date -u +%FT%TZ) the tool changed: restarted $container"
fi
