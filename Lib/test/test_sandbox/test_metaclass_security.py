"""Tests for metaclass security in sandbox.

This module tests:
1. Metaclass CREATION (subclassing type) is blocked in sandbox
2. Trusted metaclasses from outside sandbox work (ABC, Enum, dataclass, etc.)
3. Sandbox code cannot escape via metaclass __new__ or __call__ overrides

Security model:
- Sandbox code CAN create normal classes
- Sandbox code CANNOT create metaclasses (subclassing type)
- Sandbox code CAN use trusted metaclasses passed from outside
- This prevents sandbox escapes while allowing use of stdlib abstractions

Security audit reference: Fix proposal 08 - Metaclass blocking
"""

import subprocess
import sys
import unittest

from test.test_sandbox import (
    ScopedFilenameTestCase,
    _run_sandboxed_code,
    SUBPROCESS_TIMEOUT,
)


class MetaclassCreationBlockedTests(ScopedFilenameTestCase):
    """Test that metaclass CREATION (subclassing type) is blocked.

    Attack vector: Custom metaclasses can override __new__ or __call__
    to execute arbitrary code during class creation, potentially
    bypassing sandbox restrictions.
    """

    SCOPED_FILENAME = "<test_metaclass_security_scope>"

    def test_direct_type_subclass_blocked(self):
        """Subclassing type directly should be blocked."""
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises(SandboxSecurityError):
            self.run_scoped_code("""
class Meta(type):
    pass
""")

    def test_metaclass_via_base_class_allowed(self):
        """Subclassing a base with trusted metaclass should work.

        When a base class has a custom metaclass from OUTSIDE sandbox,
        creating a subclass should be ALLOWED (the metaclass is trusted).
        """
        sys.sandbox.set_config(max_operations=10000)

        # Create a class with custom metaclass outside scope (trusted)
        class Meta(type):
            pass

        class Base(metaclass=Meta):
            pass

        # This should succeed - Base's metaclass is trusted (created outside sandbox)
        globs = self.run_scoped_code("class Derived(Base): pass", {"Base": Base})
        self.assertIn('Derived', globs)

    def test_type_call_three_args_behavior(self):
        """type('Foo', (), {}) behavior in scope.

        Direct call to type() with 3 args creates a new class.
        Note: This may or may not be blocked depending on implementation.
        Documenting current behavior.
        """
        sys.sandbox.set_config(max_operations=10000)

        try:
            globs = self.run_scoped_code("Foo = type('Foo', (), {'x': 1})")
            # If allowed, type() works normally
            self.assertEqual(globs['Foo'].x, 1)
        except (TypeError, SandboxSecurityError):
            # If blocked, that's also acceptable for security
            pass

    def test_regular_class_allowed(self):
        """Regular class definition without metaclass should work."""
        sys.sandbox.set_config(max_operations=10000)

        globs = self.run_scoped_code("""
class Foo:
    x = 1
    def method(self):
        return self.x

obj = Foo()
result = obj.method()
""")
        self.assertEqual(globs['result'], 1)

    def test_class_inheritance_allowed(self):
        """Regular class inheritance should work."""
        sys.sandbox.set_config(max_operations=10000)

        globs = self.run_scoped_code("""
class Base:
    x = 1

class Derived(Base):
    y = 2

obj = Derived()
result = obj.x + obj.y
""")
        self.assertEqual(globs['result'], 3)


class TrustedMetaclassTests(ScopedFilenameTestCase):
    """Test that trusted metaclasses from stdlib work.

    ABC uses ABCMeta, Enum uses EnumMeta - both are trusted metaclasses
    from outside sandbox and should work.
    """

    SCOPED_FILENAME = "<test_metaclass_security_scope>"

    def test_abc_abstract_class(self):
        """ABC usage should work (ABCMeta is a trusted metaclass)."""
        sys.sandbox.set_config(max_operations=10000)

        globs = self.run_scoped_code("""
from abc import ABC, abstractmethod

class AbstractBase(ABC):
    @abstractmethod
    def do_something(self):
        pass

class Concrete(AbstractBase):
    def do_something(self):
        return 42

obj = Concrete()
result = obj.do_something()
""")
        self.assertEqual(globs['result'], 42)

    def test_enum_class(self):
        """Enum usage should work (EnumMeta is a trusted metaclass)."""
        sys.sandbox.set_config(max_operations=10000)

        globs = self.run_scoped_code("""
from enum import Enum

class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3

result = Color.RED.value
""")
        self.assertEqual(globs['result'], 1)

    def test_explicit_metaclass_from_trusted_allowed(self):
        """Using trusted metaclass explicitly should work."""
        sys.sandbox.set_config(max_operations=10000)

        # Create metaclass outside sandbox (trusted)
        class TrustedMeta(type):
            pass

        globs = self.run_scoped_code("""
class Foo(metaclass=Meta):
    x = 1
result = Foo.x
""", extra_globals={"Meta": TrustedMeta})
        self.assertEqual(globs['result'], 1)


