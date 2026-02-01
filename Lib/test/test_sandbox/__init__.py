"""Tests for the sandbox functionality in sys module.

This package contains tests split by feature domain:

Core Functionality:
- test_limits: API basics, type/size limits, suspend/resume
- test_hooks: Object creation hooks
- test_allocations: Scoped allocation counting
- test_scope: Scope management and statement counting
- test_iterations: Iteration counting and iterator wrapper protection
- test_dunder_access: Dunder attribute blocking
- test_frozen_mode: Frozen mode and auto-mutable mode
- test_opcodes: Opcode restrictions
- test_operations: Opcode-based operation counting (SANDBOX_COUNT)
- test_bytecode: Bytecode-level verification of SANDBOX_COUNT placement

Security Tests:
- test_security: Prevention of config modification from scope
- test_container_copy_limits: dict/set copy/update bypass prevention
- test_scope_security: Scope escape vector prevention
- test_dos_prevention: Resource exhaustion prevention
- test_module_access_security: sys.modules access control
- test_frame_access: Generator/coroutine frame blocking
- test_metaclass_security: Custom metaclass blocking
- test_compile_time_limits: Constant folding bypass prevention

Integration Tests:
- test_integration: Basic integration tests
- test_harness_integration: Full harness pattern validation
- test_attack_scenarios: Documented attack vector tests
"""

import functools
import os
import signal
import subprocess
import sys
import unittest


# Default timeout for subprocess tests (seconds)
SUBPROCESS_TIMEOUT = 10

# Compile flag for operation counting (must match Include/cpython/compile.h)
PyCF_SANDBOX_COUNT = 0x8000

# Test limit values - chosen to be large enough for normal test operations
# but small enough to trigger limit checks quickly
TEST_LIST_LIMIT = 500
TEST_DICT_LIMIT = 500
TEST_SET_LIMIT = 500
TEST_TUPLE_LIMIT = 500
TEST_STR_LIMIT = 100
TEST_INT_DIGITS_LIMIT = 5  # ~45 decimal digits (each internal digit ~9 decimals)


class TestLimits:
    """Standard limit values for tests.

    Use these constants instead of magic numbers in tests for consistency
    and easier maintenance.
    """
    TINY = 5
    SMALL = 10
    MEDIUM = 100
    LARGE = 500
    XLARGE = 1000

    # Specific limit names for clarity
    LIST = MEDIUM
    DICT = MEDIUM
    SET = MEDIUM
    TUPLE = MEDIUM
    STRING = 100
    INT_DIGITS = 5


# Standard exception tuples for consistent ordering in assertRaises
# Note: These sandbox exceptions are built-in to this modified CPython
# They are not available in standard Python
try:
    SECURITY_EXCEPTIONS = (SandboxSecurityError, AttributeError, TypeError)
    OVERFLOW_EXCEPTIONS = (SandboxOverflowError, SandboxMemoryError)
    RUNTIME_EXCEPTIONS = (SandboxRuntimeError,)
    ALL_SANDBOX_EXCEPTIONS = (
        SandboxSecurityError, SandboxOverflowError,
        SandboxRuntimeError, SandboxMemoryError,
        SandboxTypeError, SandboxImportError
    )
except NameError:
    # Running on standard Python without sandbox support
    SECURITY_EXCEPTIONS = (AttributeError, TypeError)
    OVERFLOW_EXCEPTIONS = (OverflowError, MemoryError)
    RUNTIME_EXCEPTIONS = (RuntimeError,)
    ALL_SANDBOX_EXCEPTIONS = ()


# Timeout for individual test methods (seconds)
TEST_TIMEOUT = 3


class TestTimeoutError(Exception):
    """Raised when a test exceeds its timeout."""
    pass


