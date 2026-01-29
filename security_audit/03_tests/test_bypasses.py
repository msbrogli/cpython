#!/usr/bin/env python3
"""
CPython Sandbox Security Audit - Bypass Tests
Date: 2026-01-29

This test suite verifies the bypass hypotheses identified in the security audit.
Tests are designed to run in subprocess isolation to prevent state interference.

Usage:
    ./python security_audit/03_tests/test_bypasses.py
"""

import subprocess
import sys
import unittest
from typing import Tuple


def run_sandbox_test(code: str, timeout: int = 10) -> Tuple[int, str, str]:
    """Run a sandbox test in a subprocess.

    Returns (returncode, stdout, stderr).
    """
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        timeout=timeout
    )
    return result.returncode, result.stdout, result.stderr


class TestContainerResizeBypasses(unittest.TestCase):
    """Tests for container resize bypass vectors (CRITICAL)."""

    def test_HYP_001_dict_incremental_growth_resize(self):
        """HYP-001: Dict incremental growth triggers unchecked resize."""
        code = '''
import sys
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<string>')
d = {}
try:
    for i in range(500):
        d[i] = i
    if len(d) == 500:
        print("BYPASS: Dict grew to 500 items despite max_dict_size=100")
    else:
        print(f"PARTIAL: Dict has {len(d)} items")
except SandboxOverflowError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-001 Result: {out.strip()}")
        # This should show BYPASS if vulnerability exists
        self.assertIn(out.strip(), ["BYPASS: Dict grew to 500 items despite max_dict_size=100",
                                    "BLOCKED: Dict size (101) exceeds sandbox limit (100)"])

    def test_HYP_002_dict_copy_external(self):
        """HYP-002: Dict copy from external large dict."""
        code = '''
import sys
big_dict = {i: i for i in range(500)}  # Outside sandbox scope
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<string>')
try:
    my_dict = big_dict.copy()
    if len(my_dict) == 500:
        print("BYPASS: Copied 500-item dict despite max_dict_size=100")
    else:
        print(f"PARTIAL: Dict has {len(my_dict)} items")
except SandboxOverflowError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-002 Result: {out.strip()}")

    def test_HYP_003_set_incremental_growth_resize(self):
        """HYP-003: Set incremental growth triggers unchecked resize."""
        code = '''
import sys
sys.sandbox.max_set_size = 100
sys.sandbox.add_filename('<string>')
s = set()
try:
    for i in range(500):
        s.add(i)
    if len(s) == 500:
        print("BYPASS: Set grew to 500 items despite max_set_size=100")
    else:
        print(f"PARTIAL: Set has {len(s)} items")
except SandboxOverflowError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-003 Result: {out.strip()}")

    def test_HYP_004_set_copy_external(self):
        """HYP-004: Set copy from external large set."""
        code = '''
import sys
big_set = {i for i in range(500)}  # Outside sandbox scope
sys.sandbox.max_set_size = 100
sys.sandbox.add_filename('<string>')
try:
    my_set = big_set.copy()
    if len(my_set) == 500:
        print("BYPASS: Copied 500-item set despite max_set_size=100")
    else:
        print(f"PARTIAL: Set has {len(my_set)} items")
except SandboxOverflowError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-004 Result: {out.strip()}")

    def test_HYP_005_dict_constructor_large_iterable(self):
        """HYP-005: dict() constructor with large external iterable."""
        code = '''
import sys
big_items = [(i, i) for i in range(500)]  # Outside sandbox scope
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<string>')
try:
    my_dict = dict(big_items)
    if len(my_dict) == 500:
        print("BYPASS: dict() created 500 items despite max_dict_size=100")
    else:
        print(f"PARTIAL: Dict has {len(my_dict)} items")
except SandboxOverflowError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-005 Result: {out.strip()}")

    def test_HYP_006_set_constructor_large_iterable(self):
        """HYP-006: set() constructor with large external iterable."""
        code = '''
import sys
big_list = list(range(500))  # Outside sandbox scope
sys.sandbox.max_set_size = 100
sys.sandbox.add_filename('<string>')
try:
    my_set = set(big_list)
    if len(my_set) == 500:
        print("BYPASS: set() created 500 items despite max_set_size=100")
    else:
        print(f"PARTIAL: Set has {len(my_set)} items")
except SandboxOverflowError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-006 Result: {out.strip()}")

    def test_HYP_020_dict_update_large(self):
        """HYP-020: dict.update() with large external dict."""
        code = '''
import sys
big_dict = {i: i for i in range(500)}
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<string>')
try:
    my_dict = {}
    my_dict.update(big_dict)
    if len(my_dict) == 500:
        print("BYPASS: update() resulted in 500 items despite max_dict_size=100")
    else:
        print(f"PARTIAL: Dict has {len(my_dict)} items")
except SandboxOverflowError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-020 Result: {out.strip()}")


class TestTypeLiteralBypasses(unittest.TestCase):
    """Tests for type restriction literal bypasses (HIGH)."""

    def test_HYP_007_float_literal_bypass(self):
        """HYP-007: Float literal bypasses allow_float=0."""
        code = '''
