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


def load_tests(loader, tests, pattern):
    """Load tests from all modules in this package."""
    this_dir = os.path.dirname(__file__)
    saved_path = sys.path[:]
    package_tests = loader.discover(start_dir=this_dir, pattern='test*.py')
    sys.path[:] = saved_path
    tests.addTests(package_tests)
    return tests
