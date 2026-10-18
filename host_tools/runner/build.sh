#!/bin/bash
# ==============================================================================
# Build Standalone ARMv7 Static Binary for s7pro_runner
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[*] Building s7pro_runner (ARMv7 Linux Static)..."
CGO_ENABLED=0 GOOS=linux GOARCH=arm GOARM=7 go build -ldflags="-s -w" -o s7pro_runner main.go

echo "[+] Built: $SCRIPT_DIR/s7pro_runner"
file s7pro_runner || true
