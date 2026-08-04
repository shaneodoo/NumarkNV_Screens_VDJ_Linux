#!/usr/bin/env bash
# VirtualDJ + Numark NV dual LCDs
#
# - nv-screens runs OUTSIDE bwrap (so sudo USB re-enum works on exit)
# - only Wine is bwrap'd for winealsa.so
# - wire Wine once (no retry thrash in qpwgraph)
# - on exit: stop host → authorized 0→1 hub re-enum → firmware logos
#
set -euo pipefail

ROOT="${ROOT:-$HOME/src/nv-screens}"
WINEPREFIX="${WINEPREFIX:-$HOME/.wine}"
export WINEPREFIX
export WINEESYNC="${WINEESYNC:-1}"
export WINEFSYNC="${WINEFSYNC:-1}"
export WINEDEBUG="${WINEDEBUG:--d2d,-dwrite,-font}"
export NV_FACADE_NAME_MODE="${NV_FACADE_NAME_MODE:-factory}"

_NV_SO="$ROOT/wine-patch/x86_64-unix/winealsa.so"
_NV_DST="/usr/lib64/wine-wow64/wine/x86_64-unix/winealsa.so"

DOS="$WINEPREFIX/dosdevices"
VDJ_SETTINGS="$WINEPREFIX/drive_c/users/$USER/AppData/Local/VirtualDJ/settings.xml"
MOUNT="/mnt/shane1"
EXE="$WINEPREFIX/drive_c/Program Files/VirtualDJ/virtualdj.exe"

LOG="/tmp/nv-midi-connect.log"
NV_LOG="/tmp/nv-screens-live.log"
NV_PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/nv-screens.pid"
NV_SCRIPT="$ROOT/bin/nv-screens"
WIRE_SCRIPT="$ROOT/scripts/wire_hybrid.sh"
USB_RESET="$ROOT/scripts/usb-reset-nv.sh"
CSV_LOG="$ROOT/captures/vdj-from-wine-live.csv"
BRIDGE_LOG="$ROOT/captures/live-bridge.txt"

mkdir -p "$HOME/bin" "$ROOT/captures"
echo "$(date -Is) === desktop launch ===" >>"$LOG"
log() { echo "$(date -Is) $*" >>"$LOG"; }

if [[ -d "$MOUNT/DJ" ]]; then
  ln -sfn "$MOUNT" "$DOS/d:"
  [[ -b /dev/sdb1 ]] && ln -sfn /dev/sdb1 "$DOS/d::" || true
  ln -sfn "$MOUNT/DJ" "$HOME/Music/DJ" || true
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

FAV="$WINEPREFIX/drive_c/users/$USER/AppData/Local/VirtualDJ/Folders/DJ.vdjfolder"
mkdir -p "$(dirname "$FAV")"
printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' '<FavoriteFolder path="D:\DJ" />' > "$FAV"
python3 "${ROOT}/bin/vdj-set-nv-audio.py" 2>/dev/null || python3 "$HOME/bin/vdj-set-nv-audio.py" 2>/dev/null || true

kill_by_pidfile() {
  local pf="$1"
  [[ -f "$pf" ]] || return 0
  local pid
  pid=$(cat "$pf" 2>/dev/null || true)
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    log "TERM nv-screens pid $pid (clear + release bulk + stock re-enum)"
    kill -TERM "$pid" 2>/dev/null || true
    local i
    # Host now runs authorized re-enum itself (~8–12s with sleeps)
    for i in $(seq 1 40); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.4
    done
    if kill -0 "$pid" 2>/dev/null; then
      log "KILL -9 pid $pid (stock re-enum may still run below)"
      kill -9 "$pid" 2>/dev/null || true
      sleep 0.5
    fi
  fi
  rm -f "$pf"
}

force_logo_rebind() {
  log "USB authorized re-enum for stock firmware logos"
  if [[ -x "$USB_RESET" ]]; then
    if sudo -n "$USB_RESET" >>"$LOG" 2>&1; then
      log "usb-reset OK — stock logos"
      return 0
    fi
    log "WARN sudo -n $USB_RESET failed (check sudoers NOPASSWD)"
  fi
  return 1
}

nv_midi_present() {
  aconnect -l 2>/dev/null | grep -q 'NV Graphics' \
    && aconnect -l 2>/dev/null | grep -q 'NV Audio'
}

