#!/usr/bin/env bash
# Start LCD host + wire MIDI + launch VirtualDJ under Wine.
# Logs: ~/.local/state/nv-screens/  (per user, not /tmp)
set -euo pipefail

# ROOT: env, or parent of this bin/, or ~/src/nv-screens
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
# Keep logs short for long gigs — defaults are small; override with env if needed.
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/nv-screens"
mkdir -p "$STATE_DIR" "$HOME/bin" 2>/dev/null || true
LOG="${NV_CONNECT_LOG:-$STATE_DIR/midi-connect.log}"
NV_LOG="${NV_SCREENS_LOG:-$STATE_DIR/screens-live.log}"
NV_PIDFILE="${XDG_RUNTIME_DIR:-$STATE_DIR}/nv-screens.pid"
NV_SCRIPT="$ROOT/bin/nv-screens"
WIRE_SCRIPT="$ROOT/scripts/wire_hybrid.sh"
USB_RESET="$ROOT/scripts/usb-reset-nv.sh"
# CSV traffic dump is huge — off unless NV_CSV_LOG=1
CSV_LOG="$STATE_DIR/vdj-from-wine-live.csv"
BRIDGE_LOG="$STATE_DIR/live-bridge.txt"
# Max size (bytes) before trim; default 1 MiB each (~few thousand lines)
LOG_MAX_BYTES="${NV_LOG_MAX_BYTES:-1048576}"

# Keep only the tail of a log if it grew past LOG_MAX_BYTES.
#
# IMPORTANT: nv-screens' stdout (NV_LOG) and the CSV logger (CSV_LOG) hold
# a long-lived open file descriptor to these paths for the whole gig. A
# naive "write tail to a new file, then mv over the original" swaps in a
# *new inode* — the running process keeps appending into the OLD, now
# unlinked inode, which (a) never actually stops growing, defeating the
# whole point of trimming, and (b) leaves the on-disk file stale after the
# first trim (breaks `tail -f` and the "see $NV_LOG" diagnostic on
# failure). Truncating the SAME inode in place (plain `>` redirection,
# which reuses the existing inode instead of creating a new one) keeps
# any O_APPEND writer correctly appending after the new, shorter content.
trim_log() {
  local f="$1" max="${2:-$LOG_MAX_BYTES}" sz keep tmp
  [[ -f "$f" ]] || return 0
  sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
  (( sz > max )) || return 0
  keep=$(( max / 2 ))
  (( keep < 65536 )) && keep=65536
  tmp=$(mktemp "${f}.XXXXXX.tmp") || return 0
  if tail -c "$keep" "$f" >"$tmp" 2>/dev/null; then
    # `>"$f"` truncates the EXISTING inode in place (path already exists)
    # instead of creating a new one — do not change this to `mv`.
    cat "$tmp" >"$f" 2>/dev/null || true
  fi
  rm -f "$tmp"
}

# While host runs, periodically trim state logs (long gigs)
log_trimmer() {
  local pidfile="$1"
  while true; do
    sleep 120
    [[ -f "$pidfile" ]] || break
    local p
    p=$(cat "$pidfile" 2>/dev/null || true)
    [[ -n "${p:-}" ]] && kill -0 "$p" 2>/dev/null || break
    trim_log "$NV_LOG"
    trim_log "$LOG"
    trim_log "$CSV_LOG" "$((LOG_MAX_BYTES * 2))"
    trim_log "$BRIDGE_LOG"
  done
}

# Fresh session logs (don't append forever across gigs)
: >"$NV_LOG" 2>/dev/null || true
: >"$BRIDGE_LOG" 2>/dev/null || true
rm -f "$CSV_LOG" 2>/dev/null || true
trim_log "$LOG"
: >>"$LOG" 2>/dev/null || LOG="$STATE_DIR/midi-connect.log"

log() { echo "$(date -Is) $*" >>"$LOG" 2>/dev/null || true; trim_log "$LOG"; }
log "=== desktop launch === ROOT=$ROOT user=$USER log_max=${LOG_MAX_BYTES}"

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
  # Optional bulk CSV (dev only — fills disks on long sets)
  local csv_args=()
  if [[ "${NV_CSV_LOG:-0}" == "1" ]]; then
    : >"$CSV_LOG"
    csv_args=(--csv-log "$CSV_LOG" --vdj-csv "$CSV_LOG")
    log "CSV traffic log ON → $CSV_LOG (NV_CSV_LOG=1)"
  else
    rm -f "$CSV_LOG" 2>/dev/null || true
    log "CSV traffic log off (set NV_CSV_LOG=1 to enable)"
  fi
  nohup python3 -u "$NV_SCRIPT" \
    --patchbay --no-wait --live-only \
    --idle-after-vdj-s 2 \
    --wake-mode open \
    "${csv_args[@]}" \
    >>"$NV_LOG" 2>&1 &
  echo $! >"$NV_PIDFILE"
  log "nv-screens pid=$(cat "$NV_PIDFILE")"
  # Cap log growth during the session
  log_trimmer "$NV_PIDFILE" &
  disown $! 2>/dev/null || true
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

