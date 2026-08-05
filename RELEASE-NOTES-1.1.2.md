# v1.1.2 — Multi-user install fix

End-user install polish: multi-user safe launcher + reliable desktop icon.

## Fixed
- **Permission denied on launch** — shared `/tmp/nv-*.log` files owned by the first user blocked other accounts (`Permission denied` at first log write). Logs are now per-user under `~/.local/state/nv-screens/`.
- **App menu / desktop icon wrong path** — installer always writes a thin wrapper with absolute `ROOT` and a `.desktop` with absolute `Exec=`, `TryExec=`, and `Path=`.
- Removed hardcoded `/mnt/shane1` media mount (optional `NV_DJ_MOUNT` if you need a D: drive).
- winealsa bind path probes common distros, not only Fedora.

## Installer
- Always bakes absolute paths (no “only when DEST ≠ default” sed).
- Clearer PATH warning when `~/bin` is not on `$PATH`.
- `NV_INSTALL_YES=1` for non-interactive install; `NV_INSTALL_ROOT` / `NV_BIN_DIR` still supported.
- Log paths printed at end of install.

## Upgrade
```bash
cd ~/src/NumarkNV_Screens_VDJ_Linux   # or your clone
git pull
./install.sh
~/bin/start-virtualdj.sh
```

Or app menu → **VirtualDJ (Numark NV)**.

Logs if something fails:
```text
~/.local/state/nv-screens/screens-live.log
~/.local/state/nv-screens/midi-connect.log
```

Full notes: [CHANGELOG.md](CHANGELOG.md)
