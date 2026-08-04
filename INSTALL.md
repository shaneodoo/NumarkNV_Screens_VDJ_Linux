# Easy install guide

**Numark NV + VirtualDJ on Linux** (v1.1.0)

Get dual LCDs + Controllers working with VirtualDJ under Wine.  
No Windows required on the host PC.

---

## What you need

| Item | Notes |
|------|--------|
| **Numark NV** | Plugged in over USB |
| **Linux PC** | Fedora, Ubuntu, Zorin, etc. |
| **Wine** | Wine or Wine Staging |
| **VirtualDJ (Windows)** | Installed *inside* Wine (same as on Windows) |
| **Internet** | First-time package download only |

You do **not** need a Windows dual-boot for day-to-day use.

---

## 1. Install system packages

### Fedora / RHEL

```bash
sudo dnf install wine python3-pyusb bubblewrap alsa-utils git
```

### Ubuntu / Zorin / Debian

```bash
sudo apt update
sudo apt install wine python3-pyusb bubblewrap alsa-utils git
```

### Arch

```bash
sudo pacman -S wine python-pyusb bubblewrap alsa-utils git
```

If PyUSB is missing:

```bash
python3 -m pip install --user pyusb
```

---

## 2. Install VirtualDJ in Wine (once)

1. Install Wine if you have not already (step 1).
2. Download the **Windows** VirtualDJ installer from virtualdj.com.
3. Run it under Wine, for example:

```bash
wine ~/Downloads/install_virtualdj.exe
```

4. Finish the VDJ installer as you would on Windows (license, folders).

Default location is usually:

`~/.wine/drive_c/Program Files/VirtualDJ/virtualdj.exe`

---

## 3. Get this project

```bash
mkdir -p ~/src
cd ~/src
git clone https://github.com/shaneodoo/NumarkNV_Screens_VDJ_Linux.git
cd NumarkNV_Screens_VDJ_Linux
```

Or download the **Source code (zip)** from the [Releases](https://github.com/shaneodoo/NumarkNV_Screens_VDJ_Linux/releases) page, unzip, and open that folder in a terminal.

---

## 4. Run the installer

```bash
chmod +x install.sh
./install.sh
```

Answer **Y** when asked. The script will:

- Check Python, Wine, ALSA, PyUSB  
- Copy files (default: `~/src/nv-screens`)  
- Put **`start-virtualdj.sh`** in `~/bin`  
- Offer to install USB rules (password once)  
- Add an app menu entry: **VirtualDJ (Numark NV)**

---

## 5. USB permissions (if the installer skipped them)

```bash
sudo cp config/udev/99-numark-nv.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Unplug and replug the Numark NV once.

---

## 6. Optional: logos back on quit (no password prompt)

When you close VirtualDJ, the host restores the stock NV logos. That uses a small script as root.

1. Open sudoers safely:

```bash
sudo visudo
```

2. Add **one line** at the end (change `YOURUSER` and path if needed):

```text
YOURUSER ALL=(root) NOPASSWD: /home/YOURUSER/src/nv-screens/scripts/usb-reset-nv.sh
```

If you installed only from the git clone folder and never copied to `~/src/nv-screens`, use that full path instead, e.g.:

```text
YOURUSER ALL=(root) NOPASSWD: /home/YOURUSER/src/NumarkNV_Screens_VDJ_Linux/scripts/usb-reset-nv.sh
```

An older path still works if you used 1.0.x:

```text
…/tools/usb-reset-nv.sh
```

(that file is now a tiny wrapper to `scripts/`).

---

## 7. Start VirtualDJ + screens

Plug in the NV, then either:

- App menu → **VirtualDJ (Numark NV)**  
- Or terminal:

```bash
start-virtualdj.sh
```

If `start-virtualdj.sh` is not found:

```bash
~/bin/start-virtualdj.sh
# or
~/src/nv-screens/bin/start-virtualdj.sh
```

What happens:

1. LCD host starts and wakes both screens  
2. MIDI is wired (Controllers + displays)  
3. VirtualDJ opens under Wine  

When you **quit VirtualDJ**, the host stops and (if sudoers is set) logos return.

---

## 8. First time inside VirtualDJ

1. **Config → Controllers**  
   - You should see **Numark NV**, **NV Display Left**, **NV Display Right** (or similar factory names).  
2. Mapping: **Numark NV - Custom Mapping** (or factory default if you prefer).  
3. **Config → Audio**  
   - Prefer **NV Audio** for master/phones when the card is present.  
4. Load a track — left/right LCDs should show deck UI / waveforms.  
5. Turn a **browse** encoder (SEL) — library list appears on that side’s LCD.  
6. Optional: click the **song** list with the mouse — library can open on the LCD (mapping must be loaded; restart VDJ once after install if needed).

---

## Check that the hardware is seen

```bash
lsusb | grep -i 15e4
```

You want three lines (Control / Audio / Graphics), for example:

- `15e4:1005` Control  
- `15e4:1033` Audio (left LCD + sound)  
- `15e4:2033` Graphics (right LCD)  

MIDI clients (while the host is running):

```bash
aconnect -l | head -40
```

Look for `nv-screens` and `nv-screens-facade-midi`.

---

## Everyday use

| Action | How |
|--------|-----|
| Start session | `start-virtualdj.sh` or app menu |
| Stop session | Quit VirtualDJ as usual |
| Logs (if something fails) | `/tmp/nv-screens-live.log` and `/tmp/nv-midi-connect.log` |

---

## Upgrading from 1.0.0

```bash
cd ~/src/NumarkNV_Screens_VDJ_Linux   # or your clone path
git pull
./install.sh
```

Paths changed (`tools2`/`src2` → `bin`/`nv_screens`/`scripts`). The installer updates `~/bin/start-virtualdj.sh`.

---

## Troubleshooting (quick)

| Problem | Try this |
|---------|----------|
| Screens stay on logo | Is `nv-screens` running? Check `/tmp/nv-screens-live.log`. Unplug/replug NV, run `start-virtualdj.sh` again. |
| No Controllers in VDJ | Host must be up **before** or with the launcher; check `aconnect -l` for facade ports. |
| No sound | Config → Audio → NV Audio / correct Wine ALSA device. |
| “Permission denied” USB | Step 5 (udev), replug NV. |
| Logos not restoring | Step 6 (sudoers). Manual: `sudo ~/src/nv-screens/scripts/usb-reset-nv.sh` |
| Mouse list not on LCD | Restart VDJ once; use browse knob once; ensure Custom Mapping is selected. |

More detail: [docs/HYBRID-DAILY.md](docs/HYBRID-DAILY.md), [docs/SYSTEM-PICTURE.md](docs/SYSTEM-PICTURE.md).

---

## Uninstall (optional)

```bash
rm -f ~/bin/start-virtualdj.sh ~/bin/vdj-set-nv-audio.py
rm -f ~/.local/share/applications/numark-nv-virtualdj.desktop
# optional: remove install tree
# rm -rf ~/src/nv-screens
# optional: remove udev rule
# sudo rm /etc/udev/rules.d/99-numark-nv.rules
```

VirtualDJ and Wine stay installed unless you remove them yourself.

---

## License / disclaimer

See [LICENSE](LICENSE). Not affiliated with Numark, inMusic, or Atomix / VirtualDJ.  
For use with hardware you own.
