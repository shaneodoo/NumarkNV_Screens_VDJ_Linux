#!/usr/bin/env bash
# Restore stock NV logos: optional wipe, then USB authorized 0→1 re-enum.
# Needs root (sudo -n). Sudoers example:
#   USER ALL=(root) NOPASSWD: /path/to/scripts/usb-reset-nv.sh
#
# Stock restore for Numark NV LCDs after VDJ (USB finding):
#
#   1) Zero-chrome bulk wipe  — overwrite VDJ metadata (0507/0521/0524/… blanked)
#   2) authorized 0→1         — soft re-plug → firmware logos
#
# There is NO logo SysEx in the capture. Logos = re-enum after wipe.
#
# Usage (passwordless after sudoers — path = YOUR install tree):
#   sudo -n "$ROOT/scripts/usb-reset-nv.sh"
#
# Sudoers once (replace INSTALL_ROOT with your install folder):
#   echo "$USER ALL=(root) NOPASSWD: INSTALL_ROOT/scripts/usb-reset-nv.sh" \
#     | sudo tee /etc/sudoers.d/nv-screens-restore
#   sudo chmod 440 /etc/sudoers.d/nv-screens-restore
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WIPE_PY="$ROOT/scripts/nv_zero_wipe.py"  # optional; skipped if missing
CLOSE_BULK="$ROOT/data/wake/close-bulk.bin"

# Canonical USB identity — see config/nv-ids.env (single source of truth)
# shellcheck source=/dev/null
source "$ROOT/config/nv-ids.env"

log() { echo "[nv-usb-reset] $*"; }

# ---------------------------------------------------------------------------
# Phase 1: zero wipe (user python / libusb — must NOT need root for usbfs
# if udev rules allow; may fail if another process holds devices)
# ---------------------------------------------------------------------------
phase_zero_wipe() {
  if [[ ! -f "$CLOSE_BULK" ]]; then
    log "skip zero wipe — missing $CLOSE_BULK"
    return 0
  fi
  if [[ ! -f "$WIPE_PY" ]]; then
    log "skip zero wipe — missing $WIPE_PY"
    return 0
  fi
  log "phase 1/2: bulk wipe before re-enum"
  # Run as the invoking user when possible (script may re-exec as root)
  local pyuser="${SUDO_USER:-$USER}"
  if [[ "$(id -u)" -eq 0 && -n "${SUDO_USER:-}" ]]; then
    # Prefer wipe as original user so usbfs perms / pyusb match session
    if sudo -u "$SUDO_USER" -n true 2>/dev/null; then
      sudo -u "$SUDO_USER" python3 "$WIPE_PY" || log "zero wipe failed (busy?) — continue to re-enum"
    else
      # sudo -u may not be NOPASSWD; try as root anyway
      python3 "$WIPE_PY" || log "zero wipe failed — continue to re-enum"
    fi
  else
    python3 "$WIPE_PY" || log "zero wipe failed (busy?) — continue to re-enum"
  fi
}

# ---------------------------------------------------------------------------
# Phase 2: authorized re-enum (needs root)
# ---------------------------------------------------------------------------
if [[ "$(id -u)" -ne 0 ]]; then
  # Phase 1 as user first (hold bulk while we still can)
  phase_zero_wipe
  log "phase 2/2: elevating for authorized re-enum…"
  exec sudo -n "$0" --reenum-only "$@"
fi

# Root path
if [[ "${1:-}" != "--reenum-only" ]]; then
  # Invoked already as root (sudo -n script): still try wipe as SUDO_USER
  phase_zero_wipe
else
  shift || true
  log "phase 2/2: authorized re-enum only (wipe already attempted)"
fi

syswrite() {
  local file="$1" val="$2"
  printf '%s' "$val" >"$file"
}

find_dev_path() {
  local want="$1" d
  for d in /sys/bus/usb/devices/*; do
    [[ -f "$d/idVendor" && -f "$d/idProduct" ]] || continue
    if [[ "$(cat "$d/idVendor" 2>/dev/null)" == "$NV_VID" \
       && "$(cat "$d/idProduct" 2>/dev/null)" == "$want" ]]; then
      echo "$d"
      return 0
    fi
  done
  return 1
}

reset_dev() {
  local pid="$1" name="$2" path
  path=$(find_dev_path "$pid" || true)
  if [[ -z "${path:-}" ]]; then
    log "$name ($NV_VID:$pid) not present — skip"
    return 1
  fi
  log "stock re-enum $name → $(basename "$path")"

  if [[ -f "$path/authorized" ]]; then
    log "  authorized=0 (disconnect)"
    syswrite "$path/authorized" 0
    sleep 1.3
    if [[ ! -f "$path/authorized" ]]; then
      local i
      for i in $(seq 1 24); do
        path=$(find_dev_path "$pid" || true)
        [[ -n "${path:-}" && -f "${path}/authorized" ]] && break
        sleep 0.2
      done
    fi
    if [[ -n "${path:-}" && -f "$path/authorized" ]]; then
      log "  authorized=1 (reconnect → firmware logo)"
      syswrite "$path/authorized" 1
    else
      log "  WARN could not re-authorize $name"
      return 1
    fi
    sleep 2.0
  else
    local dev
    dev=$(basename "$path")
    log "  no authorized — unbind/bind $dev"
    echo "$dev" > /sys/bus/usb/drivers/usb/unbind || true
    sleep 1.3
    echo "$dev" > /sys/bus/usb/drivers/usb/bind || true
    sleep 2.0
  fi
  return 0
}

log "phase 2/2: authorized re-enum (Graphics + Audio) → stock logos"
reset_dev "$NV_PID_GRAPHICS" "Graphics" || true
reset_dev "$NV_PID_AUDIO" "Audio" || true
sleep 0.8

log "amidi after re-enum:"
amidi -l 2>/dev/null | sed 's/^/  /' || true
log "cards:"
grep -E 'Control|Graphics|Audio' /proc/asound/cards 2>/dev/null | sed 's/^/  /' || true

if amidi -l 2>/dev/null | grep -qi 'NV Graphics' \
  && amidi -l 2>/dev/null | grep -qi 'NV Audio'; then
  log "OK — wipe attempted + re-enum done (blank tiles then logos)"
  exit 0
fi
log "WARN MIDI incomplete after re-enum"
exit 1
