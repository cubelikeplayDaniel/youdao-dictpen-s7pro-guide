#!/bin/bash
# ==============================================================================
# NetEase Youdao Dictionary Pen S7 Pro (Y08_CV1813_V0)
# Sysroot Extraction & Symlink Sanitization Tool
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_DIR="${1:-"$REPO_ROOT/sysroot"}"

echo "=== S7 Pro Sysroot Extraction Tool ==="
echo "Target directory: $TARGET_DIR"

# 1. 检查 ADB 连接
echo "[*] Checking ADB device connection..."
if ! adb get-state >/dev/null 2>&1; then
    echo "[-] Error: No ADB device detected. Please connect S7 Pro via USB."
    exit 1
fi

DEVICE_NAME=$(adb shell uname -n 2>/dev/null || echo "Unknown")
echo "[+] Connected to device: $DEVICE_NAME"

# 2. 创建目录结构
mkdir -p "$TARGET_DIR/lib"
mkdir -p "$TARGET_DIR/usr/lib"
mkdir -p "$TARGET_DIR/usr/include"
mkdir -p "$TARGET_DIR/oem/lib"

# 3. 提取系统关键库
echo "[*] Pulling /lib (C runtime, dynamic linker, core system libs)..."
adb pull /lib/. "$TARGET_DIR/lib/" || true

echo "[*] Pulling /usr/lib (ALSA, libcurl, FreeType, SQLite, multimedia libs)..."
adb pull /usr/lib/. "$TARGET_DIR/usr/lib/" || true

echo "[*] Pulling /oem/lib (Vendor specialized libraries)..."
adb pull /oem/lib/. "$TARGET_DIR/oem/lib/" || true

echo "[*] Pulling /usr/include (C/C++ development headers if present)..."
adb pull /usr/include/. "$TARGET_DIR/usr/include/" || true

# 4. 修复绝对符号链接 (Sanitize Absolute Symlinks)
# 宿主端链接器若遇到 /lib/libc.so.6 的绝对软链接，会尝试寻找宿主机上的根目录导致链接失败或污染。
echo "[*] Sanitizing absolute symbolic links in sysroot..."
find "$TARGET_DIR" -type l | while read -r link; do
    target=$(readlink "$link")
    # 如果目标是绝对路径以 /lib 或 /usr/lib 开头
    if [[ "$target" == /* ]]; then
        # 转换为相对目标
        link_dir=$(dirname "$link")
        rel_target=$(python3 -c "import os.path; print(os.path.relpath('$TARGET_DIR$target', '$link_dir'))")
        rm "$link"
        ln -s "$rel_target" "$link"
        echo "  Fixed: $(basename "$link") -> $rel_target"
    fi
done

echo "=== Sysroot extraction completed successfully at $TARGET_DIR ==="
