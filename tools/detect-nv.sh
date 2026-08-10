#!/usr/bin/env bash
# Detect connected Numark NV USB interfaces and cross-check them against
# config/nv-ids.env (the known/expected PIDs). Prints what's plugged in,
# and separately flags any 15e4 (Numark) devices whose PID ISN'T in
# config/nv-ids.env yet — e.g. a future NV II — so new hardware surfaces
# automatically instead of silently being ignored.
#
# Usage:
#   tools/detect-nv.sh            # human-readable
#   tools/detect-nv.sh --env      # KEY=VALUE lines, for sourcing/scripting
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/config/nv-ids.env"

MODE="${1:-human}"

declare -A KNOWN_NAMES=(
  ["$NV_PID_CONTROL"]="Control"
  ["$NV_PID_AUDIO"]="Audio"
  ["$NV_PID_GRAPHICS"]="Graphics"
)

FOUND_KNOWN=()
FOUND_UNKNOWN=()

for d in /sys/bus/usb/devices/*; do
  [[ -f "$d/idVendor" && -f "$d/idProduct" ]] || continue
  vid="$(cat "$d/idVendor" 2>/dev/null || true)"
  [[ "$vid" == "$NV_VID" ]] || continue
  pid="$(cat "$d/idProduct" 2>/dev/null || true)"
  [[ -n "$pid" ]] || continue

  if [[ -n "${KNOWN_NAMES[$pid]:-}" ]]; then
    FOUND_KNOWN+=("$pid:${KNOWN_NAMES[$pid]}:$(basename "$d")")
  else
    FOUND_UNKNOWN+=("$pid:$(basename "$d")")
  fi
done

if [[ "$MODE" == "--env" ]]; then
  for entry in "${FOUND_KNOWN[@]}"; do
    IFS=: read -r pid name sysfs <<<"$entry"
    echo "NV_PRESENT_${name^^}=1"
  done
  exit 0
fi

echo "Numark NV (${NV_VID}:*) USB scan:"
if ((${#FOUND_KNOWN[@]} == 0)); then
  echo "  (none of the known interfaces present)"
else
  for entry in "${FOUND_KNOWN[@]}"; do
    IFS=: read -r pid name sysfs <<<"$entry"
    echo "  ✓ $name  (${NV_VID}:${pid})  $sysfs"
  done
fi

if ((${#FOUND_UNKNOWN[@]} > 0)); then
  echo
  echo "  ! Unrecognized Numark device(s) — not in config/nv-ids.env:"
  for entry in "${FOUND_UNKNOWN[@]}"; do
    IFS=: read -r pid sysfs <<<"$entry"
    echo "    ${NV_VID}:${pid}  $sysfs"
  done
  echo "    If this is a new NV variant, add an NV_PID_* line for it in"
  echo "    config/nv-ids.env — every script picks it up automatically."
fi
