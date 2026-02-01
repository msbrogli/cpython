"""Dangerous attack scenario tests that could hang if limits fail.

This module contains tests for memory and CPU exhaustion attacks that
intentionally trigger resource-intensive operations. These tests rely
on sandbox limits to prevent hangs.

These tests are separated from the main test suite to allow running
"safe" tests without risk of hangs during development.

Security audit reference: Attack scenario tests (dangerous subset)
"""

import sys
import unittest

from test.test_sandbox import (
    _run_sandboxed_code,
    SUBPROCESS_TIMEOUT,
)


class MemoryExhaustionAttacks(unittest.TestCase):
    """Test prevention of memory exhaustion attacks."""

    def test_huge_string_multiplication_attack(self):
        """Attack: 'x' * huge_number to exhaust memory."""
        code = '''
import sys
sys.sandbox.set_config(max_str_length=10000)
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
sys.sandbox.set_config(max_list_size=10000)
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
sys.sandbox.set_config(max_iterations=100)
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
sys.sandbox.set_config(max_recursion_depth=50)
sys.sandbox.enter_scope()
def bomb():
    return bomb()
bomb()  # Should raise SandboxRecursionError or RecursionError
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
