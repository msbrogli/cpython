"""Tests for DoS (Denial of Service) prevention through sandbox limits.

This module tests that resource exhaustion attacks are prevented by
the sandbox's various limits.

Security audit reference: DoS prevention tests
"""

import subprocess
import sys
import unittest

from test.test_sandbox import (
    ScopedFilenameTestCase,
    _run_sandboxed_code,
    SUBPROCESS_TIMEOUT,
)


class InputBlockingTests(ScopedFilenameTestCase):
    """Test that input() is blocked to prevent stdin DoS.

    Attack vector: input() blocks waiting for stdin, causing indefinite hang.
    Security fix reference: Fix proposal 09
    """

    SCOPED_FILENAME = "<test_dos_prevention_scope>"

    def test_input_blocked_in_scope(self):
        """input() should be blocked in sandbox scope."""
        sys.sandbox.set_limits(max_operations=10000)

        with self.assertRaises((SandboxSecurityError, OSError)):
            self.run_scoped_code("user_input = input('Enter: ')")

    def test_input_allowed_outside_scope(self):
        """input() should work outside sandbox scope.

        Note: We can't actually call input() in tests without blocking,
        but we verify the function exists.
        """
        # Just verify input is a callable outside scope
        self.assertTrue(callable(input))


class OperationLimitLoopTests(ScopedFilenameTestCase):
    """Test that operation limits prevent infinite loops."""

    SCOPED_FILENAME = "<test_dos_prevention_scope>"

    def test_infinite_loop_stopped_by_operation_limit(self):
        """Infinite while loop should be stopped by operation limit."""
        sys.sandbox.set_limits(max_operations=100)

        with self.assertRaises(SandboxRuntimeError) as cm:
            self.run_scoped_code("""
x = 0
while True:
    x += 1
""")
        self.assertIn("operation", str(cm.exception).lower())

    def test_infinite_for_loop_stopped(self):
        """Infinite for loop (via generator) should be stopped."""
        sys.sandbox.set_limits(max_operations=100, max_iterations=1000)

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
        sys.sandbox.set_limits(max_operations=100)

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
        sys.sandbox.set_limits(max_list_size=1000)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("bomb = list(range(1000000))")

    def test_large_dict_blocked(self):
        """Large dict creation should be blocked by size limits."""
        sys.sandbox.set_limits(max_dict_size=1000)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("bomb = {i: i for i in range(1000000)}")

    def test_large_set_blocked(self):
        """Large set creation should be blocked by size limits."""
        sys.sandbox.set_limits(max_set_size=1000)

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
        sys.sandbox.set_limits(
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
        sys.sandbox.set_limits(max_iterations=1000)

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
        sys.sandbox.set_limits(max_int_digits=10)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("huge = 10 ** 1000")

    def test_integer_multiplication_bomb_blocked(self):
        """Integer multiplication bomb should be blocked."""
        sys.sandbox.set_limits(max_int_digits=10)

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
        sys.sandbox.set_limits(max_str_length=1000)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("n = 10000; huge = 'x' * n")

    def test_string_multiplication_bomb_blocked(self):
        """String multiplication bomb should be blocked."""
        sys.sandbox.set_limits(max_str_length=1000)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("""
s = 'x'
for _ in range(20):
    s = s + s
""")


class SubprocessDoSTests(unittest.TestCase):
    """Subprocess tests for DoS prevention that need full isolation."""

    def test_combined_limits_prevent_dos(self):
        """Multiple limits active should prevent various DoS vectors.

        Note: Uses max_iterations as the loop limit since subprocess code
        is not compiled with PyCF_SANDBOX_COUNT flag (required for max_operations).
        """
        code = '''
import sys
sys.sandbox.set_limits(
    max_iterations=100,
    max_list_size=100,
    max_str_length=1000,
    max_int_digits=10,
)
sys.sandbox.enter_scope()

# Infinite loop - should trigger iteration limit
x = 0
for _ in iter(int, 1):
    x += 1
'''
        result = _run_sandboxed_code(code)
        # Should fail with sandbox error (non-zero exit)
        self.assertNotEqual(result.returncode, 0)
        # Verify it was a sandbox error
        self.assertIn("Sandbox", result.stderr)

    def test_exception_handling_works_under_limits(self):
        """Exception handling should still work under tight limits."""
        code = '''
import sys
sys.sandbox.set_limits(
    max_iterations=1000,
    max_list_size=100,
)
sys.sandbox.enter_scope()

try:
    raise ValueError("test error")
except ValueError as e:
    if str(e) == "test error":
        sys.exit(0)
    else:
        sys.exit(2)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Exception handling failed: {result.stderr}")

    def test_graceful_limit_cascade(self):
        """When one limit triggers, verify it's a sandbox error.

        Note: When a limit is triggered, the exception cascades if
        exception handling itself exceeds limits. We verify sandbox
        errors are raised (not crashes or security bypasses).
        """
        code = '''
import sys
sys.sandbox.set_limits(
    max_iterations=100,
)
sys.sandbox.enter_scope()

# This will trigger iteration limit
for _ in iter(int, 1):
    x = 1
'''
        result = _run_sandboxed_code(code)
        # Should fail with sandbox error
        self.assertNotEqual(result.returncode, 0)
        # Verify it's a sandbox error, not a crash
        self.assertIn("SandboxRuntimeError", result.stderr)


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
