"""Tests for frozen mode functionality."""

import sys
import unittest

from test.test_sandbox import _run_sandboxed_code, _get_settable_limits


class FrozenModeTests(unittest.TestCase):
    """Test sandbox frozen mode functionality.

    Frozen mode prevents attribute addition, modification, and deletion
    on objects. It supports both a global freeze flag (in _PySandboxState)
    and per-instance freeze/mutable flags (in ob_flags).

    Frozen mode is scope-aware: restrictions are only enforced when the
    current executing frame's filename is in the registered sandbox scope.
    This means unittest framework code (running from unittest/case.py) is
    not affected, so self.assertRaises() works correctly.
    """

    def setUp(self):
        self.original_limits = _get_settable_limits()
        sys.entersandboxscope()

    def tearDown(self):
        # Ensure frozen mode is disabled
        sys.setsandboxfrozenmode(False)
        # Ensure limits are resumed
        while sys.issandboxsuspended():
            sys.resumesandboxlimits()
        sys.setsandboxlimits(**self.original_limits)
        # Exit sandbox scope
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass

    # --- Global frozen mode: get/set ---

    def test_getsandboxfrozenmode_default_false(self):
        """Global frozen mode should be disabled by default."""
        self.assertFalse(sys.getsandboxfrozenmode())

    def test_setsandboxfrozenmode_enables(self):
        """setsandboxfrozenmode(True) should enable frozen mode."""
        sys.setsandboxfrozenmode(True)
        is_frozen = sys.getsandboxfrozenmode()
        sys.setsandboxfrozenmode(False)
        self.assertTrue(is_frozen)

    def test_setsandboxfrozenmode_disables(self):
        """setsandboxfrozenmode(False) should disable frozen mode."""
        sys.setsandboxfrozenmode(True)
        sys.setsandboxfrozenmode(False)
        self.assertFalse(sys.getsandboxfrozenmode())

    # --- Global frozen mode: blocks attribute set ---

    def test_frozen_mode_blocks_instance_setattr(self):
        """Frozen mode should block setting attributes on instances."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 1  # Before freeze

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError) as cm:
            obj.y = 2
        self.assertIn("frozen mode", str(cm.exception))

    def test_frozen_mode_blocks_instance_delattr(self):
        """Frozen mode should block deleting attributes on instances."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 1

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError) as cm:
            del obj.x
        self.assertIn("frozen mode", str(cm.exception))

    def test_frozen_mode_blocks_type_setattr(self):
        """Frozen mode should block setting attributes on types."""
        class Foo:
            pass

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError) as cm:
            Foo.class_var = 42
        self.assertIn("frozen mode", str(cm.exception))

    def test_frozen_mode_allows_after_disable(self):
        """Disabling frozen mode should allow modifications again."""
        class Foo:
            pass
        obj = Foo()

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError):
            obj.x = 1

        sys.setsandboxfrozenmode(False)
        obj.x = 1  # Should succeed now
        self.assertEqual(obj.x, 1)

    def test_frozen_mode_blocks_setattr_builtin(self):
        """Frozen mode should block setattr() builtin."""
        class Foo:
            pass
        obj = Foo()

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError):
            setattr(obj, 'x', 1)

    def test_frozen_mode_blocks_delattr_builtin(self):
        """Frozen mode should block delattr() builtin."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 1

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError):
            delattr(obj, 'x')

    # --- Per-instance freeze ---

    def test_sandboxfreezeobject_freezes_object(self):
        """sandboxfreezeobject should freeze a specific object."""
        class Foo:
            pass
        obj = Foo()
        obj.a = 10

        sys.sandboxfreezeobject(obj)
        self.assertTrue(sys.sandboxisobjectfrozen(obj))

        with self.assertRaises(SandboxAttributeError) as cm:
            obj.b = 20
        self.assertIn("frozen object", str(cm.exception))

    def test_sandboxisobjectfrozen_default_false(self):
        """New objects should not be frozen by default."""
        class Foo:
            pass
        obj = Foo()
        self.assertFalse(sys.sandboxisobjectfrozen(obj))

    def test_per_instance_freeze_without_global_mode(self):
        """Per-instance freeze should work without global frozen mode."""
        class Foo:
            pass
        obj = Foo()
        obj.a = 1

        self.assertFalse(sys.getsandboxfrozenmode())
        sys.sandboxfreezeobject(obj)

        with self.assertRaises(SandboxAttributeError):
            obj.b = 2

    def test_per_instance_freeze_blocks_delete(self):
        """Per-instance freeze should block attribute deletion."""
        class Foo:
            pass
        obj = Foo()
        obj.a = 1

        sys.sandboxfreezeobject(obj)
        with self.assertRaises(SandboxAttributeError):
            del obj.a

    def test_frozen_does_not_affect_other_objects(self):
        """Freezing one object should not affect other objects."""
        class Foo:
            pass
        obj1 = Foo()
        obj2 = Foo()

        sys.sandboxfreezeobject(obj1)

        # obj1 is frozen
        with self.assertRaises(SandboxAttributeError):
            obj1.x = 1

        # obj2 is not frozen
        obj2.x = 1
        self.assertEqual(obj2.x, 1)

    # --- Mutable override ---

    def test_sandboxsetobjectmutable_overrides_global_freeze(self):
        """Mutable flag should override global frozen mode."""
        class Foo:
            pass
        obj = Foo()

        sys.setsandboxfrozenmode(True)
        sys.sandboxsetobjectmutable(obj)

        obj.x = 42  # Should succeed
        self.assertEqual(obj.x, 42)

    def test_sandboxsetobjectmutable_clear(self):
        """sandboxsetobjectmutable(obj, False) should clear the mutable flag."""
        class Foo:
            pass
        obj = Foo()

        sys.sandboxsetobjectmutable(obj)
        sys.setsandboxfrozenmode(True)
        obj.x = 1  # Should succeed

        sys.sandboxsetobjectmutable(obj, False)
        with self.assertRaises(SandboxAttributeError):
            obj.y = 2

    def test_mutable_overrides_per_instance_freeze(self):
        """Mutable flag should override per-instance freeze."""
        class Foo:
            pass
        obj = Foo()

        sys.sandboxfreezeobject(obj)
        sys.sandboxsetobjectmutable(obj)

        obj.x = 1  # Should succeed despite frozen flag
        self.assertEqual(obj.x, 1)

    # --- Suspend/resume interaction ---

    def test_suspend_bypasses_global_frozen_mode(self):
        """Suspending sandbox should bypass global frozen mode."""
        class Foo:
            pass
        obj = Foo()

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError):
            obj.x = 1

        sys.suspendsandboxlimits()
        obj.x = 1  # Should succeed while suspended

        sys.resumesandboxlimits()
        with self.assertRaises(SandboxAttributeError):
            obj.y = 2
        self.assertEqual(obj.x, 1)

    def test_suspend_bypasses_per_instance_freeze(self):
        """Suspending sandbox should bypass per-instance freeze."""
        class Foo:
            pass
        obj = Foo()
        obj.a = 1

        sys.sandboxfreezeobject(obj)
        with self.assertRaises(SandboxAttributeError):
            obj.b = 2

        sys.suspendsandboxlimits()
        obj.b = 2  # Should succeed while suspended
        self.assertEqual(obj.b, 2)

        sys.resumesandboxlimits()
        with self.assertRaises(SandboxAttributeError):
            obj.c = 3

    def test_nested_suspend_with_frozen_mode(self):
        """Nested suspend/resume should work correctly with frozen mode."""
        class Foo:
            pass
        obj = Foo()

        sys.setsandboxfrozenmode(True)

        sys.suspendsandboxlimits()
        sys.suspendsandboxlimits()
        obj.x = 1  # Should succeed

        sys.resumesandboxlimits()
        obj.y = 2  # Should still succeed (still suspended once)

        sys.resumesandboxlimits()
        with self.assertRaises(SandboxAttributeError):
            obj.z = 3  # Should fail (fully resumed)

    # --- Error message distinction ---

    def test_global_freeze_error_message(self):
        """Global freeze should produce a specific error message."""
        class Foo:
            pass
        obj = Foo()

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError) as cm:
            obj.x = 1
        msg = str(cm.exception)
        self.assertIn("frozen mode is active", msg)
        self.assertIn("Foo", msg)

    def test_per_instance_freeze_error_message(self):
        """Per-instance freeze should produce a specific error message."""
        class Foo:
            pass
        obj = Foo()
        sys.sandboxfreezeobject(obj)

        with self.assertRaises(SandboxAttributeError) as cm:
            obj.x = 1
        msg = str(cm.exception)
        self.assertIn("frozen object", msg)
        self.assertIn("Foo", msg)

    # --- Various object types ---

    def test_frozen_mode_blocks_module_attr(self):
        """Frozen mode should block setting attributes on modules."""
        import types
        mod = types.ModuleType('testmod')

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError):
            mod.x = 1

    def test_frozen_mode_blocks_function_attr(self):
        """Frozen mode should block setting attributes on functions."""
        def func():
            pass

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError):
            func.custom_attr = 42

    def test_freeze_class_object(self):
        """Freezing a class should block setting class attributes."""
        class Foo:
            pass

        sys.sandboxfreezeobject(Foo)
        with self.assertRaises(SandboxAttributeError):
            Foo.class_var = 1

    # --- Edge cases ---

    def test_frozen_mode_allows_reading_attributes(self):
        """Frozen mode should not affect reading attributes."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 42

        sys.setsandboxfrozenmode(True)
        val = obj.x  # Reading should work
        self.assertEqual(val, 42)

    def test_frozen_mode_allows_method_calls(self):
        """Frozen mode should not block calling methods."""
        class Foo:
            def greet(self):
                return "hello"
        obj = Foo()

        sys.setsandboxfrozenmode(True)
        result = obj.greet()
        self.assertEqual(result, "hello")

    def test_mutable_object_in_global_freeze_can_delete(self):
        """Mutable objects should allow attribute deletion in frozen mode."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 1
        sys.sandboxsetobjectmutable(obj)

        sys.setsandboxfrozenmode(True)
        del obj.x  # Should succeed
        self.assertFalse(hasattr(obj, 'x'))


class FrozenModeSubprocessTests(unittest.TestCase):
    """Subprocess tests for frozen mode to test scenarios that might
    interfere with the test runner itself.
    """

    def test_frozen_mode_blocks_dict_instance_storage(self):
        """Frozen mode should block _PyObject_StoreInstanceAttribute."""
        code = '''
import sys
sys.entersandboxscope()

class Foo:
    pass

obj = Foo()
sys.setsandboxfrozenmode(True)

try:
    obj.x = 1
    print("FAIL: should have raised")
    sys.exit(1)
except SandboxAttributeError as e:
    if "frozen mode" in str(e):
        print("PASS")
        sys.exit(0)
    print(f"FAIL: wrong message: {e}")
    sys.exit(1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Dict storage not blocked: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_frozen_mode_integration_with_exec(self):
        """Frozen mode should work in exec'd code."""
        code = '''
import sys
sys.entersandboxscope()

class Box:
    pass

box = Box()
box.value = 10
sys.sandboxsetobjectmutable(box)

sys.setsandboxfrozenmode(True)

# exec'd code should also be affected by frozen mode
exec("""
try:
    # New object - not mutable, should be blocked
    class Dummy:
        pass
    d = Dummy()
    d.x = 1
    print("FAIL")
    sys.exit(1)
except SandboxAttributeError:
    pass

# Mutable object should still work
box.value = 20
if box.value == 20:
    print("PASS")
else:
    print("FAIL: wrong value")
    sys.exit(1)
""")

sys.setsandboxfrozenmode(False)
sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Exec integration failed: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_frozen_mode_exception_hierarchy(self):
        """SandboxAttributeError from frozen mode should be a SandboxError."""
        code = '''
import sys
sys.entersandboxscope()

class Foo:
    pass

obj = Foo()
sys.setsandboxfrozenmode(True)

try:
    obj.x = 1
    sys.exit(1)
except SandboxError:
    # Should be catchable as SandboxError (parent class)
    print("PASS")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Exception hierarchy wrong: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_frozen_mode_with_property_descriptor(self):
        """Frozen mode should block property setters."""
        code = '''
import sys
sys.entersandboxscope()

class Foo:
    def __init__(self):
        self._x = 0

    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, value):
        self._x = value

obj = Foo()
obj.x = 10  # Works before freeze

sys.setsandboxfrozenmode(True)
try:
    obj.x = 20  # Should be blocked
    print("FAIL")
    sys.exit(1)
except SandboxAttributeError:
    print("PASS")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Property setter not blocked: stdout={result.stdout!r} stderr={result.stderr!r}")


if __name__ == '__main__':
    unittest.main()
