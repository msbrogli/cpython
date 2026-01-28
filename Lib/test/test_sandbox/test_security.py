"""Tests for sandbox security: prevent configuration modification from within scope.

This module tests that code running inside sandbox scope cannot modify
sandbox configuration, ensuring sandboxed code cannot escape its restrictions.
"""

import sys
import unittest

from test.test_sandbox import SandboxTestCase


class SandboxSecurityErrorTests(unittest.TestCase):
    """Test the SandboxSecurityError exception class."""

    def test_sandboxsecurityerror_exists(self):
        """SandboxSecurityError should be accessible as a builtin."""
        # SandboxSecurityError should be a builtin exception like ValueError
        # __builtins__ can be either a dict or a module depending on context
        if isinstance(__builtins__, dict):
            self.assertIn('SandboxSecurityError', __builtins__)
        else:
            self.assertTrue(hasattr(__builtins__, 'SandboxSecurityError'))

    def test_sandboxsecurityerror_inherits_from_sandboxerror(self):
        """SandboxSecurityError should be a subclass of SandboxError."""
        self.assertTrue(issubclass(SandboxSecurityError, SandboxError))

    def test_sandboxsecurityerror_inherits_from_exception(self):
        """SandboxSecurityError should be a subclass of Exception."""
        self.assertTrue(issubclass(SandboxSecurityError, Exception))

    def test_can_raise_sandboxsecurityerror(self):
        """Should be able to raise and catch SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            raise SandboxSecurityError("test message")

    def test_can_catch_as_sandboxerror(self):
        """Should be able to catch SandboxSecurityError as SandboxError."""
        with self.assertRaises(SandboxError):
            raise SandboxSecurityError("test message")


class SandboxConfigModificationBlockedTests(SandboxTestCase):
    """Test that config modifications are blocked from within sandbox scope."""

    def _run_in_scope(self, code_str):
        """Execute code in sandbox scope via compile/exec."""
        filename = "<sandbox_test>"
        sys.sandbox.add_filename(filename)
        try:
            code = compile(code_str, filename, "exec")
            exec(code, {"sys": sys})
        finally:
            sys.sandbox.remove_filename(filename)

    def test_set_max_statements_blocked_from_scope(self):
        """Setting max_statements from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError) as ctx:
            self._run_in_scope("sys.sandbox.max_statements = 99999")
        self.assertIn("Cannot modify sandbox configuration", str(ctx.exception))

    def test_set_max_allocations_blocked_from_scope(self):
        """Setting max_allocations from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.max_allocations = 99999")

    def test_set_max_iterations_blocked_from_scope(self):
        """Setting max_iterations from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.max_iterations = 99999")

    def test_set_max_operations_blocked_from_scope(self):
        """Setting max_operations from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.max_operations = 99999")

    def test_set_max_int_digits_blocked_from_scope(self):
        """Setting max_int_digits from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.max_int_digits = 99999")

    def test_set_max_str_length_blocked_from_scope(self):
        """Setting max_str_length from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.max_str_length = 99999")

    def test_set_max_bytes_length_blocked_from_scope(self):
        """Setting max_bytes_length from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.max_bytes_length = 99999")

    def test_set_max_list_size_blocked_from_scope(self):
        """Setting max_list_size from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.max_list_size = 99999")

    def test_set_max_dict_size_blocked_from_scope(self):
        """Setting max_dict_size from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.max_dict_size = 99999")

    def test_set_max_set_size_blocked_from_scope(self):
        """Setting max_set_size from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.max_set_size = 99999")

    def test_set_max_tuple_size_blocked_from_scope(self):
        """Setting max_tuple_size from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.max_tuple_size = 99999")

    def test_set_allow_float_blocked_from_scope(self):
        """Setting allow_float from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.allow_float = False")

    def test_set_allow_complex_blocked_from_scope(self):
        """Setting allow_complex from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.allow_complex = False")

    def test_set_allow_dunder_access_blocked_from_scope(self):
        """Setting allow_dunder_access from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.allow_dunder_access = False")

    def test_set_frozen_mode_blocked_from_scope(self):
        """Setting frozen_mode from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.frozen_mode = False")

    def test_set_auto_mutable_blocked_from_scope(self):
        """Setting auto_mutable from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.auto_mutable = True")

    def test_set_opcode_restrict_mode_blocked_from_scope(self):
        """Setting opcode_restrict_mode from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.opcode_restrict_mode = False")

    def test_set_banned_opcodes_blocked_from_scope(self):
        """Setting banned_opcodes from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.banned_opcodes = set()")

    def test_set_creation_hook_blocked_from_scope(self):
        """Setting creation_hook from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.creation_hook = None")


