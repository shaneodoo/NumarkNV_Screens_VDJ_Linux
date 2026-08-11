#!/usr/bin/env bash
# Detect connected Numark NV (or compatible) USB interfaces and optionally
# write config/nv-ids.env from what is actually plugged in.
#
# Usage:
#   tools/detect-nv.sh              # human-readable report
#   tools/detect-nv.sh --env        # KEY=VALUE for shell (presence flags)
#   tools/detect-nv.sh --write      # rewrite config/nv-ids.env from USB scan
#   tools/detect-nv.sh --write /path/to/config/nv-ids.env
#
# Classification uses sysfs product strings when present (Control / Audio /
# Graphics). Falls back to stock Numark NV product IDs if the deck is unplugged
# so a first-time install still has a usable config.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-human}"
OUT_PATH="${2:-}"

# Stock Numark NV factory identity (product, not machine-specific).
# Used only when the device is not connected at detect time.
STOCK_VID="15e4"
STOCK_PID_CONTROL="1005"
STOCK_PID_AUDIO="1033"
STOCK_PID_GRAPHICS="2033"

# Prefer existing config for VID scan width; else stock.
if [[ -f "$ROOT/config/nv-ids.env" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/config/nv-ids.env" 2>/dev/null || true
fi
SCAN_VID="${NV_VID:-$STOCK_VID}"
SCAN_VID="${SCAN_VID,,}"

# pid -> role (control|audio|graphics)
declare -A ROLE_BY_PID=()
# role -> pid
declare -A PID_BY_ROLE=()

_classify_role() {
  local pid="$1" product="$2" role=""
  product="${product,,}"
  case "$product" in
    *control*) role=control ;;
    *audio*|*pcm*|*sound*) role=audio ;;
    *graphics*|*display*|*screen*|*lcd*) role=graphics ;;
  esac
  # Stock PID map if product string empty/unknown
  if [[ -z "$role" ]]; then
    case "$pid" in
      1005) role=control ;;
      1033) role=audio ;;
      2033) role=graphics ;;
    esac
  fi
  printf '%s' "$role"
}

