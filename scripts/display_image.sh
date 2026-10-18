#!/bin/bash
# ==============================================================================
# NetEase Youdao Dictionary Pen S7 Pro (Y08_CV1813_V0)
# Instant Screen Display Tool (Renders PNG directly to 240x1020 Framebuffer)
# ==============================================================================

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <image.png> [--keep-official]"
    echo "  --keep-official: Do not pause official miniapp (default: pause official UI)"
    exit 1
fi

LOCAL_IMG="$1"
PAUSE_OFFICIAL=true

if [[ "${2:-}" == "--keep-official" ]]; then
    PAUSE_OFFICIAL=false
fi

if [ ! -f "$LOCAL_IMG" ]; then
    echo "[-] Error: Local image file '$LOCAL_IMG' does not exist."
    exit 1
fi

echo "[*] Checking device connection..."
adb get-state >/dev/null

if [ "$PAUSE_OFFICIAL" = true ]; then
    echo "[*] Pausing official miniapp to take exclusive ownership of screen..."
    adb shell "killall -STOP miniapp 2>/dev/null || true"
fi

echo "[*] Pushing image to device..."
adb push "$LOCAL_IMG" /tmp/_display_temp.png >/dev/null

echo "[*] Rendering to /dev/fb0 via fbshow..."
adb shell "fbshow /tmp/_display_temp.png /dev/fb0 0"

echo "[+] Screen rendered successfully!"
echo "    To return to the official dictionary UI at any time, run:"
echo "    ./scripts/restore_official_ui.sh"