# Resolve every symlink under $WINEPREFIX/dosdevices/* to its real host
# target, deduped. This is exactly how winecfg's "Drives" tab is
# implemented under the hood — reading it (instead of hardcoding paths)
# means whatever you add/remove/change in winecfg is picked up
# automatically on the next launch, and nothing beyond what YOU configured
# there is exposed to the sandbox.
_nv_wine_drive_targets() {
  local prefix="$1"
  local -A seen=()
  local link target

  [[ -d "$prefix/dosdevices" ]] || return 0

  while IFS= read -r -d '' link; do
    target="$(readlink -f -- "$link" 2>/dev/null)" || continue
    [[ -e "$target" ]] || continue          # dangling symlink — skip
    [[ -n "${seen[$target]:-}" ]] && continue
    seen[$target]=1
    printf '%s\0' "$target"
  done < <(find "$prefix/dosdevices" -maxdepth 1 -type l -print0 2>/dev/null)
}

run_wine() {
  if [[ -z "${NV_SKIP_WINEALSA_BWRAP:-}" && -f "$_NV_SO" && -n "$_NV_DST" && -x /usr/bin/bwrap ]]; then
    if [[ -n "${NV_BWRAP_FULL_HOST:-}" ]]; then
      # Escape hatch: old unrestricted behaviour (binds the ENTIRE host
      # filesystem in). Only use this to unblock a gig if the curated bind
      # list below is missing something it needs — then report what broke.
      log "Wine under bwrap (winealsa only → $_NV_DST) [NV_BWRAP_FULL_HOST=1: full host bind]"
      /usr/bin/bwrap --dev-bind / / --bind "$_NV_SO" "$_NV_DST" --die-with-parent \
        wine "$EXE" "$@"
      return $?
    fi

    # Minimal bind set: only what Wine/Vulkan/ALSA/USB and your configured
    # winecfg drives actually need — NOT the whole host filesystem.
    local bwrap_args=(
      # Merged-/usr distro layout (Fedora et al.) — /lib, /lib64, /bin,
      # /sbin are normally symlinks into /usr; recreate them so anything
      # resolving those paths still works from inside the sandbox.
      --symlink usr/lib     /lib
      --symlink usr/lib64   /lib64
      --symlink usr/bin     /bin
      --symlink usr/sbin    /sbin
      --ro-bind /usr        /usr
      --ro-bind /etc        /etc
      --proc    /proc
      # Full real /dev passthrough — needed for GPU (Vulkan/DXVK, /dev/dri),
      # audio (/dev/snd), and raw USB access (nv-screens' pyusb, /dev/bus/usb).
      --dev-bind /dev       /dev
      # Read-WRITE: scripts/usb-reset-nv.sh writes to sysfs
      # (.../authorized) to re-enumerate the NV over USB — read-only here
      # would silently break that.
      --bind    /sys        /sys
      # Wayland/X11, PipeWire/PulseAudio, and D-Bus session sockets live
      # under /run (usually /run/user/$UID) and /tmp (X11).
      --bind    /run        /run
      --bind    /tmp         /tmp
      # The Wine prefix itself (registry, drive_c, and the dosdevices
      # symlinks we just read above).
      --bind    "$WINEPREFIX" "$WINEPREFIX"
    )

    local drive_list=()
    while IFS= read -r -d '' t; do
      bwrap_args+=(--bind "$t" "$t")
      drive_list+=("$t")
    done < <(_nv_wine_drive_targets "$WINEPREFIX")

    bwrap_args+=(--bind "$_NV_SO" "$_NV_DST" --die-with-parent)

    log "Wine under bwrap (winealsa only → $_NV_DST)"
    if ((${#drive_list[@]})); then
      log "  winecfg drives bound: ${drive_list[*]}"
    else
      log "  WARN: no drives resolved from $WINEPREFIX/dosdevices — VDJ may not see any files. Check winecfg's Drives tab."
    fi

    /usr/bin/bwrap "${bwrap_args[@]}" wine "$EXE" "$@"
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
  echo "  Install VirtualDJ under Wine first." >&2
fi

set +e
run_wine "$@"
rc=$?
set -e
log "Wine exited rc=$rc"
kill_old_nv_screens --exit
exit "$rc"