import sys
sys.sandbox.allow_float = 0
sys.sandbox.add_filename('<string>')
try:
    x = 1.5  # Literal, not float() call
    if isinstance(x, float):
        print("BYPASS: Float literal 1.5 created despite allow_float=0")
    else:
        print(f"UNEXPECTED: x is {type(x)}")
except SandboxTypeError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-007 Result: {out.strip()}")

    def test_HYP_008_complex_literal_bypass(self):
        """HYP-008: Complex literal bypasses allow_complex=0."""
        code = '''
import sys
sys.sandbox.allow_complex = 0
sys.sandbox.add_filename('<string>')
try:
    x = 1+2j  # Literal, not complex() call
    if isinstance(x, complex):
        print("BYPASS: Complex literal 1+2j created despite allow_complex=0")
    else:
        print(f"UNEXPECTED: x is {type(x)}")
except SandboxTypeError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-008 Result: {out.strip()}")

    def test_HYP_011_tuple_multiplication_bypass(self):
        """HYP-011: Tuple multiplication bypasses max_tuple_size."""
        code = '''
import sys
sys.sandbox.max_tuple_size = 50
sys.sandbox.add_filename('<string>')
try:
    t = (1, 2, 3) * 100  # Should create 300-item tuple
    if len(t) == 300:
        print("BYPASS: Tuple multiplication created 300 items despite max_tuple_size=50")
    else:
        print(f"PARTIAL: Tuple has {len(t)} items")
except SandboxOverflowError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-011 Result: {out.strip()}")

    def test_HYP_019_arithmetic_float_creation(self):
        """HYP-019: Division creating float with allow_float=0."""
        code = '''
import sys
sys.sandbox.allow_float = 0
sys.sandbox.add_filename('<string>')
try:
    x = 1 / 2  # True division returns float
    if isinstance(x, float):
        print("BYPASS: Division 1/2 created float despite allow_float=0")
    else:
        print(f"UNEXPECTED: x is {type(x)} = {x}")
except SandboxTypeError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-019 Result: {out.strip()}")


class TestCompileTimeFoldingBypasses(unittest.TestCase):
    """Tests for compile-time constant folding bypasses (HIGH)."""

    def test_HYP_009_string_multiplication_folding(self):
        """HYP-009: String multiplication folded at compile time."""
        code = '''
import sys
sys.sandbox.max_str_length = 100
sys.sandbox.add_filename('<string>')
try:
    s = "a" * 200  # May be folded at compile time (limit=4096)
    if len(s) == 200:
        print("BYPASS: String 'a'*200 created despite max_str_length=100")
    else:
        print(f"PARTIAL: String has {len(s)} chars")
except SandboxOverflowError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-009 Result: {out.strip()}")

    def test_HYP_009b_string_multiplication_runtime(self):
        """HYP-009b: String multiplication at runtime (not foldable)."""
        code = '''
import sys
sys.sandbox.max_str_length = 100
sys.sandbox.add_filename('<string>')
n = 200  # Variable prevents folding
try:
    s = "a" * n  # Runtime multiplication
    if len(s) == 200:
        print("BYPASS: String 'a'*n created despite max_str_length=100")
    else:
        print(f"PARTIAL: String has {len(s)} chars")
except SandboxOverflowError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-009b Result: {out.strip()}")

    def test_HYP_010_bytes_multiplication_folding(self):
        """HYP-010: Bytes multiplication folded at compile time."""
        code = '''
import sys
sys.sandbox.max_bytes_length = 100
sys.sandbox.add_filename('<string>')
try:
    b = b"a" * 200  # May be folded at compile time
    if len(b) == 200:
        print("BYPASS: Bytes b'a'*200 created despite max_bytes_length=100")
    else:
        print(f"PARTIAL: Bytes has {len(b)} bytes")
except SandboxOverflowError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-010 Result: {out.strip()}")

    def test_HYP_010b_bytes_multiplication_runtime(self):
        """HYP-010b: Bytes multiplication at runtime (not foldable)."""
        code = '''
import sys
sys.sandbox.max_bytes_length = 100
sys.sandbox.add_filename('<string>')
n = 200  # Variable prevents folding
try:
    b = b"a" * n  # Runtime multiplication
    if len(b) == 200:
        print("BYPASS: Bytes b'a'*n created despite max_bytes_length=100")
    else:
        print(f"PARTIAL: Bytes has {len(b)} bytes")
except SandboxOverflowError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-010b Result: {out.strip()}")


class TestDunderAccessBypasses(unittest.TestCase):
    """Tests for dunder attribute access bypasses (HIGH)."""

    def test_HYP_012_builtins_via_load_name(self):
        """HYP-012: __builtins__ access via LOAD_NAME (not LOAD_ATTR)."""
        code = '''
