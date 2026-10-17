#!/usr/bin/env bash
# Copy the rlogs of a route from the device: fetch_route.sh <route> <dest dir> [ssh host]
set -e

ROUTE="$1"
DEST="$2"
HOST="${3:-comma4}"

if [ -z "$ROUTE" ] || [ -z "$DEST" ]; then
  echo "usage: $0 <route, e.g. 0000018b--91b661fef8> <dest dir> [ssh host]"
  exit 1
fi

mkdir -p "$DEST"
for seg in $(ssh "$HOST" "ls -d /data/media/0/realdata/${ROUTE}--* | sed 's/.*--//' | sort -n"); do
  scp -q "$HOST:/data/media/0/realdata/${ROUTE}--${seg}/rlog.zst" "$DEST/rlog_${seg}.zst"
done
echo "copied $(ls "$DEST"/rlog_*.zst | wc -l | tr -d ' ') segments to $DEST"
