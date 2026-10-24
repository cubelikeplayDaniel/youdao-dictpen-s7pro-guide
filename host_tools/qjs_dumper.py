import sys
import struct

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

JS_ATOM_END = 209  # QuickJS 2020-07-05 predefined atoms cutoff (0xd1)

class QJSReader:
    def __init__(self, data):
        self.data = data
        self.idx = 0
        self.atoms = []
        self.first_atom = JS_ATOM_END

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

    def read_i32(self):
        v = struct.unpack_from("<i", self.data, self.idx)[0]
        self.idx += 4
        return v

    def read_u64(self):
        v = struct.unpack_from("<Q", self.data, self.idx)[0]
        self.idx += 8
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

    def read_atom(self):
        v = self.read_leb()
        if v & 1:
            return f"<atom_uint32:{v >> 1}>"
        idx = v >> 1
        if idx < self.first_atom:
            return f"<predef_atom:{idx}>"
        user_idx = idx - self.first_atom
        if user_idx < len(self.atoms):
            return self.atoms[user_idx]
        return f"<unknown_atom:{idx}>"

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
                raw = self.read_object()
            return arr
        elif tag == BC_TAG_MODULE:
            return self.read_module()
        elif tag == BC_TAG_FUNCTION_BYTECODE:
            return self.read_function()
        else:
            raise ValueError(f"Unknown BC tag {tag} at offset {self.idx - 1}")

    def read_module(self):
        mod_name = self.read_atom()
        req_count = self.read_leb()
        req_modules = []
        for _ in range(req_count):
            req_name = self.read_atom()
            req_modules.append(req_name)

        export_count = self.read_leb()
        exports = []
        for _ in range(export_count):
            exp_type = self.read_u8()
            if exp_type == 0: # LOCAL
                var_idx = self.read_leb()
                local_name = None
                req_idx = None
            else:
                req_idx = self.read_leb()
                local_name = self.read_atom()
            exp_name = self.read_atom()
            exports.append((exp_type, exp_name, local_name, req_idx))

        star_export_count = self.read_leb()
        star_exports = []
        for _ in range(star_export_count):
            star_exports.append(self.read_leb())

        import_count = self.read_leb()
        imports = []
        for _ in range(import_count):
            var_idx = self.read_leb()
            import_name = self.read_atom()
            req_mod_idx = self.read_leb()
            imports.append((var_idx, import_name, req_mod_idx))

        # In QuickJS 2020-07-05 there is NO has_tla byte
        func = self.read_object()

        return {
            "type": "Module",
            "name": mod_name,
            "req_modules": req_modules,
            "exports": exports,
            "imports": imports,
            "func": func
        }

    def read_function(self):
        return self.read_function_body()

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
            vardefs.append((vname, scope_next, var_ref_idx, flags_var))

        closure_vars = []
        for _ in range(closure_var_count):
            cname = self.read_atom()
            v_idx = self.read_leb()
            f = self.read_u8()
            closure_vars.append((cname, v_idx, f))

        bytecode = self.data[self.idx:self.idx + byte_code_len]
        self.idx += byte_code_len

        debug_info = None
        if has_debug:
            dbg_filename = self.read_atom()
            line_num = self.read_leb()
            pc2line_len = self.read_leb()
            pc2line = self.data[self.idx:self.idx + pc2line_len]
            self.idx += pc2line_len
            debug_info = {"file": dbg_filename, "line": line_num, "pc2line_len": pc2line_len}

        cpool = []
        for _ in range(cpool_count):
            cpool.append(self.read_object())

        return {
            "name": func_name,
            "args": arg_count,
            "vars": var_count,
            "vardefs": [v[0] for v in vardefs],
            "closure_vars": [c[0] for c in closure_vars],
            "bytecode_len": len(bytecode),
            "bytecode": bytecode,
            "debug": debug_info,
            "cpool": cpool
        }

if __name__ == "__main__":
    with open(sys.argv[1], "rb") as f:
        data = f.read()
    r = QJSReader(data)
    r.parse_header()
    print("=== ATOMS ===")
    for i, a in enumerate(r.atoms):
        print(f"[{i:3d}] {repr(a)}")
    print("\n=== TOP LEVEL OBJECT ===")
    obj = r.read_object()
    import pprint
    def dump_summary(o, depth=0):
        indent = "  " * depth
        if isinstance(o, dict):
            if "type" in o and o["type"] == "Module":
                print(f"{indent}MODULE {o['name']}")
                print(f"{indent}  Req: {o['req_modules']}")
                print(f"{indent}  Exports: {o['exports']}")
                print(f"{indent}  Imports: {o['imports']}")
                print(f"{indent}  Function:")
                dump_summary(o["func"], depth + 1)
            elif "bytecode_len" in o:
                print(f"{indent}FUNCTION {o['name']} (args={o['args']}, vars={o['vars']}, cpool_count={len(o['cpool'])}, bc_len={o['bytecode_len']})")
                print(f"{indent}  vardefs: {o['vardefs']}")
                print(f"{indent}  closures: {o['closure_vars']}")
                if o['debug']:
                    print(f"{indent}  debug: {o['debug']}")
                print(f"{indent}  cpool:")
                for ci, c in enumerate(o['cpool']):
                    if isinstance(c, dict) and "bytecode_len" in c:
                        print(f"{indent}    [{ci}] Child Function:")
                        dump_summary(c, depth + 3)
                    else:
                        print(f"{indent}    [{ci}] {repr(c)}")
            else:
                pprint.pprint(o, depth=depth+1)
        else:
            print(f"{indent}{repr(o)}")
    dump_summary(obj)
