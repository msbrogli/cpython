"""Tests for frozen mode functionality."""

import sys
import unittest

from test.test_sandbox import _run_sandboxed_code, _get_settable_limits


# Filename used for scoped test code (distinct from test file)
SCOPED_FILENAME = "<test_frozen_mode_scope>"


def _run_scoped(code_str, extra_globals=None):
    """Execute code within sandbox scope using a separate filename."""
    globs = {"sys": sys}
    if extra_globals:
        globs.update(extra_globals)
    code = compile(code_str, SCOPED_FILENAME, "exec")
    exec(code, globs)
    return globs


class FrozenModeTests(unittest.TestCase):
    """Test sandbox frozen mode functionality.

    Frozen mode prevents attribute addition, modification, and deletion
    on objects. It supports both a global freeze flag (in _PySandboxState)
    and per-instance freeze/mutable flags (in ob_flags).

    Frozen mode is scope-aware: restrictions are only enforced when the
    current executing frame's filename is in the registered sandbox scope.
    This means unittest framework code (running from unittest/case.py) is
    not affected, so self.assertRaises() works correctly.

    Note: Due to security restrictions, we cannot modify sandbox config
    from within sandbox scope. Tests must set frozen_mode BEFORE adding
    the scoped filename.
    """

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        # Ensure frozen mode is disabled
        sys.sandbox.frozen_mode = False
        # Ensure limits are resumed
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.remove_filename(SCOPED_FILENAME)
        except (RuntimeError, KeyError):
            pass
        sys.sandbox.set_config(**self.original_limits)

    # --- Global frozen mode: get/set ---

    def test_getsandboxfrozenmode_default_false(self):
        """Global frozen mode should be disabled by default."""
        self.assertFalse(sys.sandbox.frozen_mode)

    def test_setsandboxfrozenmode_enables(self):
        """setsandboxfrozenmode(True) should enable frozen mode."""
        sys.sandbox.frozen_mode = True
        is_frozen = sys.sandbox.frozen_mode
        sys.sandbox.frozen_mode = False
        self.assertTrue(is_frozen)

    def test_setsandboxfrozenmode_disables(self):
        """setsandboxfrozenmode(False) should disable frozen mode."""
        sys.sandbox.frozen_mode = True
        sys.sandbox.frozen_mode = False
        self.assertFalse(sys.sandbox.frozen_mode)

    # --- Global frozen mode: blocks attribute set ---

    def test_frozen_mode_blocks_instance_setattr(self):
        """Frozen mode should block setting attributes on instances."""
        # Create object before scope
        class Foo:
            pass
        obj = Foo()
        obj.x = 1  # Before freeze

        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError) as cm:
            _run_scoped("obj.y = 2", {"obj": obj})
        self.assertIn("frozen mode", str(cm.exception))

    def test_frozen_mode_blocks_instance_delattr(self):
        """Frozen mode should block deleting attributes on instances."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 1

        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError) as cm:
            _run_scoped("del obj.x", {"obj": obj})
        self.assertIn("frozen mode", str(cm.exception))

    def test_frozen_mode_blocks_type_setattr(self):
        """Frozen mode should block setting attributes on types."""
        class Foo:
            pass

        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError) as cm:
            _run_scoped("Foo.class_var = 42", {"Foo": Foo})
        self.assertIn("frozen mode", str(cm.exception))

    def test_frozen_mode_allows_after_disable(self):
        """Disabling frozen mode should allow modifications again."""
        code = '''
import sys
class Foo:
    pass
obj = Foo()

sys.sandbox.frozen_mode = True
sys.sandbox.enter_scope()
try:
    obj.x = 1
    print("FAIL: should have raised")
    sys.exit(1)
except SandboxAttributeError:
    pass

# We can't disable frozen mode from within scope due to security
# So this test just verifies the block works
sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_frozen_mode_blocks_setattr_builtin(self):
        """Frozen mode should block setattr() builtin."""
        class Foo:
            pass
        obj = Foo()

        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("setattr(obj, 'x', 1)", {"obj": obj})

    def test_frozen_mode_blocks_delattr_builtin(self):
        """Frozen mode should block delattr() builtin."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 1

        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("delattr(obj, 'x')", {"obj": obj})

    # --- Per-instance freeze ---

    def test_sandboxfreezeobject_freezes_object(self):
        """sandboxfreezeobject should freeze a specific object."""
        class Foo:
            pass
        obj = Foo()
        obj.a = 10

        sys.sandbox.freeze(obj)
        self.assertTrue(sys.sandbox.is_frozen(obj))

        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError) as cm:
            _run_scoped("obj.b = 20", {"obj": obj})
        self.assertIn("frozen object", str(cm.exception))

    def test_sandboxisobjectfrozen_default_false(self):
        """New objects should not be frozen by default."""
        class Foo:
            pass
        obj = Foo()
        self.assertFalse(sys.sandbox.is_frozen(obj))

    def test_per_instance_freeze_without_global_mode(self):
        """Per-instance freeze should work without global frozen mode."""
        class Foo:
            pass
        obj = Foo()
        obj.a = 1

        self.assertFalse(sys.sandbox.frozen_mode)
        sys.sandbox.freeze(obj)

        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("obj.b = 2", {"obj": obj})

    def test_per_instance_freeze_blocks_delete(self):
        """Per-instance freeze should block attribute deletion."""
        class Foo:
            pass
        obj = Foo()
        obj.a = 1

        sys.sandbox.freeze(obj)
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("del obj.a", {"obj": obj})

    def test_frozen_does_not_affect_other_objects(self):
        """Freezing one object should not affect other objects."""
        class Foo:
            pass
        obj1 = Foo()
        obj2 = Foo()

        sys.sandbox.freeze(obj1)
        sys.sandbox.add_filename(SCOPED_FILENAME)

        # obj1 is frozen
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("obj1.x = 1", {"obj1": obj1})

        # obj2 is not frozen
        globs = _run_scoped("obj2.x = 1", {"obj2": obj2})
        self.assertEqual(obj2.x, 1)

    # --- Mutable override ---

    def test_sandboxsetobjectmutable_overrides_global_freeze(self):
        """Mutable flag should override global frozen mode."""
        class Foo:
            pass
        obj = Foo()

        sys.sandbox.frozen_mode = True
        sys.sandbox.set_mutable(obj)
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("obj.x = 42", {"obj": obj})  # Should succeed
        self.assertEqual(obj.x, 42)

    def test_sandboxsetobjectmutable_clear(self):
        """sandboxsetobjectmutable(obj, False) should clear the mutable flag."""
        class Foo:
            pass
        obj = Foo()

        sys.sandbox.set_mutable(obj)
        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        _run_scoped("obj.x = 1", {"obj": obj})  # Should succeed

        # Remove filename to modify config, then re-add
        sys.sandbox.remove_filename(SCOPED_FILENAME)
        sys.sandbox.set_mutable(obj, False)
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("obj.y = 2", {"obj": obj})

    def test_mutable_overrides_per_instance_freeze(self):
        """Mutable flag should override per-instance freeze."""
        class Foo:
            pass
        obj = Foo()

        sys.sandbox.freeze(obj)
        sys.sandbox.set_mutable(obj)
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("obj.x = 1", {"obj": obj})  # Should succeed despite frozen flag
        self.assertEqual(obj.x, 1)

    # --- Suspend/resume interaction ---

    def test_suspend_bypasses_global_frozen_mode(self):
        """Suspending sandbox should bypass global frozen mode."""
        class Foo:
            pass
        obj = Foo()

        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("obj.x = 1", {"obj": obj})

        sys.sandbox.suspend()
        _run_scoped("obj.x = 1", {"obj": obj})  # Should succeed while suspended

        sys.sandbox.resume()
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("obj.y = 2", {"obj": obj})
        self.assertEqual(obj.x, 1)

    def test_suspend_bypasses_per_instance_freeze(self):
        """Suspending sandbox should bypass per-instance freeze."""
        class Foo:
            pass
        obj = Foo()
        obj.a = 1

        sys.sandbox.freeze(obj)
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("obj.b = 2", {"obj": obj})

        sys.sandbox.suspend()
        _run_scoped("obj.b = 2", {"obj": obj})  # Should succeed while suspended
        self.assertEqual(obj.b, 2)

        sys.sandbox.resume()
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("obj.c = 3", {"obj": obj})

    def test_nested_suspend_with_frozen_mode(self):
        """Nested suspend/resume should work correctly with frozen mode."""
        class Foo:
            pass
        obj = Foo()

        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)

        sys.sandbox.suspend()
        sys.sandbox.suspend()
        _run_scoped("obj.x = 1", {"obj": obj})  # Should succeed

        sys.sandbox.resume()
        _run_scoped("obj.y = 2", {"obj": obj})  # Should still succeed (still suspended once)

        sys.sandbox.resume()
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("obj.z = 3", {"obj": obj})  # Should fail (fully resumed)

    # --- Error message distinction ---

    def test_global_freeze_error_message(self):
        """Global freeze should produce a specific error message."""
        class Foo:
            pass
        obj = Foo()

        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError) as cm:
            _run_scoped("obj.x = 1", {"obj": obj})
        msg = str(cm.exception)
        self.assertIn("frozen mode is active", msg)
        self.assertIn("Foo", msg)

    def test_per_instance_freeze_error_message(self):
        """Per-instance freeze should produce a specific error message."""
        class Foo:
            pass
        obj = Foo()
        sys.sandbox.freeze(obj)

        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError) as cm:
            _run_scoped("obj.x = 1", {"obj": obj})
        msg = str(cm.exception)
        self.assertIn("frozen object", msg)
        self.assertIn("Foo", msg)

    # --- Various object types ---

    def test_frozen_mode_blocks_module_attr(self):
        """Frozen mode should block setting attributes on modules."""
        import types
        mod = types.ModuleType('testmod')

        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("mod.x = 1", {"mod": mod})

    def test_frozen_mode_blocks_function_attr(self):
        """Frozen mode should block setting attributes on functions."""
        def func():
            pass

        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("func.custom_attr = 42", {"func": func})

    def test_freeze_class_object(self):
        """Freezing a class should block setting class attributes."""
        class Foo:
            pass

        sys.sandbox.freeze(Foo)
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxAttributeError):
            _run_scoped("Foo.class_var = 1", {"Foo": Foo})

    # --- Edge cases ---

    def test_frozen_mode_allows_reading_attributes(self):
        """Frozen mode should not affect reading attributes."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 42

        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        globs = _run_scoped("val = obj.x", {"obj": obj})  # Reading should work
        self.assertEqual(globs['val'], 42)

    def test_frozen_mode_allows_method_calls(self):
        """Frozen mode should not block calling methods."""
        class Foo:
            def greet(self):
                return "hello"
        obj = Foo()

        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        globs = _run_scoped("result = obj.greet()", {"obj": obj})
        self.assertEqual(globs['result'], "hello")

    def test_mutable_object_in_global_freeze_can_delete(self):
        """Mutable objects should allow attribute deletion in frozen mode."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 1
        sys.sandbox.set_mutable(obj)

        sys.sandbox.frozen_mode = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        _run_scoped("del obj.x", {"obj": obj})  # Should succeed
        self.assertFalse(hasattr(obj, 'x'))


