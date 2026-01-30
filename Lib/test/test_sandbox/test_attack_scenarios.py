"""Tests for documented attack vector scenarios.

This module contains tests for specific attack scenarios identified
in the security audit. Each test documents an attack vector and
verifies that the sandbox properly prevents it.

Security audit reference: Attack scenario tests
"""

import subprocess
import sys
import unittest

from test.test_sandbox import (
    SandboxTestCase,
    _run_sandboxed_code,
    SUBPROCESS_TIMEOUT,
)


class MemoryExhaustionAttacks(unittest.TestCase):
    """Test prevention of memory exhaustion attacks."""

    def test_huge_string_multiplication_attack(self):
        """Attack: 'x' * huge_number to exhaust memory."""
        code = '''
import sys
sys.sandbox.set_limits(max_str_length=10000)
sys.sandbox.enter_scope()
n = 10**9
bomb = 'x' * n  # Should raise SandboxOverflowError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Sandbox", result.stderr)

    def test_huge_list_attack(self):
        """Attack: list(range(huge_number)) to exhaust memory."""
        code = '''
import sys
sys.sandbox.set_limits(max_list_size=10000)
sys.sandbox.enter_scope()
bomb = list(range(10**8))  # Should raise SandboxOverflowError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Sandbox", result.stderr)


class CPUExhaustionAttacks(unittest.TestCase):
    """Test prevention of CPU exhaustion attacks."""

    def test_infinite_loop_attack(self):
        """Attack: Infinite iteration to hang process.

        Note: Uses max_iterations since subprocess code isn't compiled
        with PyCF_SANDBOX_COUNT flag required for max_operations.
        """
        code = '''
import sys
sys.sandbox.set_limits(max_iterations=100)
sys.sandbox.enter_scope()
for _ in iter(int, 1):  # Infinite iterator
    pass  # Should raise SandboxRuntimeError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxRuntimeError", result.stderr)

    def test_recursive_bomb_attack(self):
        """Attack: Infinite recursion to exhaust stack.

        Note: Uses max_recursion_depth to limit recursion depth.
        """
        code = '''
import sys
sys.sandbox.set_limits(max_recursion_depth=50)
sys.sandbox.enter_scope()
def bomb():
    return bomb()
bomb()  # Should raise SandboxRecursionError or RecursionError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)


class SandboxEscapeAttacks(unittest.TestCase):
    """Test prevention of sandbox escape attacks."""

    def test_dunder_class_escape(self):
        """Attack: Access __class__.__bases__ to escape restrictions."""
        code = '''
import sys
sys.sandbox.set_limits(allow_dunder_access=False)
sys.sandbox.enter_scope()
x = 1
bases = x.__class__.__bases__  # Should raise SandboxAttributeError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Sandbox", result.stderr)

    def test_subclasses_escape(self):
        """Attack: Use __subclasses__() to find dangerous classes."""
        code = '''
import sys
sys.sandbox.set_limits(allow_dunder_access=False)
sys.sandbox.enter_scope()
subs = object.__subclasses__()  # Should raise SandboxAttributeError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Sandbox", result.stderr)

    def test_code_object_escape(self):
        """Attack: Access function.__code__ to manipulate bytecode."""
        code = '''
import sys
sys.sandbox.set_limits(allow_dunder_access=False)
sys.sandbox.enter_scope()
def innocent():
    pass
code_obj = innocent.__code__  # Should raise SandboxAttributeError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Sandbox", result.stderr)

    def test_frame_escape_via_generator(self):
        """Attack: Access gi_frame to get frame locals/globals."""
        code = '''
import sys
sys.sandbox.enter_scope()
def gen():
    yield 1
g = gen()
frame = g.gi_frame  # Should raise SandboxAttributeError
globals_dict = frame.f_globals
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Sandbox", result.stderr)


class ConfigManipulationAttacks(unittest.TestCase):
    """Test prevention of sandbox config manipulation from within scope."""

    def test_disable_limits_attack(self):
        """Attack: Try to disable limits from within scope."""
        code = '''
import sys
sys.sandbox.set_limits(max_list_size=10)
sys.sandbox.enter_scope()
sys.sandbox.set_limits(max_list_size=0)  # Should raise SandboxSecurityError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxSecurityError", result.stderr)

    def test_exit_scope_attack(self):
        """Attack: Try to exit scope from within scope."""
        code = '''