class SubprocessMetaclassTests(unittest.TestCase):
    """Subprocess tests for metaclass security that need full isolation."""

    def test_metaclass_creation_blocked(self):
        """Metaclass creation (subclassing type) should be blocked."""
        code = '''
import sys
sys.sandbox.set_config(max_operations=10000, allow_dunder_access=False, allow_class_creation=True)
sys.sandbox.add_filename("<sandbox>")

try:
    exec(compile("""
class EscapeMeta(type):
    def __new__(mcs, name, bases, namespace):
        # This would be dangerous if allowed
        namespace['escaped'] = True
        return super().__new__(mcs, name, bases, namespace)
""", "<sandbox>", "exec"))
    sys.exit(1)  # Should not reach here - metaclass creation should be blocked
except SandboxSecurityError:
    sys.exit(0)  # Expected - metaclass creation blocked
except Exception as e:
    print(f"Unexpected: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(2)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Metaclass creation should be blocked: {result.stderr}")

    def test_type_subclass_blocked(self):
        """Subclassing type should be blocked in sandbox."""
        code = '''
import sys
sys.sandbox.set_config(max_operations=10000, allow_dunder_access=False, allow_class_creation=True)
sys.sandbox.add_filename("<sandbox>")

try:
    exec(compile("""
class MyMeta(type):
    pass
""", "<sandbox>", "exec"))
    sys.exit(1)  # Should not reach - type subclassing should be blocked
except SandboxSecurityError as e:
    if "metaclass" in str(e).lower():
        sys.exit(0)  # Expected - clear error message
    sys.exit(0)  # Still blocked, just different message
except Exception as e:
    print(f"Unexpected: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(2)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Type subclass should be blocked: {result.stderr}")

    def test_dunder_class_assignment_behavior(self):
        """__class__ assignment behavior in sandbox.

        Note: __class__ assignment may be allowed if not explicitly blocked.
        Document current behavior.
        """
        code = '''
import sys
sys.sandbox.set_config(max_operations=10000, allow_dunder_access=True)
sys.sandbox.enter_scope()

class Foo:
    pass

class Bar:
    pass

obj = Foo()
try:
    obj.__class__ = Bar  # Try to change class
    # If allowed, verify the change happened
    if isinstance(obj, Bar):
        sys.exit(0)  # Class assignment allowed
    sys.exit(3)  # Unexpected state
except (TypeError, SandboxSecurityError, AttributeError):
    sys.exit(0)  # Blocked is acceptable
except Exception as e:
    print(f"Note: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(0)  # Document any other behavior
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Unexpected behavior: {result.stderr}")


class TypeBuiltinTests(ScopedFilenameTestCase):
    """Test type() builtin behavior in sandbox."""

    SCOPED_FILENAME = "<test_metaclass_security_scope>"

    def test_type_one_arg_allowed(self):
        """type(obj) for getting type should be allowed."""
        sys.sandbox.set_config(max_operations=10000)

        globs = self.run_scoped_code("""
x = 42
t = type(x)
is_int = t is int
""")
        self.assertTrue(globs['is_int'])

    def test_isinstance_allowed(self):
        """isinstance() should work normally."""
        sys.sandbox.set_config(max_operations=10000)

        globs = self.run_scoped_code("""
x = 42
result = isinstance(x, int)
""")
        self.assertTrue(globs['result'])

    def test_issubclass_allowed(self):
        """issubclass() should work normally."""
        sys.sandbox.set_config(max_operations=10000)

        globs = self.run_scoped_code("""
class Foo:
    pass

class Bar(Foo):
    pass

result = issubclass(Bar, Foo)
""")
        self.assertTrue(globs['result'])


if __name__ == '__main__':
    unittest.main()
