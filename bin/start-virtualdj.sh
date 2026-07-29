#!/usr/bin/env bash
# VirtualDJ desktop icon — clean nv-screens bridge, then Wine VDJ
#
#   1) KILL any existing nv-screens / graphics_guard
#   2) START nv-screens fresh:
#        • claim real NV Graphics via libusb (kernel ALSA card gone)
#        • virtual ALSA "NV Graphics" facade so VDJ still sees Graphics IN
#        • BRIDGE ONLY: Wine MIDI → USB-MIDI bulk cells → real Graphics
#        • NO capture/test CSV paint loop
#   3) START Wine VirtualDJ
#   4) Wire: Wine ⟷ Control/Audio/virtual Graphics; outs → vdj_in
#      Guard: Wine never ALSA-connects to *kernel* NV Graphics
#
set -euo pipefail

ROOT="${ROOT:-$HOME/src/nv-screens}"
WINEPREFIX="${WINEPREFIX:-$HOME/.wine}"
export WINEPREFIX
export WINEESYNC="${WINEESYNC:-1}"
export WINEFSYNC="${WINEFSYNC:-1}"
export WINEDEBUG="${WINEDEBUG:--d2d,-dwrite,-font}"

# Re-exec under bubblewrap so Wine loads Numark-aware winealsa.so (VID/PID +
# hide kernel "MIDI 1" / PipeWire junk). Desktop icon must do this or factory
# displays never bind. Set NV_SKIP_WINEALSA_BWRAP=1 to disable.
_NV_SO="$ROOT/wine-patch/x86_64-unix/winealsa.so"
_NV_DST="/usr/lib64/wine-wow64/wine/x86_64-unix/winealsa.so"
if [[ -z "${NV_INSIDE_WINEALSA_BWRAP:-}" && -z "${NV_SKIP_WINEALSA_BWRAP:-}" \
      && -f "$_NV_SO" && -x /usr/bin/bwrap ]]; then
  export NV_INSIDE_WINEALSA_BWRAP=1
  export NV_FACADE_NAME_MODE="${NV_FACADE_NAME_MODE:-factory}"
  exec /usr/bin/bwrap --dev-bind / / --bind "$_NV_SO" "$_NV_DST" --die-with-parent \
    "$0" "$@"
fi

DOS="$WINEPREFIX/dosdevices"
VDJ_SETTINGS="$WINEPREFIX/drive_c/users/$USER/AppData/Local/VirtualDJ/settings.xml"
MOUNT="${NV_LIBRARY_MOUNT:-}"
EXE="$WINEPREFIX/drive_c/Program Files/VirtualDJ/virtualdj.exe"

LOG="/tmp/nv-vdj-launch.log"
NV_LOG="/tmp/nv-screens-live.log"
NV_PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/nv-screens.pid"
GUARD_PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/nv-graphics-guard.pid"
NV_SCRIPT="$ROOT/tools2/nv_screens.py"
WIRE_SCRIPT="$ROOT/tools/wire_hybrid.sh"
GUARD_SCRIPT="$ROOT/tools/graphics_guard.sh"

mkdir -p "$HOME/bin" "$ROOT/captures"
echo "$(date -Is) === desktop launch ===" >>"$LOG"

log() { echo "$(date -Is) $*" >>"$LOG"; }

# --- optional library drive (NV_LIBRARY_MOUNT) ---
if [[ -n "${MOUNT:-}" && -d "${MOUNT}/DJ" ]]; then
  ln -sfn "$MOUNT" "$DOS/d:"
  ln -sfn "$MOUNT/DJ" "$HOME/Music/DJ" || true
elif [[ -n "${MOUNT:-}" && -d "$MOUNT" ]]; then
  ln -sfn "$MOUNT" "$DOS/d:"
fi
ln -sfn "$HOME" "$DOS/z:"
rm -f "$DOS/j:" "$DOS/j::" "$DOS/y:" 2>/dev/null || true

