#!/usr/bin/env python3
"""
Test suite for Falcon QuickJS Decompiler
Validates parsing, AST extraction, and pseudocode reconstruction
against both synthesized test bundles and real Youdao firmware .js.bin files.
"""

import os
import sys
import tempfile
import unittest
import subprocess

HOST_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
DECOMPILER = os.path.join(HOST_TOOLS_DIR, "falcon_qjs_decompiler.py")
COMPILE_TOOL = os.path.join(HOST_TOOLS_DIR, "compile_js_bin.py")
REVERSE_DUMP_DIR = os.path.join(os.path.dirname(HOST_TOOLS_DIR), "reverse_dump")

class TestFalconDecompiler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _compile_js(self, js_code, is_module=False, external_modules=None):
        js_file = os.path.join(self.temp_dir.name, "test.js")
        bin_file = os.path.join(self.temp_dir.name, "test.js.bin")
        with open(js_file, "w", encoding="utf-8") as f:
            f.write(js_code)
        cmd = [sys.executable, COMPILE_TOOL, js_file, bin_file]
        if is_module:
            cmd.append("-m")
        if external_modules:
            for mod in external_modules:
                cmd.extend(["-M", mod])
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Compilation failed: {res.stderr}")
        self.assertTrue(os.path.exists(bin_file))
        return bin_file

    def _decompile(self, bin_path, ast_mode=False):
        cmd = [sys.executable, DECOMPILER]
        if ast_mode:
            cmd.append("--ast")
        cmd.append(bin_path)
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Decompilation failed: {res.stderr}")
        return res.stdout

    def test_simple_function_bytecode(self):
        js_code = """
        function add(a, b) {
            return a + b;
        }
        """
        bin_path = self._compile_js(js_code)
        output = self._decompile(bin_path)
        self.assertIn("function add", output)
        self.assertIn("return", output)

    def test_object_and_math_bytecode(self):
        js_code = """
        const config = {
            timeout: 5000,
            retries: 3,
            enabled: true
        };
        function calculateArea(width, height) {
            return width * height;
        }
        """
        bin_path = self._compile_js(js_code)
        output = self._decompile(bin_path)
        self.assertIn("5000", output)
        self.assertIn("calculateArea", output)

    def test_module_exports_and_imports(self):
        js_code = """
        import { foo } from 'bar';
        export const pi = 3.14159;
        export default function run() {
            return foo() + 42;
        }
        """
        bin_path = self._compile_js(js_code, is_module=True, external_modules=['bar'])
        output = self._decompile(bin_path)
        self.assertIn("import", output)
        self.assertIn("bar", output)
        self.assertIn("export default", output)

    def test_ast_json_mode(self):
        js_code = "function greet(name) { return 'Hello, ' + name; }"
        bin_path = self._compile_js(js_code)
        output = self._decompile(bin_path, ast_mode=True)
        import json
        ast = json.loads(output)
        self.assertIn("atoms", ast)
        self.assertIn("root", ast)
        self.assertEqual(ast["root"]["type"], "FunctionBytecode")

    def test_firmware_global_manager(self):
        bin_path = os.path.join(REVERSE_DUMP_DIR, "8080222437664451/a/globalManager-3d6cf71e.js.bin")
        if not os.path.exists(bin_path):
            self.skipTest("Firmware binary not present")
        output = self._decompile(bin_path)
        self.assertIn("import global from 'global'", output)
        self.assertIn("getGlobalManager", output)
        self.assertIn("export default", output)

    def test_firmware_wifi_manager(self):
        bin_path = os.path.join(REVERSE_DUMP_DIR, "8080222437664451/a/wifiManager-c4516d12.js.bin")
        if not os.path.exists(bin_path):
            self.skipTest("Firmware binary not present")
        output = self._decompile(bin_path)
        self.assertIn("import wifi from 'wifi'", output)
        self.assertIn("getWifiManager", output)

    def test_firmware_app_js_bin(self):
        bin_path = os.path.join(REVERSE_DUMP_DIR, "8080222437664451/a/app.js.bin")
        if not os.path.exists(bin_path):
            self.skipTest("Firmware binary not present")
        output = self._decompile(bin_path)
        self.assertIn("$falcon.__AppClazz", output)
        self.assertIn("$falcon.__loadModuleDefault", output)

if __name__ == "__main__":
    unittest.main()
