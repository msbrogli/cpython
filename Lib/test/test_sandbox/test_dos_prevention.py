"""Tests for DoS (Denial of Service) prevention through sandbox limits.

This module tests that resource exhaustion attacks are prevented by
the sandbox's various limits.

Note: Dangerous tests that could hang if limits fail have been moved to
test_dos_prevention_dangerous.py.

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


if __name__ == '__main__':
    unittest.main()
