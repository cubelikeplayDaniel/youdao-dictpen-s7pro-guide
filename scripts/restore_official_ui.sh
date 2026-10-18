#!/bin/bash
# ==============================================================================
# NetEase Youdao Dictionary Pen S7 Pro (Y08_CV1813_V0)
# Restore Official Youdao Dictionary Pen UI
# ==============================================================================

set -euo pipefail

echo "[*] Resuming official miniapp process..."
adb shell "killall -CONT miniapp 2>/dev/null || true"
echo "[+] Official Youdao Dictionary UI restored!"
