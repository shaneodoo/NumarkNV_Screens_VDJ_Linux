# Troubleshooting

## No Display Left/Right in Controllers

- Launch via `~/bin/start-virtualdj.sh` (not bare `wine virtualdj.exe`).  
- Need bwrap **or** system winealsa install.  
- Run `tools/clear-vdj-midi-clutter.sh` if custom mappers stuck.

## LCDs black / logo only

```bash
tail -f /tmp/nv-screens-live.log
# expect: claimed 15e4:2033 and 1033, LCD wake done ok=12
lsusb | grep 15e4
```

udev rules + user in `audio`/`plugdev`.

## Title/artist when a track is loaded

Normal — live VDJ paint.

## NV Audio card missing while running

MIDI claim can drop PCM. Try `tools/rebind-nv-audio-pcm.sh` (may need sudo).

## Patchbay: floating “NV Audio MIDI 1”

Normal; do not connect to Wine. Sound is PCM, not that MIDI port.

## Facade left after quit

Use our launcher (waits for Wine, then stops nv-screens). Or:  
`pkill -f tools2/nv_screens.py`
