#!/usr/bin/env python3
import sys
import os
import re
import subprocess

def compile_js_to_bin(js_path, bin_path, is_module=False, external_modules=None):
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    qjsc = os.path.join(repo_dir, "host_tools", "qjsc")
    if not os.path.exists(qjsc):
        raise FileNotFoundError(f"qjsc compiler not found at {qjsc}")

    c_out = bin_path + ".tmp.c"
    cmd = [qjsc]
    if is_module:
        cmd.append("-m")
    if external_modules:
        for mod in external_modules:
            cmd.extend(["-M", mod])
    cmd.extend(["-c", "-o", c_out, js_path])
    
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"qjsc compilation failed: {res.stderr}")
    
    with open(c_out, "r") as f:
        c_content = f.read()
    if os.path.exists(c_out):
        os.remove(c_out)
    
    match = re.search(r"const uint8_t [^\[]+\[\d+\] = \{([^}]+)\};", c_content, re.DOTALL)
    if not match:
        raise ValueError("Could not find byte array in qjsc output")
    
    hex_str = match.group(1)
    bytes_list = [int(x.strip(), 16) for x in hex_str.split(",") if x.strip()]
    bin_data = bytes(bytes_list)
    
    with open(bin_path, "wb") as f:
        f.write(bin_data)
    
    return len(bin_data)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: compile_js_bin.py <input.js> <output.js.bin> [-m] [-M module_name]")
        sys.exit(1)
    is_m = "-m" in sys.argv
    ext_mods = []
    for i, arg in enumerate(sys.argv):
        if arg == "-M" and i + 1 < len(sys.argv):
            ext_mods.append(sys.argv[i + 1])
    size = compile_js_to_bin(sys.argv[1], sys.argv[2], is_module=is_m, external_modules=ext_mods)
    print(f"Compiled {sys.argv[1]} -> {sys.argv[2]} ({size} bytes)")