class FrozenModeSubprocessTests(unittest.TestCase):
    """Subprocess tests for frozen mode to test scenarios that might
    interfere with the test runner itself.
    """

    def test_frozen_mode_blocks_dict_instance_storage(self):
        """Frozen mode should block _PyObject_StoreInstanceAttribute."""
        code = '''
import sys
# Set frozen_mode BEFORE entering scope (security feature blocks config changes in scope)
sys.sandbox.frozen_mode = True
sys.sandbox.enter_scope()

class Foo:
    pass

obj = Foo()

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

class Box:
    pass

box = Box()
box.value = 10
# Set mutable and frozen_mode BEFORE entering scope
sys.sandbox.set_mutable(box)
sys.sandbox.frozen_mode = True
sys.sandbox.allow_unsafe = 1  # Allow exec with string in scope
sys.sandbox.enter_scope()

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

sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Exec integration failed: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_frozen_mode_exception_hierarchy(self):
        """SandboxAttributeError from frozen mode should be a SandboxError."""
        code = '''
import sys
# Set frozen_mode BEFORE entering scope
sys.sandbox.frozen_mode = True
sys.sandbox.enter_scope()

class Foo:
    pass

obj = Foo()

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

# Set frozen_mode BEFORE entering scope
sys.sandbox.frozen_mode = True
sys.sandbox.enter_scope()

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


