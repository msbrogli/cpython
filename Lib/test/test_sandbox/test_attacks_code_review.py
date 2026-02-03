"""Tests for sandbox bypass vulnerabilities identified in CODE-REVIEW.md.

This module contains security tests for vulnerabilities identified in the
production-readiness code review. Each test verifies that a specific attack
vector is properly blocked.

Test behavior:
- PASS = Protection is working (secure)
- FAIL = Vulnerability exists (needs fix)

Vulnerabilities tested:
1. P0: Specialized opcode bypass - LOAD_ATTR_* skip dunder access checks
2. P0: Import parent module bypass - parent import allowed when only submodule whitelisted
3. P1: exec() __builtins__ injection - attacker-supplied __builtins__ not validated

Also verifies protections that ARE working:
- PyIter_Send() - generator.send() correctly enforces iteration limits
- exec() empty builtins - correctly rejected

Reference: CODE-REVIEW.md sections 6 and 10
"""

import subprocess
import sys
import unittest

from test.test_sandbox import (
    SandboxTestCase,
    _run_sandboxed_code,
    SUBPROCESS_TIMEOUT,
)


class TestPyIterSendProtected(unittest.TestCase):
    """Verify generator.send() correctly enforces iteration limits.

    CODE-REVIEW.md claimed PyIter_Send() bypasses iteration limits, but testing
    shows that iteration checks ARE properly enforced for generator.send().
    """

    def test_generator_send_enforces_iteration_limit(self):
        """generator.send(None) must enforce iteration limit."""
        code = '''
import sys

def infinite_gen():
    while True:
        x = yield 1

sys.sandbox.set_config(max_iterations=10)
sys.sandbox.enter_scope()

gen = infinite_gen()
next(gen)  # Prime the generator

count = 0
try:
    for _ in range(50):
        gen.send(None)
        count += 1
except SandboxRuntimeError:
    print(f"PROTECTED: stopped at {count} iterations")
    sys.exit(0)

print(f"VULNERABLE: completed {count} send() calls (limit was 10)")
sys.exit(1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: generator.send() bypasses iteration limit. "
            f"stdout={result.stdout}, stderr={result.stderr}")

    def test_generator_send_with_value_enforces_limit(self):
        """generator.send(value) must enforce iteration limit."""
        code = '''
import sys

def echo_gen():
    while True:
        received = yield
        yield received

sys.sandbox.set_config(max_iterations=20)
sys.sandbox.enter_scope()

gen = echo_gen()
next(gen)  # Prime

count = 0
try:
    for i in range(50):
        gen.send(i)
        next(gen)
        count += 1
except SandboxRuntimeError:
    print(f"PROTECTED: stopped at {count}")
    sys.exit(0)

print(f"VULNERABLE: completed {count} iterations")
sys.exit(1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: generator.send(value) bypasses iteration limit. "
            f"stdout={result.stdout}, stderr={result.stderr}")

    def test_coroutine_send_enforces_limit(self):
        """Coroutine send must enforce iteration limit."""
        code = '''
import sys

async def async_gen():
    for i in range(100):
        yield i

sys.sandbox.set_config(max_iterations=10)
sys.sandbox.enter_scope()

async def test():
    count = 0
    async for x in async_gen():
        count += 1
    return count

import asyncio
try:
    result = asyncio.run(test())
    print(f"VULNERABLE: completed {result} iterations")
    sys.exit(1)
except SandboxRuntimeError:
    print("PROTECTED: iteration limit enforced")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: coroutine send bypasses iteration limit. "
            f"stdout={result.stdout}, stderr={result.stderr}")


class TestSpecializedOpcodeDunderBypass(unittest.TestCase):
    """P0: Specialized opcodes must enforce dunder access checks.

    Vulnerability: After adaptive specialization, LOAD_ATTR_INSTANCE_VALUE,
    LOAD_ATTR_SLOT, STORE_ATTR_SLOT, etc. skip _PySandbox_CheckDunderAccess().

    These tests FAIL until the vulnerability is fixed.
    """

    def test_load_attr_instance_value_blocks_dunder(self):
        """LOAD_ATTR_INSTANCE_VALUE must block dunder access after specialization."""
        code = '''
import sys

class Target:
    def __init__(self):
        self.__secret__ = "leaked"

obj = Target()

# Warm up to trigger LOAD_ATTR -> LOAD_ATTR_INSTANCE_VALUE specialization
def access_dunder(o):
    return o.__secret__

# Run many times OUTSIDE sandbox to trigger specialization
for _ in range(50):
    try:
        access_dunder(obj)
    except:
        pass

# Now enable sandbox with dunder blocking
sys.sandbox.set_config(allow_dunder_access=False)
sys.sandbox.enter_scope()

try:
    result = access_dunder(obj)
    print(f"VULNERABLE: accessed __secret__ = {result}")
    sys.exit(1)
