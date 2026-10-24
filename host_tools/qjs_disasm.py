#!/usr/bin/env python3
"""
QuickJS Bytecode Disassembler for Falcon (QuickJS 2020-07-05)
"""

import sys
import os
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qjs_opcodes import OPCODES
from qjs_atoms import PREDEF_ATOMS, JS_ATOM_END

def short_opcode_info(op):
    if op < len(OPCODES):
        return OPCODES[op]
    return ('<unknown>', 1, 0, 0, 'none')

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

def read_sleb128(data, idx):
    shift = 0
    val = 0
    while True:
        b = data[idx]
        idx += 1
        val |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    if shift < 32 and (b & 0x40):
        val |= -(1 << shift)
    return val, idx

BC_TAG_NULL = 1
BC_TAG_UNDEFINED = 2
BC_TAG_BOOL_FALSE = 3
BC_TAG_BOOL_TRUE = 4
BC_TAG_INT32 = 5
BC_TAG_FLOAT64 = 6
BC_TAG_STRING = 7
BC_TAG_OBJECT = 8
BC_TAG_ARRAY = 9
BC_TAG_BIG_INT = 10
BC_TAG_BIG_FLOAT = 11
BC_TAG_BIG_DECIMAL = 12
BC_TAG_TEMPLATE_OBJECT = 13
BC_TAG_FUNCTION_BYTECODE = 14
BC_TAG_MODULE = 15
BC_TAG_TYPED_ARRAY = 16
BC_TAG_ARRAY_BUFFER = 17
BC_TAG_SHARED_ARRAY_BUFFER = 18
BC_TAG_DATE = 19
BC_TAG_OBJECT_VALUE = 20
BC_TAG_OBJECT_REFERENCE = 21