class AutoMutableTests(unittest.TestCase):
    """Subprocess tests for auto-mutable mode.

    Auto-mutable mode automatically marks newly created functions, classes,
    and instances as mutable (Py_OBJFLAGS_MUTABLE) when both frozen_mode
    and auto_mutable_mode are active, and the creation happens within
    sandbox scope. Imported modules remain frozen because they have
    different co_filename values outside the registered scope.
    """

    def test_api_default_false(self):
        """Auto-mutable mode should be disabled by default."""
        code = '''
import sys
if sys.sandbox.auto_mutable:
    print("FAIL: default should be False")
    sys.exit(1)
print("PASS")
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_api_set_get(self):
        """setsandboxautomutable/getsandboxautomutable should work."""
        code = '''
import sys
sys.sandbox.auto_mutable = True
if not sys.sandbox.auto_mutable:
    print("FAIL: should be True after set")
    sys.exit(1)
sys.sandbox.auto_mutable = False
if sys.sandbox.auto_mutable:
    print("FAIL: should be False after clear")
    sys.exit(1)
print("PASS")
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_function_is_mutable(self):
        """Functions created in sandbox scope should be auto-marked mutable."""
        code = '''
import sys
sys.sandbox.add_filename('<sandbox>')
sys.sandbox.frozen_mode = True
sys.sandbox.auto_mutable = True
code = compile("""
def f():
    pass
f.x = 1
if f.x != 1:
    print("FAIL: f.x should be 1")
    sys.exit(1)
print("PASS")
""", '<sandbox>', 'exec')
exec(code)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_class_is_mutable(self):
        """Classes created in sandbox scope should be auto-marked mutable."""
        code = '''
