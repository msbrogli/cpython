"""Tests for class creation in sandbox with allow_dunder_access=False.

This module tests the allow_class_creation feature which allows class creation
even when allow_dunder_access=False by whitelisting specific dunders needed
for class body execution.

Security properties tested:
1. Class creation works with allow_class_creation=True (default)
2. Class body dunders are whitelisted (__name__, __module__, __qualname__, etc.)
3. Metaclass CREATION (subclassing type) is blocked
4. Trusted metaclasses from outside sandbox work
5. Introspection dunders are still blocked (__class__, __subclasses__)
"""

import sys
import unittest
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, IntEnum

from test.test_sandbox import (
    ScopedFilenameTestCase,
    _run_sandboxed_code,
    SUBPROCESS_TIMEOUT,
)


class BasicClassCreationTests(ScopedFilenameTestCase):
    """Test basic class creation with allow_dunder_access=False."""

    SCOPED_FILENAME = "<test_class_creation_scope>"

    def setUp(self):
        super().setUp()
        # Set up the typical sandbox configuration
        sys.sandbox.set_config(
            max_operations=10000,
            allow_dunder_access=False,
            allow_class_creation=True,
        )

    def test_simple_class_creation(self):
        """Simple class definition should work."""
        globs = self.run_scoped_code("""
class Foo:
    pass

obj = Foo()
result = True
""")
        self.assertTrue(globs['result'])

    def test_class_with_methods(self):
        """Class with methods should work."""
        globs = self.run_scoped_code("""
class Calculator:
    def add(self, a, b):
        return a + b

calc = Calculator()
result = calc.add(2, 3)
""")
        self.assertEqual(globs['result'], 5)

    def test_class_with_docstring(self):
        """Class with docstring should work."""
        globs = self.run_scoped_code('''
class Documented:
    """This is a documented class."""

    def method(self):
        """This is a documented method."""
        return 42

result = Documented().method()
''')
        self.assertEqual(globs['result'], 42)

    def test_class_with_class_attributes(self):
        """Class with class attributes should work."""
        globs = self.run_scoped_code("""
class Config:
    debug = True
    max_retries = 3

result = Config.debug and Config.max_retries == 3
""")
        self.assertTrue(globs['result'])

    def test_class_with_init(self):
        """Class with __init__ method should work."""
        globs = self.run_scoped_code("""
class Person:
    def __init__(self, name, age):
        self.name = name
        self.age = age

person = Person("Alice", 30)
result = person.name == "Alice" and person.age == 30
""")
        self.assertTrue(globs['result'])

    def test_class_inheritance(self):
        """Class inheritance should work."""
        globs = self.run_scoped_code("""
class Animal:
    def speak(self):
        return "..."

class Dog(Animal):
    def speak(self):
        return "Woof!"

dog = Dog()
result = dog.speak()
""")
        self.assertEqual(globs['result'], "Woof!")

    def test_multiple_inheritance(self):
        """Multiple inheritance should work."""
        globs = self.run_scoped_code("""
class A:
    def method_a(self):
        return "A"

class B:
    def method_b(self):
        return "B"

class C(A, B):
    def method_c(self):
        return "C"

obj = C()
result = obj.method_a() + obj.method_b() + obj.method_c()
""")
        self.assertEqual(globs['result'], "ABC")

    def test_class_with_slots(self):
        """Class with __slots__ should work."""
        globs = self.run_scoped_code("""
class Efficient:
    __slots__ = ('x', 'y')

    def __init__(self, x, y):
        self.x = x
        self.y = y

obj = Efficient(1, 2)
result = obj.x + obj.y
""")
        self.assertEqual(globs['result'], 3)


class ClassAnnotationsTests(ScopedFilenameTestCase):
    """Test class creation with annotations."""

    SCOPED_FILENAME = "<test_class_annotations_scope>"

    def setUp(self):
        super().setUp()
        sys.sandbox.set_config(
            max_operations=10000,
            allow_dunder_access=False,
            allow_class_creation=True,
        )

    def test_class_with_type_annotations(self):
        """Class with type annotations should work."""
        globs = self.run_scoped_code("""
class Point:
    x: int
    y: int

    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y

p = Point(1, 2)
result = p.x + p.y
""")
        self.assertEqual(globs['result'], 3)

    def test_class_with_default_annotations(self):
        """Class with annotated attributes with defaults should work."""
        globs = self.run_scoped_code("""
class Config:
    debug: bool = False
    max_size: int = 100

cfg = Config()
result = not cfg.debug and cfg.max_size == 100
""")
        self.assertTrue(globs['result'])


