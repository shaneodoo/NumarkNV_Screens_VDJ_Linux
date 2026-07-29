#!/usr/bin/env bash
# Keep Wine OFF *kernel* NV Graphics / NV Audio MIDI so:
#   - libusb owns real paint bulk
#   - facade presents Windows drivernames "NV Graphics" / "NV Audio"
#     without a second "… MIDI 1" general-midi device confusing VDJ
#
# Virtual client nv-screens-facade-midi is ALLOWED (that is the driver view).
set -euo pipefail

ONCE=0
INTERVAL=1
[[ "${1:-}" == "--once" ]] && ONCE=1

find_client() {
  local name="$1"
  aconnect -l 2>/dev/null | awk -v n="$name" '
    $1=="client" {
      id=$2; gsub(/:/,"",id)
      if (index($0, n)) { print id; exit }
    }'
}

find_kernel_client() {
  local name="$1"
  aconnect -l 2>/dev/null | awk -v n="$name" '
    $1=="client" {
      id=$2; gsub(/:/,"",id)
      if (index($0, n) && index($0, "type=kernel")) { print id; exit }
    }'
}

disc_pair() {
  local a="$1" b="$2"
  aconnect -d "$a" "$b" 2>/dev/null || true
  aconnect -d "$b" "$a" 2>/dev/null || true
}

free_kernel_display_midi() {
  local WINE GFX_KERN AUD_KERN CTL_KERN FACADE NVS i p
  WINE=$(find_client "WINE midi driver") || true
  GFX_KERN=$(find_kernel_client "NV Graphics") || true
  AUD_KERN=$(find_kernel_client "NV Audio") || true
  CTL_KERN=$(find_kernel_client "NV Control") || true
  FACADE=$(find_client "nv-screens-facade-midi") || true
  NVS=$(find_client "nv-screens") || true

  # Graphics + Audio MIDI always off Wine (facade owns those roles)
  for KERN in ${GFX_KERN:-} ${AUD_KERN:-}; do
    [[ -n "$KERN" ]] || continue
    if [[ -n "${WINE:-}" ]]; then
      for i in 0 1 2 3 4 5 6 7 8 9; do
        disc_pair "${WINE}:$i" "${KERN}:0"
      done
    fi
    if [[ -n "${NVS:-}" ]]; then
      for p in 0 1 2 3; do
        disc_pair "${NVS}:$p" "${KERN}:0"
      done
    fi
  done

  # Kernel Control: only isolate from Wine when facade is bridging it
  # (otherwise jogs would have no path). Do NOT break facade↔kernel bridge.
  if [[ -n "${CTL_KERN:-}" && -n "${FACADE:-}" && -n "${WINE:-}" ]]; then
    for i in 0 1 2 3 4 5 6 7 8 9; do
      disc_pair "${WINE}:$i" "${CTL_KERN}:0"
    done
  fi
}

if [[ "$ONCE" -eq 1 ]]; then
  free_kernel_display_midi
  echo "graphics_guard: once done (kernel Graphics+Audio MIDI; facade kept)"
  exit 0
fi

echo "graphics_guard: loop ${INTERVAL}s — Wine off kernel NV Graphics/Audio MIDI"
echo "                (nv-screens-facade-midi is allowed)"
while true; do
  free_kernel_display_midi
  sleep "$INTERVAL"
done
