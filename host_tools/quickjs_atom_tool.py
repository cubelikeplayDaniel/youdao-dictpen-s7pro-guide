#!/usr/bin/env python3
"""
QuickJS Bytecode (.js.bin) Atom Table Tool
Parses, displays, and modifies string atoms in compiled QuickJS bytecode.
Compatible with Alibaba HaaS UI / Falcon bytecode formats (QuickJS 20200705).
"""

import sys
import os

def read_leb128(data, idx):
    shift = 0
    val = 0
    while True:
        b = data[idx]
        idx += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return val, idx

def write_leb128(val):
    out = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val != 0:
            b |= 0x80
        out.append(b)
        if val == 0:
            break
    return bytes(out)

def parse_bytecode(data):
    assert data[0] == 1, "Invalid QuickJS bytecode header (expected tag 0x01)"
    atom_count, idx = read_leb128(data, 1)
    atoms = []
    for _ in range(atom_count):
        v, idx = read_leb128(data, idx)
        is_wide = v & 1
        length = v >> 1
        if is_wide:
            s = data[idx:idx + length * 2].decode("utf-16le", errors="replace")
            idx += length * 2
        else:
            s = data[idx:idx + length].decode("utf-8", errors="replace")
            idx += length
        atoms.append(s)
    raw_bytecode = data[idx:]
    return atoms, raw_bytecode

def serialize_bytecode(atoms, raw_bytecode):
    out = bytearray([1])
    out.extend(write_leb128(len(atoms)))
    for a in atoms:
        if isinstance(a, str):
            encoded = a.encode("utf-8")
        else:
            encoded = a
        v = (len(encoded) << 1) | 0
        out.extend(write_leb128(v))
        out.extend(encoded)
    out.extend(raw_bytecode)
    return bytes(out)

def dump_atoms(path):
    with open(path, "rb") as f:
        data = f.read()
    atoms, raw_code = parse_bytecode(data)
    print(f"File: {path} ({len(data)} bytes)")
    print(f"Atom count: {len(atoms)}, Bytecode instructions: {len(raw_code)} bytes\n")
    for i, a in enumerate(atoms):
        print(f"[{i:3d}] {repr(a)}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.js.bin>")
        sys.exit(1)
    dump_atoms(sys.argv[1])
