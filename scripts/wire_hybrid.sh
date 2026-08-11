#!/usr/bin/env bash
# Wire Wine MIDI to NV Control / Audio / Graphics facades and nv-screens.
#
set -euo pipefail

find_client() {
  local name="$1"
  aconnect -l 2>/dev/null | awk -v n="$name" '
    $1=="client" {
      id=$2; gsub(/:/,"",id)
      if (index($0, n)) { print id; exit }
    }'
}

# Kernel USB card only (type=kernel) — never the virtual user facade
find_kernel_client() {
  local name="$1"
  aconnect -l 2>/dev/null | awk -v n="$name" '
    $1=="client" {
      id=$2; gsub(/:/,"",id)
      if (index($0, n) && index($0, "type=kernel")) { print id; exit }
    }'
}

# User-space virtual facade (type=user)
find_user_client() {
  local name="$1"
  aconnect -l 2>/dev/null | awk -v n="$name" '
    $1=="client" {
      id=$2; gsub(/:/,"",id)
      if (index($0, n) && index($0, "type=user")) { print id; exit }
    }'
}

find_ports() {
  local cid="$1"
  local role="$2"
  aconnect -l 2>/dev/null | awk -v cid="$cid" -v role="$role" '
    $1=="client" { cur=$2; gsub(/:/, "", cur); next }
    cur==cid && index($0, role) {
      if (match($0, /^[[:space:]]*([0-9]+)/, m)) print m[1]
    }
  '
}

WINE=$(find_client "WINE midi driver")
NVS=$(find_client "nv-screens")
CTL=$(find_client "NV Control")
AUD=$(find_client "NV Audio")
# Virtual display facade (long client name → Wine port-only names)
GFX_USER=$(find_user_client "nv-screens-facade-midi")
# older client names
if [[ -z "${GFX_USER:-}" ]]; then
  GFX_USER=$(find_user_client "nv-screens-facade")
fi
if [[ -z "${GFX_USER:-}" ]]; then
  GFX_USER=$(find_user_client "NV Graphics")
