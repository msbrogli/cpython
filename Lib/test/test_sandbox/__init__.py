"""Tests for the sandbox functionality in sys module.

This package contains tests split by feature domain:
- test_limits: API basics, type/size limits, suspend/resume
- test_hooks: Object creation hooks
- test_allocations: Scoped allocation counting
- test_scope: Scope management and statement counting
- test_iterations: Iteration counting and iterator wrapper protection
- test_dunder_access: Dunder attribute blocking
- test_frozen_mode: Frozen mode and auto-mutable mode
- test_integration: Integration tests
- test_opcodes: Opcode restrictions
- test_operations: Opcode-based operation counting (SANDBOX_COUNT)
- test_bytecode: Bytecode-level verification of SANDBOX_COUNT placement
"""

import os
import subprocess
import sys
import unittest


# Default timeout for subprocess tests (seconds)
SUBPROCESS_TIMEOUT = 10

# Test limit values - chosen to be large enough for normal test operations
# but small enough to trigger limit checks quickly
TEST_LIST_LIMIT = 500
TEST_DICT_LIMIT = 500
TEST_SET_LIMIT = 500
TEST_TUPLE_LIMIT = 500
TEST_STR_LIMIT = 100
TEST_INT_DIGITS_LIMIT = 5  # ~45 decimal digits (each internal digit ~9 decimals)


def _run_sandboxed_code(code, timeout=SUBPROCESS_TIMEOUT):
    """Run code in a subprocess with sandbox limits.

    Args:
        code: Python code to execute as a string
        timeout: Maximum time to wait for the subprocess (seconds)

    Returns:
        subprocess.CompletedProcess with returncode, stdout, and stderr
    """
    return subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        timeout=timeout
    )


def _get_settable_limits():
    """Get current limits for restoring in tearDown."""
    return sys.sandbox.get_limits()


class SandboxTestCase(unittest.TestCase):
    """Base class for sandbox tests with common setUp/tearDown patterns.

    This base class handles:
    - Saving and restoring original sandbox limits
    - Exiting any active sandbox scope
    - Resuming any suspended sandbox limits
    - Resetting counters for clean test state

    Subclasses can override setUp() and tearDown() but should call
    super().setUp() and super().tearDown() to ensure proper cleanup.
    """

    def setUp(self):
        """Set up test fixtures - save state and ensure clean scope."""
        # Exit any lingering scope from previous tests
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        # Save original limits for restoration
        self.original_limits = _get_settable_limits()
        # Reset counters for clean test state
        sys.sandbox.reset_counts()

    def tearDown(self):
        """Tear down test fixtures - restore original state."""
        # Resume any suspended limits
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        # Exit scope if entered
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        # Restore original limits
        sys.sandbox.set_limits(**self.original_limits)
        # Reset counters
        sys.sandbox.reset_counts()


class SandboxScopedTestCase(SandboxTestCase):
    """Base class for tests that run inside sandbox scope.

    This automatically enters scope in setUp and exits in tearDown.
    """

    def setUp(self):
        """Set up test fixtures and enter sandbox scope."""
        super().setUp()
        sys.sandbox.enter_scope()

    def tearDown(self):
        """Exit sandbox scope and restore state."""
        # Note: super().tearDown() will handle exit_scope()
        super().tearDown()


def load_tests(loader, tests, pattern):
    """Load tests from all modules in this package."""
    this_dir = os.path.dirname(__file__)
    saved_path = sys.path[:]
    package_tests = loader.discover(start_dir=this_dir, pattern='test*.py')
    sys.path[:] = saved_path
    tests.addTests(package_tests)
    return tests
