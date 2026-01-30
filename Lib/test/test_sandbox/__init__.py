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
- test_security: Security tests for preventing config modification from scope
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
    # Prepend import and module access restriction disabling for legacy tests
    preamble = "import sys; sys.sandbox.import_restrict_mode = False; sys.sandbox.module_access_restrict_mode = False\n"
    return subprocess.run(
        [sys.executable, '-c', preamble + code],
        capture_output=True,
        text=True,
        timeout=timeout
    )


def _run_scoped_test(limit_name, limit_value, test_code, extra_setup=""):
    """Run a sandbox limit test in a subprocess.

    This is a helper for tests that need to set limits and enter scope.
    All sandbox configuration must happen before enter_scope() due to
    security restrictions that prevent modifying config from within scope.

    Args:
        limit_name: Name of the limit to set (e.g., 'max_int_digits')
        limit_value: Value for the limit
        test_code: Python code to run after entering scope
        extra_setup: Additional setup code to run before entering scope

    Returns:
        subprocess.CompletedProcess with returncode, stdout, and stderr
    """
    code = f'''
import sys
# Disable import and module access restrictions for legacy tests
sys.sandbox.import_restrict_mode = False
sys.sandbox.module_access_restrict_mode = False
{extra_setup}
sys.sandbox.set_limits({limit_name}={limit_value})
sys.sandbox.enter_scope()
{test_code}
'''
    return _run_sandboxed_code(code)


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
        # Note: SandboxSecurityError is raised if we're in scope (which prevents
        # modifying sandbox config). This can happen if a previous test added
        # the test file itself to scope and didn't clean up.
        try:
            sys.sandbox.exit_scope()
        except (RuntimeError, SandboxSecurityError):
            pass
        # Disable import restrictions for existing tests
        # (tests weren't designed with import restrictions in mind)
        try:
            sys.sandbox.import_restrict_mode = False
        except SandboxSecurityError:
            pass
        # Disable module access restrictions for existing tests
        # (tests weren't designed with module access restrictions in mind)
        try:
            sys.sandbox.module_access_restrict_mode = False
        except SandboxSecurityError:
            pass
        # Reset counters for clean test state (may fail if in scope)
        try:
            sys.sandbox.reset_counts()
        except SandboxSecurityError:
            pass

    def tearDown(self):
        """Tear down test fixtures - restore original state."""
        # Resume any suspended limits (may fail if in scope)
        try:
            while sys.sandbox.suspended:
                sys.sandbox.resume()
        except SandboxSecurityError:
            pass
        # Exit scope if entered
        try:
            sys.sandbox.exit_scope()
        except (RuntimeError, SandboxSecurityError):
            pass
        # Reset all sandbox state to defaults
        try:
            sys.sandbox.reset()
        except SandboxSecurityError:
            pass


class SandboxScopedTestCase(SandboxTestCase):
    """Base class for tests that run inside sandbox scope.

    NOTE: Due to security restrictions, we cannot call enter_scope() from the
    test file itself (it would put the test file in scope and prevent cleanup).
    Instead, this base class registers a specific filename and provides
    run_scoped_code() to execute code in that scope.

    If you need to run Python statements directly in scope (not via exec),
    you must convert your test to use subprocess tests instead.
    """

    # Filename used for scoped test code
    SCOPED_FILENAME = "<test_scoped_code>"

    def setUp(self):
        """Set up test fixtures and register scoped filename."""
        super().setUp()
        # Add a specific filename to scope instead of the test file itself
        # This allows cleanup to work properly
        sys.sandbox.add_filename(self.SCOPED_FILENAME)

    def tearDown(self):
        """Remove scoped filename and restore state."""
        # Remove the scoped filename - this works because the test framework
        # itself is not in scope (only code with SCOPED_FILENAME is)
        try:
            sys.sandbox.remove_filename(self.SCOPED_FILENAME)
        except (RuntimeError, KeyError):
            pass
        super().tearDown()

    def run_scoped_code(self, code_str, extra_globals=None):
        """Execute code within sandbox scope.

        Args:
            code_str: Python code to execute
            extra_globals: Additional globals dict to pass to exec

        Returns:
            The globals dict after execution (useful for checking results)
        """
        globs = {"sys": sys}
        if extra_globals:
            globs.update(extra_globals)
        code = compile(code_str, self.SCOPED_FILENAME, "exec")
        exec(code, globs)
        return globs


def load_tests(loader, tests, pattern):
    """Load tests from all modules in this package."""
    this_dir = os.path.dirname(__file__)
    saved_path = sys.path[:]
    package_tests = loader.discover(start_dir=this_dir, pattern='test*.py')
    sys.path[:] = saved_path
    tests.addTests(package_tests)
    return tests
