"""Tests for sandbox security: prevent configuration modification from within scope.

This module tests that code running inside sandbox scope cannot modify
sandbox configuration, ensuring sandboxed code cannot escape its restrictions.
"""

import gc
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


class V001V002CompileBlockedTests(SandboxTestCase):
    """Test that compile() is blocked in sandbox scope.

    The compile() function allows creating code objects with arbitrary filenames,
    which could be used to escape scope tracking. This test ensures compile()
    is blocked when called from within sandbox scope.
    """

    def _run_in_scope(self, code_str):
        """Execute code in sandbox scope via compile/exec."""
        filename = "<sandbox_test>"
        sys.sandbox.add_filename(filename)
        try:
            # compile() is called from OUTSIDE scope (this test file is not in scope)
            code = compile(code_str, filename, "exec")
            exec(code, {"sys": sys, "compile": compile})
        finally:
            sys.sandbox.remove_filename(filename)

    def test_compile_blocked_in_scope(self):
        """compile() should be blocked in sandbox scope."""
        with self.assertRaises(SandboxSecurityError) as ctx:
            self._run_in_scope("compile('x=1', 'attacker.py', 'exec')")
        self.assertIn("compile", str(ctx.exception))
        self.assertIn("not allowed", str(ctx.exception))

    def test_compile_allowed_with_allow_unsafe(self):
        """compile() should be allowed when allow_unsafe=True."""
        sys.sandbox.allow_unsafe = True
        try:
            filename = "<sandbox_test>"
            sys.sandbox.add_filename(filename)
            try:
                code = compile("result = compile('x=1', 'test.py', 'exec')", filename, "exec")
                ns = {"compile": compile, "result": None}
                exec(code, ns)
                self.assertIsNotNone(ns["result"])
            finally:
                sys.sandbox.remove_filename(filename)
        finally:
            sys.sandbox.allow_unsafe = False

    def test_compile_allowed_outside_scope(self):
        """compile() should work outside sandbox scope."""
        code = compile("x = 1", "test.py", "exec")
        self.assertIsNotNone(code)