class SandboxMethodsBlockedTests(SandboxTestCase):
    """Test that config-modifying methods are blocked from within scope."""

    def _run_in_scope(self, code_str):
        """Execute code in sandbox scope via compile/exec."""
        filename = "<sandbox_test>"
        sys.sandbox.add_filename(filename)
        try:
            code = compile(code_str, filename, "exec")
            exec(code, {"sys": sys})
        finally:
            sys.sandbox.remove_filename(filename)

    def test_set_limits_blocked_from_scope(self):
        """Calling set_limits() from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.set_limits(max_statements=99999)")

    def test_reset_blocked_from_scope(self):
        """Calling reset() from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.reset()")

    def test_reset_counts_blocked_from_scope(self):
        """Calling reset_counts() from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.reset_counts()")

    def test_enter_scope_blocked_from_scope(self):
        """Calling enter_scope() from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.enter_scope()")

    def test_exit_scope_blocked_from_scope(self):
        """Calling exit_scope() from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.exit_scope()")

    def test_add_filename_blocked_from_scope(self):
        """Calling add_filename() from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.add_filename('other.py')")

    def test_remove_filename_blocked_from_scope(self):
        """Calling remove_filename() from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.remove_filename('<sandbox_test>')")

    def test_add_frame_blocked_from_scope(self):
        """Calling add_frame() from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.add_frame()")

    def test_clear_filenames_blocked_from_scope(self):
        """Calling clear_filenames() from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.clear_filenames()")

    def test_suspend_blocked_from_scope(self):
        """Calling suspend() from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.suspend()")

    def test_resume_blocked_from_scope(self):
        """Calling resume() from scope should raise SandboxSecurityError."""
        # First suspend from outside scope so resume is valid
        sys.sandbox.suspend()
        try:
            with self.assertRaises(SandboxSecurityError):
                self._run_in_scope("sys.sandbox.resume()")
        finally:
            sys.sandbox.resume()

    def test_freeze_blocked_from_scope(self):
        """Calling freeze() from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.freeze(object())")

    def test_set_mutable_blocked_from_scope(self):
        """Calling set_mutable() from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("sys.sandbox.set_mutable(object())")


class SandboxContextManagersBlockedTests(SandboxTestCase):
    """Test that context manager enter methods are blocked from within scope."""

    def _run_in_scope(self, code_str):
        """Execute code in sandbox scope via compile/exec."""
        filename = "<sandbox_test>"
        sys.sandbox.add_filename(filename)
        try:
            code = compile(code_str, filename, "exec")
            exec(code, {"sys": sys})
        finally:
            sys.sandbox.remove_filename(filename)

    def test_scope_context_manager_blocked_from_scope(self):
        """Using scope() context manager from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("ctx = sys.sandbox.scope(); ctx.__enter__()")

    def test_suspended_limits_context_manager_blocked_from_scope(self):
        """Using suspended_limits() from scope should raise SandboxSecurityError."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("ctx = sys.sandbox.suspended_limits(); ctx.__enter__()")