class TrustedMetaclassTests(ScopedFilenameTestCase):
    """Test that trusted metaclasses from outside sandbox work."""

    SCOPED_FILENAME = "<test_trusted_metaclass_scope>"

    def setUp(self):
        super().setUp()
        sys.sandbox.set_config(
            max_operations=10000,
            allow_dunder_access=False,
            allow_class_creation=True,
        )

    def test_abc_inheritance(self):
        """Subclassing ABC (which uses ABCMeta) should work."""
        globs = self.run_scoped_code("""
from abc import ABC, abstractmethod

class Shape(ABC):
    @abstractmethod
    def area(self):
        pass

class Square(Shape):
    def __init__(self, side):
        self.side = side

    def area(self):
        return self.side * self.side

s = Square(5)
result = s.area()
""")
        self.assertEqual(globs['result'], 25)

    def test_inherit_from_trusted_abc_base(self):
        """Inheriting from a trusted ABC base class works."""
        # Create the base class outside sandbox scope
        class TrustedBase(ABC):
            @abstractmethod
            def do_work(self):
                pass

        globs = self.run_scoped_code("""
class Worker(Base):
    def do_work(self):
        return "done"

w = Worker()
result = w.do_work()
""", extra_globals={"Base": TrustedBase})
        self.assertEqual(globs['result'], "done")

    def test_enum_creation(self):
        """Creating Enum subclasses should work."""
        globs = self.run_scoped_code("""
from enum import Enum

class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3

result = Color.RED.value
""")
        self.assertEqual(globs['result'], 1)

    def test_int_enum_creation(self):
        """Creating IntEnum subclasses should work."""
        globs = self.run_scoped_code("""
from enum import IntEnum

class Priority(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3

result = Priority.HIGH + Priority.LOW
""")
        self.assertEqual(globs['result'], 4)


class DataclassTests(ScopedFilenameTestCase):
    """Test dataclass creation in sandbox."""

    SCOPED_FILENAME = "<test_dataclass_scope>"

    def setUp(self):
        super().setUp()
        sys.sandbox.set_config(
            max_operations=10000,
            allow_dunder_access=False,
            allow_class_creation=True,
        )

    def test_basic_dataclass(self):
        """Basic dataclass definition should work."""
        globs = self.run_scoped_code("""
from dataclasses import dataclass

@dataclass
class Point:
    x: int
    y: int

p = Point(3, 4)
result = p.x + p.y
""")
        self.assertEqual(globs['result'], 7)

    def test_dataclass_with_defaults(self):
        """Dataclass with default values should work."""
        globs = self.run_scoped_code("""
from dataclasses import dataclass

@dataclass
class Config:
    name: str
    debug: bool = False
    max_size: int = 100

cfg = Config(name="test")
result = cfg.name == "test" and not cfg.debug and cfg.max_size == 100
""")
        self.assertTrue(globs['result'])

    def test_dataclass_with_field(self):
        """Dataclass with field() should work."""
        globs = self.run_scoped_code("""
from dataclasses import dataclass, field

@dataclass
class Container:
    items: list = field(default_factory=list)

    def add(self, item):
        self.items.append(item)

c = Container()
c.add(1)
c.add(2)
result = len(c.items)
""")
        self.assertEqual(globs['result'], 2)


class MetaclassCreationBlockedTests(ScopedFilenameTestCase):
    """Test that metaclass CREATION is blocked in sandbox."""

    SCOPED_FILENAME = "<test_metaclass_blocked_scope>"

    def setUp(self):
        super().setUp()
        sys.sandbox.set_config(
            max_operations=10000,
            allow_dunder_access=False,
            allow_class_creation=True,
        )

    def test_direct_type_subclass_blocked(self):
        """Subclassing type directly should be blocked."""
        with self.assertRaises(SandboxSecurityError):
            self.run_scoped_code("""
class Meta(type):
    pass
""")

    def test_type_subclass_with_new_blocked(self):
        """Subclassing type with __new__ override should be blocked."""
        with self.assertRaises(SandboxSecurityError):
            self.run_scoped_code("""
class Meta(type):
    def __new__(mcs, name, bases, namespace):
        return super().__new__(mcs, name, bases, namespace)
""")

    def test_indirect_type_subclass_blocked(self):
        """Subclassing a metaclass should be blocked."""
        # Create a metaclass outside sandbox
        class TrustedMeta(type):
            pass

        with self.assertRaises(SandboxSecurityError):
            self.run_scoped_code("""
class MyMeta(BaseMeta):
    pass
""", extra_globals={"BaseMeta": TrustedMeta})