except SandboxAttributeError:
    print("PROTECTED: dunder access blocked")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: LOAD_ATTR_INSTANCE_VALUE bypasses dunder check. "
            f"stdout={result.stdout}, stderr={result.stderr}")

    def test_load_attr_slot_blocks_dunder(self):
        """LOAD_ATTR_SLOT must block __class__ access after specialization."""
        code = '''
import sys

class SlottedTarget:
    __slots__ = ['value']
    def __init__(self):
        self.value = 42

obj = SlottedTarget()

# Access __class__ many times to trigger specialization
def get_class(o):
    return o.__class__

for _ in range(50):
    get_class(obj)

sys.sandbox.set_config(allow_dunder_access=False)
sys.sandbox.enter_scope()

try:
    cls = get_class(obj)
    print(f"VULNERABLE: accessed __class__ = {cls}")
    sys.exit(1)
except SandboxAttributeError:
    print("PROTECTED: __class__ access blocked")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: LOAD_ATTR_SLOT bypasses dunder check. "
            f"stdout={result.stdout}, stderr={result.stderr}")

    def test_store_attr_slot_blocks_dunder(self):
        """STORE_ATTR_SLOT must block dunder store after specialization."""
        code = '''
import sys

class MutableTarget:
    __doc__ = "original doc"

# Warm up store to trigger STORE_ATTR -> STORE_ATTR_SLOT specialization
def set_doc(cls, val):
    cls.__doc__ = val

for _ in range(50):
    try:
        set_doc(MutableTarget, "warming up")
    except:
        pass

sys.sandbox.set_config(allow_dunder_access=False)
sys.sandbox.enter_scope()

try:
    set_doc(MutableTarget, "hacked via specialization")
    print(f"VULNERABLE: __doc__ modified")
    sys.exit(1)
except SandboxAttributeError:
    print("PROTECTED: __doc__ store blocked")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: STORE_ATTR_SLOT bypasses dunder check. "
            f"stdout={result.stdout}, stderr={result.stderr}")

    def test_load_method_blocks_dunder(self):
        """LOAD_METHOD_* must block dunder method access after specialization."""
        code = '''
import sys

class MethodTarget:
    def __repr__(self):
        return "secret repr"

obj = MethodTarget()

# Warm up method access
def get_repr_method(o):
    return o.__repr__

for _ in range(50):
    try:
        get_repr_method(obj)
    except:
        pass

sys.sandbox.set_config(allow_dunder_access=False)
sys.sandbox.enter_scope()

try:
    method = get_repr_method(obj)
    print(f"VULNERABLE: accessed __repr__ method")
    sys.exit(1)
except SandboxAttributeError:
    print("PROTECTED: __repr__ access blocked")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: LOAD_METHOD bypasses dunder check. "
            f"stdout={result.stdout}, stderr={result.stderr}")

    def test_specialization_code_object_access_blocked(self):
        """__code__ access must be blocked even after specialization."""
        code = '''
import sys

def target_function():
    return "safe"

# Warm up __code__ access
def get_code(f):
    return f.__code__

for _ in range(50):
    try:
        get_code(target_function)
    except:
        pass

sys.sandbox.set_config(allow_dunder_access=False)
sys.sandbox.enter_scope()

try:
    code_obj = get_code(target_function)
    print(f"VULNERABLE: accessed __code__")
    sys.exit(1)
except SandboxAttributeError:
    print("PROTECTED: __code__ access blocked")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: __code__ access bypasses dunder check after specialization. "
            f"stdout={result.stdout}, stderr={result.stderr}")


class TestImportParentModuleBypass(unittest.TestCase):
    """P0: Parent module import must be blocked when only submodule whitelisted.

    Vulnerability: sandbox_imports.c:299-308 allows parent module import
    if ANY submodule is whitelisted, via check_has_any_submodule_entry().

    These tests FAIL until the vulnerability is fixed.
    """

    def test_parent_import_blocked_when_only_submodule_whitelisted(self):
        """import json must be blocked when only json.decoder is whitelisted."""
        code = '''
import sys

# Only whitelist the submodule decoder, NOT the parent json
sys.sandbox.allowed_imports = {("json", "decoder")}
sys.sandbox.import_allow_submodules = True
sys.sandbox.import_restrict_mode = True
sys.sandbox.enter_scope()

try:
    import json  # Bare parent import - should be blocked
    print(f"VULNERABLE: imported json module")
    sys.exit(1)
except SandboxImportError:
    print("PROTECTED: parent import blocked")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: parent module import allowed when only submodule whitelisted. "
            f"stdout={result.stdout}, stderr={result.stderr}")

    def test_grandparent_import_blocked(self):
        """import xml must be blocked when only xml.etree.ElementTree whitelisted."""
        code = '''
import sys

# Whitelist a deeply nested submodule
sys.sandbox.allowed_imports = {("xml.etree", "ElementTree")}
sys.sandbox.import_allow_submodules = True
sys.sandbox.import_restrict_mode = True
sys.sandbox.enter_scope()

try:
    import xml  # Grandparent import - should be blocked
    print(f"VULNERABLE: imported xml")
    sys.exit(1)