fi
GFX_KERN=$(find_kernel_client "NV Graphics")
GFX_ANY=$(find_client "nv-screens-facade")
WINE_OUTS=( $(find_ports "$WINE" "WINE ALSA Output") )
if [[ ${#WINE_OUTS[@]} -eq 0 && -n "${WINE:-}" ]]; then
  WINE_OUTS=(1 2 3 4 5 6 7 8)
fi

echo "WINE=${WINE:-?} NVS=${NVS:-?} CTL=${CTL:-?} AUD=${AUD:-?} GFX_USER=${GFX_USER:--} GFX_KERN=${GFX_KERN:--} OUTS=${WINE_OUTS[*]:-}"

if [[ -z "${WINE:-}" || -z "${NVS:-}" ]]; then
  echo "Need WINE midi driver + nv-screens running (--patchbay)." >&2
  exit 1
fi

disc() { aconnect -d "$1" "$2" 2>/dev/null || true; }
conn() { aconnect "$1" "$2" 2>/dev/null || true; }
# soft_conn: do not disconnect first (avoids patchbay blink)
soft_conn() { aconnect "$1" "$2" 2>/dev/null || true; }

# --- Kernel Graphics must never be opened by Wine (libusb owns real OUT) ---
if [[ -n "${GFX_KERN:-}" ]]; then
  disc "${GFX_KERN}:0" "${WINE}:0"
  for i in 0 1 2 3 4 5 6 7 8 9; do
    disc "${WINE}:$i" "${GFX_KERN}:0"
    disc "${GFX_KERN}:0" "${WINE}:$i"
  done
  for p in 0 1 2 3; do
    disc "${NVS}:$p" "${GFX_KERN}:0"
    disc "${GFX_KERN}:0" "${NVS}:$p"
  done
  echo "Kernel NV Graphics ALSA isolated (libusb owns real paint)"
fi

# Kill feedback: old monitor_out/log_out → Wine (ports no longer created, safe)
disc "${NVS}:2" "${WINE}:0"
disc "${NVS}:3" "${WINE}:0"
for i in 0 1 2 3 4 5 6 7 8; do
  disc "${NVS}:2" "${WINE}:$i"
  disc "${NVS}:3" "${WINE}:$i"
done

# Junk MIDI: never let Wine keep these (Controllers spam + slow identify)
for junk in "Midi Through" "PipeWire-System" "PipeWire-RT-Event"; do
  J=$(find_client "$junk") || true
  if [[ -n "${J:-}" && -n "${WINE:-}" ]]; then
    for i in 0 1 2 3 4 5 6 7 8 9; do
      disc "${WINE}:$i" "${J}:0"
      disc "${J}:0" "${WINE}:$i"
    done
    disc "${J}:0" "${WINE}:0"
    echo "Isolated junk MIDI: $junk ($J)"
  fi
done

# Clear any all-to-all mesh first (was triplicating every SysEx → clunky/wrong LCD)
for i in "${WINE_OUTS[@]}"; do
  [[ -n "${GFX_KERN:-}" ]] && disc "${WINE}:$i" "${GFX_KERN}:0"
  disc "${WINE}:$i" "${NVS}:0"
  if [[ -n "${GFX_USER:-}" ]]; then
    for p in 0 1 2 3 4; do
      disc "${WINE}:$i" "${GFX_USER}:$p"
    done
  fi
done

# --- Facade 1:1: Wine outs = Control, Display Left, Display Right ---
# Do NOT wire Control (out 0) into vdj_in (LED path is separate).
if [[ -n "${GFX_USER:-}" ]]; then
  # facade → Wine input (identity + HW control rebroadcast)
  for p in 0 1 2; do
    soft_conn "${GFX_USER}:$p" "${WINE}:0"
  done
  # 1:1 wine output → facade port (do NOT mesh)
  map_n=${#WINE_OUTS[@]}
  for idx in 0 1 2; do
    if (( idx < map_n )); then
      soft_conn "${WINE}:${WINE_OUTS[$idx]}" "${GFX_USER}:$idx"
      echo "  map Wine:${WINE_OUTS[$idx]} → facade:$idx"
    fi
  done
  # Paint SysEx taps: Display outs only → host vdj_in (track load / browser)
  for idx in 1 2; do
    if (( idx < map_n )); then
      soft_conn "${WINE}:${WINE_OUTS[$idx]}" "${NVS}:0"
      echo "  map Wine:${WINE_OUTS[$idx]} → vdj_in (paint)"
    fi
  done
  echo "Wine ⟷ facade 1:1 (Control + Display L/R) + display→vdj_in paint"
else
  echo "NOTE: no nv-screens-facade client yet (start nv-screens --patchbay)"
  for i in "${WINE_OUTS[@]}"; do
    soft_conn "${WINE}:$i" "${NVS}:0"
  done
  echo "Wine outs → nv-screens:vdj_in (no facade)"
fi

# Kernel Control — proven topology:
#   kernel CTL → facade:0     (HW jogs/pads into facade → Wine)
#   Wine Control out → kernel CTL  (LEDs)
# Do NOT reverse facade→kernel (echo). Do NOT mesh all Wine outs to kernel.
if [[ -n "${CTL:-}" ]]; then
  CTL_K=$(find_kernel_client "NV Control")
  CTL_ISO="${CTL_K:-$CTL}"
  for i in 0 1 2 3 4 5 6 7 8 9; do
    disc "${WINE}:$i" "${CTL_ISO}:0"
    disc "${CTL_ISO}:0" "${WINE}:$i"
  done
  if [[ -n "${GFX_USER:-}" ]]; then
    disc "${GFX_USER}:0" "${CTL_ISO}:0"
    soft_conn "${CTL_ISO}:0" "${GFX_USER}:0"
    if ((${#WINE_OUTS[@]} > 0)); then
      soft_conn "${WINE}:${WINE_OUTS[0]}" "${CTL_ISO}:0"
      echo "  map Wine:${WINE_OUTS[0]} → kernel NV Control (LEDs)"
    fi
    echo "Kernel NV Control: HW→facade + Wine Control out→kernel (LEDs)"
  else
    soft_conn "${CTL_ISO}:0" "${WINE}:0"
    if ((${#WINE_OUTS[@]} > 0)); then
      soft_conn "${WINE}:${WINE_OUTS[0]}" "${CTL_ISO}:0"
    fi
    echo "Wine ⟷ kernel Control (no facade)"
  fi
fi

# Kernel Audio MIDI: leave UNWIRED when facade is up (Display Left uses facade).
# qpwgraph will show a floating "NV Audio MIDI 1" node — that is OK.
# PCM (hw:Audio) is separate; Wine sound does not need this MIDI cable.
if [[ -n "${AUD:-}" ]]; then
  AUD_K=$(find_kernel_client "NV Audio")
  AUD_ISO="${AUD_K:-$AUD}"
  if [[ -n "${GFX_USER:-}" ]]; then
    disc "${AUD_ISO}:0" "${WINE}:0"
    for i in 0 1 2 3 4 5 6 7 8 9; do
      disc "${WINE}:$i" "${AUD_ISO}:0"
      disc "${AUD_ISO}:0" "${WINE}:$i"
    done
    # Also unhook from nv-screens vdj_in if anything linked it
    if [[ -n "${NVS:-}" ]]; then
      disc "${AUD_ISO}:0" "${NVS}:0"
      disc "${NVS}:0" "${AUD_ISO}:0"
    fi
    echo "Kernel NV Audio MIDI isolated (floating in patchbay is normal; PCM still works)"
  else
    disc "${AUD_ISO}:0" "${WINE}:0"
    conn "${AUD_ISO}:0" "${WINE}:0"
    for i in "${WINE_OUTS[@]}"; do
      disc "${WINE}:$i" "${AUD_ISO}:0"
      conn "${WINE}:$i" "${AUD_ISO}:0"
    done
    echo "Wine ⟷ kernel Audio MIDI (no facade)"
  fi
fi

echo
aconnect -l 2>/dev/null | awk '
  /client / {c=$0}
  /NV Control|NV Graphics|NV Audio|nv-screens|WINE midi|Display Left|Display Right/ {print; show=1; next}
  show && /^client / {show=0}
  show {print}
'
if [[ -n "${GFX_KERN:-}" ]]; then
  if aconnect -l 2>/dev/null | awk -v g="$GFX_KERN" '
    $1=="client" { gsub(/:/,"",$2); if ($2==g) f=1; else if(f) exit }
    f && /WINE/ { print; exit 1 }
  '; then
    :
  else
    echo "WARN: kernel NV Graphics still linked to Wine — run graphics_guard"
  fi
fi
echo
echo "NOTE: real LCD paint = libusb bulk (not an ALSA cable)."
echo "      Facade → Wine: NV Control + NV Display Left + NV Display Right"
echo "      (or NV Audio/Graphics)"
echo "      Kernel Graphics missing = exclusive claim — good."
