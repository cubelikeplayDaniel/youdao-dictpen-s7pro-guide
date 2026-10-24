#!/usr/bin/env python3
"""
Falcon Vue SFC Compiler (Python CLI interface)
Translates Vue 2.6 Single File Components (.vue) into Falcon-compatible JS bundles
and QuickJS 2020-07-05 bytecode (.js.bin) for Youdao Dictionary Pen S7 Pro.
"""

import sys
import os
import subprocess

def main():
    if len(sys.argv) < 2 or "-h" in sys.argv or "--help" in sys.argv:
        print("""Falcon Vue SFC Compiler
Usage: python3 falcon_vue_compiler.py <input.vue> [output.js or output.js.bin] [options]

Options:
  --page             Wrap component in a $falcon.Page class subclass
  --scope-id <id>    Custom scope ID (default: data-v-<hash>)
  --rel-path <path>  Custom relative file path for __file
  --js-only          Only produce .js file even if output is .js.bin
""")
        sys.exit(0)

    cur_dir = os.path.dirname(os.path.abspath(__file__))
    js_compiler = os.path.join(cur_dir, "falcon_vue_compiler.js")

    cmd = ["node", js_compiler] + sys.argv[1:]
    res = subprocess.run(cmd)
    sys.exit(res.returncode)

if __name__ == "__main__":
    main()
