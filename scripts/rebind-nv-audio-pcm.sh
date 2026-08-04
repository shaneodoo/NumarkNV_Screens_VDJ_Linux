#!/usr/bin/env bash
# Restore NV Audio ALSA PCM after libusb claims MIDI interface 1.
#
# Usage: rebind-nv-audio-pcm.sh [sysfs-name]
#   sysfs-name e.g. 1-4.2 (from /sys/bus/usb/devices/)
#
# bind/unbind need root. Optional sudoers line (once):
#   shane ALL=(root) NOPASSWD: /home/shane/src/nv-screens/scripts/rebind-nv-audio-pcm.sh
set -euo pipefail

log() { echo "[nv-rebind] $*"; }

# Already have PCM + MIDI?
if grep -q '15e4:1033' /proc/asound/card*/usbid 2>/dev/null \
  && amidi -l 2>/dev/null | grep -qi 'NV Audio'; then
  log "PCM + NV Audio MIDI already present"
  exit 0
fi

DEV="${1:-}"
if [[ -z "$DEV" ]]; then
  # Discover by idProduct
  for d in /sys/bus/usb/devices/*; do
    [[ -f "$d/idVendor" && -f "$d/idProduct" ]] || continue
    v=$(cat "$d/idVendor" 2>/dev/null || true)
    p=$(cat "$d/idProduct" 2>/dev/null || true)
    if [[ "$v" == "15e4" && "$p" == "1033" ]]; then
      DEV=$(basename "$d")
      break
    fi
  done
fi
if [[ -z "$DEV" || ! -d "/sys/bus/usb/devices/$DEV" ]]; then
  log "NV Audio USB device not found"
  exit 1
fi

run() {
  if [[ -w /sys/bus/usb/drivers/snd-usb-audio/bind ]]; then
    "$@"
  elif command -v sudo >/dev/null && sudo -n true 2>/dev/null; then
    sudo -n "$@"
  else
    # Re-exec whole script under sudo -n if allowed
    if command -v sudo >/dev/null && [[ -z "${NV_REBIND_ROOT:-}" ]]; then
      export NV_REBIND_ROOT=1
      exec sudo -n "$0" "$DEV"
    fi
    log "need root to bind PCM (sudo -n $0)"
    exit 2
  fi
}

DRV=/sys/bus/usb/drivers/snd-usb-audio
for ifn in 0 2; do
  IF="${DEV}:1.${ifn}"
  [[ -d "/sys/bus/usb/devices/$IF" ]] || continue
  if [[ -e "/sys/bus/usb/devices/$IF/driver" ]]; then
    echo "$IF" | run tee "$DRV/unbind" >/dev/null 2>&1 || true
    sleep 0.05
  fi
  echo "$IF" | run tee "$DRV/bind" >/dev/null 2>&1 || {
    log "bind failed for $IF"
  }
done
sleep 0.4
if grep -q '15e4:1033' /proc/asound/card*/usbid 2>/dev/null; then
  card=$(grep -l '15e4:1033' /proc/asound/card*/usbid | head -1 | sed 's|.*/card||;s|/usbid||')
  log "PCM restored card$card ($DEV)"
  exit 0
fi
log "PCM still missing for $DEV"
exit 1
