# Install — Numark NV + VirtualDJ on Linux

## What you need

| Item | Notes |
|------|--------|
| Numark NV | Plugged in over USB |
| Linux PC | Fedora, Ubuntu, Zorin, etc. |
| Wine | Wine or Wine Staging |
| VirtualDJ | Install the desktop app **under Wine** (from virtualdj.com) |
| Python + pyusb | For the LCD host |
| alsa-utils | `aconnect` / `amidi` |

## 1. Packages

**Fedora**

```bash
sudo dnf install wine python3-pyusb bubblewrap alsa-utils git
```

**Ubuntu / Debian / Zorin**

```bash
sudo apt update
sudo apt install wine python3-pyusb bubblewrap alsa-utils git
```

**Arch**

```bash
sudo pacman -S wine python-pyusb bubblewrap alsa-utils git
```

If pyusb is still missing: `python3 -m pip install --user pyusb`

## 2. VirtualDJ under Wine (once)

1. Install Wine.
2. Download the VirtualDJ installer from virtualdj.com.
3. Run it: `wine ~/Downloads/install_virtualdj.exe` (path may vary).
4. Finish the installer.

Default path is usually:

`~/.wine/drive_c/Program Files/VirtualDJ/virtualdj.exe`

## 3. Get this project

```bash
mkdir -p ~/src
cd ~/src
git clone https://github.com/shaneodoo/NumarkNV_Screens_VDJ_Linux.git
cd NumarkNV_Screens_VDJ_Linux
```

Or download the source zip from the Releases page and open that folder.

## 4. Installer

```bash
chmod +x install.sh
./install.sh
```

It will:

- Check Python, Wine, ALSA, PyUSB  
- Copy files (default: `~/src/nv-screens`)  
- Put `start-virtualdj.sh` in `~/bin`  
- Offer USB udev rules (password once)  
- Add app menu entry: **VirtualDJ (Numark NV)**

## 5. USB permissions (if skipped)

```bash
sudo cp config/udev/99-numark-nv.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Unplug and replug the Numark NV once.

## 6. Logos on quit (optional, no password each time)

```bash
sudo visudo
```

Add one line (use your user and path):

```text
YOURUSER ALL=(root) NOPASSWD: /home/YOURUSER/src/nv-screens/scripts/usb-reset-nv.sh
```

Older installs may use `tools/usb-reset-nv.sh` (same script, thin wrapper).

## 7. Start

Plug in the NV, then:

- App menu → **VirtualDJ (Numark NV)**  
- Or: `start-virtualdj.sh`  
- Or: `~/bin/start-virtualdj.sh`

On quit, the host stops and logos restore if sudoers is set.

## 8. First time in VirtualDJ

- Controllers: factory Numark NV / Display Left / Display Right where available  
- Audio: NV Audio / NUMARK NV if listed  

## Everyday

| Action | How |
|--------|-----|
| Start | `start-virtualdj.sh` or app menu |
| Stop | Quit VirtualDJ |
| Logs | `~/.local/state/nv-screens/screens-live.log` and `midi-connect.log` |

## Troubleshooting

| Problem | Try |
|---------|-----|
| Screens stay on logo | Check `screens-live.log`. Unplug/replug NV. Run launcher again. |
| No controllers | Host must be running; check `aconnect -l` for `nv-screens`. |
| No sound | Audio settings → NV Audio. |
| USB permission denied | Step 5 udev, replug. |
| Start fails with log permission | Use this tree (logs are per-user under `~/.local/state/nv-screens/`). Re-run `./install.sh`. |
| App menu wrong path | Re-run `./install.sh`. Or run `~/bin/start-virtualdj.sh` in a terminal. |
| Logos not restoring | Step 6 sudoers. Manual: `sudo ~/src/nv-screens/scripts/usb-reset-nv.sh` |

## Upgrade

```bash
cd ~/src/NumarkNV_Screens_VDJ_Linux
git pull
./install.sh
```
