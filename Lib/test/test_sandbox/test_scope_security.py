"""Tests for sandbox scope security and escape prevention.

This module tests that scope detection cannot be bypassed and that
code objects from outside scope are properly handled.

Security audit reference: Scope escape vectors
"""

import subprocess
import sys
import unittest

from test.test_sandbox import (
    SandboxTestCase,
    ScopedFilenameTestCase,
    _run_sandboxed_code,
    SUBPROCESS_TIMEOUT,
)


class ScopeEscapeTests(ScopedFilenameTestCase):
    """Test that scope detection cannot be bypassed."""

    SCOPED_FILENAME = "<test_scope_security_scope>"

    def test_wrong_filename_code_not_in_scope(self):
        """Code compiled with unregistered filename is not in scope.

        This is a design characteristic: scope is filename-based.
        Code with unregistered filename runs without limits.
        """
        sys.sandbox.set_config(max_list_size=10)

        # Code with registered filename is in scope
        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("lst = list(range(50))")

        # Code with unregistered filename is NOT in scope
        unregistered_code = compile("lst = list(range(50))", "<unregistered>", "exec")
        globs = {"sys": sys}
        exec(unregistered_code, globs)  # Should succeed - not in scope
        self.assertEqual(len(globs['lst']), 50)

    def test_code_object_exec_in_scope(self):
        """exec(code_obj) where code_obj filename is in scope should work."""
        sys.sandbox.set_config(max_list_size=100)

        # Create code object with scoped filename
        scoped_code = compile("lst = list(range(50))", self.SCOPED_FILENAME, "exec")
        globs = {"sys": sys}
        exec(scoped_code, globs)  # In scope, within limit
        self.assertEqual(len(globs['lst']), 50)

    def test_exit_scope_blocked_from_within(self):
        """exit_scope() should be blocked when called from within scope."""
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises(SandboxSecurityError) as cm:
            self.run_scoped_code("sys.sandbox.exit_scope()")
        self.assertIn("scope", str(cm.exception).lower())

    def test_set_limits_blocked_from_within_scope(self):
        """set_limits() should be blocked when called from within scope."""
        sys.sandbox.set_config(max_list_size=100)

        with self.assertRaises(SandboxSecurityError) as cm:
            self.run_scoped_code("sys.sandbox.set_config(max_list_size=999999)")
        self.assertIn("scope", str(cm.exception).lower())

    def test_remove_filename_blocked_from_within_scope(self):
        """remove_filename() should be blocked from within scope."""
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises(SandboxSecurityError) as cm:
            self.run_scoped_code(f"sys.sandbox.remove_filename('{self.SCOPED_FILENAME}')")

    def test_nested_exec_blocked_in_scope(self):
        """compile() and exec() are blocked in sandbox scope.

        This is a security feature - compile() and exec() could be used
        to generate code that bypasses sandbox restrictions.
        """
        sys.sandbox.set_config(max_list_size=10)

        with self.assertRaises(SandboxSecurityError):
            self.run_scoped_code("""
nested_code = compile("lst = list(range(50))", "<test>", "exec")
""")

    def test_eval_blocked_in_scope(self):
        """eval() is blocked in sandbox scope.

        This is a security feature - eval() could be used to bypass
        sandbox restrictions.
        """
        sys.sandbox.set_config(max_list_size=10)

        with self.assertRaises(SandboxSecurityError):
            self.run_scoped_code("""
result = eval("1 + 2")
""")


class ScopeModificationTests(ScopedFilenameTestCase):
    """Test that scope cannot be modified from within scope."""

    SCOPED_FILENAME = "<test_scope_security_scope>"

    def test_add_filename_blocked_from_scope(self):
        """add_filename() should be blocked from within scope."""
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises(SandboxSecurityError):
            self.run_scoped_code("sys.sandbox.add_filename('<attacker_file>')")

    def test_reset_blocked_from_scope(self):
        """reset() should be blocked from within scope."""
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises(SandboxSecurityError):
            self.run_scoped_code("sys.sandbox.reset()")

    def test_reset_counts_blocked_from_scope(self):
        """reset_counts() should be blocked from within scope."""
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises(SandboxSecurityError):
            self.run_scoped_code("sys.sandbox.reset_counts()")

    def test_suspend_blocked_from_scope(self):
        """suspend() should be blocked from within scope."""
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises(SandboxSecurityError):
            self.run_scoped_code("sys.sandbox.suspend()")


