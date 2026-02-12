"""Benchmark: Class creation operations.

Exercises _PySandbox_CheckMetaclassAllowed.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import setup_sandbox, make_bench_funcs, add_common_args

SOURCE = """
class Base:
    def method(self):
        return 42

def class_simple():
    \"\"\"Simple class definition.\"\"\"
    i = 0
    while i < 5000:
        class MyClass:
            x = 1
            y = 2
        i += 1
    return MyClass

def class_with_init():
    \"\"\"Class definition with __init__.\"\"\"
    i = 0
    while i < 5000:
        class MyClass:
            def __init__(self):
                self.x = 1
                self.y = 2
        i += 1
    return MyClass

def class_inheritance():
    \"\"\"Class with inheritance.\"\"\"
    i = 0
    while i < 5000:
        class Child(Base):
            def child_method(self):
                return 99
        i += 1
    return Child

def class_multiple_inheritance():
    \"\"\"Class with multiple inheritance.\"\"\"
    class Mixin1:
        def m1(self):
            return 1

    class Mixin2:
        def m2(self):
            return 2

    i = 0
    while i < 3000:
        class Combined(Base, Mixin1, Mixin2):
            pass
        i += 1
    return Combined

def class_instantiation():
    \"\"\"Object instantiation.\"\"\"
    class Obj:
        def __init__(self, a, b):
            self.a = a
            self.b = b

    i = 0
    while i < 10000:
        o = Obj(1, 2)
        o = Obj(3, 4)
        o = Obj(5, 6)
        i += 1
    return o

def class_with_methods():
    \"\"\"Class with multiple methods.\"\"\"
    i = 0
    while i < 3000:
        class MyClass:
            def __init__(self):
                self.x = 0

            def get(self):
                return self.x

            def set(self, v):
                self.x = v

            def __repr__(self):
                return f"MyClass({self.x})"

            def __eq__(self, other):
                return self.x == other.x
        i += 1
    return MyClass

def class_with_classmethod():
    \"\"\"Class with classmethods and staticmethods.\"\"\"
    i = 0
    while i < 3000:
        class MyClass:
            count = 0

            @classmethod
            def from_value(cls, v):
                obj = cls()
                obj.val = v
                return obj

            @staticmethod
            def helper(x):
                return x * 2

            def __init__(self):
                self.val = 0
        i += 1
    return MyClass
"""

if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    ns = make_bench_funcs(SOURCE)

    runner.bench_func('class_simple', ns['class_simple'])
    runner.bench_func('class_with_init', ns['class_with_init'])
    runner.bench_func('class_inheritance', ns['class_inheritance'])
    runner.bench_func('class_multiple_inheritance', ns['class_multiple_inheritance'])
    runner.bench_func('class_instantiation', ns['class_instantiation'])
    runner.bench_func('class_with_methods', ns['class_with_methods'])
    runner.bench_func('class_with_classmethod', ns['class_with_classmethod'])
