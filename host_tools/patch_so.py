#!/usr/bin/env python3
"""
NetEase Youdao Dictionary Pen S7 Pro - Native Library ELF Patcher
Patches libjsapi_baidupan.so to execute arbitrary root commands on startup.

Mechanism:
1. Replaces 'remove\\x00' (7 bytes) with 'system\\x00' (7 bytes) in .dynstr.
2. In custom_init_jsapis at 0x12484, changes BL puts@plt (0xebfffad9) to BL remove@plt (0xebfffb27).
   When resolved by the dynamic linker (dlopen), remove@plt resolves to libc system().
3. Injects inline shell command into unused rodata at 0x2dfeb and updates the PC-relative pointer at 0x12490.
"""

import sys
import os
import struct

def patch_libjsapi(input_path, output_path, command=None):
    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found.")
        sys.exit(1)

    with open(input_path, "rb") as f:
        so = bytearray(f.read())

    # 1. Patch .dynstr: replace "remove\x00" with "system\x00"
    idx = so.find(b"remove\x00")
    if idx == -1:
        print("Warning: 'remove\\x00' not found in binary, checking if already patched...")
        if so.find(b"system\x00") == -1:
            print("Error: neither 'remove' nor 'system' found in .dynstr.")
            sys.exit(1)
    else:
        so[idx:idx+7] = b"system\x00"
        print(f"[+] Patched .dynstr: 'remove' -> 'system' at offset {hex(idx)}")

    # 2. Patch custom_init_jsapis at 0x12484:
    # Change BL puts@plt to BL remove@plt (system@plt): 0xebfffb27
    so[0x12484:0x12488] = struct.pack("<I", 0xebfffb27)
    print("[+] Patched custom_init_jsapis at 0x12484: BL system@plt (0xebfffb27)")

    # 3. Patch command string pointer at 0x12490:
    target_offset = 0x2dfeb
    pc_at_load = 0x12488
    rel_offset = target_offset - pc_at_load
    so[0x12490:0x12494] = struct.pack("<I", rel_offset)
    print(f"[+] Patched R0 offset at 0x12490: {hex(rel_offset)} (points to {hex(target_offset)})")

    # 4. Write command string
    if not command:
        command = b"touch /tmp/.adb_auth_verified; echo root:root|chpasswd 2>/dev/null; sh /userdata/app/*/init.sh &\x00"
    elif isinstance(command, str):
        command = command.encode("utf-8") + b"\x00"

    assert len(command) <= 139, f"Command too long ({len(command)} > 139 bytes)"
    so[target_offset:target_offset+len(command)] = command
    print(f"[+] Injected command at {hex(target_offset)}: {command}")

    with open(output_path, "wb") as f:
        f.write(so)

    print(f"[SUCCESS] Patched ELF written to: {output_path}")

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "/private/tmp/libjsapi_baidupan.so"
    dst = sys.argv[2] if len(sys.argv) > 2 else "/private/tmp/libjsapi_baidupan_patched.so"
    cmd = sys.argv[3] if len(sys.argv) > 3 else None
    patch_libjsapi(src, dst, cmd)
