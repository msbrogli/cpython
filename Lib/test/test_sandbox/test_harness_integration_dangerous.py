"""Dangerous harness integration tests that could hang if limits fail.

This module contains subprocess isolation tests that intentionally
trigger infinite loops to verify timeout protection. These tests
could hang if subprocess timeout fails.

These tests are separated from the main test suite to allow running
"safe" tests without risk of hangs during development.

Security audit reference: Harness integration tests (dangerous subset)
"""

import subprocess
import sys
import unittest

from test.test_sandbox import (
    SUBPROCESS_TIMEOUT,
    _run_sandboxed_code,
)


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


if __name__ == '__main__':
    unittest.main()
