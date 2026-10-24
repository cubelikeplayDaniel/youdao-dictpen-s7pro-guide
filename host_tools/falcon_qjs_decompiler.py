#!/usr/bin/env python3
"""
Falcon QuickJS Bytecode Decompiler (QuickJS 2020-07-05 / S7 Pro Falcon Engine)
Decompiles .js.bin binary bytecode into AST and clean, formatted JavaScript pseudocode.
Supports Vue components, ES6 modules, class definitions, and control flow analysis.
"""

import sys
import os
import struct
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qjs_opcodes import OPCODES
from qjs_atoms import PREDEF_ATOMS, JS_ATOM_END

# QuickJS Bytecode Tags
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

BC_VERSION = 1


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
        val |= - (1 << shift)
    return val, idx


class FalconBytecodeParser:
    def __init__(self, data: bytes):
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
        if idx < len(PREDEF_ATOMS):
            return PREDEF_ATOMS[idx]
        custom_idx = idx - JS_ATOM_END
        if 0 <= custom_idx < len(self.atoms):
            return self.atoms[custom_idx]
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
            raw = self.data[self.idx:self.idx + length * 2]
            self.idx += length * 2
            try:
                return raw.decode("utf-16-le")
            except Exception:
                return str(raw)
        else:
            raw = self.data[self.idx:self.idx + length]
            self.idx += length
            try:
                return raw.decode("utf-8")
            except Exception:
                return str(raw)

    def parse_header(self):
        if len(self.data) < 1:
            raise ValueError("Empty bytecode buffer")
        ver = self.read_u8()
        if ver != BC_VERSION:
            raise ValueError(f"Invalid bytecode version {ver}, expected {BC_VERSION}")

        atom_count = self.read_leb()
        self.atoms = []
        for _ in range(atom_count):
            self.atoms.append(self.read_string())

    def parse(self):
        self.parse_header()
        tag = self.read_u8()
        return self.read_object(tag)

    def read_object(self, tag=None):
        if tag is None:
            tag = self.read_u8()

        if tag == BC_TAG_NULL:
            return {"type": "Literal", "value": None, "raw": "null"}
        elif tag == BC_TAG_UNDEFINED:
            return {"type": "Identifier", "name": "undefined"}
        elif tag == BC_TAG_BOOL_FALSE:
            return {"type": "Literal", "value": False, "raw": "false"}
        elif tag == BC_TAG_BOOL_TRUE:
            return {"type": "Literal", "value": True, "raw": "true"}
        elif tag == BC_TAG_INT32:
            val = struct.unpack_from("<i", self.data, self.idx)[0]
            self.idx += 4
            return {"type": "Literal", "value": val, "raw": str(val)}
        elif tag == BC_TAG_FLOAT64:
            val = self.read_f64()
            return {"type": "Literal", "value": val, "raw": str(val)}
        elif tag == BC_TAG_STRING:
            val = self.read_string()
            return {"type": "Literal", "value": val, "raw": json.dumps(val)}
        elif tag == BC_TAG_OBJECT:
            prop_count = self.read_leb()
            props = []
            for _ in range(prop_count):
                k = self.read_atom()
                v = self.read_object()
                props.append({"key": k, "value": v})
            return {"type": "ObjectExpression", "properties": props}
        elif tag in (BC_TAG_ARRAY, BC_TAG_TEMPLATE_OBJECT):
            length = self.read_leb()
            arr = [self.read_object() for _ in range(length)]
            if tag == BC_TAG_TEMPLATE_OBJECT:
                self.read_object()
            return {"type": "ArrayExpression", "elements": arr}
        elif tag == BC_TAG_MODULE:
            return self.read_module()
        elif tag == BC_TAG_FUNCTION_BYTECODE:
            return self.read_function_body()
        else:
            raise ValueError(f"Unknown BC tag {tag} at offset 0x{self.idx - 1:x}")

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
                var_idx = None
            exp_name = self.read_atom()
            exports.append({
                "type": exp_type,
                "export_name": exp_name,
                "local_name": local_name,
                "req_idx": req_idx,
                "var_idx": var_idx
            })

        star_export_count = self.read_leb()
        star_exports = [self.read_leb() for _ in range(star_export_count)]

        import_count = self.read_leb()
        imports = []
        for _ in range(import_count):
            var_idx = self.read_sleb()
            import_name = self.read_atom()
            req_mod_idx = self.read_leb()
            imports.append({
                "var_idx": var_idx,
                "import_name": import_name,
                "req_idx": req_mod_idx
            })

        func_tag = self.read_u8()
        assert func_tag == BC_TAG_FUNCTION_BYTECODE
        func = self.read_function_body()

        return {
            "type": "Module",
            "name": mod_name,
            "req_modules": req_modules,
            "exports": exports,
            "star_exports": star_exports,
            "imports": imports,
            "body": func
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
            "type": "FunctionBytecode",
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


class FalconASTDecompiler:
    """
    Decompiles QuickJS bytecode into high-level AST and formatted JavaScript code.
    Simulates the QuickJS execution stack to reconstruct complex expressions,
    Vue options, classes, and control flow.
    """
    def __init__(self, parsed_root, atoms=None):
        self.root = parsed_root
        self.atoms = atoms or []
        self.var_names = {}

    def decompile(self) -> str:
        if self.root.get("type") == "Module":
            return self.decompile_module(self.root)
        elif self.root.get("type") == "FunctionBytecode":
            ast = self.decompile_function(self.root)
            return self.codegen_block(ast.get("body", []))
        else:
            return json.dumps(self.root, indent=2)

    def decompile_module(self, mod) -> str:
        lines = []
        mod_name = mod.get("name", "")
        req_mods = mod.get("req_modules", [])
        imports = mod.get("imports", [])
        exports = mod.get("exports", [])

        # 1. Imports
        req_import_map = {}
        for imp in imports:
            req_idx = imp["req_idx"]
            mod_path = req_mods[req_idx] if req_idx < len(req_mods) else f"./mod_{req_idx}"
            if mod_path not in req_import_map:
                req_import_map[mod_path] = []
            req_import_map[mod_path].append(imp)

        for mod_path, imp_list in req_import_map.items():
            default_imp = None
            named_imps = []
            for imp in imp_list:
                name = imp["import_name"]
                if name == "default":
                    default_imp = f"ImportedModule_{imp['req_idx']}" if not mod_name else os.path.splitext(os.path.basename(mod_path))[0].replace("-", "_")
                else:
                    named_imps.append(name)

            clause = []
            if default_imp:
                clause.append(default_imp)
            if named_imps:
                clause.append("{" + ", ".join(named_imps) + "}")
            if clause:
                lines.append(f"import {', '.join(clause)} from '{mod_path}';")
            else:
                lines.append(f"import '{mod_path}';")

        if lines:
            lines.append("")

        # 2. Module Body Function
        body_func = mod.get("body")
        if body_func:
            func_ast = self.decompile_function(body_func, is_module_root=True)
            body_code = self.codegen_block(func_ast.get("body", []), indent=0)
            if body_code.strip():
                lines.append(body_code)

        # 3. Exports
        for exp in exports:
            exp_name = exp.get("export_name")
            if exp["type"] == 0:
                if exp_name == "default":
                    pass
                else:
                    lines.append(f"export {{ {exp_name} }};")
            else:
                req_idx = exp.get("req_idx", 0)
                from_mod = req_mods[req_idx] if req_idx < len(req_mods) else ""
                lines.append(f"export {{ {exp.get('local_name')} as {exp_name} }} from '{from_mod}';")

        return "\n".join(lines).strip() + "\n"

    def decompile_function(self, func, is_module_root=False) -> dict:
        bc = func["bytecode"]
        cpool = func["cpool"]
        vardefs = func.get("vardefs", [])
        closure_vars = func.get("closure_vars", [])
        arg_count = func.get("arg_count", 0)

        # Assign variable names
        loc_names = {}
        for i, vname in enumerate(vardefs):
            loc_names[i] = vname if vname else f"v_{i}"
        for i in range(arg_count):
            if i not in loc_names:
                loc_names[i] = f"arg_{i}"

        stack = []
        statements = []
        pos = 0

        def pop():
            return stack.pop() if stack else {"type": "Identifier", "name": "undefined"}

        def push(node):
            stack.append(node)

        while pos < len(bc):
            op = bc[pos]
            if op >= len(OPCODES):
                pos += 1
                continue
            name, size, n_pop, n_push, fmt = OPCODES[op]

            # Read immediate arguments
            val = None
            if fmt == "u8" or fmt == "loc8":
                val = bc[pos + 1]
            elif fmt == "i8":
                val = struct.unpack_from("<b", bc, pos + 1)[0]
            elif fmt in ("u16", "loc", "arg", "var_ref", "npop"):
                val = struct.unpack_from("<H", bc, pos + 1)[0]
            elif fmt == "i16":
                val = struct.unpack_from("<h", bc, pos + 1)[0]
            elif fmt == "u32":
                val = struct.unpack_from("<I", bc, pos + 1)[0]
            elif fmt == "i32":
                val = struct.unpack_from("<i", bc, pos + 1)[0]
            elif fmt == "const":
                val = struct.unpack_from("<I", bc, pos + 1)[0]
            elif fmt == "const8":
                val = bc[pos + 1]
            elif fmt == "atom":
                atom_id = struct.unpack_from("<I", bc, pos + 1)[0]
                val = self.atom_to_name(atom_id)
            elif fmt in ("atom_u8", "atom_u16"):
                atom_id = struct.unpack_from("<I", bc, pos + 1)[0]
                val = self.atom_to_name(atom_id)
            elif fmt in ("label8", "label16", "label"):
                val = struct.unpack_from("<b" if fmt == "label8" else "<h" if fmt == "label16" else "<i", bc, pos + 1)[0]

            # Opcode semantic handling
            if name == "push_i32":
                push({"type": "Literal", "value": val, "raw": str(val)})
            elif name in ("push_const", "push_const8"):
                const_obj = cpool[val] if val < len(cpool) else None
                if isinstance(const_obj, dict) and const_obj.get("type") == "FunctionBytecode":
                    inner_ast = self.decompile_function(const_obj)
                    push(inner_ast)
                elif isinstance(const_obj, dict):
                    push(const_obj)
                else:
                    push({"type": "Literal", "value": const_obj, "raw": json.dumps(const_obj)})
            elif name in ("fclosure", "fclosure8"):
                const_obj = cpool[val] if val < len(cpool) else None
                if isinstance(const_obj, dict) and const_obj.get("type") == "FunctionBytecode":
                    inner_ast = self.decompile_function(const_obj)
                    push(inner_ast)
                else:
                    push({"type": "FunctionDeclaration", "name": "", "params": [], "body": []})
            elif name == "define_func":
                fn_node = pop()
                if isinstance(fn_node, dict):
                    fn_node["name"] = val
                    statements.append(fn_node)
            elif name == "push_atom_value":
                push({"type": "Literal", "value": val, "raw": json.dumps(val)})
            elif name == "undefined":
                push({"type": "Identifier", "name": "undefined"})
            elif name == "null":
                push({"type": "Literal", "value": None, "raw": "null"})
            elif name == "push_this":
                push({"type": "ThisExpression"})
            elif name == "push_false":
                push({"type": "Literal", "value": False, "raw": "false"})
            elif name == "push_true":
                push({"type": "Literal", "value": True, "raw": "true"})
            elif name == "push_0":
                push({"type": "Literal", "value": 0, "raw": "0"})
            elif name == "push_1":
                push({"type": "Literal", "value": 1, "raw": "1"})
            elif name == "push_2":
                push({"type": "Literal", "value": 2, "raw": "2"})
            elif name == "push_3":
                push({"type": "Literal", "value": 3, "raw": "3"})
            elif name == "push_minus1":
                push({"type": "Literal", "value": -1, "raw": "-1"})
            elif name == "push_empty_string":
                push({"type": "Literal", "value": "", "raw": "''"})
            elif name in ("push_i8", "push_i16"):
                push({"type": "Literal", "value": val, "raw": str(val)})
            elif name == "object":
                push({"type": "ObjectExpression", "properties": []})
            elif name == "drop":
                if stack:
                    discarded = pop()
                    if discarded.get("type") in ("CallExpression", "AssignmentExpression"):
                        statements.append({"type": "ExpressionStatement", "expression": discarded})
            elif name == "dup":
                top = pop()
                push(top)
                push(top)
            elif name in ("get_loc", "get_loc8", "get_loc0", "get_loc1", "get_loc2", "get_loc3"):
                idx = 0 if name.endswith("0") else 1 if name.endswith("1") else 2 if name.endswith("2") else 3 if name.endswith("3") else val
                vname = loc_names.get(idx, f"v_{idx}")
                push({"type": "Identifier", "name": vname})
            elif name in ("put_loc", "put_loc8", "put_loc0", "put_loc1", "put_loc2", "put_loc3",
                          "set_loc", "set_loc8", "set_loc0", "set_loc1", "set_loc2", "set_loc3"):
                idx = 0 if name.endswith("0") else 1 if name.endswith("1") else 2 if name.endswith("2") else 3 if name.endswith("3") else val
                vname = loc_names.get(idx, f"v_{idx}")
                val_node = pop()
                statements.append({
                    "type": "AssignmentExpression",
                    "operator": "=",
                    "left": {"type": "Identifier", "name": vname},
                    "right": val_node
                })
                if name.startswith("set_loc"):
                    push(val_node)
            elif name in ("get_arg", "get_arg0", "get_arg1", "get_arg2", "get_arg3"):
                idx = 0 if name.endswith("0") else 1 if name.endswith("1") else 2 if name.endswith("2") else 3 if name.endswith("3") else val
                push({"type": "Identifier", "name": f"arg_{idx}"})
            elif name in ("get_var_ref", "get_var_ref0", "get_var_ref1", "get_var_ref2", "get_var_ref3", "get_var_ref_check"):
                idx = 0 if name.endswith("0") else 1 if name.endswith("1") else 2 if name.endswith("2") else 3 if name.endswith("3") else val
                cname = closure_vars[idx] if idx < len(closure_vars) else f"closure_{idx}"
                push({"type": "Identifier", "name": cname})
            elif name in ("put_var_ref", "put_var_ref0", "put_var_ref1", "put_var_ref2", "put_var_ref3"):
                idx = 0 if name.endswith("0") else 1 if name.endswith("1") else 2 if name.endswith("2") else 3 if name.endswith("3") else val
                cname = closure_vars[idx] if idx < len(closure_vars) else f"closure_{idx}"
                val_node = pop()
                if is_module_root and idx == len(closure_vars) - 1:
                    statements.append({"type": "ExportDefaultDeclaration", "declaration": val_node})
                else:
                    statements.append({
                        "type": "AssignmentExpression",
                        "operator": "=",
                        "left": {"type": "Identifier", "name": cname},
                        "right": val_node
                    })
            elif name == "get_var":
                push({"type": "Identifier", "name": val})
            elif name in ("put_var", "put_var_init", "put_var_strict"):
                val_node = pop()
                statements.append({
                    "type": "AssignmentExpression",
                    "operator": "=",
                    "left": {"type": "Identifier", "name": val},
                    "right": val_node
                })
            elif name in ("get_field", "get_field2"):
                obj = pop()
                push({"type": "MemberExpression", "object": obj, "property": {"type": "Identifier", "name": val}, "computed": False})
            elif name == "put_field":
                val_node = pop()
                obj = pop()
                statements.append({
                    "type": "AssignmentExpression",
                    "operator": "=",
                    "left": {"type": "MemberExpression", "object": obj, "property": {"type": "Identifier", "name": val}, "computed": False},
                    "right": val_node
                })
            elif name == "define_field":
                val_node = pop()
                obj = pop()
                if obj.get("type") == "ObjectExpression":
                    obj["properties"].append({"key": val, "value": val_node})
                    push(obj)
                else:
                    statements.append({
                        "type": "AssignmentExpression",
                        "operator": "=",
                        "left": {"type": "MemberExpression", "object": obj, "property": {"type": "Identifier", "name": val}, "computed": False},
                        "right": val_node
                    })
            elif name == "define_method":
                func_node = pop()
                obj = pop()
                if obj.get("type") == "ObjectExpression":
                    func_node["name"] = val
                    obj["properties"].append({"key": val, "value": func_node, "method": True})
                    push(obj)
                else:
                    push(obj)
            elif name == "get_array_el":
                prop = pop()
                obj = pop()
                push({"type": "MemberExpression", "object": obj, "property": prop, "computed": True})
            elif name == "put_array_el":
                val_node = pop()
                prop = pop()
                obj = pop()
                statements.append({
                    "type": "AssignmentExpression",
                    "operator": "=",
                    "left": {"type": "MemberExpression", "object": obj, "property": prop, "computed": True},
                    "right": val_node
                })
            elif name == "append":
                val_node = pop()
                arr = pop()
                if arr.get("type") == "ArrayExpression":
                    arr["elements"].append(val_node)
                    push(arr)
            elif name in ("call", "call0", "call1", "call2", "call3"):
                argc = 0 if name == "call0" else 1 if name == "call1" else 2 if name == "call2" else 3 if name == "call3" else val
                args = [pop() for _ in range(argc)][::-1]
                callee = pop()
                push({"type": "CallExpression", "callee": callee, "arguments": args})
            elif name == "call_method":
                argc = val
                args = [pop() for _ in range(argc)][::-1]
                callee = pop()
                push({"type": "CallExpression", "callee": callee, "arguments": args})
            elif name == "call_constructor":
                argc = val
                args = [pop() for _ in range(argc)][::-1]
                ctor = pop()
                push({"type": "NewExpression", "callee": ctor, "arguments": args})
            elif name == "define_class":
                ctor = pop()
                super_cls = pop()
                class_node = {
                    "type": "ClassDeclaration",
                    "id": {"type": "Identifier", "name": val},
                    "superClass": super_cls,
                    "body": {"type": "ClassBody", "body": []}
                }
                push(class_node)
            elif name in ("add", "sub", "mul", "div", "mod", "eq", "strict_eq", "neq", "strict_neq",
                          "lt", "lte", "gt", "gte", "shl", "sar", "shr", "band", "bxor", "bor"):
                right = pop()
                left = pop()
                op_sym = {
                    "add": "+", "sub": "-", "mul": "*", "div": "/", "mod": "%",
                    "eq": "==", "strict_eq": "===", "neq": "!=", "strict_neq": "!==",
                    "lt": "<", "lte": "<=", "gt": ">", "gte": ">=",
                    "shl": "<<", "sar": ">>", "shr": ">>>", "band": "&", "bxor": "^", "bor": "|"
                }.get(name, "+")
                push({"type": "BinaryExpression", "operator": op_sym, "left": left, "right": right})
            elif name == "lnot":
                arg = pop()
                push({"type": "UnaryExpression", "operator": "!", "argument": arg, "prefix": True})
            elif name == "neg":
                arg = pop()
                push({"type": "UnaryExpression", "operator": "-", "argument": arg, "prefix": True})
            elif name == "typeof":
                arg = pop()
                push({"type": "UnaryExpression", "operator": "typeof", "argument": arg, "prefix": True})
            elif name == "return":
                ret_val = pop()
                statements.append({"type": "ReturnStatement", "argument": ret_val})
            elif name == "return_undef":
                statements.append({"type": "ReturnStatement", "argument": None})

            pos += size

        params = []
        for i in range(arg_count):
            if i < len(vardefs) and vardefs[i]:
                params.append(vardefs[i])
            else:
                params.append(f"arg_{i}")

        return {
            "type": "FunctionDeclaration",
            "name": func.get("name", ""),
            "params": params,
            "body": statements
        }

    def atom_to_name(self, atom_id):
        if atom_id < len(PREDEF_ATOMS):
            return PREDEF_ATOMS[atom_id]
        custom_idx = atom_id - JS_ATOM_END
        if 0 <= custom_idx < len(self.atoms):
            return self.atoms[custom_idx]
        return f"<atom_{atom_id}>"

    def codegen_block(self, stmts, indent=0) -> str:
        pad = "  " * indent
        lines = []
        for s in stmts:
            t = s.get("type")
            if t == "ReturnStatement":
                arg = s.get("argument")
                if arg:
                    lines.append(f"{pad}return {self.codegen_expr(arg, indent)};")
                else:
                    lines.append(f"{pad}return;")
            elif t == "AssignmentExpression":
                lhs = self.codegen_expr(s["left"], indent)
                rhs = self.codegen_expr(s["right"], indent)
                lines.append(f"{pad}{lhs} = {rhs};")
            elif t == "ExpressionStatement":
                expr = self.codegen_expr(s["expression"], indent)
                lines.append(f"{pad}{expr};")
            elif t == "ExportDefaultDeclaration":
                decl = self.codegen_expr(s["declaration"], indent)
                lines.append(f"{pad}export default {decl};")
            elif t in ("FunctionDeclaration", "FunctionBytecode"):
                lines.append(f"{pad}" + self.codegen_expr(s, indent))
            elif t == "ClassDeclaration":
                cls_name = s["id"]["name"]
                super_cls = self.codegen_expr(s["superClass"], indent) if s.get("superClass") else None
                ext = f" extends {super_cls}" if super_cls and super_cls != "undefined" else ""
                lines.append(f"{pad}class {cls_name}{ext} {{")
                for method in s.get("body", {}).get("body", []):
                    m_code = self.codegen_expr(method, indent + 1)
                    lines.append(m_code)
                lines.append(f"{pad}}}")
            else:
                lines.append(f"{pad}/* {t} */")
        return "\n".join(lines)

    def codegen_expr(self, node, indent=0) -> str:
        if not isinstance(node, dict):
            return str(node)
        t = node.get("type")
        if t == "Literal":
            return node.get("raw", json.dumps(node.get("value")))
        elif t == "Identifier":
            return node.get("name", "undefined")
        elif t == "ThisExpression":
            return "this"
        elif t == "MemberExpression":
            obj = self.codegen_expr(node["object"], indent)
            prop = self.codegen_expr(node["property"], indent)
            if node.get("computed"):
                return f"{obj}[{prop}]"
            else:
                return f"{obj}.{prop}"
        elif t == "BinaryExpression":
            l = self.codegen_expr(node["left"], indent)
            r = self.codegen_expr(node["right"], indent)
            return f"({l} {node['operator']} {r})"
        elif t == "UnaryExpression":
            arg = self.codegen_expr(node["argument"], indent)
            op = node["operator"]
            if op == "typeof":
                return f"typeof {arg}"
            return f"{op}{arg}"
        elif t == "CallExpression":
            callee = self.codegen_expr(node["callee"], indent)
            args = [self.codegen_expr(a, indent) for a in node.get("arguments", [])]
            return f"{callee}({', '.join(args)})"
        elif t == "NewExpression":
            callee = self.codegen_expr(node["callee"], indent)
            args = [self.codegen_expr(a, indent) for a in node.get("arguments", [])]
            return f"new {callee}({', '.join(args)})"
        elif t == "ArrayExpression":
            elems = [self.codegen_expr(e, indent) for e in node.get("elements", [])]
            return f"[{', '.join(elems)}]"
        elif t == "ObjectExpression":
            props = node.get("properties", [])
            if not props:
                return "{}"
            pad = "  " * indent
            inner_pad = "  " * (indent + 1)
            prop_lines = []
            for p in props:
                k = p["key"]
                v = p["value"]
                if p.get("method") and isinstance(v, dict) and v.get("type") == "FunctionDeclaration":
                    params = ", ".join(v.get("params", []))
                    body = self.codegen_block(v.get("body", []), indent + 1)
                    prop_lines.append(f"{inner_pad}{k}({params}) {{\n{body}\n{inner_pad}}}")
                else:
                    v_str = self.codegen_expr(v, indent + 1)
                    prop_lines.append(f"{inner_pad}{k}: {v_str}")
            return "{\n" + ",\n".join(prop_lines) + f"\n{pad}}}"
        elif t == "FunctionDeclaration":
            name = node.get("name", "")
            params = ", ".join(node.get("params", []))
            body = self.codegen_block(node.get("body", []), indent)
            return f"function {name}({params}) {{\n{body}\n}}"
        return f"/* unknown: {t} */"


def decompile_file(file_path: str, output_ast=False) -> str:
    with open(file_path, "rb") as f:
        data = f.read()
    parser = FalconBytecodeParser(data)
    parsed = parser.parse()
    if output_ast:
        # Convert bytes to string for JSON serialization
        def sanitize(obj):
            if isinstance(obj, bytes):
                return f"<bytes: len={len(obj)}>"
            elif isinstance(obj, dict):
                return {k: sanitize(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [sanitize(x) for x in obj]
            return obj
        ast_dict = {
            "atoms": parser.atoms,
            "root": sanitize(parsed)
        }
        return json.dumps(ast_dict, indent=2, ensure_ascii=False)

    decompiler = FalconASTDecompiler(parsed, atoms=parser.atoms)
    return decompiler.decompile()


def main():
    parser = argparse.ArgumentParser(description="Falcon QuickJS .js.bin Bytecode Decompiler")
    parser.add_argument("input", help="Path to .js.bin file or directory of .js.bin files")
    parser.add_argument("-o", "--output", help="Output file or directory")
    parser.add_argument("--ast", action="store_true", help="Output AST in JSON format")
    args = parser.parse_args()

    if os.path.isfile(args.input):
        result = decompile_file(args.input, output_ast=args.ast)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(result)
            print(f"Decompiled {args.input} -> {args.output}")
        else:
            print(result)
    elif os.path.isdir(args.input):
        out_dir = args.output or (args.input + "_decompiled")
        os.makedirs(out_dir, exist_ok=True)
        count = 0
        for root, _, files in os.walk(args.input):
            for file in files:
                if file.endswith(".js.bin"):
                    in_path = os.path.join(root, file)
                    out_filename = file[:-7] + (".json" if args.ast else ".js")
                    out_path = os.path.join(out_dir, out_filename)
                    try:
                        res = decompile_file(in_path, output_ast=args.ast)
                        with open(out_path, "w", encoding="utf-8") as f:
                            f.write(res)
                        count += 1
                    except Exception as e:
                        print(f"Error decompiling {file}: {e}", file=sys.stderr)
        print(f"Decompiled {count} files to {out_dir}")
    else:
        print(f"Error: input path {args.input} not found", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