if [[ -f "$VDJ_SETTINGS" ]]; then
  python3 - "$VDJ_SETTINGS" <<'PY' || true
import re, sys
from pathlib import Path
p = Path(sys.argv[1])
t = p.read_text(encoding="utf-8", errors="replace")
for a, b in [
    (r"<ignoreDrives\s*/>", "<ignoreDrives>Z</ignoreDrives>"),
    (r"<ignoreDrives>[^<]*</ignoreDrives>", "<ignoreDrives>Z</ignoreDrives>"),
    (r"<controllerRefreshRate>[^<]*</controllerRefreshRate>", "<controllerRefreshRate>30</controllerRefreshRate>"),
]:
    t2, n = re.subn(a, b, t, count=1)
    if n:
        t = t2
p.write_text(t, encoding="utf-8")
PY
fi

python3 "$HOME/bin/vdj-set-nv-audio.py" 2>/dev/null || true

kill_by_pidfile() {
  local pf="$1"
  [[ -f "$pf" ]] || return 0
  local pid
  pid=$(cat "$pf" 2>/dev/null || true)
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    log "Graceful stop pid $pid from $pf (splash blank + facade teardown)"
    # TERM → blank_lcds(open/splash) + patchbay.close + USB reattach.
    # Need several seconds so splash can finish before -9.
    kill -TERM "$pid" 2>/dev/null || true
    local i
    for i in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.4
    done
    if kill -0 "$pid" 2>/dev/null; then
      log "Force kill $pid after graceful wait"
      kill -9 "$pid" 2>/dev/null || true
    else
      log "nv-screens exited cleanly after blank"
    fi
  fi
  rm -f "$pf"
}

# --- HARD kill every nv-screens / guard instance (desktop icon = clean slate) ---
kill_old_nv_screens() {
  log "Killing previous nv-screens / graphics_guard"
  kill_by_pidfile "$NV_PIDFILE"
  kill_by_pidfile "$GUARD_PIDFILE"
  local p
  for p in $(ps -eo pid=,cmd= | awk -v s="$NV_SCRIPT" 'index($0, s) && $0 !~ /awk/ {print $1}'); do
    log "  kill leftover nv_screens $p"
    kill -9 "$p" 2>/dev/null || true
  done
  for p in $(ps -eo pid=,cmd= | awk '/tools2\/nv_screens\.py/ && !/awk/ {print $1}'); do
    kill -9 "$p" 2>/dev/null || true
  done
  for p in $(ps -eo pid=,cmd= | awk '/graphics_guard\.sh/ && !/awk/ {print $1}'); do
    log "  kill leftover guard $p"
    kill -9 "$p" 2>/dev/null || true
  done
  # give USB a moment to release after libusb claim
  sleep 1.2
  log "nv-screens kill complete"
}

start_nv_screens() {
  export NV_FACADE_NAME_MODE="${NV_FACADE_NAME_MODE:-factory}"
  if [[ -x "$ROOT/tools/clear-vdj-midi-clutter.sh" ]]; then
    bash "$ROOT/tools/clear-vdj-midi-clutter.sh" >>"$LOG" 2>&1 || true
  fi

  log "Starting nv-screens facade_names=$NV_FACADE_NAME_MODE"
  : >"$NV_LOG"

  # open = splash only (0506/0508/0530); live-only = VDJ SysEx paint
  local wake="${NV_WAKE_MODE:-open}"
  local extra=(
    --patchbay --no-wait --live-only
    --idle-after-vdj-s 2
    --wake-mode "$wake"
  )
  log "live-only + wake=$wake"

  nohup python3 -u "$NV_SCRIPT" "${extra[@]}" >>"$NV_LOG" 2>&1 &
  echo $! >"$NV_PIDFILE"
  log "nv-screens pid=$(cat "$NV_PIDFILE")"
}

