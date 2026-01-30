"""Tests for recommended safe_exec harness pattern.

This module tests the complete recommended harness pattern from the
security audit, validating that all components work together correctly.

Security audit reference: Harness integration tests

NOTE: The harness pattern uses subprocess isolation because:
1. exec() and eval() are blocked inside sandbox scope
2. Exception handling inside scope can cascade sandbox errors
3. Subprocess provides ultimate isolation and timeout protection

The recommended pattern is to run untrusted code in a subprocess
with sandbox limits configured before entering scope.
"""

import subprocess
import sys
import unittest

from test.test_sandbox import (
    SUBPROCESS_TIMEOUT,
    _run_sandboxed_code,
)


class SafeExecHarnessTests(unittest.TestCase):
    """Test the recommended safe_exec harness pattern.

    Note: These tests use subprocess because the recommended harness
    pattern is to run untrusted code in isolated processes.
    """

    def test_simple_code_works(self):
        """Simple safe code should execute successfully."""
        code = '''
import sys
sys.sandbox.enter_scope()
x = 1 + 2
y = x * 3
result = y + 1
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Simple code failed: {result.stderr}")

    def test_infinite_loop_stopped(self):
        """Infinite loop should be stopped by iteration limit.

        Note: Uses max_iterations since subprocess code isn't compiled
        with PyCF_SANDBOX_COUNT flag required for max_operations.
        """
        code = '''
import sys
sys.sandbox.set_limits(max_iterations=100)
sys.sandbox.enter_scope()
for _ in iter(int, 1):  # Infinite iterator
    x = 1
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxRuntimeError", result.stderr)

    def test_large_list_blocked(self):
        """Large list creation should be blocked."""
        code = '''
import sys
sys.sandbox.set_limits(max_list_size=100)
sys.sandbox.enter_scope()
huge = list(range(10000))
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Sandbox", result.stderr)

    def test_import_blocked_when_restricted(self):
        """Import should be blocked when import_restrict_mode enabled."""
        code = '''
import sys
sys.sandbox.import_restrict_mode = True
sys.sandbox.allowed_modules = set()
sys.sandbox.enter_scope()
import os
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxImportError", result.stderr)


class MultiLimitInteractionTests(unittest.TestCase):
    """Test multiple limits interacting correctly."""

    def test_all_limits_active(self):
        """All size/execution limits active simultaneously."""
        code = '''
import sys
sys.sandbox.set_limits(
    max_iterations=1000,
    max_list_size=100,
    max_dict_size=100,
    max_set_size=100,
    max_tuple_size=100,
    max_str_length=1000,
    max_int_digits=50,
)
sys.sandbox.enter_scope()

# Operations within limits should work
lst = list(range(50))
d = {i: i for i in range(50)}
s = set(range(50))
t = tuple(range(50))
x = 10 ** 50  # Within int digit limit
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Operations within limits failed: {result.stderr}")

    def test_limit_interaction_no_cascade(self):
        """One limit triggered shouldn't affect other operations."""
        code = '''
import sys
sys.sandbox.set_limits(
    max_list_size=10,
)
sys.sandbox.enter_scope()

# Other operations should still work
x = 1 + 2
y = "hello" * 10
d = {"a": 1, "b": 2}

# Now trigger list limit (in subprocess, this causes exit)
big_list = list(range(100))
'''
        result = _run_sandboxed_code(code)
        # Should fail due to list limit
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Sandbox", result.stderr)


class SubprocessIsolationTests(unittest.TestCase):
    """Test subprocess as ultimate isolation mechanism."""

    def test_subprocess_timeout_kills_runaway(self):
        """Subprocess timeout should kill runaway code."""
        code = '''
# No sandbox limits - just pure loop
x = 0
while True:
    x += 1
'''
        with self.assertRaises(subprocess.TimeoutExpired):
            subprocess.run(
                [sys.executable, '-c', code],
                capture_output=True,
                text=True,
                timeout=1
            )

    def test_sandbox_limits_faster_than_timeout(self):
        """Sandbox limits should catch issues before timeout."""
        code = '''
import sys
sys.sandbox.set_limits(max_iterations=100)
sys.sandbox.enter_scope()
for _ in iter(int, 1):  # Infinite iterator
    x = 1
'''
        # Should complete quickly with sandbox error, not timeout
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=5  # Generous timeout
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxRuntimeError", result.stderr)


class RestrictedBuiltinsTests(unittest.TestCase):
    """Test that dangerous builtins are blocked."""

    def test_exec_blocked_in_scope(self):
        """exec() should be blocked in sandbox scope."""
        code = '''
import sys
sys.sandbox.enter_scope()
exec('x = 1')
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxSecurityError", result.stderr)

    def test_eval_blocked_in_scope(self):
        """eval() should be blocked in sandbox scope."""
        code = '''
import sys
sys.sandbox.enter_scope()
x = eval('1 + 2')
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxSecurityError", result.stderr)

    def test_compile_blocked_in_scope(self):
        """compile() should be blocked in sandbox scope."""
        code = '''
import sys
sys.sandbox.enter_scope()
code_obj = compile('x = 1', '<test>', 'exec')
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxSecurityError", result.stderr)

    def test_open_blocked_when_io_disabled(self):
        """open() should be blocked when allow_io=False."""
        code = '''
import sys
sys.sandbox.set_limits(allow_io=False)
sys.sandbox.enter_scope()
f = open('/etc/passwd', 'r')
'''
        result = _run_sandboxed_code(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxSecurityError", result.stderr)

    def test_input_blocked_in_scope(self):
        """input() should be blocked in sandbox scope."""
        code = '''
import sys
sys.sandbox.enter_scope()
x = input()
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


if __name__ == '__main__':
    unittest.main()