class FilenameScopeTests(SandboxTestCase):
    """Test filename-based scope management."""

    SCOPED_FILENAME = "<test_scope_security_scope>"

    def tearDown(self):
        try:
            sys.sandbox.remove_filename(self.SCOPED_FILENAME)
        except (RuntimeError, KeyError):
            pass
        try:
            sys.sandbox.remove_filename("<other_scope>")
        except (RuntimeError, KeyError):
            pass
        super().tearDown()

    def test_multiple_filenames_in_scope(self):
        """Multiple filenames can be in scope simultaneously."""
        sys.sandbox.set_config(max_list_size=10)
        sys.sandbox.add_filename(self.SCOPED_FILENAME)
        sys.sandbox.add_filename("<other_scope>")

        # Both filenames should be in scope
        with self.assertRaises(SandboxOverflowError):
            code1 = compile("lst = list(range(50))", self.SCOPED_FILENAME, "exec")
            exec(code1, {"sys": sys})

        with self.assertRaises(SandboxOverflowError):
            code2 = compile("lst = list(range(50))", "<other_scope>", "exec")
            exec(code2, {"sys": sys})

    def test_remove_filename_allows_bypass(self):
        """Removing filename from scope disables restrictions for that file."""
        sys.sandbox.set_config(max_list_size=10)
        sys.sandbox.add_filename(self.SCOPED_FILENAME)

        # In scope - should fail
        with self.assertRaises(SandboxOverflowError):
            code = compile("lst = list(range(50))", self.SCOPED_FILENAME, "exec")
            exec(code, {"sys": sys})

        # Remove from scope
        sys.sandbox.remove_filename(self.SCOPED_FILENAME)

        # Not in scope anymore - should succeed
        code = compile("lst = list(range(50))", self.SCOPED_FILENAME, "exec")
        globs = {"sys": sys}
        exec(code, globs)
        self.assertEqual(len(globs['lst']), 50)


class SubprocessScopeTests(unittest.TestCase):
    """Subprocess tests for scope security that need full isolation."""

    def test_enter_scope_adds_current_file(self):
        """enter_scope() should add the current file to scope."""
        code = '''
import sys
sys.sandbox.set_config(max_list_size=10)
sys.sandbox.enter_scope()
try:
    lst = list(range(50))
    sys.exit(2)  # Should not reach
except SandboxOverflowError:
    sys.exit(0)  # Expected
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Test failed with stderr: {result.stderr}")

    def test_exit_scope_blocked_after_enter(self):
        """exit_scope() should be blocked after enter_scope()."""
        code = '''
import sys
sys.sandbox.enter_scope()
try:
    sys.sandbox.exit_scope()
    sys.exit(2)  # Should not reach
except SandboxSecurityError:
    sys.exit(0)  # Expected
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Test failed with stderr: {result.stderr}")

    def test_scope_persists_across_function_calls(self):
        """Scope restrictions should persist across function calls."""
        code = '''
import sys
sys.sandbox.set_config(max_list_size=10)
sys.sandbox.enter_scope()

def create_large_list():
    return list(range(50))

try:
    lst = create_large_list()
    sys.exit(2)  # Should not reach
except SandboxOverflowError:
    sys.exit(0)  # Expected
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Test failed with stderr: {result.stderr}")

    def test_scope_applies_to_imported_modules(self):
        """Scope restrictions should apply to code in imported modules.

        Note: This depends on how the module was compiled (its filename).
        Standard library modules typically have different filenames.
        """
        code = '''
import sys
sys.sandbox.set_config(max_list_size=10)
sys.sandbox.enter_scope()

# json module operations should NOT be in scope (different filename)
import json
try:
    # This creates lists internally but those are in json module's file
    result = json.loads('[1, 2, 3]')
    sys.exit(0)  # Expected to succeed
except SandboxOverflowError:
    sys.exit(2)  # Should not happen
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Test failed with stderr: {result.stderr}")


class FrameBasedScopeTests(unittest.TestCase):
    """Test add_frame() based scope management."""

    def test_add_frame_subprocess(self):
        """add_frame() should add current frame's filename to scope."""
        code = '''
import sys
sys.sandbox.set_config(max_list_size=10)
sys.sandbox.add_frame()  # Adds <string> to scope
try:
    lst = list(range(50))
    sys.exit(2)  # Should not reach
except SandboxOverflowError:
    sys.exit(0)  # Expected
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Test failed with stderr: {result.stderr}")


if __name__ == '__main__':
    unittest.main()