class IntrospectionStillBlockedTests(ScopedFilenameTestCase):
    """Test that introspection dunders remain blocked."""

    SCOPED_FILENAME = "<test_introspection_blocked_scope>"

    def setUp(self):
        super().setUp()
        sys.sandbox.set_config(
            max_operations=10000,
            allow_dunder_access=False,
            allow_class_creation=True,
        )

    def test_class_attribute_blocked(self):
        """Reading __class__ attribute should be blocked."""
        with self.assertRaises(SandboxAttributeError):
            self.run_scoped_code("""
x = {}
c = x.__class__
""")

    def test_bases_attribute_blocked(self):
        """Reading __bases__ attribute should be blocked."""
        with self.assertRaises(SandboxAttributeError):
            self.run_scoped_code("""
class Foo:
    pass
b = Foo.__bases__
""")

    def test_subclasses_method_blocked(self):
        """Calling __subclasses__() should be blocked."""
        with self.assertRaises(SandboxAttributeError):
            self.run_scoped_code("""
subs = object.__subclasses__()
""")

    def test_mro_attribute_blocked(self):
        """Reading __mro__ attribute should be blocked."""
        with self.assertRaises(SandboxAttributeError):
            self.run_scoped_code("""
class Foo:
    pass
m = Foo.__mro__
""")

    def test_dict_attribute_blocked(self):
        """Reading __dict__ on class should be blocked."""
        with self.assertRaises(SandboxAttributeError):
            self.run_scoped_code("""
class Foo:
    x = 1
d = Foo.__dict__
""")


class AllowClassCreationFalseTests(ScopedFilenameTestCase):
    """Test behavior when allow_class_creation=False."""

    SCOPED_FILENAME = "<test_allow_class_creation_false_scope>"

    def setUp(self):
        super().setUp()
        sys.sandbox.set_config(
            max_operations=10000,
            allow_dunder_access=False,
            allow_class_creation=False,  # Disable class creation whitelist
        )

    def test_class_creation_blocked_when_disabled(self):
        """Class creation should be blocked when allow_class_creation=False."""
        with self.assertRaises(SandboxAttributeError):
            self.run_scoped_code("""
class Foo:
    pass
""")


class SubprocessClassCreationTests(unittest.TestCase):
    """Subprocess tests for class creation isolation."""

    def test_class_creation_full_isolation(self):
        """Test class creation works in full subprocess isolation."""
        code = '''
import sys
sys.sandbox.set_config(
    allow_dunder_access=False,
    allow_class_creation=True,
)
sys.sandbox.add_filename("<sandbox>")

exec(compile("""
class Foo:
    def __init__(self, x):
        self.x = x

    def double(self):
        return self.x * 2

f = Foo(21)
if f.double() == 42:
    sys.exit(0)
else:
    sys.exit(1)
""", "<sandbox>", "exec"))
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Class creation failed: {result.stderr}")

    def test_metaclass_creation_blocked_subprocess(self):
        """Test metaclass creation is blocked in subprocess."""
        code = '''
import sys
sys.sandbox.set_config(
    allow_dunder_access=False,
    allow_class_creation=True,
)
sys.sandbox.add_filename("<sandbox>")

try:
    exec(compile("""
class Meta(type):
    pass
""", "<sandbox>", "exec"))
    sys.exit(1)  # Should not reach here
except SandboxSecurityError:
    sys.exit(0)  # Expected
except Exception as e:
    print(f"Unexpected: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(2)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Metaclass should be blocked: {result.stderr}")

    def test_dataclass_in_subprocess(self):
        """Test dataclass creation works in subprocess."""
        code = '''
import sys
sys.sandbox.set_config(
    allow_dunder_access=False,
    allow_class_creation=True,
)
sys.sandbox.add_filename("<sandbox>")

exec(compile("""
from dataclasses import dataclass

@dataclass
class Point:
    x: int
    y: int

p = Point(3, 4)
if p.x == 3 and p.y == 4:
    sys.exit(0)
else:
    sys.exit(1)
""", "<sandbox>", "exec"))
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Dataclass creation failed: {result.stderr}")

    def test_enum_in_subprocess(self):
        """Test enum creation works in subprocess."""
        code = '''