kill_old_nv_screens() {
  # $1 = --exit  → full logo re-enum after VDJ quits (clean shutdown)
  # default      → startup cleanup; skip re-enum if devices already healthy
  local mode="${1:-}"
  log "Stopping nv-screens / leftover paint tools (mode=${mode:-start})"
  local had_host=0
  if [[ -f "$NV_PIDFILE" ]]; then
    local pid
    pid=$(cat "$NV_PIDFILE" 2>/dev/null || true)
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
      had_host=1
    fi
  fi
  kill_by_pidfile "$NV_PIDFILE"
  local p
  for p in $(ps -eo pid=,cmd= | awk '/graphics_guard\.sh/ && !/awk/ {print $1}'); do
    kill -9 "$p" 2>/dev/null || true
    had_host=1
  done
  for p in $(ps -eo pid=,cmd= | awk -v s="$NV_SCRIPT" 'index($0, s) && $0 !~ /awk/ {print $1}'); do
    kill -9 "$p" 2>/dev/null || true
    had_host=1
  done
  sleep 0.3

  if [[ "$mode" == "--exit" ]]; then
    # Clean shutdown: host may already re-enum; rebind if logos needed
    force_logo_rebind || true
    log "stop complete (exit)"
    return 0
  fi

  # STARTUP: do NOT always wipe+re-enum (that was ~15–25s before Wine).
  # After a clean previous exit, Audio/Graphics are already present.
  if [[ "$had_host" -eq 1 ]]; then
    if nv_midi_present; then
      log "skip startup re-enum — NV Audio/Graphics already present"
    else
      log "NV MIDI missing after killing host — re-enum"
      force_logo_rebind || true
    fi
  else
    if nv_midi_present; then
      log "skip startup re-enum — no prior host, devices OK"
    else
      log "NV MIDI missing at start — re-enum"
      force_logo_rebind || true
    fi
  fi
  log "stop complete (start)"
}

start_nv_screens() {
  if [[ -x "$ROOT/scripts/clear-vdj-midi-clutter.sh" ]]; then
    bash "$ROOT/scripts/clear-vdj-midi-clutter.sh" >>"$LOG" 2>&1 || true
  fi
  log "Starting nv-screens (host, not bwrap)"
  : >"$NV_LOG"
  : >"$BRIDGE_LOG"
  : >"$CSV_LOG"
  nohup python3 -u "$NV_SCRIPT" \
    --patchbay --no-wait --live-only \
    --idle-after-vdj-s 2 \
    --wake-mode open \
    --csv-log "$CSV_LOG" --vdj-csv "$CSV_LOG" \
    >>"$NV_LOG" 2>&1 &
  echo $! >"$NV_PIDFILE"
  log "nv-screens pid=$(cat "$NV_PIDFILE")"
}

wait_for_nv_client() {
  local i
  for i in $(seq 1 40); do
    aconnect -l 2>/dev/null | grep -q "nv-screens" && return 0
    sleep 0.25
  done
  return 1
}

wire_once() {
  # Single wire pass — no 3× retry thrash
  local i
  for i in $(seq 1 60); do
    if aconnect -l 2>/dev/null | grep -q "WINE midi driver"; then
      log "Wine MIDI up — wire once"
      bash "$WIRE_SCRIPT" >>"$LOG" 2>&1 || log "wire failed"
      return 0
    fi
    sleep 0.5
  done
  log "WARN Wine MIDI never appeared for wire"
  return 1
}

run_wine() {
  if [[ -z "${NV_SKIP_WINEALSA_BWRAP:-}" && -f "$_NV_SO" && -x /usr/bin/bwrap ]]; then
    log "Wine under bwrap (winealsa only)"
    /usr/bin/bwrap --dev-bind / / --bind "$_NV_SO" "$_NV_DST" --die-with-parent \
      wine "$EXE" "$@"
  else
    wine "$EXE" "$@"
  fi
}

# ========== LAUNCH ==========
kill_old_nv_screens
start_nv_screens

if ! wait_for_nv_client; then
  echo "nv-screens failed — see $NV_LOG" >&2
  tail -40 "$NV_LOG" >&2 || true
  exit 1
fi

if [[ -x "$HOME/bin/vdj-set-nv-audio.py" ]]; then
  python3 "${ROOT}/bin/vdj-set-nv-audio.py" >>"$LOG" 2>&1 || python3 "$HOME/bin/vdj-set-nv-audio.py" >>"$LOG" 2>&1 || true
fi
wine reg add 'HKCU\Software\Wine\Drivers' /v Audio /t REG_SZ /d alsa /f >/dev/null 2>&1 || true
bash "$ROOT/scripts/apply-nv-spoof.sh" >>"$LOG" 2>&1 || true

# Wire in background once Wine appears — no re-wire loop
wire_once &

echo "=============================================="
echo "  VirtualDJ + Numark NV"
echo "=============================================="
echo "  Wake:  raw bulk open+empty"
echo "  Paint: live VDJ"
echo "  Close: release host → USB authorized re-enum → logos"
echo "  Log:   $NV_LOG"
echo "=============================================="

set +e
run_wine "$@"
rc=$?
set -e
log "Wine exited rc=$rc"
kill_old_nv_screens --exit
exit "$rc"
