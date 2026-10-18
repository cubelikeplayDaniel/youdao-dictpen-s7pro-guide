#!/bin/bash
# ==============================================================================
# NetEase Youdao Dictionary Pen S7 Pro (Y08_CV1813_V0)
# Rapid Deployment & Remote Execution Tool
# ==============================================================================

set -euo pipefail

usage() {
    echo "Usage: $0 <local_file> [target_directory] [options]"
    echo ""
    echo "Options:"
    echo "  --run              Execute binary immediately after deployment"
    echo "  --ip <device_ip>   Deploy via Wireless SSH/SCP instead of ADB"
    echo "  --port <port>      SSH port (default: 22)"
    echo "  -h, --help         Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 build/hello_hardware /userdata/bin/ --run"
    echo "  $0 build/my_app /userdisk/bin/ --ip 192.168.2.2 --run"
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

LOCAL_FILE="$1"
shift

if [ ! -f "$LOCAL_FILE" ]; then
    echo "[-] Error: Local file '$LOCAL_FILE' not found."
    exit 1
fi

TARGET_DIR="/userdata/bin"
AUTO_RUN=false
REMOTE_IP=""
SSH_PORT=22

while [[ $# -gt 0 ]]; do
    case "$1" in
        --run)
            AUTO_RUN=true
            shift
            ;;
        --ip)
            REMOTE_IP="$2"
            shift 2
            ;;
        --port)
            SSH_PORT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            TARGET_DIR="$1"
            shift
            ;;
    esac
done

FILE_NAME=$(basename "$LOCAL_FILE")
REMOTE_PATH="${TARGET_DIR%/}/$FILE_NAME"

echo "=== S7 Pro Deploy Tool ==="
echo "Local source:  $LOCAL_FILE"
echo "Remote target: $REMOTE_PATH"

if [ -n "$REMOTE_IP" ]; then
    echo "[*] Deploying via Wireless SSH/SCP ($REMOTE_IP:$SSH_PORT)..."
    ssh -p "$SSH_PORT" -o StrictHostKeyChecking=no "root@$REMOTE_IP" "mkdir -p '$TARGET_DIR'"
    scp -P "$SSH_PORT" -o StrictHostKeyChecking=no "$LOCAL_FILE" "root@$REMOTE_IP:$REMOTE_PATH"
    ssh -p "$SSH_PORT" -o StrictHostKeyChecking=no "root@$REMOTE_IP" "chmod +x '$REMOTE_PATH'"
    echo "[+] Deployed successfully via SCP!"

    if [ "$AUTO_RUN" = true ]; then
        echo "[*] Executing $REMOTE_PATH via SSH..."
        echo "------------------------------------------------------------"
        ssh -p "$SSH_PORT" -o StrictHostKeyChecking=no "root@$REMOTE_IP" "$REMOTE_PATH"
        echo "------------------------------------------------------------"
    fi
else
    echo "[*] Deploying via ADB..."
    adb shell "mkdir -p '$TARGET_DIR'"
    adb push "$LOCAL_FILE" "$REMOTE_PATH"
    adb shell "chmod +x '$REMOTE_PATH'"
    echo "[+] Deployed successfully via ADB!"

    if [ "$AUTO_RUN" = true ]; then
        echo "[*] Executing $REMOTE_PATH via ADB shell..."
        echo "------------------------------------------------------------"
        adb shell "$REMOTE_PATH"
        echo "------------------------------------------------------------"
    fi
fi