class QJSDisassembler:
    def __init__(self, data):
        self.data = data
        self.idx = 0
        self.atoms = []

    def read_u8(self):
        b = self.data[self.idx]
        self.idx += 1
        return b

    def read_u16(self):
        v = struct.unpack_from("<H", self.data, self.idx)[0]
        self.idx += 2
        return v

    def read_u32(self):
        v = struct.unpack_from("<I", self.data, self.idx)[0]
        self.idx += 4
        return v

    def read_f64(self):
        v = struct.unpack_from("<d", self.data, self.idx)[0]
        self.idx += 8
        return v

    def read_leb(self):
        val, self.idx = read_leb128(self.data, self.idx)
        return val

    def read_sleb(self):
        val, self.idx = read_sleb128(self.data, self.idx)
        return val

    def atom_to_str(self, idx):
        if idx < JS_ATOM_END:
            return PREDEF_ATOMS[idx]
        user_idx = idx - JS_ATOM_END
        if user_idx < len(self.atoms):
            return self.atoms[user_idx]
        return f"<atom_{idx}>"

    def read_atom(self):
        v = self.read_leb()
        if v & 1:
            return f"{v >> 1}"
        idx = v >> 1
        return self.atom_to_str(idx)

    def read_string(self):
        v = self.read_leb()
        is_wide = v & 1
        length = v >> 1
        if is_wide:
            s = self.data[self.idx:self.idx + length * 2].decode("utf-16le", errors="replace")
            self.idx += length * 2
        else:
            s = self.data[self.idx:self.idx + length].decode("utf-8", errors="replace")
            self.idx += length
        return s

    def parse_header(self):
        ver = self.read_u8()
        assert ver == 1, f"Expected version 1, got {ver}"
        atom_count = self.read_leb()
        for _ in range(atom_count):
            self.atoms.append(self.read_string())

    def read_object(self):
        tag = self.read_u8()
        if tag == BC_TAG_NULL:
            return None
        elif tag == BC_TAG_UNDEFINED:
            return "<undefined>"
        elif tag == BC_TAG_BOOL_FALSE:
            return False
        elif tag == BC_TAG_BOOL_TRUE:
            return True
        elif tag == BC_TAG_INT32:
            return self.read_sleb()
        elif tag == BC_TAG_FLOAT64:
            return self.read_f64()
        elif tag == BC_TAG_STRING:
            return self.read_string()
        elif tag == BC_TAG_OBJECT:
            prop_count = self.read_leb()
            obj = {}
            for _ in range(prop_count):
                k = self.read_atom()
                v = self.read_object()
                obj[k] = v
            return obj
        elif tag in (BC_TAG_ARRAY, BC_TAG_TEMPLATE_OBJECT):
            length = self.read_leb()
            arr = [self.read_object() for _ in range(length)]
            if tag == BC_TAG_TEMPLATE_OBJECT:
                self.read_object()
            return arr
        elif tag == BC_TAG_MODULE:
            return self.read_module()
        elif tag == BC_TAG_FUNCTION_BYTECODE:
            return self.read_function_body()
        else:
            raise ValueError(f"Unknown BC tag {tag} at offset {self.idx - 1}")

    def read_module(self):
        mod_name = self.read_atom()
        req_count = self.read_leb()
        req_modules = [self.read_atom() for _ in range(req_count)]

        export_count = self.read_leb()
        exports = []
        for _ in range(export_count):
            exp_type = self.read_u8()
            if exp_type == 0:
                var_idx = self.read_leb()
                local_name = None
                req_idx = None
            else:
                req_idx = self.read_leb()
                local_name = self.read_atom()
            exp_name = self.read_atom()
            exports.append((exp_type, exp_name, local_name, req_idx))

        star_export_count = self.read_leb()
        star_exports = [self.read_leb() for _ in range(star_export_count)]

        import_count = self.read_leb()
        imports = []
        for _ in range(import_count):
            var_idx = self.read_sleb()
            import_name = self.read_atom()
            req_mod_idx = self.read_leb()
            imports.append((var_idx, import_name, req_mod_idx))

        func_tag = self.read_u8()
        assert func_tag == BC_TAG_FUNCTION_BYTECODE
        func = self.read_function_body()

        return {
            "type": "Module",
            "name": mod_name,
            "req_modules": req_modules,
            "exports": exports,
            "imports": imports,
            "func": func
        }

    def read_function_body(self):
        flags = self.read_u16()
        has_debug = bool((flags >> 9) & 1)
        js_mode = self.read_u8()
        func_name = self.read_atom()
        arg_count = self.read_leb()
        var_count = self.read_leb()
        def_arg_count = self.read_leb()
        stack_size = self.read_leb()
        closure_var_count = self.read_leb()
        cpool_count = self.read_leb()
        byte_code_len = self.read_leb()

        total_vars = self.read_leb()
        vardefs = []
        for _ in range(total_vars):
            vname = self.read_atom()
            scope_next = self.read_leb() - 1
            var_ref_idx = self.read_leb()
            flags_var = self.read_u8()
            vardefs.append(vname)

        closure_vars = []
        for _ in range(closure_var_count):
            cname = self.read_atom()
            v_idx = self.read_leb()
            f = self.read_u8()
            closure_vars.append(cname)

        bytecode = self.data[self.idx:self.idx + byte_code_len]
        self.idx += byte_code_len

        debug_info = None
        if has_debug:
            dbg_filename = self.read_atom()
            line_num = self.read_leb()
            pc2line_len = self.read_leb()
            pc2line = self.data[self.idx:self.idx + pc2line_len]
            self.idx += pc2line_len
            debug_info = {"file": dbg_filename, "line": line_num}

        cpool = []
        for _ in range(cpool_count):
            cpool.append(self.read_object())

        return {
            "type": "Function",
            "name": func_name,
            "arg_count": arg_count,
            "var_count": var_count,
            "stack_size": stack_size,
            "vardefs": vardefs,
            "closure_vars": closure_vars,
            "bytecode": bytecode,
            "debug": debug_info,
            "cpool": cpool
        }

    def disasm_bc(self, func, indent=""):
        bc = func["bytecode"]
        cpool = func["cpool"]
        pos = 0
        lines = []
        while pos < len(bc):
            op = bc[pos]
            name, size, n_pop, n_push, fmt = short_opcode_info(op)
            pos_next = pos + size
            arg_str = ""
            if fmt == "none" or fmt == "none_int" or fmt == "none_loc" or fmt == "none_arg" or fmt == "none_var_ref" or fmt == "npopx":
                pass
            elif fmt == "u8":
                val = bc[pos + 1]
                arg_str = f"{val}"
            elif fmt == "i8":
                val = struct.unpack_from("<b", bc, pos + 1)[0]
                arg_str = f"{val}"
            elif fmt == "loc8":
                val = bc[pos + 1]
                vname = func["vardefs"][val] if val < len(func["vardefs"]) else f"loc{val}"
                arg_str = f"loc{val} ({vname})"
            elif fmt == "const8":
                idx = bc[pos + 1]
                cp_val = cpool[idx] if idx < len(cpool) else "?"
                if isinstance(cp_val, dict) and cp_val.get("type") == "Function":
                    arg_str = f"const[{idx}] -> Function '{cp_val['name']}'"
                else:
                    arg_str = f"const[{idx}] = {repr(cp_val)}"
            elif fmt == "label8":
                val = struct.unpack_from("<b", bc, pos + 1)[0]
                target = pos + 2 + val
                arg_str = f"-> {target:4d}"
            elif fmt == "u16" or fmt == "arg" or fmt == "loc" or fmt == "var_ref" or fmt == "npop":
                val = struct.unpack_from("<H", bc, pos + 1)[0]
                arg_str = f"{val}"
            elif fmt == "label16":
                val = struct.unpack_from("<h", bc, pos + 1)[0]
                target = pos + 3 + val
                arg_str = f"-> {target:4d}"
            elif fmt == "i32" or fmt == "u32":
                val = struct.unpack_from("<i", bc, pos + 1)[0]
                arg_str = f"{val}"
            elif fmt == "label":
                val = struct.unpack_from("<i", bc, pos + 1)[0]
                target = pos + 5 + val
                arg_str = f"-> {target:4d}"
            elif fmt == "const":
                idx = struct.unpack_from("<I", bc, pos + 1)[0]
                cp_val = cpool[idx] if idx < len(cpool) else "?"
                if isinstance(cp_val, dict) and cp_val.get("type") == "Function":
                    arg_str = f"const[{idx}] -> Function '{cp_val['name']}'"
                else:
                    arg_str = f"const[{idx}] = {repr(cp_val)}"
            elif fmt == "atom":
                atom_idx = struct.unpack_from("<I", bc, pos + 1)[0]
                astr = self.atom_to_str(atom_idx)
                arg_str = f"'{astr}'"
            elif fmt == "atom_u8":
                atom_idx = struct.unpack_from("<I", bc, pos + 1)[0]
                u8_val = bc[pos + 5]
                astr = self.atom_to_str(atom_idx)
                arg_str = f"'{astr}', {u8_val}"
            elif fmt == "atom_u16":
                atom_idx = struct.unpack_from("<I", bc, pos + 1)[0]
                u16_val = struct.unpack_from("<H", bc, pos + 5)[0]
                astr = self.atom_to_str(atom_idx)
                arg_str = f"'{astr}', {u16_val}"
            lines.append(f"{indent}  {pos:4d}: {name:20s} {arg_str}")
            pos = pos_next
        return "\n".join(lines)