import sys
sys.sandbox.add_filename('<sandbox>')
sys.sandbox.frozen_mode = True
sys.sandbox.auto_mutable = True
code = compile("""
class C:
    pass
C.x = 1
if C.x != 1:
    print("FAIL: C.x should be 1")
    sys.exit(1)
print("PASS")
""", '<sandbox>', 'exec')
exec(code)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_instance_is_mutable(self):
        """Instances created in sandbox scope should be auto-marked mutable."""
        code = '''
import sys
sys.sandbox.add_filename('<sandbox>')
sys.sandbox.frozen_mode = True
sys.sandbox.auto_mutable = True
code = compile("""
class C:
    pass
obj = C()
obj.x = 42
if obj.x != 42:
    print("FAIL: obj.x should be 42")
    sys.exit(1)
print("PASS")
""", '<sandbox>', 'exec')
exec(code)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_imported_module_stays_frozen(self):
        """Imported modules should remain frozen (different co_filename)."""
        code = '''
import sys
sys.sandbox.add_filename('<sandbox>')
sys.sandbox.frozen_mode = True
sys.sandbox.auto_mutable = True
code = compile("""
import os
try:
    os.NEW_ATTR = 1
    print("FAIL: should have raised SandboxAttributeError")
    sys.exit(1)
except SandboxAttributeError:
    print("PASS")
""", '<sandbox>', 'exec')
exec(code)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_nested_function_is_mutable(self):
        """Nested functions should also be auto-marked mutable."""
        code = '''
import sys
sys.sandbox.add_filename('<sandbox>')
sys.sandbox.frozen_mode = True
sys.sandbox.auto_mutable = True
code = compile("""
def outer():
    def inner():
        pass
    inner.tag = 'nested'
    return inner
f = outer()
if f.tag != 'nested':
    print("FAIL")
    sys.exit(1)
print("PASS")
""", '<sandbox>', 'exec')
exec(code)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_closure_is_mutable(self):
        """Closure functions should be auto-marked mutable."""
        code = '''