import sys
sys.sandbox.allow_dunder_access = 0
sys.sandbox.add_filename('<string>')
try:
    b = __builtins__  # LOAD_NAME, not LOAD_ATTR
    if b is not None:
        print("BYPASS: __builtins__ accessible via LOAD_NAME")
    else:
        print("UNEXPECTED: __builtins__ is None")
except SandboxAttributeError as e:
    print(f"BLOCKED: {e}")
except NameError as e:
    print(f"NAME_ERROR: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-012 Result: {out.strip()}")

    def test_HYP_013_builtins_via_globals(self):
        """HYP-013: __builtins__ access via globals() dict lookup."""
        code = '''
import sys
sys.sandbox.allow_dunder_access = 0
sys.sandbox.add_filename('<string>')
try:
    b = globals()["__builtins__"]  # Dict access, not attr
    if b is not None:
        print("BYPASS: __builtins__ accessible via globals()['__builtins__']")
    else:
        print("UNEXPECTED: __builtins__ is None")
except SandboxAttributeError as e:
    print(f"BLOCKED: {e}")
except KeyError as e:
    print(f"KEY_ERROR: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-013 Result: {out.strip()}")

    def test_HYP_012b_builtins_import_access(self):
        """HYP-012b: Can we get __import__ from __builtins__?"""
        code = '''
import sys
sys.sandbox.allow_dunder_access = 0
sys.sandbox.import_restrict_mode = 1
sys.sandbox.allowed_imports = frozenset()
sys.sandbox.add_filename('<string>')
try:
    b = __builtins__
    # Try to get __import__ - depends on builtins type
    if isinstance(b, dict):
        imp = b.get("__import__")
    else:
        imp = getattr(b, "__import__", None)

    if imp is not None:
        # Try to use it
        try:
            os = imp("os")
            print("CRITICAL_BYPASS: Imported os via __builtins__.__import__")
        except SandboxImportError as e:
            print("PARTIAL_BYPASS: Got __import__ but import still blocked")
    else:
        print("BLOCKED: Could not get __import__ from __builtins__")
except SandboxAttributeError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-012b Result: {out.strip()}")


class TestImportBypasses(unittest.TestCase):
    """Tests for import restriction bypasses (HIGH)."""

    def test_HYP_014_unregistered_filename_bypass(self):
        """HYP-014: Pre-compiled code with unregistered filename."""
        code = '''
import sys
# Compile with DIFFERENT filename than registered
code_obj = compile('print("EXECUTED")', '<EXTERNAL>', 'exec')
sys.sandbox.import_restrict_mode = 1
sys.sandbox.allowed_imports = frozenset()
sys.sandbox.add_filename('<SANDBOX>')  # Different from code's filename

# Check if limits apply to this code
sys.sandbox.max_statements = 1  # Very low limit
try:
    for _ in range(10):  # Should hit limit if in scope
        exec(code_obj)
    print("BYPASS: Code with external filename bypassed statement limit")
except SandboxRuntimeError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-014 Result: {out.strip()}")

    def test_HYP_015_sys_modules_access(self):
        """HYP-015: Access modules via sys.modules without import."""
        code = '''
import sys
import os  # Pre-import outside sandbox scope

sys.sandbox.import_restrict_mode = 1
sys.sandbox.allowed_imports = frozenset([('sys', '')])
sys.sandbox.add_filename('<string>')

try:
    # Get os from sys.modules (already imported)
    os_mod = sys.modules.get('os')
    if os_mod is not None:
        # Try to use it
        result = os_mod.getcwd()
        print(f"BYPASS: Accessed os via sys.modules, cwd={result}")
    else:
        print("UNEXPECTED: os not in sys.modules")
except SandboxSecurityError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-015 Result: {out.strip()}")


class TestScopeEscapeBypasses(unittest.TestCase):
    """Tests for scope escape bypasses (MEDIUM)."""

    def test_HYP_016_generator_frame_escape(self):
        """HYP-016: Generator frame uses definition filename, not caller's."""
        code = '''
import sys

# Define generator OUTSIDE sandbox scope
def gen():
    for i in range(1000):
        yield i

sys.sandbox.max_iterations = 10  # Very low
sys.sandbox.add_filename('<string>')

try:
    # Call generator from sandbox
    result = list(gen())  # Generator frame has different filename
    if len(result) == 1000:
        print("BYPASS: Generator completed 1000 iterations despite max_iterations=10")
    else:
        print(f"PARTIAL: Got {len(result)} iterations")
except SandboxRuntimeError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-016 Result: {out.strip()}")

    def test_HYP_018_import_side_effect_scope(self):
        """HYP-018: Module init code escapes statement limit."""
        code = '''
