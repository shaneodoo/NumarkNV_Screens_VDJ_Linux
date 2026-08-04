#!/usr/bin/env bash
# Compatibility wrapper — real script lives in scripts/
exec "$(cd "$(dirname "$0")/.." && pwd)/scripts/usb-reset-nv.sh" "$@"
