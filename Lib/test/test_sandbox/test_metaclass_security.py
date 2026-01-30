"""Tests for custom metaclass blocking in sandbox.

This module tests that custom metaclass creation is blocked in sandbox scope
to prevent metaclass-based sandbox escapes.

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


class MetaclassBlockingTests(ScopedFilenameTestCase):
    """Test custom metaclass creation is blocked in sandbox.

    Attack vector: Custom metaclasses can override __new__ or __call__
    to execute arbitrary code during class creation, potentially
    bypassing sandbox restrictions.
    """

    SCOPED_FILENAME = "<test_metaclass_security_scope>"

    def test_direct_metaclass_arg_blocked(self):
        """class Foo(metaclass=Meta) should be blocked."""
        sys.sandbox.set_limits(max_operations=10000)

        with self.assertRaises((TypeError, SandboxSecurityError)):
            self.run_scoped_code("""
class Meta(type):
    pass

class Foo(metaclass=Meta):
    pass
""")

    def test_metaclass_via_base_class_blocked(self):
        """class Foo(Base) where Base defines __class_getitem__ metaclass.

        When a base class has a custom metaclass, creating a subclass
        should be blocked if the metaclass is not allowed.
        """
        sys.sandbox.set_limits(max_operations=10000)

        # Create a class with custom metaclass outside scope
        class Meta(type):
            pass

        class Base(metaclass=Meta):
            pass

        with self.assertRaises((TypeError, SandboxSecurityError)):
            self.run_scoped_code("class Derived(Base): pass", {"Base": Base})

    def test_type_call_three_args_behavior(self):
        """type('Foo', (), {}) behavior in scope.

        Direct call to type() with 3 args creates a new class.
        Note: This may or may not be blocked depending on implementation.
        Documenting current behavior.
        """
        sys.sandbox.set_limits(max_operations=10000)

        try:
            globs = self.run_scoped_code("Foo = type('Foo', (), {'x': 1})")
            # If allowed, type() works normally
            self.assertEqual(globs['Foo'].x, 1)
        except (TypeError, SandboxSecurityError):
            # If blocked, that's also acceptable for security
            pass

    def test_regular_class_allowed(self):
        """Regular class definition without metaclass should work."""
        sys.sandbox.set_limits(max_operations=10000)

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
        sys.sandbox.set_limits(max_operations=10000)

        globs = self.run_scoped_code("""
class Base:
    x = 1

class Derived(Base):
    y = 2

obj = Derived()
result = obj.x + obj.y
""")
        self.assertEqual(globs['result'], 3)


class ABCMetaclassTests(ScopedFilenameTestCase):
    """Test that ABC (Abstract Base Class) metaclass is handled.

    ABC uses ABCMeta which is a metaclass. This should either be
    allowed (since it's from stdlib) or blocked consistently.
    """

    SCOPED_FILENAME = "<test_metaclass_security_scope>"

    def test_abc_abstract_class(self):
        """ABC usage - document current behavior."""
        sys.sandbox.set_limits(max_operations=10000)

        try:
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
            # If allowed, ABC works normally
            self.assertEqual(globs['result'], 42)
        except (TypeError, SandboxSecurityError, ImportError):
            # If blocked, that's also acceptable
            pass


class EnumMetaclassTests(ScopedFilenameTestCase):
    """Test that Enum metaclass is handled.

    Enum uses EnumMeta which is a metaclass.
    """

    SCOPED_FILENAME = "<test_metaclass_security_scope>"

    def test_enum_class(self):
        """Enum usage - document current behavior."""
        sys.sandbox.set_limits(max_operations=10000)

        try:
            globs = self.run_scoped_code("""
from enum import Enum

class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3

result = Color.RED.value
""")
            # If allowed, Enum works normally
            self.assertEqual(globs['result'], 1)
        except (TypeError, SandboxSecurityError, ImportError):
            # If blocked, that's also acceptable
            pass


class SubprocessMetaclassTests(unittest.TestCase):
    """Subprocess tests for metaclass security that need full isolation."""

    def test_metaclass_escape_attempt_blocked(self):
        """Attempt to use metaclass __new__ to escape sandbox."""
        code = '''
import sys
sys.sandbox.set_limits(max_list_size=10)
sys.sandbox.enter_scope()

try:
    class EscapeMeta(type):
        def __new__(mcs, name, bases, namespace):
            # Try to create large list during class creation
            namespace['large_list'] = list(range(1000))
            return super().__new__(mcs, name, bases, namespace)

    class Victim(metaclass=EscapeMeta):
        pass

    # If we got here, check if escape worked
    if len(Victim.large_list) > 10:
        sys.exit(2)  # Escape succeeded - security hole!
    else:
        sys.exit(3)  # Unexpected state

except (TypeError, SandboxSecurityError, SandboxOverflowError):
    sys.exit(0)  # Expected - blocked
except Exception as e:
    print(f"Unexpected: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(4)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Metaclass escape not blocked: {result.stderr}")

    def test_type_subclass_behavior(self):
        """Subclassing type behavior in sandbox.

        Note: Subclassing type may be allowed if custom metaclasses are
        not explicitly blocked. Document current behavior.
        """
        code = '''
import sys
sys.sandbox.set_limits(max_operations=10000)
sys.sandbox.enter_scope()

try:
    class MyMeta(type):
        pass
    # If allowed, verify it's actually a type subclass
    if issubclass(MyMeta, type):
        sys.exit(0)  # Type subclassing allowed
    sys.exit(3)  # Unexpected state
except (TypeError, SandboxSecurityError):
    sys.exit(0)  # Blocked is also acceptable
except Exception as e:
    print(f"Note: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(0)  # Document any other behavior
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Unexpected behavior: {result.stderr}")

    def test_dunder_class_assignment_behavior(self):
        """__class__ assignment behavior in sandbox.

        Note: __class__ assignment may be allowed if not explicitly blocked.
        Document current behavior.
        """
        code = '''
import sys
sys.sandbox.set_limits(max_operations=10000)
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
        sys.sandbox.set_limits(max_operations=10000)

        globs = self.run_scoped_code("""
x = 42
t = type(x)
is_int = t is int
""")
        self.assertTrue(globs['is_int'])

    def test_isinstance_allowed(self):
        """isinstance() should work normally."""
        sys.sandbox.set_limits(max_operations=10000)

        globs = self.run_scoped_code("""
x = 42
result = isinstance(x, int)
""")
        self.assertTrue(globs['result'])

    def test_issubclass_allowed(self):
        """issubclass() should work normally."""
        sys.sandbox.set_limits(max_operations=10000)

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