import sys
sys.sandbox.set_config(
    allow_dunder_access=False,
    allow_class_creation=True,
)
sys.sandbox.add_filename("<sandbox>")

exec(compile("""
from enum import Enum

class Status(Enum):
    PENDING = 1
    RUNNING = 2
    DONE = 3

if Status.DONE.value == 3:
    sys.exit(0)
else:
    sys.exit(1)
""", "<sandbox>", "exec"))
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Enum creation failed: {result.stderr}")


class SuperTests(ScopedFilenameTestCase):
    """Test that super() works correctly with class creation.

    Note: super().greet() works for non-dunder methods, but super().__init__()
    requires allow_dunder_access=True because __init__ is blocked by dunder access
    restrictions. The class body whitelist only applies during class body execution,
    not during method calls.
    """

    SCOPED_FILENAME = "<test_super_scope>"

    def setUp(self):
        super().setUp()
        sys.sandbox.set_config(
            max_operations=10000,
            allow_dunder_access=False,
            allow_class_creation=True,
        )

    def test_super_in_method(self):
        """super() in method should work for non-dunder methods."""
        globs = self.run_scoped_code("""
class Base:
    def greet(self):
        return "Hello"

class Derived(Base):
    def greet(self):
        return super().greet() + ", World!"

d = Derived()
result = d.greet()
""")
        self.assertEqual(globs['result'], "Hello, World!")

    def test_super_init_blocked_without_dunder_access(self):
        """super().__init__() is blocked when allow_dunder_access=False.

        The class body whitelist only applies during class body execution.
        Method calls like super().__init__() access __init__ as an attribute,
        which is blocked by dunder restrictions.
        """
        with self.assertRaises(SandboxAttributeError):
            self.run_scoped_code("""
class Base:
    def __init__(self, x):
        self.x = x

class Derived(Base):
    def __init__(self, x, y):
        super().__init__(x)  # This is blocked - __init__ access
        self.y = y

d = Derived(1, 2)
""")

    def test_super_init_works_with_dunder_access(self):
        """super().__init__() works when allow_dunder_access=True."""
        sys.sandbox.set_config(
            max_operations=10000,
            allow_dunder_access=True,  # Enable dunder access for __init__
            allow_class_creation=True,
        )

        globs = self.run_scoped_code("""
class Base:
    def __init__(self, x):
        self.x = x

class Derived(Base):
    def __init__(self, x, y):
        super().__init__(x)
        self.y = y

d = Derived(1, 2)
result = d.x + d.y
""")
        self.assertEqual(globs['result'], 3)


