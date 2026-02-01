"""Dangerous DoS prevention tests that could hang if limits fail.

This module contains tests that intentionally trigger infinite loops,
memory bombs, and other resource exhaustion attacks. These tests rely
on sandbox limits to prevent hangs - if limits fail, the tests will hang.

These tests are separated from the main test suite to allow running
"safe" tests without risk of hangs during development.

Security audit reference: DoS prevention tests (dangerous subset)
"""

import subprocess
import sys
import unittest

from test.test_sandbox import (
    ScopedFilenameTestCase,
    _run_sandboxed_code,
    SUBPROCESS_TIMEOUT,
)


class OperationLimitLoopTests(ScopedFilenameTestCase):
    """Test that operation limits prevent infinite loops."""

    SCOPED_FILENAME = "<test_dos_prevention_scope>"

    def test_infinite_loop_stopped_by_operation_limit(self):
        """Infinite while loop should be stopped by operation limit."""
        sys.sandbox.set_config(max_operations=100)

        with self.assertRaises(SandboxRuntimeError) as cm:
            self.run_scoped_code("""
x = 0
while True:
    x += 1
""")
        self.assertIn("operation", str(cm.exception).lower())

    def test_infinite_for_loop_stopped(self):
        """Infinite for loop (via generator) should be stopped."""
        sys.sandbox.set_config(max_operations=100, max_iterations=1000)

        with self.assertRaises(SandboxRuntimeError):
            self.run_scoped_code("""
def infinite_gen():
    while True:
        yield 1
for x in infinite_gen():
    pass
""")

    def test_deeply_nested_calls_stopped(self):
        """Deep recursion should be stopped by operation limit."""
        sys.sandbox.set_config(max_operations=100)

        with self.assertRaises((SandboxRuntimeError, RecursionError)):
            self.run_scoped_code("""
def recurse(n):
    return recurse(n + 1)
recurse(0)
""")


class MemoryLimitTests(ScopedFilenameTestCase):
    """Test that container size limits prevent memory bombs."""

    SCOPED_FILENAME = "<test_dos_prevention_scope>"

    def test_large_list_blocked(self):
        """Large list creation should be blocked by size limits."""
        sys.sandbox.set_config(max_list_size=1000)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("bomb = list(range(1000000))")

    def test_large_dict_blocked(self):
        """Large dict creation should be blocked by size limits."""
        sys.sandbox.set_config(max_dict_size=1000)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("bomb = {i: i for i in range(1000000)}")

    def test_large_set_blocked(self):
        """Large set creation should be blocked by size limits."""
        sys.sandbox.set_config(max_set_size=1000)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("bomb = set(range(1000000))")


class CombinedOperationLimitTests(ScopedFilenameTestCase):
    """Test that operation limits prevent CPU bombs."""

    SCOPED_FILENAME = "<test_dos_prevention_scope>"

    def test_cpu_bomb_stopped_by_operation_limit(self):
        """CPU-intensive operations should be limited.

        Note: Operations are counted via SANDBOX_COUNT opcodes in compiled code.
        When count_iterations_as_operations=True, iterations also count.
        """
        sys.sandbox.set_config(
            max_operations=1000,
            count_iterations_as_operations=True
        )

        with self.assertRaises(SandboxRuntimeError) as cm:
            self.run_scoped_code("""
x = 0
for i in range(1000000):
    x = x + i
""")
        self.assertIn("operation", str(cm.exception).lower())


class IterationLimitTests(ScopedFilenameTestCase):
    """Test that iteration limits prevent exhaustion attacks."""

    SCOPED_FILENAME = "<test_dos_prevention_scope>"

    def test_iteration_bomb_stopped(self):
        """Excessive iterations should be stopped by iteration limit."""
        sys.sandbox.set_config(max_iterations=1000)

        with self.assertRaises(SandboxRuntimeError) as cm:
            self.run_scoped_code("""
for i in range(1000000):
    pass
""")
        self.assertIn("iteration", str(cm.exception).lower())


class IntegerSizeLimitTests(ScopedFilenameTestCase):
    """Test that integer size limits prevent memory exhaustion."""

    SCOPED_FILENAME = "<test_dos_prevention_scope>"

    def test_huge_integer_blocked(self):
        """Creating huge integers should be blocked."""
        sys.sandbox.set_config(max_int_digits=10)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("huge = 10 ** 1000")

    def test_integer_multiplication_bomb_blocked(self):
        """Integer multiplication bomb should be blocked."""
        sys.sandbox.set_config(max_int_digits=10)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("""
x = 2
for _ in range(100):
    x = x * x
""")


class StringSizeLimitTests(ScopedFilenameTestCase):
    """Test that string size limits prevent memory exhaustion."""

    SCOPED_FILENAME = "<test_dos_prevention_scope>"

    def test_huge_string_blocked(self):
        """Creating huge strings should be blocked."""
        sys.sandbox.set_config(max_str_length=1000)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("n = 10000; huge = 'x' * n")

    def test_string_multiplication_bomb_blocked(self):
        """String multiplication bomb should be blocked."""
        sys.sandbox.set_config(max_str_length=1000)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("""
s = 'x'
for _ in range(20):
    s = s + s
""")


class TimeoutTests(unittest.TestCase):
    """Test that subprocess timeout provides ultimate DoS protection."""

    def test_subprocess_timeout_kills_runaway(self):
        """Subprocess timeout should kill runaway code."""
        code = '''
import time
# Even if sandbox limits fail, subprocess timeout catches it
while True:
    pass  # Would run forever
'''
        with self.assertRaises(subprocess.TimeoutExpired):
            subprocess.run(
                [sys.executable, '-c', code],
                capture_output=True,
                text=True,
                timeout=1
            )


if __name__ == '__main__':
    unittest.main()