_scan() {
  ROLE_BY_PID=()
  PID_BY_ROLE=()
  local d vid pid product role
  for d in /sys/bus/usb/devices/*; do
    [[ -f "$d/idVendor" && -f "$d/idProduct" ]] || continue
    vid="$(tr '[:upper:]' '[:lower:]' <"$d/idVendor" 2>/dev/null || true)"
    [[ "$vid" == "$SCAN_VID" || "$vid" == "15e4" ]] || continue
    pid="$(tr '[:upper:]' '[:lower:]' <"$d/idProduct" 2>/dev/null || true)"
    [[ -n "$pid" ]] || continue
    product=""
    [[ -f "$d/product" ]] && product="$(tr -d '\n' <"$d/product" 2>/dev/null || true)"
    role="$(_classify_role "$pid" "$product")"
    [[ -n "$role" ]] || continue
    ROLE_BY_PID["$pid"]="$role"
    # First wins per role (stable sysfs order)
    if [[ -z "${PID_BY_ROLE[$role]:-}" ]]; then
      PID_BY_ROLE["$role"]="$pid"
    fi
  done
}

_write_env_file() {
  local path="$1"
  local vid control audio graphics source_note
  vid="${SCAN_VID}"
  # Prefer live scan; fill gaps from stock NV
  control="${PID_BY_ROLE[control]:-}"
  audio="${PID_BY_ROLE[audio]:-}"
  graphics="${PID_BY_ROLE[graphics]:-}"
  source_note="Detected from USB at install/detect time."
  if [[ -z "$control" && -z "$audio" && -z "$graphics" ]]; then
    source_note="Device not connected — stock Numark NV factory IDs (re-run with deck plugged: tools/detect-nv.sh --write)."
    control="$STOCK_PID_CONTROL"
    audio="$STOCK_PID_AUDIO"
    graphics="$STOCK_PID_GRAPHICS"
    vid="$STOCK_VID"
  else
    [[ -n "$control" ]] || control="$STOCK_PID_CONTROL"
    [[ -n "$audio" ]] || audio="$STOCK_PID_AUDIO"
    [[ -n "$graphics" ]] || graphics="$STOCK_PID_GRAPHICS"
  fi

  mkdir -p "$(dirname "$path")"
  cat >"$path" <<EOF
# Numark NV — canonical USB identity (single source of truth)
#
# Written by tools/detect-nv.sh / install.sh from the machine that ran install.
# Do not commit machine-local copies with personal paths; this file only holds
# USB VID/PIDs (hex, no 0x prefix).
#
# $source_note
#
# Re-scan and overwrite:
#   tools/detect-nv.sh --write
#   tools/detect-nv.sh --write /path/to/config/nv-ids.env
#
# Format: KEY=VALUE — shell-sourceable; parsed by nv_screens/ids.py.

NV_VID=$vid

# Product IDs (one physical controller = multiple USB interfaces)
NV_PID_CONTROL=$control
NV_PID_AUDIO=$audio
NV_PID_GRAPHICS=$graphics
EOF
  echo "Wrote $path"
  echo "  NV_VID=$vid"
  echo "  NV_PID_CONTROL=$control"
  echo "  NV_PID_AUDIO=$audio"
  echo "  NV_PID_GRAPHICS=$graphics"
}

_scan

if [[ "$MODE" == "--write" ]]; then
  target="${OUT_PATH:-$ROOT/config/nv-ids.env}"
  _write_env_file "$target"
  exit 0
fi

if [[ "$MODE" == "--env" ]]; then
  for role in control audio graphics; do
    if [[ -n "${PID_BY_ROLE[$role]:-}" ]]; then
      echo "NV_PRESENT_${role^^}=1"
      echo "NV_PID_${role^^}=${PID_BY_ROLE[$role]}"
    fi
  done
  echo "NV_VID=${SCAN_VID}"
  exit 0
fi

echo "Numark / vendor ${SCAN_VID}:* USB scan:"
if ((${#PID_BY_ROLE[@]} == 0)); then
  echo "  (no matching interfaces present)"
  echo "  Stock factory IDs would be used on --write:"
  echo "    VID=$STOCK_VID CONTROL=$STOCK_PID_CONTROL AUDIO=$STOCK_PID_AUDIO GRAPHICS=$STOCK_PID_GRAPHICS"
else
  for role in control audio graphics; do
    if [[ -n "${PID_BY_ROLE[$role]:-}" ]]; then
      echo "  ✓ ${role^}  (${SCAN_VID}:${PID_BY_ROLE[$role]})"
    else
      case "$role" in
        control) echo "  · Control   (not seen — stock $STOCK_PID_CONTROL on --write)" ;;
        audio)   echo "  · Audio     (not seen — stock $STOCK_PID_AUDIO on --write)" ;;
        graphics) echo "  · Graphics  (not seen — stock $STOCK_PID_GRAPHICS on --write)" ;;
      esac
    fi
  done
fi

# Unrecognized 15e4 PIDs not classified
echo
unknown=0
for d in /sys/bus/usb/devices/*; do
  [[ -f "$d/idVendor" && -f "$d/idProduct" ]] || continue
  vid="$(tr '[:upper:]' '[:lower:]' <"$d/idVendor" 2>/dev/null || true)"
  [[ "$vid" == "15e4" || "$vid" == "$SCAN_VID" ]] || continue
  pid="$(tr '[:upper:]' '[:lower:]' <"$d/idProduct" 2>/dev/null || true)"
  [[ -n "$pid" ]] || continue
  if [[ -z "${ROLE_BY_PID[$pid]:-}" ]]; then
    product=""
    [[ -f "$d/product" ]] && product="$(tr -d '\n' <"$d/product" 2>/dev/null || true)"
    echo "  ! Unclassified ${vid}:${pid}  $(basename "$d")  ${product:-}"
    unknown=1
  fi
done
if (( unknown )); then
  echo "    If this is your controller, classify it (product string / nv-ids.env) and re-run --write."
fi
echo
echo "Write config:  $0 --write"