class AllowMagicMethodsTests(ScopedFilenameTestCase):
    """Test the allow_magic_methods config flag."""

    SCOPED_FILENAME = "<test_allow_magic_methods_scope>"

    def setUp(self):
        super().setUp()
        # Default config with allow_class_creation=True
        sys.sandbox.set_config(
            max_operations=10000,
            allow_dunder_access=False,
            allow_class_creation=True,
        )

    def test_magic_methods_allowed_by_default(self):
        """Magic methods should work by default."""
        # allow_magic_methods defaults to True
        globs = self.run_scoped_code("""
class Foo:
    def __init__(self):
        self.value = 42

f = Foo()
result = f.value
""")
        self.assertEqual(globs['result'], 42)

    def test_magic_methods_blocked_when_disabled(self):
        """Magic methods blocked when allow_magic_methods=False."""
        sys.sandbox.set_config(
            allow_class_creation=True,
            allow_magic_methods=False,
        )
        with self.assertRaises(SandboxAttributeError):
            self.run_scoped_code("""
class Foo:
    def __init__(self):
        pass
""")

    def test_str_magic_method_blocked_when_disabled(self):
        """__str__ blocked when allow_magic_methods=False."""
        sys.sandbox.set_config(
            allow_class_creation=True,
            allow_magic_methods=False,
        )
        with self.assertRaises(SandboxAttributeError):
            self.run_scoped_code("""
class Foo:
    def __str__(self):
        return "Foo"
""")

    def test_basic_class_works_without_magic_methods(self):
        """Basic class creation works even without magic methods."""
        sys.sandbox.set_config(
            allow_class_creation=True,
            allow_magic_methods=False,
        )
        globs = self.run_scoped_code('''
class Point:
    """A point in 2D space."""
    __slots__ = ('x', 'y')
    x: int
    y: int

result = True
''')
        self.assertTrue(globs['result'])

    def test_regular_methods_work_without_magic_methods(self):
        """Regular (non-dunder) methods work when allow_magic_methods=False."""
        sys.sandbox.set_config(
            allow_class_creation=True,
            allow_magic_methods=False,
        )
        globs = self.run_scoped_code("""
class Calculator:
    def add(self, a, b):
        return a + b

calc = Calculator()
result = calc.add(2, 3)
""")
        self.assertEqual(globs['result'], 5)

    def test_class_attributes_work_without_magic_methods(self):
        """Class attributes work when allow_magic_methods=False."""
        sys.sandbox.set_config(
            allow_class_creation=True,
            allow_magic_methods=False,
        )
        globs = self.run_scoped_code("""
class Config:
    debug = True
    max_retries = 3

result = Config.debug and Config.max_retries == 3
""")
        self.assertTrue(globs['result'])

    def test_inheritance_works_without_magic_methods(self):
        """Inheritance works when allow_magic_methods=False."""
        sys.sandbox.set_config(
            allow_class_creation=True,
            allow_magic_methods=False,
        )
        globs = self.run_scoped_code("""
class Animal:
    def speak(self):
        return "..."

class Dog(Animal):
    def speak(self):
        return "Woof!"

dog = Dog()
result = dog.speak()
""")
        self.assertEqual(globs['result'], "Woof!")

    def test_docstring_works_without_magic_methods(self):
        """Class with docstring works when allow_magic_methods=False."""
        sys.sandbox.set_config(
            allow_class_creation=True,
            allow_magic_methods=False,
        )
        globs = self.run_scoped_code('''
class Documented:
    """This is a documented class."""

    def method(self):
        """This method does something."""
        return 42

result = Documented().method()
''')
        self.assertEqual(globs['result'], 42)

    def test_annotations_work_without_magic_methods(self):
        """Type annotations work when allow_magic_methods=False."""
        sys.sandbox.set_config(
            allow_class_creation=True,
            allow_magic_methods=False,
        )
        globs = self.run_scoped_code("""
class TypedClass:
    x: int
    y: str = "default"

result = TypedClass.y
""")
        self.assertEqual(globs['result'], "default")

    def test_get_config_includes_allow_magic_methods(self):
        """get_config() should include allow_magic_methods."""
        sys.sandbox.set_config(allow_magic_methods=False)
        config = sys.sandbox.get_config()
        self.assertIn('allow_magic_methods', config)
        self.assertFalse(config['allow_magic_methods'])

        sys.sandbox.set_config(allow_magic_methods=True)
        config = sys.sandbox.get_config()
        self.assertTrue(config['allow_magic_methods'])

    def test_property_getter_setter(self):
        """allow_magic_methods property should work."""
        original = sys.sandbox.allow_magic_methods

        sys.sandbox.allow_magic_methods = False
        self.assertFalse(sys.sandbox.allow_magic_methods)

        sys.sandbox.allow_magic_methods = True
        self.assertTrue(sys.sandbox.allow_magic_methods)

        # Restore
        sys.sandbox.allow_magic_methods = original


class AllowMagicMethodsSubprocessTests(unittest.TestCase):
    """Subprocess tests for allow_magic_methods."""

    def test_magic_methods_blocked_subprocess(self):
        """Test magic methods blocked in subprocess."""
        code = '''
import sys
sys.sandbox.set_config(
    allow_dunder_access=False,
    allow_class_creation=True,
    allow_magic_methods=False,
)
sys.sandbox.add_filename("<sandbox>")

try:
    exec(compile("""
class Foo:
    def __init__(self):
        pass
""", "<sandbox>", "exec"))
    sys.exit(1)  # Should not reach here
except SandboxAttributeError:
    sys.exit(0)  # Expected
except Exception as e:
    print(f"Unexpected: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(2)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Magic method should be blocked: {result.stderr}")

    def test_basic_class_works_subprocess(self):
        """Test basic class works without magic methods in subprocess."""
        code = '''
import sys
sys.sandbox.set_config(
    allow_dunder_access=False,
    allow_class_creation=True,
    allow_magic_methods=False,
)
sys.sandbox.add_filename("<sandbox>")

try:
    exec(compile("""
class Point:
    __slots__ = ('x', 'y')
    x: int
    y: int
""", "<sandbox>", "exec"))
    sys.exit(0)  # Should work
except Exception as e:
    print(f"Unexpected: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Basic class should work: {result.stderr}")


if __name__ == '__main__':
    unittest.main()