except SandboxImportError:
    print("PROTECTED: grandparent import blocked")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: grandparent module import allowed. "
            f"stdout={result.stdout}, stderr={result.stderr}")

    def test_from_import_parent_blocked(self):
        """from json import loads must be blocked when only json.decoder whitelisted."""
        code = '''
import sys

sys.sandbox.allowed_imports = {("json", "decoder")}
sys.sandbox.import_allow_submodules = True
sys.sandbox.import_restrict_mode = True
sys.sandbox.enter_scope()

try:
    from json import loads, dumps  # Should be blocked
    print(f"VULNERABLE: imported json.loads and json.dumps")
    sys.exit(1)
except SandboxImportError:
    print("PROTECTED: from import blocked")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: from-import allows access to non-whitelisted names. "
            f"stdout={result.stdout}, stderr={result.stderr}")


class TestExecBuiltinsInjection(unittest.TestCase):
    """P1: exec()/eval() must validate __builtins__ parameter.

    Vulnerability: bltinmodule.c:1055-1058 uses attacker-provided __builtins__
    dict without validation if it already exists in globals.

    These tests FAIL until the vulnerability is fixed.
    """

    def test_exec_rejects_custom_import(self):
        """exec() must reject custom __import__ in __builtins__."""
        code = '''
import sys
import builtins

# Save the real import
real_import = builtins.__import__

# Create a malicious import that ignores sandbox
def malicious_import(name, globals=None, locals=None, fromlist=(), level=0):
    return real_import(name, globals, locals, fromlist, level)

# Block ALL imports in sandbox
sys.sandbox.allowed_imports = set()
sys.sandbox.import_restrict_mode = True
sys.sandbox.enter_scope()

# Create custom builtins with our malicious import
custom_builtins = dict(vars(builtins))
custom_builtins['__import__'] = malicious_import

try:
    exec("import os", {'__builtins__': custom_builtins})
    print("VULNERABLE: imported os via custom __builtins__")
    sys.exit(1)
except (SandboxImportError, SandboxSecurityError):
    print("PROTECTED: custom builtins rejected or import blocked")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: exec() accepts custom __import__ in __builtins__. "
            f"stdout={result.stdout}, stderr={result.stderr}")

    def test_eval_rejects_custom_builtins(self):
        """eval() must reject custom __builtins__."""
        code = '''
import sys
import builtins

real_import = builtins.__import__

def malicious_import(name, *args, **kwargs):
    return real_import(name, *args, **kwargs)

sys.sandbox.allowed_imports = set()
sys.sandbox.import_restrict_mode = True
sys.sandbox.enter_scope()

custom_builtins = dict(vars(builtins))
custom_builtins['__import__'] = malicious_import

try:
    result = eval("__import__('os')", {'__builtins__': custom_builtins})
    print(f"VULNERABLE: eval with custom builtins imported os")
    sys.exit(1)
except (SandboxImportError, SandboxSecurityError):
    print("PROTECTED: custom builtins rejected")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: eval() accepts custom __builtins__. "
            f"stdout={result.stdout}, stderr={result.stderr}")

    def test_exec_rejects_empty_builtins(self):
        """exec() must reject empty __builtins__ in sandbox scope."""
        code = '''
import sys

sys.sandbox.enter_scope()

try:
    exec("x = len([1,2,3])", {'__builtins__': {}})
    print("VULNERABLE: exec succeeded with empty builtins")
    sys.exit(1)
except NameError:
    # len is not defined - empty builtins was accepted
    print("VULNERABLE: empty __builtins__ accepted")
    sys.exit(1)
except SandboxSecurityError:
    print("PROTECTED: invalid builtins rejected")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: exec() accepts empty __builtins__. "
            f"stdout={result.stdout}, stderr={result.stderr}")

    def test_exec_rejects_modified_open(self):
        """exec() must reject modified builtins with custom open()."""
        code = '''
import sys
import builtins

# Create builtins with potentially dangerous open
custom_builtins = dict(vars(builtins))

sys.sandbox.enter_scope()

try:
    local_vars = {}
    exec("f = open", {'__builtins__': custom_builtins}, local_vars)
    print("VULNERABLE: can inject custom builtins")
    sys.exit(1)
except SandboxSecurityError:
    print("PROTECTED: custom builtins rejected")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: exec() accepts custom __builtins__ dict. "
            f"stdout={result.stdout}, stderr={result.stderr}")


class TestCombinedBypassScenarios(unittest.TestCase):
    """Combined attack scenarios using multiple vectors."""

    def test_generator_send_enforces_limits(self):
        """Verify generator.send() correctly enforces iteration limits."""
        code = '''
import sys

def compute_gen():
    total = 0
    while True:
        n = yield total
        if n is not None:
            total += n * n

sys.sandbox.set_config(max_iterations=100, max_operations=1000)
sys.sandbox.enter_scope()

gen = compute_gen()
next(gen)  # Prime

try:
    for i in range(10000):
        gen.send(i)
    print("VULNERABLE: completed 10000 computations")
    sys.exit(1)
except (SandboxRuntimeError, SandboxOverflowError):
    print("PROTECTED: iteration/operation limit enforced")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
            f"Vulnerability: generator.send() bypasses limits. "
            f"stdout={result.stdout}, stderr={result.stderr}")


if __name__ == '__main__':
    unittest.main()
