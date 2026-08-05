#!/usr/bin/env bash
# VirtualDJ + Numark NV dual LCDs
#
# - nv-screens runs OUTSIDE bwrap (so sudo USB re-enum works on exit)
# - only Wine is bwrap'd for winealsa.so
# - wire Wine once (no retry thrash in qpwgraph)
# - on exit: stop host → authorized 0→1 hub re-enum → firmware logos
#
# Multi-user safe: logs live under ~/.local/state/nv-screens (not /tmp).
# ROOT auto-detects from this script's location when installed in-tree.
#
set -euo pipefail

# ---------- resolve ROOT ----------
# 1) env ROOT (set by install wrapper / Flatpak)
# 2) this script lives in <tree>/bin/ → parent is ROOT
# 3) fallback ~/src/nv-screens
_resolve_root() {
  local here parent
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  parent="$(cd "$here/.." && pwd)"
  if [[ -x "$here/nv-screens" && -d "$parent/nv_screens" ]]; then
    echo "$parent"
    return
  fi
  if [[ -x "$here/bin/nv-screens" && -d "$here/nv_screens" ]]; then
    echo "$here"
    return
  fi
  echo "${HOME}/src/nv-screens"
}

if [[ -z "${ROOT:-}" ]]; then
  ROOT="$(_resolve_root)"
fi
export ROOT

if [[ ! -x "$ROOT/bin/nv-screens" ]]; then
  echo "ERROR: nv-screens not found at $ROOT/bin/nv-screens" >&2
  echo "  Re-run the installer from the git checkout:" >&2
  echo "    ./install.sh" >&2
  echo "  Or set ROOT to your install folder:" >&2
  echo "    ROOT=/path/to/nv-screens start-virtualdj.sh" >&2
  exit 1
fi

WINEPREFIX="${WINEPREFIX:-$HOME/.wine}"
export WINEPREFIX
export WINEESYNC="${WINEESYNC:-1}"
export WINEFSYNC="${WINEFSYNC:-1}"
export WINEDEBUG="${WINEDEBUG:--d2d,-dwrite,-font}"
export NV_FACADE_NAME_MODE="${NV_FACADE_NAME_MODE:-factory}"

_NV_SO="$ROOT/wine-patch/x86_64-unix/winealsa.so"
# Common distro locations for winealsa.so (bind-over only if file exists)
_NV_DST=""
for _cand in \
  "/usr/lib64/wine-wow64/wine/x86_64-unix/winealsa.so" \
  "/usr/lib64/wine/x86_64-unix/winealsa.so" \
  "/usr/lib/wine/x86_64-unix/winealsa.so" \
  "/usr/lib/x86_64-linux-gnu/wine/x86_64-unix/winealsa.so"
do
  if [[ -e "$_cand" ]]; then
    _NV_DST="$_cand"
    break
  fi
done

DOS="$WINEPREFIX/dosdevices"
VDJ_SETTINGS="$WINEPREFIX/drive_c/users/$USER/AppData/Local/VirtualDJ/settings.xml"
EXE="$WINEPREFIX/drive_c/Program Files/VirtualDJ/virtualdj.exe"
# Optional DJ media mount — set NV_DJ_MOUNT or leave unset (no shane-specific paths)
MOUNT="${NV_DJ_MOUNT:-}"

# Per-user state (never share /tmp logs across accounts)
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/nv-screens"
mkdir -p "$STATE_DIR" "$HOME/bin" "$ROOT/captures" 2>/dev/null || true
LOG="${NV_CONNECT_LOG:-$STATE_DIR/midi-connect.log}"
NV_LOG="${NV_SCREENS_LOG:-$STATE_DIR/screens-live.log}"
NV_PIDFILE="${XDG_RUNTIME_DIR:-$STATE_DIR}/nv-screens.pid"
NV_SCRIPT="$ROOT/bin/nv-screens"
WIRE_SCRIPT="$ROOT/scripts/wire_hybrid.sh"
USB_RESET="$ROOT/scripts/usb-reset-nv.sh"
CSV_LOG="$STATE_DIR/vdj-from-wine-live.csv"
BRIDGE_LOG="$STATE_DIR/live-bridge.txt"

# Ensure we can write logs (create empty files we own)
: >>"$LOG" 2>/dev/null || LOG="$STATE_DIR/midi-connect.log"
: >>"$LOG" || true

log() { echo "$(date -Is) $*" >>"$LOG" 2>/dev/null || true; }
log "=== desktop launch === ROOT=$ROOT user=$USER"

if [[ -n "$MOUNT" && -d "$MOUNT/DJ" ]]; then
  ln -sfn "$MOUNT" "$DOS/d:" 2>/dev/null || true
  ln -sfn "$MOUNT/DJ" "$HOME/Music/DJ" 2>/dev/null || true
fi
if [[ -d "$DOS" ]]; then
  ln -sfn "$HOME" "$DOS/z:" 2>/dev/null || true
  rm -f "$DOS/j:" "$DOS/j::" "$DOS/y:" 2>/dev/null || true
fi

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
if [[ -d "$WINEPREFIX" ]]; then
  mkdir -p "$(dirname "$FAV")" 2>/dev/null || true
  printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' '<FavoriteFolder path="D:\DJ" />' > "$FAV" 2>/dev/null || true
fi
python3 "${ROOT}/bin/vdj-set-nv-audio.py" 2>/dev/null || true

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
  if [[ -z "${NV_SKIP_WINEALSA_BWRAP:-}" && -f "$_NV_SO" && -n "$_NV_DST" && -x /usr/bin/bwrap ]]; then
    log "Wine under bwrap (winealsa only → $_NV_DST)"
    /usr/bin/bwrap --dev-bind / / --bind "$_NV_SO" "$_NV_DST" --die-with-parent \
      wine "$EXE" "$@"
  else
    if [[ ! -f "$_NV_SO" ]]; then
      log "WARN winealsa.so patch missing at $_NV_SO — running plain wine"
    elif [[ -z "$_NV_DST" ]]; then
      log "WARN system winealsa.so not found — running plain wine"
    fi
    wine "$EXE" "$@"
  fi
}

# ========== LAUNCH ==========
kill_old_nv_screens
start_nv_screens

if ! wait_for_nv_client; then
  echo "nv-screens failed — see $NV_LOG" >&2
  tail -40 "$NV_LOG" 2>/dev/null >&2 || true
  exit 1
fi

python3 "${ROOT}/bin/vdj-set-nv-audio.py" >>"$LOG" 2>&1 || true
wine reg add 'HKCU\Software\Wine\Drivers' /v Audio /t REG_SZ /d alsa /f >/dev/null 2>&1 || true
bash "$ROOT/scripts/apply-nv-spoof.sh" >>"$LOG" 2>&1 || true

# Wire in background once Wine appears — no re-wire loop
wire_once &

echo "=============================================="
echo "  VirtualDJ + Numark NV"
echo "=============================================="
echo "  Root:  $ROOT"
echo "  Wake:  raw bulk open+empty"
echo "  Paint: live VDJ"
echo "  Close: release host → USB authorized re-enum → logos"
echo "  Log:   $NV_LOG"
echo "=============================================="

if [[ ! -f "$EXE" ]]; then
  echo "WARNING: VirtualDJ not found at:" >&2
  echo "  $EXE" >&2
  echo "  Install the Windows VirtualDJ build under Wine first." >&2
fi

set +e
run_wine "$@"
rc=$?
set -e
log "Wine exited rc=$rc"
kill_old_nv_screens --exit
exit "$rc"