def print_function(disasm, f, depth=0):
    indent = "  " * depth
    print(f"\n{indent}=== Function: '{f['name']}' (args={f['arg_count']}, vars={f['var_count']}, closures={f['closure_vars']}) ===")
    if f["debug"]:
        print(f"{indent}Debug: {f['debug']}")
    print(f"{indent}Vardefs: {f['vardefs']}")
    print(f"{indent}Disassembly:")
    dis = disasm.disasm_bc(f, indent)
    print(dis)
    for ci, c in enumerate(f["cpool"]):
        if isinstance(c, dict) and c.get("type") == "Function":
            print_function(disasm, c, depth + 1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: qjs_disasm.py <file.js.bin>")
        sys.exit(1)
    with open(sys.argv[1], "rb") as fp:
        data = fp.read()
    disasm = QJSDisassembler(data)
    disasm.parse_header()
    print("=== FILE SUMMARY ===")
    print(f"File: {sys.argv[1]} ({len(data)} bytes)")
    print(f"Atoms count: {len(disasm.atoms)}")
    top = disasm.read_object()
    if top.get("type") == "Module":
        print(f"Module: {top['name']}")
        print(f"Exports: {top['exports']}")
        print(f"Imports: {top['imports']}")
        print_function(disasm, top["func"])
    elif top.get("type") == "Function":
        print_function(disasm, top)