class V007IterBlockedTests(SandboxTestCase):
    """Test that __iter__ access is blocked in sandbox scope.

    Direct access to __iter__ could bypass the sandbox iterator wrapper,
    allowing unbounded iteration. This test ensures __iter__ is blocked.
    """

    def _run_in_scope(self, code_str, extra_globals=None):
        """Execute code in sandbox scope via compile/exec."""
        filename = "<sandbox_test>"
        sys.sandbox.add_filename(filename)
        try:
            code = compile(code_str, filename, "exec")
            ns = {"sys": sys}
            if extra_globals:
                ns.update(extra_globals)
            exec(code, ns)
            return ns
        finally:
            sys.sandbox.remove_filename(filename)

    def test_iter_dunder_blocked_in_scope(self):
        """__iter__ access should be blocked in sandbox scope."""
        with self.assertRaises(SandboxSecurityError) as ctx:
            self._run_in_scope("[1, 2, 3].__iter__()")
        self.assertIn("__iter__", str(ctx.exception))
        self.assertIn("not allowed", str(ctx.exception))

    def test_iter_dunder_on_dict_blocked(self):
        """__iter__ on dict should be blocked in sandbox scope."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("{'a': 1}.__iter__()")

    def test_iter_dunder_on_string_blocked(self):
        """__iter__ on string should be blocked in sandbox scope."""
        with self.assertRaises(SandboxSecurityError):
            self._run_in_scope("'abc'.__iter__()")

    def test_iter_allowed_with_allow_unsafe(self):
        """__iter__ should be allowed when allow_unsafe=True."""
        sys.sandbox.allow_unsafe = True
        try:
            ns = self._run_in_scope("result = [1, 2, 3].__iter__()")
            self.assertIsNotNone(ns.get("result"))
        finally:
            sys.sandbox.allow_unsafe = False

    def test_for_loop_still_works(self):
        """for loops should work (use wrapped iterators)."""
        ns = self._run_in_scope("result = [x for x in [1, 2, 3]]")
        self.assertEqual(ns.get("result"), [1, 2, 3])

    def test_iter_builtin_still_works(self):
        """iter() builtin should work (returns wrapped iterator)."""
        ns = self._run_in_scope("result = list(iter([1, 2, 3]))", {"iter": iter, "list": list})
        self.assertEqual(ns.get("result"), [1, 2, 3])


class V008DescriptorFrozenTests(SandboxTestCase):
    """Test that descriptor protocol respects frozen state.

    Property setters and __set__/__delete__ descriptors should be blocked
    when the target object is frozen.
    """

    def _run_in_scope(self, code_str, extra_globals=None):
        """Execute code in sandbox scope via compile/exec."""
        filename = "<sandbox_test>"
        sys.sandbox.add_filename(filename)
        try:
            code = compile(code_str, filename, "exec")
            ns = {"sys": sys}
            if extra_globals:
                ns.update(extra_globals)
            exec(code, ns)
            return ns
        finally:
            sys.sandbox.remove_filename(filename)

    def test_property_setter_blocked_on_frozen(self):
        """Property setter should be blocked on frozen objects."""
        class C:
            def __init__(self):
                self._x = 0

            @property
            def x(self):
                return self._x

            @x.setter
            def x(self, v):
                self._x = v

        obj = C()
        sys.sandbox.freeze(obj)
        sys.sandbox.frozen_mode = True
        try:
            with self.assertRaises(SandboxAttributeError):
                self._run_in_scope("obj.x = 5", {"obj": obj})
        finally:
            sys.sandbox.frozen_mode = False

    def test_property_deleter_blocked_on_frozen(self):
        """Property deleter should be blocked on frozen objects."""
        class C:
            def __init__(self):
                self._x = 0

            @property
            def x(self):
                return self._x

            @x.deleter
            def x(self):
                del self._x

        obj = C()
        obj._x = 5
        sys.sandbox.freeze(obj)
        sys.sandbox.frozen_mode = True
        try:
            with self.assertRaises(SandboxAttributeError):
                self._run_in_scope("del obj.x", {"obj": obj})
        finally:
            sys.sandbox.frozen_mode = False

    def test_custom_descriptor_set_blocked_on_frozen(self):
        """Custom __set__ descriptor should be blocked on frozen objects."""
        class Desc:
            def __get__(self, obj, cls):
                return getattr(obj, '_val', None)

            def __set__(self, obj, value):
                obj._val = value

        class C:
            x = Desc()

        obj = C()
        sys.sandbox.freeze(obj)
        sys.sandbox.frozen_mode = True
        try:
            with self.assertRaises(SandboxAttributeError):
                self._run_in_scope("obj.x = 10", {"obj": obj})
        finally:
            sys.sandbox.frozen_mode = False

    def test_property_setter_works_on_mutable(self):
        """Property setter should work on mutable objects in frozen mode."""
        class C:
            def __init__(self):
                self._x = 0

            @property
            def x(self):
                return self._x

            @x.setter
            def x(self, v):
                self._x = v

        obj = C()
        sys.sandbox.set_mutable(obj, True)
        sys.sandbox.frozen_mode = True
        try:
            self._run_in_scope("obj.x = 5", {"obj": obj})
            self.assertEqual(obj.x, 5)
        finally:
            sys.sandbox.frozen_mode = False


class V009GCBlockedTests(SandboxTestCase):
    """Test that gc module introspection is blocked in sandbox scope.

    gc.get_objects(), gc.get_referrers(), gc.get_referents(), gc.collect(),
    gc.freeze(), and gc.unfreeze() could be used to access or manipulate
    internal state. These should be blocked in sandbox scope.
    """

    def _run_in_scope(self, code_str, extra_globals=None):
        """Execute code in sandbox scope via compile/exec."""
        filename = "<sandbox_test>"
        sys.sandbox.add_filename(filename)
        try:
            code = compile(code_str, filename, "exec")
            ns = {"sys": sys, "gc": gc}
            if extra_globals:
                ns.update(extra_globals)
            exec(code, ns)
            return ns
        finally:
            sys.sandbox.remove_filename(filename)

    def test_gc_get_objects_blocked(self):
        """gc.get_objects() should be blocked in sandbox scope."""
        with self.assertRaises(SandboxSecurityError) as ctx:
            self._run_in_scope("gc.get_objects()")
        self.assertIn("gc.get_objects", str(ctx.exception))

    def test_gc_get_referrers_blocked(self):
        """gc.get_referrers() should be blocked in sandbox scope."""
        with self.assertRaises(SandboxSecurityError) as ctx:
            self._run_in_scope("gc.get_referrers([])")
        self.assertIn("gc.get_referrers", str(ctx.exception))

    def test_gc_get_referents_blocked(self):
        """gc.get_referents() should be blocked in sandbox scope."""
        with self.assertRaises(SandboxSecurityError) as ctx:
            self._run_in_scope("gc.get_referents([])")
        self.assertIn("gc.get_referents", str(ctx.exception))

    def test_gc_collect_blocked(self):
        """gc.collect() should be blocked in sandbox scope."""
        with self.assertRaises(SandboxSecurityError) as ctx:
            self._run_in_scope("gc.collect()")
        self.assertIn("gc.collect", str(ctx.exception))

    def test_gc_freeze_blocked(self):
        """gc.freeze() should be blocked in sandbox scope."""
        with self.assertRaises(SandboxSecurityError) as ctx:
            self._run_in_scope("gc.freeze()")
        self.assertIn("gc.freeze", str(ctx.exception))

    def test_gc_unfreeze_blocked(self):
        """gc.unfreeze() should be blocked in sandbox scope."""
        with self.assertRaises(SandboxSecurityError) as ctx:
            self._run_in_scope("gc.unfreeze()")
        self.assertIn("gc.unfreeze", str(ctx.exception))

    def test_gc_allowed_with_allow_unsafe(self):
        """gc functions should be allowed when allow_unsafe=True."""
        sys.sandbox.allow_unsafe = True
        try:
            ns = self._run_in_scope("result = gc.get_objects()")
            self.assertIsInstance(ns.get("result"), list)
        finally:
            sys.sandbox.allow_unsafe = False

    def test_gc_allowed_outside_scope(self):
        """gc functions should work outside sandbox scope."""
        objs = gc.get_objects()
        self.assertIsInstance(objs, list)


class AllowUnsafePropertyTests(SandboxTestCase):
    """Test the allow_unsafe property functionality."""

    def test_allow_unsafe_default_is_false(self):
        """allow_unsafe should default to False."""
        sys.sandbox.reset()
        self.assertFalse(sys.sandbox.allow_unsafe)

    def test_allow_unsafe_can_be_set(self):
        """allow_unsafe should be settable."""
        sys.sandbox.allow_unsafe = True
        self.assertTrue(sys.sandbox.allow_unsafe)
        sys.sandbox.allow_unsafe = False
        self.assertFalse(sys.sandbox.allow_unsafe)

    def test_allow_unsafe_setting_blocked_from_scope(self):
        """Setting allow_unsafe from scope should raise SandboxSecurityError."""
        filename = "<sandbox_test>"
        sys.sandbox.add_filename(filename)
        try:
            code = compile("sys.sandbox.allow_unsafe = True", filename, "exec")
            with self.assertRaises(SandboxSecurityError):
                exec(code, {"sys": sys})
        finally:
            sys.sandbox.remove_filename(filename)

    def test_allow_unsafe_reset_clears_it(self):
        """reset() should clear allow_unsafe back to False."""
        sys.sandbox.allow_unsafe = True
        sys.sandbox.reset()
        self.assertFalse(sys.sandbox.allow_unsafe)


class GeneratorFrameAccessBlockedTests(SandboxTestCase):
    """Test that generator/coroutine frame access is blocked in sandbox scope.

    Generators, coroutines, and async generators created outside sandbox scope
    could expose their local variables via gi_frame, cr_frame, and ag_frame
    attributes. This would allow sandboxed code to leak information from
    outside the sandbox. These tests verify that frame access is blocked.
    """

    def _run_in_scope(self, code_str, extra_globals=None):
        """Execute code in sandbox scope via compile/exec."""
        filename = "<sandbox_test>"
        sys.sandbox.add_filename(filename)
        try:
            code = compile(code_str, filename, "exec")
            ns = {"sys": sys}
            if extra_globals:
                ns.update(extra_globals)
            exec(code, ns)
            return ns
        finally:
            sys.sandbox.remove_filename(filename)

    def test_generator_gi_frame_blocked_in_scope(self):
        """gi_frame access should be blocked in sandbox scope."""
        # Create generator outside sandbox with secrets
        def gen_with_secrets():
            secret = "SECRET_VALUE"
            yield 1

        gen = gen_with_secrets()
        next(gen)  # Start generator to populate frame

        with self.assertRaises(SandboxSecurityError) as ctx:
            self._run_in_scope("frame = gen.gi_frame", {"gen": gen})
        self.assertIn("frame access", str(ctx.exception).lower())

    def test_coroutine_cr_frame_blocked_in_scope(self):
        """cr_frame access should be blocked in sandbox scope."""
        # Create coroutine outside sandbox
        async def coro_with_secrets():
            secret = "COROUTINE_SECRET"
            return secret

        coro = coro_with_secrets()

        try:
            with self.assertRaises(SandboxSecurityError) as ctx:
                self._run_in_scope("frame = coro.cr_frame", {"coro": coro})
            self.assertIn("frame access", str(ctx.exception).lower())
        finally:
            coro.close()

    def test_async_gen_ag_frame_blocked_in_scope(self):
        """ag_frame access should be blocked in sandbox scope."""
        # Create async generator outside sandbox
        async def async_gen_with_secrets():
            secret = "ASYNC_GEN_SECRET"
            yield 1

        agen = async_gen_with_secrets()

        try:
            with self.assertRaises(SandboxSecurityError) as ctx:
                self._run_in_scope("frame = agen.ag_frame", {"agen": agen})
            self.assertIn("frame access", str(ctx.exception).lower())
        finally:
            # Clean up async generator
            try:
                agen.aclose()
            except:
                pass

    def test_generator_frame_access_allowed_outside_scope(self):
        """gi_frame access should work outside sandbox scope."""
        def gen_with_value():
            value = 42
            yield 1

        gen = gen_with_value()
        next(gen)

        # Access frame outside scope - should work
        frame = gen.gi_frame
        self.assertIsNotNone(frame)
        self.assertEqual(frame.f_locals.get("value"), 42)

    def test_coroutine_frame_access_allowed_outside_scope(self):
        """cr_frame access should work outside sandbox scope."""
        async def coro_with_value():
            value = 123
            return value

        coro = coro_with_value()

        try:
            # Access frame outside scope - should work
            frame = coro.cr_frame
            self.assertIsNotNone(frame)
        finally:
            coro.close()

    def test_async_gen_frame_access_allowed_outside_scope(self):
        """ag_frame access should work outside sandbox scope."""
        async def agen_with_value():
            value = 999
            yield 1

        agen = agen_with_value()

        try:
            # Access frame outside scope - should work (frame may be None until started)
            frame = agen.ag_frame
            # Frame access succeeds (no exception), that's the test
        finally:
            try:
                agen.aclose()
            except:
                pass

    def test_generator_frame_leak_prevented(self):
        """Verify that secrets cannot be leaked via gi_frame."""
        # This is a more complete test showing the actual attack scenario
        secret_value = "TOP_SECRET_DATA"

        def leaky_generator():
            # This local variable should NOT be accessible from sandbox
            leaked_secret = secret_value
            yield 1
            yield 2

        gen = leaky_generator()
        next(gen)  # Populate frame with locals

        # Attempt to leak the secret from within sandbox
        attack_code = '''
try:
    frame = gen.gi_frame
    leaked = frame.f_locals.get("leaked_secret")
    result = {"leaked": True, "value": leaked}
except SandboxSecurityError:
    result = {"leaked": False}
'''
        ns = self._run_in_scope(attack_code, {"gen": gen})
        self.assertFalse(ns.get("result", {}).get("leaked", True),
                         "Secret was leaked via gi_frame!")


if __name__ == '__main__':
    unittest.main()