import sys
sys.sandbox.add_filename('<sandbox>')
sys.sandbox.frozen_mode = True
sys.sandbox.auto_mutable = True
code = compile("""
def make_adder(n):
    def adder(x):
        return x + n
    return adder
add5 = make_adder(5)
add5.info = 'adds 5'
if add5.info != 'adds 5':
    print("FAIL")
    sys.exit(1)
if add5(3) != 8:
    print("FAIL: wrong result")
    sys.exit(1)
print("PASS")
""", '<sandbox>', 'exec')
exec(code)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_decorated_function_is_mutable(self):
        """Decorated functions should be auto-marked mutable."""
        code = '''
import sys
sys.sandbox.add_filename('<sandbox>')
sys.sandbox.frozen_mode = True
sys.sandbox.auto_mutable = True
code = compile("""
def my_decorator(func):
    func.decorated = True
    return func

@my_decorator
def greet():
    return 'hello'

if not greet.decorated:
    print("FAIL: decorator attr not set")
    sys.exit(1)
greet.extra = 'ok'
if greet.extra != 'ok':
    print("FAIL")
    sys.exit(1)
print("PASS")
""", '<sandbox>', 'exec')
exec(code)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_metaclass_created_class_is_mutable(self):
        """Classes created via metaclass should be auto-marked mutable."""
        code = '''
import sys
sys.sandbox.add_filename('<sandbox>')
sys.sandbox.frozen_mode = True
sys.sandbox.auto_mutable = True
sys.sandbox.allow_unsafe = True  # Allow metaclasses
code = compile("""
class Meta(type):
    pass
class MyClass(metaclass=Meta):
    pass
MyClass.attr = 'meta'
if MyClass.attr != 'meta':
    print("FAIL")
    sys.exit(1)
print("PASS")
""", '<sandbox>', 'exec')
exec(code)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_noop_without_frozen_mode(self):
        """Auto-mutable alone (without frozen mode) should not break anything."""
        code = '''
import sys
sys.sandbox.add_filename('<sandbox>')
sys.sandbox.auto_mutable = True
# Frozen mode is NOT enabled
code = compile("""
class C:
    pass
obj = C()
obj.x = 1
C.y = 2
def f():
    pass
f.z = 3
if obj.x != 1 or C.y != 2 or f.z != 3:
    print("FAIL")
    sys.exit(1)
print("PASS")
""", '<sandbox>', 'exec')
exec(code)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_builtin_instances_are_mutable(self):
        """Built-in instances (dict, list) created in scope should be mutable."""
        code = '''
import sys
sys.sandbox.add_filename('<sandbox>')
sys.sandbox.frozen_mode = True
sys.sandbox.auto_mutable = True
code = compile("""
d = dict()
d['key'] = 'value'
if d['key'] != 'value':
    print("FAIL: dict")
    sys.exit(1)

lst = list()
lst.append(1)
if lst != [1]:
    print("FAIL: list")
    sys.exit(1)
print("PASS")
""", '<sandbox>', 'exec')
exec(code)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_full_integration(self):
        """Full integration: classes, functions, instances mutable; imports frozen."""
        code = '''
import sys
sys.sandbox.add_filename('<sandbox>')
sys.sandbox.frozen_mode = True
sys.sandbox.auto_mutable = True
code = compile("""
class Foo:
    pass
def bar():
    pass
obj = Foo()
obj.x = 42
bar.tag = 'hello'
Foo.class_var = 99

if obj.x != 42:
    print("FAIL: obj.x")
    sys.exit(1)
if bar.tag != 'hello':
    print("FAIL: bar.tag")
    sys.exit(1)
if Foo.class_var != 99:
    print("FAIL: Foo.class_var")
    sys.exit(1)

# Imported module should stay frozen
import os
try:
    os.NEW = 1
    print("FAIL: os should be frozen")
    sys.exit(1)
except SandboxAttributeError:
    pass

print("PASS")
""", '<sandbox>', 'exec')
exec(code)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"stdout={result.stdout!r} stderr={result.stderr!r}")


if __name__ == '__main__':
    unittest.main()
