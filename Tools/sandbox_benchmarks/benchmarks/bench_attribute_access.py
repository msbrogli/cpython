"""Benchmark: Attribute access operations.

Exercises _PySandbox_CheckDunderAccess and _PySandbox_CheckFrozen.

Objects are created outside sandbox scope (so __init__ works with frozen_mode),
then injected into the benchmark namespace. The benchmark functions run in
sandbox scope so frozen_mode / dunder checks fire on every attribute access.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import (setup_sandbox, make_bench_code, add_common_args,
                         SANDBOX_FILENAME, HAS_SANDBOX)


# --- Setup classes and instances (outside sandbox scope) ---

class Simple:
    def __init__(self):
        self.x = 1
        self.y = 2
        self.z = 3
        self.name = "test"

class WithProperty:
    def __init__(self):
        self._val = 42

    @property
    def val(self):
        return self._val

    @val.setter
    def val(self, v):
        self._val = v

class WithSlots:
    __slots__ = ('x', 'y', 'z')
    def __init__(self):
        self.x = 1
        self.y = 2
        self.z = 3


# --- Benchmark functions (compiled in sandbox scope) ---

SOURCE = """
def getattr_normal():
    \"\"\"Normal attribute access (getattr).\"\"\"
    obj = _simple
    i = 0
    while i < 10000:
        x = obj.x
        y = obj.y
        z = obj.z
        n = obj.name
        i += 1
    return x

def setattr_normal():
    \"\"\"Normal attribute setting (setattr).\"\"\"
    obj = _simple
    i = 0
    while i < 10000:
        obj.x = 1
        obj.y = 2
        obj.z = 3
        obj.name = "test"
        i += 1

def getattr_dunder():
    \"\"\"Dunder attribute access (__class__, __dict__, etc).\"\"\"
    obj = _simple
    i = 0
    while i < 5000:
        c = obj.__class__
        d = obj.__dict__
        c = obj.__class__.__name__
        i += 1
    return c

def property_access():
    \"\"\"Property getter/setter access.\"\"\"
    obj = _prop
    i = 0
    while i < 10000:
        v = obj.val
        obj.val = v + 1
        v = obj.val
        obj.val = v - 1
        i += 1
    return v

def slots_access():
    \"\"\"Slotted attribute access.\"\"\"
    obj = _slotted
    i = 0
    while i < 10000:
        x = obj.x
        y = obj.y
        z = obj.z
        obj.x = x
        obj.y = y
        obj.z = z
        i += 1
    return x

def hasattr_check():
    \"\"\"hasattr() checks.\"\"\"
    obj = _simple
    i = 0
    while i < 10000:
        _ = hasattr(obj, 'x')
        _ = hasattr(obj, 'y')
        _ = hasattr(obj, 'missing')
        _ = hasattr(obj, '__class__')
        i += 1
    return True

def dynamic_getattr():
    \"\"\"getattr() with dynamic names.\"\"\"
    obj = _simple
    names = ['x', 'y', 'z', 'name']
    i = 0
    while i < 5000:
        j = 0
        while j < 4:
            _ = getattr(obj, names[j])
            j += 1
        i += 1
    return True

def dynamic_setattr():
    \"\"\"setattr() with dynamic names.\"\"\"
    obj = _simple
    i = 0
    while i < 5000:
        setattr(obj, 'x', 1)
        setattr(obj, 'y', 2)
        setattr(obj, 'z', 3)
        setattr(obj, 'name', 'test')
        i += 1
"""


if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    # Create instances outside sandbox scope
    simple = Simple()
    prop = WithProperty()
    slotted = WithSlots()

    # Mark objects as mutable so setattr works in frozen_mode
    if HAS_SANDBOX and sys.sandbox.enabled:
        sb = sys.sandbox
        if getattr(sb, 'frozen_mode', False):
            sb.set_mutable(simple, True)
            sb.set_mutable(prop, True)
            sb.set_mutable(slotted, True)

    # Compile benchmark functions in sandbox scope
    code = make_bench_code(SOURCE)
    ns = {
        '_simple': simple,
        '_prop': prop,
        '_slotted': slotted,
    }
    exec(code, ns)

    runner.bench_func('getattr_normal', ns['getattr_normal'])
    runner.bench_func('setattr_normal', ns['setattr_normal'])
    runner.bench_func('getattr_dunder', ns['getattr_dunder'])
    runner.bench_func('property_access', ns['property_access'])
    runner.bench_func('slots_access', ns['slots_access'])
    runner.bench_func('hasattr_check', ns['hasattr_check'])
    runner.bench_func('dynamic_getattr', ns['dynamic_getattr'])
    runner.bench_func('dynamic_setattr', ns['dynamic_setattr'])