import sys
sys.sandbox.set_limits(max_list_size=10)
sys.sandbox.enter_scope()
sys.sandbox.exit_scope()  # Should raise SandboxSecurityError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxSecurityError", result.stderr)

    def test_suspend_limits_attack(self):
        """Attack: Try to suspend limits from within scope."""
        code = '''
import sys
sys.sandbox.set_limits(max_list_size=10)
sys.sandbox.enter_scope()
sys.sandbox.suspend()  # Should raise SandboxSecurityError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxSecurityError", result.stderr)


class FileSystemAttacks(unittest.TestCase):
    """Test prevention of file system access attacks."""

    def test_open_file_attack(self):
        """Attack: Try to open and read sensitive files."""
        code = '''
import sys
sys.sandbox.set_limits(allow_io=False)
sys.sandbox.enter_scope()
f = open('/etc/passwd', 'r')  # Should raise SandboxSecurityError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxSecurityError", result.stderr)

    def test_write_file_attack(self):
        """Attack: Try to write to file system."""
        code = '''
import sys
sys.sandbox.set_limits(allow_io=False)
sys.sandbox.enter_scope()
f = open('/tmp/sandbox_test', 'w')  # Should raise SandboxSecurityError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxSecurityError", result.stderr)


class ModuleImportAttacks(unittest.TestCase):
    """Test prevention of dangerous module import attacks."""

    def test_os_import_attack(self):
        """Attack: Import os module to execute commands."""
        code = '''
import sys
sys.sandbox.import_restrict_mode = True
sys.sandbox.allowed_modules = set()
sys.sandbox.enter_scope()
import os  # Should raise SandboxImportError
os.system('echo pwned')
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxImportError", result.stderr)

    def test_subprocess_attack(self):
        """Attack: Import subprocess to execute commands."""
        code = '''
import sys
sys.sandbox.import_restrict_mode = True
sys.sandbox.allowed_modules = set()
sys.sandbox.enter_scope()
import subprocess  # Should raise SandboxImportError
subprocess.run(['echo', 'pwned'])
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxImportError", result.stderr)

    def test_ctypes_attack(self):
        """Attack: Import ctypes to call C functions."""
        code = '''
import sys
sys.sandbox.import_restrict_mode = True
sys.sandbox.allowed_modules = set()
sys.sandbox.enter_scope()
import ctypes  # Should raise SandboxImportError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxImportError", result.stderr)


class InputDoSAttacks(unittest.TestCase):
    """Test prevention of input() based DoS attacks."""

    def test_input_dos_attack(self):
        """Attack: Call input() to hang waiting for stdin."""
        code = '''
import sys
sys.sandbox.enter_scope()
user_input = input()  # Should raise SandboxSecurityError
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=5,
            input=""
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxSecurityError", result.stderr)


class MetaclassAttacks(unittest.TestCase):
    """Test prevention of metaclass-based attacks."""

    def test_metaclass_new_attack(self):
        """Attack: Use metaclass __new__ to execute code at class creation."""
        code = '''
import sys
sys.sandbox.set_limits(max_list_size=10)
sys.sandbox.enter_scope()

class EvilMeta(type):
    def __new__(mcs, name, bases, ns):
        ns['bomb'] = list(range(1000))
        return super().__new__(mcs, name, bases, ns)

class Victim(metaclass=EvilMeta):
    pass
'''
        result = _run_sandboxed_code(code)
        # Either metaclass is blocked or list creation is blocked
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Sandbox", result.stderr)


class ContainerBypassAttacks(unittest.TestCase):
    """Test prevention of container copy/update bypass attacks."""

    def test_dict_copy_bypass_attack(self):
        """Attack: Use dict.copy() to bypass size limits."""
        code = '''
import sys
large_dict = {i: i for i in range(1000)}
sys.sandbox.set_limits(max_dict_size=10)
sys.sandbox.enter_scope()
copied = large_dict.copy()  # Should raise SandboxOverflowError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Sandbox", result.stderr)

    def test_dict_update_bypass_attack(self):
        """Attack: Use dict.update() to bypass size limits."""
        code = '''
import sys
large_dict = {i: i for i in range(1000)}
sys.sandbox.set_limits(max_dict_size=10)
sys.sandbox.enter_scope()
d = {}
d.update(large_dict)  # Should raise SandboxOverflowError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Sandbox", result.stderr)

    def test_set_copy_bypass_attack(self):
        """Attack: Use set.copy() to bypass size limits."""
        code = '''
import sys
large_set = set(range(1000))
sys.sandbox.set_limits(max_set_size=10)
sys.sandbox.enter_scope()
copied = large_set.copy()  # Should raise SandboxOverflowError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Sandbox", result.stderr)


if __name__ == '__main__':
    unittest.main()