class SandboxReadAllowedFromScopeTests(SandboxTestCase):
    """Test that read operations are allowed from within sandbox scope."""

    def _run_in_scope(self, code_str):
        """Execute code in sandbox scope via compile/exec and return result."""
        filename = "<sandbox_test>"
        sys.sandbox.add_filename(filename)
        try:
            code = compile(code_str, filename, "exec")
            namespace = {"sys": sys, "result": None}
            exec(code, namespace)
            return namespace.get("result")
        finally:
            sys.sandbox.remove_filename(filename)

    def test_get_limits_allowed_from_scope(self):
        """Reading limits via get_limits() should work from scope."""
        result = self._run_in_scope("result = sys.sandbox.get_limits()")
        self.assertIsInstance(result, dict)

    def test_get_counts_allowed_from_scope(self):
        """Reading counts via get_counts() should work from scope."""
        result = self._run_in_scope("result = sys.sandbox.get_counts()")
        self.assertIsInstance(result, dict)

    def test_in_scope_allowed_from_scope(self):
        """Calling in_scope() should work from scope."""
        result = self._run_in_scope("result = sys.sandbox.in_scope()")
        self.assertTrue(result)

    def test_is_frozen_allowed_from_scope(self):
        """Calling is_frozen() should work from scope."""
        result = self._run_in_scope("result = sys.sandbox.is_frozen(object())")
        self.assertFalse(result)

    def test_read_max_statements_allowed_from_scope(self):
        """Reading max_statements property should work from scope."""
        sys.sandbox.max_statements = 1000
        result = self._run_in_scope("result = sys.sandbox.max_statements")
        self.assertEqual(result, 1000)

    def test_read_max_allocations_allowed_from_scope(self):
        """Reading max_allocations property should work from scope."""
        sys.sandbox.max_allocations = 2000
        result = self._run_in_scope("result = sys.sandbox.max_allocations")
        self.assertEqual(result, 2000)

    def test_read_frozen_mode_allowed_from_scope(self):
        """Reading frozen_mode property should work from scope."""
        result = self._run_in_scope("result = sys.sandbox.frozen_mode")
        self.assertIsInstance(result, bool)

    def test_read_suspended_allowed_from_scope(self):
        """Reading suspended property should work from scope."""
        result = self._run_in_scope("result = sys.sandbox.suspended")
        self.assertFalse(result)

    def test_read_allocation_count_allowed_from_scope(self):
        """Reading allocation_count property should work from scope."""
        result = self._run_in_scope("result = sys.sandbox.allocation_count")
        self.assertIsInstance(result, int)

    def test_read_statement_count_allowed_from_scope(self):
        """Reading statement_count property should work from scope."""
        result = self._run_in_scope("result = sys.sandbox.statement_count")
        self.assertIsInstance(result, int)

    def test_read_banned_opcodes_allowed_from_scope(self):
        """Reading banned_opcodes property should work from scope."""
        result = self._run_in_scope("result = sys.sandbox.banned_opcodes")
        self.assertIsInstance(result, frozenset)

    def test_read_creation_hook_allowed_from_scope(self):
        """Reading creation_hook property should work from scope."""
        result = self._run_in_scope("result = sys.sandbox.creation_hook")
        self.assertIsNone(result)


class SandboxNestedCallBlockedTests(SandboxTestCase):
    """Test that nested function calls in scope cannot modify config."""

    def _run_in_scope(self, code_str):
        """Execute code in sandbox scope via compile/exec."""
        filename = "<sandbox_test>"
        sys.sandbox.add_filename(filename)
        try:
            code = compile(code_str, filename, "exec")
            exec(code, {"sys": sys})
        finally:
            sys.sandbox.remove_filename(filename)

    def test_nested_function_cannot_modify_config(self):
        """A nested function in scope should not be able to modify config."""
        code = """
def attempt_escape():
    sys.sandbox.max_statements = 99999

attempt_escape()
"""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope(code)

    def test_class_method_cannot_modify_config(self):
        """A class method in scope should not be able to modify config."""
        code = """
class Attacker:
    def escape(self):
        sys.sandbox.max_statements = 99999

Attacker().escape()
"""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope(code)


class SandboxModificationOutsideScopeAllowedTests(SandboxTestCase):
    """Test that config modifications work normally outside sandbox scope."""

    def test_set_max_statements_allowed_outside_scope(self):
        """Setting max_statements outside scope should work."""
        sys.sandbox.max_statements = 5000
        self.assertEqual(sys.sandbox.max_statements, 5000)

    def test_set_limits_allowed_outside_scope(self):
        """Calling set_limits() outside scope should work."""
        sys.sandbox.set_limits(max_iterations=3000)
        self.assertEqual(sys.sandbox.max_iterations, 3000)

    def test_suspend_resume_allowed_outside_scope(self):
        """Calling suspend()/resume() outside scope should work."""
        count = sys.sandbox.suspend()
        self.assertEqual(count, 1)
        self.assertTrue(sys.sandbox.suspended)
        count = sys.sandbox.resume()
        self.assertEqual(count, 0)
        self.assertFalse(sys.sandbox.suspended)

    def test_reset_allowed_outside_scope(self):
        """Calling reset() outside scope should work."""
        sys.sandbox.max_statements = 1000
        sys.sandbox.reset()
        self.assertEqual(sys.sandbox.max_statements, 0)

    def test_scope_context_manager_allowed_outside_scope(self):
        """Using scope() context manager outside scope should work."""
        with sys.sandbox.scope():
            self.assertTrue(sys.sandbox.in_scope())
        self.assertFalse(sys.sandbox.in_scope())


if __name__ == '__main__':
    unittest.main()