wait_for_nv_client() {
  local i
  for i in $(seq 1 50); do
    if aconnect -l 2>/dev/null | grep -q "nv-screens"; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

wait_for_graphics_claimed() {
  local i
  for i in $(seq 1 50); do
    if grep -q "claimed 15e4:2033" "$NV_LOG" 2>/dev/null; then
      log "Graphics claimed via libusb"
      return 0
    fi
    if ! amidi -l 2>/dev/null | grep -qi "Graphics"; then
      log "Graphics gone from amidi"
      return 0
    fi
    sleep 0.2
  done
  log "WARN: Graphics claim not confirmed"
  return 1
}

wire_routes() {
  if ! wait_for_nv_client; then
    log "ERROR: nv-screens ALSA client missing"
    return 1
  fi
  local i
  for i in $(seq 1 180); do
    if aconnect -l 2>/dev/null | grep -q "WINE midi driver"; then
      break
    fi
    sleep 0.4
  done
  if ! aconnect -l 2>/dev/null | grep -q "WINE midi driver"; then
    log "ERROR: Wine MIDI never appeared"
    return 1
  fi
  log "Wiring Wine ⟷ Control/Audio; Wine → vdj_in; isolate Graphics"
  bash "$WIRE_SCRIPT" >>"$LOG" 2>&1 || log "wire_hybrid failed"
  bash "$GUARD_SCRIPT" --once >>"$LOG" 2>&1 || true
}

# ========== DESKTOP ICON SEQUENCE ==========
kill_old_nv_screens
start_nv_screens

if ! wait_for_nv_client; then
  echo "nv-screens failed to start — see $NV_LOG" >&2
  tail -20 "$NV_LOG" >&2 || true
  exit 1
fi
wait_for_graphics_claimed || true

if [[ -x "$GUARD_SCRIPT" ]]; then
  nohup bash "$GUARD_SCRIPT" >>"$LOG" 2>&1 &
  echo $! >"$GUARD_PIDFILE"
  log "graphics_guard pid=$(cat "$GUARD_PIDFILE")"
fi

# Point VDJ audio at current NV Audio card (card index moves after hybrid claim)
if [[ -x "$HOME/bin/vdj-set-nv-audio.py" ]]; then
  python3 "$HOME/bin/vdj-set-nv-audio.py" >>"$LOG" 2>&1 || true
fi
# Ensure Wine uses alsa backend (USB VID/PID from card usbid for NUMARK NV button)
wine reg add 'HKCU\Software\Wine\Drivers' /v Audio /t REG_SZ /d alsa /f >/dev/null 2>&1 || true
bash "$ROOT/tools/apply-nv-spoof.sh" >>"$LOG" 2>&1 || true

(
  # Wait for Wine MIDI, then wire a few times only (avoid connect/disconnect thrash)
  for i in $(seq 1 40); do
    if aconnect -l 2>/dev/null | grep -q "WINE midi driver"; then
      break
    fi
    sleep 0.5
  done
  if wire_routes; then
    log "Initial wire OK"
  fi
  for _ in 1 2 3; do
    sleep 3
    if aconnect -l 2>/dev/null | grep -q "WINE midi driver"; then
      bash "$WIRE_SCRIPT" >>"$LOG" 2>&1 || true
      bash "$GUARD_SCRIPT" --once >>"$LOG" 2>&1 || true
    fi
  done
  log "Wire retries done"
) &

echo "=============================================="
echo "  VirtualDJ + Numark NV (factory Controllers + live LCDs)"
echo "=============================================="
echo "  wake=${NV_WAKE_MODE:-open}  log=$NV_LOG"
echo "=============================================="

# Do not exec-replace: when VDJ/wine exits, tear down facade + guard so
# qpwgraph/patchbay does not keep 129:nv-screens-facade-midi forever.
set +e
wine "$EXE" "$@"
rc=$?
set -e
log "Wine/VDJ exited rc=$rc — cleaning nv-screens"
kill_old_nv_screens
exit "$rc"