import sys
sys.sandbox.max_statements = 5  # Very low
sys.sandbox.import_restrict_mode = 1
sys.sandbox.allowed_imports = frozenset([('json', '')])
sys.sandbox.add_filename('<string>')

try:
    import json  # json/__init__.py has many statements
    print("BYPASS: Imported json despite max_statements=5")
except SandboxRuntimeError as e:
    print(f"BLOCKED: {e}")
except SandboxImportError as e:
    print(f"IMPORT_BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-018 Result: {out.strip()}")


class TestFileSystemAccess(unittest.TestCase):
    """Tests for file system access vulnerabilities (CRITICAL)."""

    def test_HYP_026_open_file_access(self):
        """HYP-026: open() provides unrestricted file access."""
        code = '''
import sys
sys.sandbox.import_restrict_mode = 1
sys.sandbox.allowed_imports = frozenset()
sys.sandbox.add_filename('<string>')
try:
    data = open('/etc/passwd').readline()
    if data:
        print(f"BYPASS: Read /etc/passwd via open(): {data[:20]}...")
    else:
        print("UNEXPECTED: File empty")
except PermissionError as e:
    print(f"PERMISSION_DENIED: {e}")
except SandboxSecurityError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-026 Result: {out.strip()}")


class TestSystemExit(unittest.TestCase):
    """Tests for SystemExit vulnerabilities (HIGH)."""

    def test_HYP_027_sys_exit_raises_systemexit(self):
        """HYP-027: sys.exit() raises SystemExit."""
        code = '''
import sys
sys.sandbox.import_restrict_mode = 1
sys.sandbox.allowed_imports = frozenset([('sys', '')])
sys.sandbox.add_filename('<string>')
try:
    sys.exit(42)
    print("UNEXPECTED: sys.exit() did not raise")
except SystemExit as e:
    print(f"BYPASS: sys.exit() raised SystemExit with code {e.code}")
except SandboxSecurityError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-027 Result: {out.strip()}")


class TestInputDoS(unittest.TestCase):
    """Tests for input() DoS vulnerability (MEDIUM)."""

    def test_HYP_028_input_dos_risk(self):
        """HYP-028: input() blocks indefinitely (DoS risk).

        Note: This test doesn't actually call input() as it would block.
        Instead, it verifies input() is available (vulnerability exists).
        """
        code = '''
import sys
sys.sandbox.add_filename('<string>')
try:
    # Don't actually call input() as it would block forever
    # Just check if it's accessible
    if callable(input):
        print("BYPASS: input() is accessible (DoS risk if called)")
    else:
        print("UNEXPECTED: input is not callable")
except NameError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"HYP-028 Result: {out.strip()}")


class TestListMultiplicationConfirmed(unittest.TestCase):
    """Verify list multiplication IS blocked (sanity check)."""

    def test_list_multiplication_blocked(self):
        """List multiplication should be blocked (from existing tests)."""
        code = '''
import sys
sys.sandbox.max_list_size = 100
sys.sandbox.add_filename('<string>')
try:
    x = [1, 2, 3] * 100  # 300 items
    print(f"BYPASS: List has {len(x)} items")
except SandboxOverflowError as e:
    print(f"BLOCKED: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        print(f"List multiplication Result: {out.strip()}")
        self.assertIn("BLOCKED", out)


def main():
    """Run all tests with verbose output."""
    print("=" * 70)
    print("CPython Sandbox Security Audit - Bypass Tests")
    print("=" * 70)
    print()

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes in priority order
    suite.addTests(loader.loadTestsFromTestCase(TestContainerResizeBypasses))
    suite.addTests(loader.loadTestsFromTestCase(TestTypeLiteralBypasses))
    suite.addTests(loader.loadTestsFromTestCase(TestCompileTimeFoldingBypasses))
    suite.addTests(loader.loadTestsFromTestCase(TestDunderAccessBypasses))
    suite.addTests(loader.loadTestsFromTestCase(TestImportBypasses))
    suite.addTests(loader.loadTestsFromTestCase(TestScopeEscapeBypasses))
    suite.addTests(loader.loadTestsFromTestCase(TestFileSystemAccess))
    suite.addTests(loader.loadTestsFromTestCase(TestSystemExit))
    suite.addTests(loader.loadTestsFromTestCase(TestInputDoS))
    suite.addTests(loader.loadTestsFromTestCase(TestListMultiplicationConfirmed))

    # Run with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