def timeout_test(seconds=TEST_TIMEOUT):
    """Decorator to add timeout to a test method using signal.alarm."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not hasattr(signal, 'SIGALRM'):
                # SIGALRM not available (e.g., Windows), skip timeout
                return func(*args, **kwargs)
            def handler(signum, frame):
                raise TestTimeoutError(
                    f"Test {func.__name__} timed out after {seconds} seconds"
                )
            old_handler = signal.signal(signal.SIGALRM, handler)
            signal.alarm(seconds)
            try:
                return func(*args, **kwargs)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
        return wrapper
    return decorator


class TimeoutTestCase(unittest.TestCase):
    """Base class that wraps each test method with a timeout."""

    def run(self, result=None):
        test_method = getattr(self, self._testMethodName)
        if not getattr(test_method, '_has_timeout', False):
            wrapped = timeout_test(TEST_TIMEOUT)(test_method)
            wrapped._has_timeout = True
            setattr(self, self._testMethodName, wrapped)
        return super().run(result)


def _run_sandboxed_code(code, timeout=SUBPROCESS_TIMEOUT):
    """Run code in a subprocess with sandbox limits.

    Args:
        code: Python code to execute as a string
        timeout: Maximum time to wait for the subprocess (seconds)

    Returns:
        subprocess.CompletedProcess with returncode, stdout, and stderr
    """
    # Prepend setup: enable sandbox and disable import/module restrictions for legacy tests
    preamble = "import sys; sys.sandbox.enable(); sys.sandbox.import_restrict_mode = False; sys.sandbox.module_access_restrict_mode = False\n"
    return subprocess.run(
        [sys.executable, '-c', preamble + code],
        capture_output=True,
        text=True,
        timeout=timeout
    )


def run_sandboxed_subprocess(code, timeout=SUBPROCESS_TIMEOUT,
                              disable_import_restrict=True,
                              disable_module_restrict=True,
                              limits=None):
    """Run code in isolated subprocess with sandbox.

    This is an enhanced version of _run_sandboxed_code with more options.

    Args:
        code: Python code to execute
        timeout: Max execution time in seconds
        disable_import_restrict: Whether to disable import restrictions
        disable_module_restrict: Whether to disable module access restrictions
        limits: Optional dict of limit settings (e.g., {'max_list_size': 100})

    Returns:
        subprocess.CompletedProcess result
    """
    preamble_parts = ["import sys", "sys.sandbox.enable()"]

    if disable_import_restrict:
        preamble_parts.append("sys.sandbox.import_restrict_mode = False")
    if disable_module_restrict:
        preamble_parts.append("sys.sandbox.module_access_restrict_mode = False")
    if limits:
        limit_str = ", ".join(f"{k}={v}" for k, v in limits.items())
        preamble_parts.append(f"sys.sandbox.set_config({limit_str})")

    preamble = "\n".join(preamble_parts) + "\n"

    return subprocess.run(
        [sys.executable, "-c", preamble + code],
        capture_output=True,
        text=True,
        timeout=timeout
    )


def run_scoped_test(code_str, scoped_filename, extra_globals=None, sys_module=None,
                    count_operations=True):
    """Consolidated helper for running code in sandbox scope.

    This function compiles and executes code with a specific filename,
    allowing the code to be subject to sandbox scope restrictions when
    that filename has been registered with sys.sandbox.add_filename().

    Args:
        code_str: Python code to execute
        scoped_filename: Unique filename for scope isolation
        extra_globals: Additional globals to inject
        sys_module: sys module to use (defaults to sys)
        count_operations: If True, compile with PyCF_SANDBOX_COUNT for
                          operation counting (required for max_operations limit)

    Returns:
        dict: The globals after execution
    """
    import sys as default_sys
    sys_mod = sys_module or default_sys
    globs = {"sys": sys_mod}
    if extra_globals:
        globs.update(extra_globals)
    flags = PyCF_SANDBOX_COUNT if count_operations else 0
    code = compile(code_str, scoped_filename, "exec", flags=flags)
    exec(code, globs)
    return globs


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
# Enable sandbox and disable import/module access restrictions for legacy tests
sys.sandbox.enable()
sys.sandbox.import_restrict_mode = False
sys.sandbox.module_access_restrict_mode = False
{extra_setup}
sys.sandbox.set_config({limit_name}={limit_value})
sys.sandbox.enter_scope()
{test_code}
'''
    return _run_sandboxed_code(code)


def _get_settable_limits():
    """Get current limits for restoring in tearDown.

    Also enables sandbox - tests that save limits usually need sandbox enabled.
    """
    sys.sandbox.enable()
    return sys.sandbox.get_config()


class SandboxTestCase(TimeoutTestCase):
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
        # Enable sandbox (required before entering scope or adding filenames)
        try:
            sys.sandbox.enable()
        except SandboxSecurityError:
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

    def run_scoped_code(self, code_str, extra_globals=None, count_operations=True):
        """Execute code within sandbox scope.

        Args:
            code_str: Python code to execute
            extra_globals: Additional globals dict to pass to exec
            count_operations: If True, compile with PyCF_SANDBOX_COUNT for
                              operation counting (required for max_operations limit)

        Returns:
            The globals dict after execution (useful for checking results)
        """
        globs = {"sys": sys}
        if extra_globals:
            globs.update(extra_globals)
        flags = PyCF_SANDBOX_COUNT if count_operations else 0
        code = compile(code_str, self.SCOPED_FILENAME, "exec", flags=flags)
        exec(code, globs)
        return globs


# Alias for backward compatibility and clearer naming
ScopedFilenameTestCase = SandboxScopedTestCase


def load_tests(loader, tests, pattern):
    """Load tests from all modules in this package."""
    this_dir = os.path.dirname(__file__)
    saved_path = sys.path[:]
    package_tests = loader.discover(start_dir=this_dir, pattern='test*.py')
    sys.path[:] = saved_path
    tests.addTests(package_tests)
    return tests
