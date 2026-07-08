#!/usr/bin/env bash
# AgentScaffold afterFileEdit hook: keep the knowledge graph fresh.
#
# Non-blocking + single-flight: rapid multi-file edits never stack. At most one
# incremental index runs at a time; if edits arrive while it runs, exactly one
# more (coalesced) index runs afterward so nothing is left stale. The hook
# returns immediately with "{}" so Cursor is never blocked.
#
# Disable with SCAFFOLD_HOOK_DISABLE=1 or by deleting .cursor/hooks.json.
set -uo pipefail

# Cursor passes JSON on stdin (file_path, edits); consume and ignore it.
cat >/dev/null 2>&1 || true

emit() { printf '%s\n' '{}'; }

if [ "${SCAFFOLD_HOOK_DISABLE:-0}" = "1" ]; then
  emit
  exit 0
fi

scaffold_bin="/Users/daverobb/agentscaffold/.venv/bin/scaffold"
state_dir=".scaffold"
lock_dir="$state_dir/index.lock"
req_stamp="$state_dir/index.request"
success_stamp="$state_dir/index.last_success"
log_file="$state_dir/index-hook.log"
min_interval_seconds=0
mkdir -p "$state_dir" 2>/dev/null || true

now=$(date +%s)

if [ "$min_interval_seconds" -gt 0 ] && [ ! -d "$lock_dir" ] && [ -f "$success_stamp" ]; then
  last_success=$(cat "$success_stamp" 2>/dev/null || echo 0)
  if [ $((now - last_success)) -lt "$min_interval_seconds" ]; then
    emit
    exit 0
  fi
fi

# Record this edit as an index request (used to coalesce a trailing run).
printf '%s\n' "$now" > "$req_stamp" 2>/dev/null || true

# Reap a stale lock left behind by a killed indexer (older than 10 minutes).
if [ -d "$lock_dir" ]; then
  lock_mtime=$(stat -f %m "$lock_dir" 2>/dev/null \
    || stat -c %Y "$lock_dir" 2>/dev/null || echo "$now")
  if [ $((now - lock_mtime)) -gt 600 ]; then
    rmdir "$lock_dir" 2>/dev/null || true
  fi
fi

# Single-flight: acquire the lock or let the running indexer pick up our request.
if mkdir "$lock_dir" 2>/dev/null; then
  (
    trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT
    while :; do
      start=$(date +%s)
      "$scaffold_bin" index --incremental >> "$log_file" 2>&1 || true
      date +%s > "$success_stamp" 2>/dev/null || true
      req=$(cat "$req_stamp" 2>/dev/null || echo 0)
      [ "$req" -le "$start" ] && break
    done
  ) >/dev/null 2>&1 &
  disown 2>/dev/null || true
fi

emit
exit 0
