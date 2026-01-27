# CPython Sandbox Usage Guide

A practical guide for using the CPython sandbox to safely execute untrusted Python code with resource limits and restrictions.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Core Concepts](#core-concepts)
3. [Setting Resource Limits](#setting-resource-limits)
4. [Scope Management](#scope-management)
5. [Execution Limits](#execution-limits)
6. [Frozen Mode](#frozen-mode)
7. [Dunder Access Control](#dunder-access-control)
8. [Opcode Restrictions](#opcode-restrictions)
9. [Object Creation Hooks](#object-creation-hooks)
10. [Suspend/Resume for Trusted Code](#suspendresume-for-trusted-code)
11. [Exception Handling](#exception-handling)
12. [Complete Examples](#complete-examples)
13. [Best Practices](#best-practices)
14. [API Quick Reference](#api-quick-reference)

---

## Quick Start

The sandbox is accessed through the `sys` module. Here is a minimal example that sets up limits and runs untrusted code:

```python
import sys

# 1. Set resource limits
sys.setsandboxlimits(
    max_list_size=10_000,
    max_str_length=10_000,
    scope_max_statements=50_000,
    scope_max_iterations=100_000,
    scope_max_allocations=5_000,
    global_max_allocations=100_000,
    allow_dunder_access=False,
)

# 2. Register a filename for scope tracking
sys.addsandboxfilename("<sandbox>")

# 3. Reset counters before each execution
sys.resetsandboxcounters()

# 4. Compile and execute untrusted code
untrusted_code = """
result = sum(range(100))
"""

code = compile(untrusted_code, "<sandbox>", "exec")
namespace = {}
try:
    exec(code, namespace)
    print("Result:", namespace.get("result"))
except SandboxError as e:
    print(f"Sandbox violation: {e}")
finally:
    sys.clearsandboxfilenames()
```

---

## Core Concepts

### Sandbox State

The sandbox state is global to the interpreter. All limits, counters, and configuration are shared across all threads within the same interpreter.

### Global vs. Scoped Limits

- **Global limits** apply to all code regardless of where it runs:
  - Size limits (`max_list_size`, `max_str_length`, etc.)
  - Type restrictions (`allow_float`, `allow_complex`)
  - Global allocation limit (`global_max_allocations`)

- **Scoped limits** only apply to code whose `co_filename` is registered:
  - `scope_max_statements` -- limits executed statements
  - `scope_max_allocations` -- limits object allocations
  - `scope_max_iterations` -- limits iterator steps

### Scope Tracking

The sandbox determines which code is "sandboxed" by tracking filenames. When you compile code with `compile(source, "<sandbox>", "exec")` and register `"<sandbox>"` as a sandbox filename, all scoped limits apply to that code.

### Zero Means No Limit

All numeric limit values default to `0`, which means no limit. You must explicitly set non-zero values to enable enforcement.

---

## Setting Resource Limits

### Data Size Limits

Control the maximum size of built-in data types:

```python
sys.setsandboxlimits(
    max_int_digits=100,       # Max internal digits (~9 decimal digits each)
    max_str_length=100_000,   # Max string characters
    max_bytes_length=100_000, # Max bytes length
    max_list_size=100_000,    # Max list items
    max_dict_size=100_000,    # Max dict entries
    max_set_size=100_000,     # Max set members
    max_tuple_size=100_000,   # Max tuple items
)
```

When a limit is exceeded, a `SandboxOverflowError` is raised:

```python
sys.setsandboxlimits(max_list_size=10)
try:
    big_list = list(range(100))
except SandboxOverflowError as e:
    print(e)  # "List size (100) exceeds sandbox limit (10)"
```

### Type Restrictions

Forbid creation of specific types:

```python
sys.setsandboxlimits(
    allow_float=False,    # Forbid float creation
    allow_complex=False,  # Forbid complex creation
)
```

Attempting to create a forbidden type raises `SandboxTypeError`:

```python
sys.setsandboxlimits(allow_float=False)
try:
    x = 1.0  # SandboxTypeError: float type is forbidden in sandbox
except SandboxTypeError:
    pass
```

### Reading Current Limits

```python
limits = sys.getsandboxlimits()
# Returns dict with all current limit values:
# {'max_int_digits': 100, 'max_str_length': 100000, ...,
#  'allow_float': True, 'allow_complex': True, 'allow_dunder_access': True}
```

### Resetting Limits

Set all values to 0 (no limit) to disable the sandbox:

```python
sys.setsandboxlimits()  # All defaults are 0/True = no limits
```

---

## Scope Management

Scoped limits (statements, scoped allocations, iterations) require registering filenames to determine which code is "in scope".

### Method 1: Using `entersandboxscope()` (Simple)

For executing code in the current frame's context:

```python
sys.setsandboxlimits(scope_max_statements=10_000)

sys.entersandboxscope()  # Registers current frame's filename + resets counters
try:
    # Code executed here and below is in scope
    exec(some_code)
finally:
    sys.exitsandboxscope()  # Clears all registered filenames
```

### Method 2: Using Filenames (Recommended)

For explicit control over what code is tracked:

```python
sys.setsandboxlimits(scope_max_statements=10_000)

# Register a virtual filename
sys.addsandboxfilename("<user-code>")
sys.resetsandboxcounters()

# Compile untrusted code with that filename
code = compile(user_source, "<user-code>", "exec")
try:
    exec(code)
except SandboxRuntimeError:
    print("Statement limit exceeded")
finally:
    sys.clearsandboxfilenames()
```

This approach is preferred because:
- Only the user's code counts toward limits (not your harness code)
- The stdlib and builtins don't count toward scoped limits
- You have fine-grained control over what is tracked

### Method 3: Using `addsandboxframe()`

Register the current frame's filename without resetting counters:

```python
sys.addsandboxframe()  # Adds current frame's co_filename to tracked set
```

### Checking Scope Status

```python
if sys.issandboxinscope():
    print("Currently executing in sandbox scope")
```

### Managing Filenames

```python
sys.addsandboxfilename("<module-a>")
sys.addsandboxfilename("<module-b>")
sys.removesandboxfilename("<module-a>")  # Remove specific filename
sys.clearsandboxfilenames()               # Remove all filenames
```

---

## Execution Limits

### Statement Limit

Prevents infinite loops and long-running code by counting statement executions within scope:

```python
sys.setsandboxlimits(scope_max_statements=1000)
sys.addsandboxfilename("<sandbox>")
sys.resetsandboxcounters()

code = compile("""
x = 0
while True:
    x += 1  # Each iteration counts as statements
""", "<sandbox>", "exec")

try:
    exec(code)
except SandboxRuntimeError as e:
    print(e)  # "Sandbox statement limit exceeded"
```

### Iteration Limit

Prevents excessive iteration even through C builtins like `sum()`, `list()`, `sorted()`:

```python
sys.setsandboxlimits(scope_max_iterations=10_000)
sys.addsandboxfilename("<sandbox>")
sys.resetsandboxcounters()

code = compile("""
# Even though sum() runs in C, the iterator is wrapped
# and each step counts toward the iteration limit
total = sum(range(1_000_000))  # Will exceed iteration limit
""", "<sandbox>", "exec")

try:
    exec(code)
except SandboxRuntimeError as e:
    print(e)  # "Sandbox iteration limit exceeded"
```

### Allocation Limits

#### Global Allocation Limit

Limits total GC-tracked object allocations across all code:

```python
sys.setsandboxlimits(global_max_allocations=10_000)
sys.resetsandboxcounters()

try:
    items = []
    for i in range(100_000):
        items.append([i])  # Each [i] is a GC-tracked allocation
except SandboxMemoryError:
    print("Global allocation limit reached")
```

#### Scoped Allocation Limit

Limits allocations only from code whose filename is registered:

```python
sys.setsandboxlimits(scope_max_allocations=500)
sys.addsandboxfilename("<sandbox>")
sys.resetsandboxcounters()

code = compile("""
items = []
for i in range(10000):
    items.append([i])
""", "<sandbox>", "exec")

try:
    exec(code)
except SandboxMemoryError:
    print("Scoped allocation limit reached")
```

### Reading Counters

Check current counter values at any time:

```python
counts = sys.getsandboxcounts()
print(f"Global allocations: {counts['global_allocation_count']}")
print(f"Scoped allocations: {counts['scope_allocation_count']}")
print(f"Statements executed: {counts['scope_statement_count']}")
print(f"Iterator steps: {counts['scope_iteration_count']}")
```

### Resetting Counters

Reset all counters to 0 before each execution:

```python
sys.resetsandboxcounters()
```

---

## Frozen Mode

Frozen mode prevents attribute modifications (set/delete) on objects. This is useful for protecting shared state from sandboxed code.

### Global Frozen Mode

Block all attribute mutations within sandbox scope:

```python
# Set up scope first
sys.addsandboxfilename("<sandbox>")

# Enable frozen mode
sys.setsandboxfrozenmode(True)

code = compile("""
class Foo:
    pass
obj = Foo()
obj.x = 1  # SandboxAttributeError: cannot modify 'Foo' object: sandbox frozen mode is active
""", "<sandbox>", "exec")

try:
    exec(code)
except SandboxAttributeError as e:
    print(e)
finally:
    sys.setsandboxfrozenmode(False)
    sys.clearsandboxfilenames()
```

### Per-Object Freezing

Freeze specific objects regardless of global frozen mode:

```python
class Config:
    pass

config = Config()
config.api_key = "secret"
config.timeout = 30

# Freeze this specific object
sys.sandboxfreezeobject(config)

# Now even without global frozen mode:
try:
    config.api_key = "hacked"  # SandboxAttributeError
except SandboxAttributeError:
    print("Cannot modify frozen config")

# Check if frozen
print(sys.sandboxisobjectfrozen(config))  # True
```

### Mutable Override

Mark specific objects as always mutable, even when global frozen mode is active:

```python
# Create an output object that sandboxed code CAN modify
output = type('Output', (), {})()
sys.sandboxsetobjectmutable(output)

sys.setsandboxfrozenmode(True)
sys.addsandboxfilename("<sandbox>")

code = compile("""
output.result = 42  # Allowed because output is marked mutable
""", "<sandbox>", "exec")

exec(code, {"output": output})
print(output.result)  # 42

# Remove mutable flag if needed
sys.sandboxsetobjectmutable(output, False)
```

### Frozen Mode with Scope

Frozen mode is scope-aware. Only code with registered filenames is restricted:

```python
sys.addsandboxfilename("<sandbox>")
sys.setsandboxfrozenmode(True)

# Your harness code (not in scope) can still modify objects
class Container:
    pass
c = Container()
c.value = 42  # Works fine - your code is not in sandbox scope

# But sandboxed code cannot
code = compile("c.value = 99", "<sandbox>", "exec")
try:
    exec(code, {"c": c})
except SandboxAttributeError:
    print("Sandboxed code blocked from modifying c")
```

---

## Dunder Access Control

Block access to double-underscore (`__dunder__`) attributes from sandboxed code. This prevents introspection-based escapes like `obj.__class__.__subclasses__()`.

### Enabling Dunder Blocking

```python
sys.setsandboxlimits(allow_dunder_access=False)
sys.addsandboxfilename("<sandbox>")

code = compile("""
x = {}
# All of these are blocked:
# x.__class__
# x.__class__.__subclasses__()
# type.__bases__
try:
    cls = x.__class__  # SandboxAttributeError
except SandboxAttributeError:
    pass  # Blocked

# Normal attributes still work
class Foo:
    pass
Foo.bar = 42  # OK - not a dunder
""", "<sandbox>", "exec")

exec(code)
```

### What Counts as a Dunder

Any attribute name containing `__` (double underscore) anywhere in the name is blocked. This includes:
- `__class__`, `__dict__`, `__bases__`, `__subclasses__`
- `__init__`, `__new__`, `__del__`
- `__getattr__`, `__setattr__`, `__delattr__`

Single underscore attributes (`_private`) are not affected.

### Scope-Aware

Dunder blocking only applies within sandbox scope. Your harness code can freely use dunder attributes:

```python
sys.setsandboxlimits(allow_dunder_access=False)
sys.addsandboxfilename("<sandbox>")

# Your code (not in scope) - works fine
print(dict.__bases__)

# Sandboxed code - blocked
code = compile("print(dict.__bases__)", "<sandbox>", "exec")
try:
    exec(code)
except SandboxAttributeError:
    print("Blocked dunder access in sandbox")
```

---

## Opcode Restrictions

Ban specific bytecode opcodes from executing in sandbox scope. This provides fine-grained control over what operations sandboxed code can perform.

### Setting Up Opcode Restrictions

```python
import dis

# Ban import-related opcodes
banned = {
    dis.opmap['IMPORT_NAME'],
    dis.opmap['IMPORT_FROM'],
    dis.opmap['IMPORT_STAR'],
}

sys.setsandboxbannedopcodes(banned)
sys.setsandboxopcoderestrictmode(True)
sys.addsandboxfilename("<sandbox>")

code = compile("""
import os  # SandboxRuntimeError: Opcode N is not allowed in sandbox scope
""", "<sandbox>", "exec")

try:
    exec(code)
except SandboxRuntimeError as e:
    print(e)
finally:
    sys.setsandboxopcoderestrictmode(False)
    sys.setsandboxbannedopcodes(None)  # Clear all banned opcodes
```

### Common Opcode Sets to Ban

```python
import dis

# Ban imports
IMPORT_OPCODES = {
    dis.opmap['IMPORT_NAME'],
    dis.opmap['IMPORT_FROM'],
    dis.opmap['IMPORT_STAR'],
}

# Ban global/nonlocal variable access
GLOBAL_OPCODES = {
    dis.opmap.get('STORE_GLOBAL'),
    dis.opmap.get('DELETE_GLOBAL'),
    dis.opmap.get('LOAD_GLOBAL'),  # Note: this also blocks function calls
}

# Ban raise/exception manipulation
EXCEPTION_OPCODES = {
    dis.opmap.get('RAISE_VARARGS'),
    dis.opmap.get('RERAISE'),
}
```

### Reading Current Banned Opcodes

```python
banned = sys.getsandboxbannedopcodes()  # Returns frozenset of ints
print(f"Banned opcodes: {banned}")

mode = sys.getsandboxopcoderestrictmode()
print(f"Opcode restriction active: {mode}")
```

---

## Object Creation Hooks

Intercept object creation for monitoring or replacement.

### Setting a Hook

```python
def creation_hook(obj, type_, frame, context):
    """Called for every object created via type.__call__."""
    print(f"Created: {type_.__name__}")
    return obj  # Return original object

sys.setobjectcreationhook(creation_hook)

class Foo:
    pass

instance = Foo()  # Prints: Created Foo

sys.setobjectcreationhook(None)  # Remove hook
```

### Blocking Object Creation

```python
def block_types(obj, type_, frame, context):
    """Block creation of specific types."""
    if type_.__name__ in ('socket', 'Process'):
        raise SandboxTypeError(f"Cannot create {type_.__name__} in sandbox")
    return obj

sys.setobjectcreationhook(block_types)
```

### Replacing Objects

```python
def replace_hook(obj, type_, frame, context):
    """Replace objects at creation time."""
    if type_.__name__ == 'dict':
        # Replace with a read-only wrapper (hypothetical)
        return ReadOnlyDict(obj)
    return obj

sys.setobjectcreationhook(replace_hook)
```

### Reading Current Hook

```python
hook = sys.getobjectcreationhook()
if hook is not None:
    print(f"Hook active: {hook}")
```

---

## Suspend/Resume for Trusted Code

Temporarily bypass all sandbox limits when executing trusted code.

### Basic Usage

```python
sys.setsandboxlimits(max_list_size=10)

# Create a large list in trusted code
count = sys.suspendsandboxlimits()  # Returns 1
large_list = list(range(1000))       # Works - limits suspended
sys.resumesandboxlimits()            # Limits active again

# Now this would fail
try:
    another_list = list(range(100))  # SandboxOverflowError
except SandboxOverflowError:
    pass
```

### Nested Suspend/Resume

Suspend calls nest. Limits resume only when the count reaches 0:

```python
sys.suspendsandboxlimits()  # count = 1
sys.suspendsandboxlimits()  # count = 2
sys.resumesandboxlimits()   # count = 1 (still suspended)
sys.resumesandboxlimits()   # count = 0 (limits active again)
```

### Check Suspend Status

```python
if sys.issandboxsuspended():
    print("Limits are currently suspended")
```

### Context Manager Pattern

For cleaner code, wrap suspend/resume in a context manager:

```python
from contextlib import contextmanager

@contextmanager
def sandbox_suspended():
    sys.suspendsandboxlimits()
    try:
        yield
    finally:
        sys.resumesandboxlimits()

# Usage:
with sandbox_suspended():
    # All limits bypassed here
    large_data = process_untrusted_output(result)
```

### What Suspend Bypasses

Suspend bypasses **all** sandbox restrictions:
- Size limits (int, str, bytes, list, dict, set, tuple)
- Type restrictions (float, complex)
- Allocation counting
- Statement counting
- Iteration counting
- Frozen mode
- Dunder access blocking
- Opcode restrictions

---

## Exception Handling

All sandbox violations raise exceptions from a dedicated hierarchy.

### Exception Hierarchy

```
Exception
 +-- SandboxError                    # Base class for all sandbox violations
      +-- SandboxOverflowError       # Size/length limit exceeded
      +-- SandboxMemoryError         # Allocation limit exceeded
      +-- SandboxRuntimeError        # Statement/iteration limit, banned opcode
      +-- SandboxTypeError           # Forbidden type creation
      +-- SandboxAttributeError      # Frozen mode or dunder access blocked
```

### Catching All Sandbox Errors

```python
try:
    exec(sandboxed_code)
except SandboxError as e:
    # Catches any sandbox violation
    print(f"Sandbox violation: {type(e).__name__}: {e}")
```

### Catching Specific Errors

```python
try:
    exec(sandboxed_code)
except SandboxOverflowError:
    print("Data too large")
except SandboxMemoryError:
    print("Too many object allocations")
except SandboxRuntimeError:
    print("Execution limit exceeded (statements, iterations, or banned opcode)")
except SandboxTypeError:
    print("Forbidden type creation attempted")
except SandboxAttributeError:
    print("Attribute access blocked (frozen mode or dunder)")
except SandboxError:
    print("Other sandbox violation")
```

### Exception Availability

All sandbox exceptions are available as builtins -- no import needed:

```python
# These all work without imports:
try:
    exec(code)
except SandboxError:
    pass
except SandboxOverflowError:
    pass
```

### Single-Raise Behavior

Statement and iteration limits raise their exception **exactly once** on first violation. This allows `except` and `finally` blocks to execute normally:

```python
sys.setsandboxlimits(scope_max_statements=100)
sys.addsandboxfilename("<sandbox>")
sys.resetsandboxcounters()

code = compile("""
try:
    while True:
        pass  # Will hit statement limit
except SandboxRuntimeError:
    # This except block runs normally (no second exception)
    result = "caught"
""", "<sandbox>", "exec")

ns = {}
exec(code, ns)
print(ns["result"])  # "caught"
```

---

## Complete Examples

### Example 1: Safe Code Evaluation

```python
import sys

def safe_eval(source, allowed_globals=None, timeout_statements=100_000):
    """Safely evaluate Python code with sandbox limits."""
    # Save original limits
    original = sys.getsandboxlimits()

    try:
        # Configure sandbox
        sys.setsandboxlimits(
            max_int_digits=50,
            max_str_length=50_000,
            max_bytes_length=50_000,
            max_list_size=50_000,
            max_dict_size=10_000,
            max_set_size=10_000,
            max_tuple_size=50_000,
            scope_max_statements=timeout_statements,
            scope_max_iterations=500_000,
            scope_max_allocations=5_000,
            global_max_allocations=50_000,
            allow_dunder_access=False,
        )

        # Set up scope
        sys.addsandboxfilename("<safe-eval>")
        sys.resetsandboxcounters()

        # Enable frozen mode to protect shared state
        sys.setsandboxfrozenmode(True)

        # Prepare namespace
        namespace = {"__builtins__": __builtins__}
        if allowed_globals:
            namespace.update(allowed_globals)

        # Mark namespace as mutable so sandboxed code can write results
        sys.sandboxsetobjectmutable(namespace)

        # Compile and execute
        code = compile(source, "<safe-eval>", "exec")
        exec(code, namespace)

        return namespace

    except SandboxError as e:
        return {"error": f"{type(e).__name__}: {e}"}

    finally:
        sys.setsandboxfrozenmode(False)
        sys.clearsandboxfilenames()
        sys.setsandboxlimits(**original)
        sys.resetsandboxcounters()


# Usage
result = safe_eval("x = sum(range(100))")
print(result.get("x"))  # 4950

result = safe_eval("while True: pass")
print(result.get("error"))  # "SandboxRuntimeError: Sandbox statement limit exceeded"
```

### Example 2: Restricted Expression Evaluator

```python
import sys
import dis

def eval_expression(expr):
    """Evaluate a mathematical expression with strong restrictions."""
    original = sys.getsandboxlimits()

    try:
        # Strict limits for expressions
        sys.setsandboxlimits(
            max_int_digits=20,
            max_str_length=1000,
            allow_float=True,
            allow_complex=False,
            allow_dunder_access=False,
            scope_max_statements=100,
            scope_max_iterations=1000,
        )

        # Ban imports
        banned = {
            dis.opmap['IMPORT_NAME'],
            dis.opmap['IMPORT_FROM'],
            dis.opmap['IMPORT_STAR'],
        }
        sys.setsandboxbannedopcodes(banned)
        sys.setsandboxopcoderestrictmode(True)

        # Set up scope
        sys.addsandboxfilename("<expr>")
        sys.resetsandboxcounters()

        # Compile as eval (expression only, no statements)
        code = compile(expr, "<expr>", "eval")
        result = eval(code, {"__builtins__": {}})
        return result

    except SandboxError as e:
        raise ValueError(f"Expression error: {e}") from e

    finally:
        sys.setsandboxopcoderestrictmode(False)
        sys.setsandboxbannedopcodes(None)
        sys.clearsandboxfilenames()
        sys.setsandboxlimits(**original)
        sys.resetsandboxcounters()


# Usage
print(eval_expression("2 + 3 * 4"))    # 14
print(eval_expression("2 ** 10"))       # 1024
```

### Example 3: Multi-Tenant Code Runner

```python
import sys

class SandboxRunner:
    """Run code for multiple tenants with per-tenant limits."""

    def __init__(self, max_statements=50_000, max_allocations=10_000):
        self.max_statements = max_statements
        self.max_allocations = max_allocations

    def run(self, tenant_id, source):
        """Run source code for a tenant, return results or error."""
        filename = f"<tenant-{tenant_id}>"
        original = sys.getsandboxlimits()

        try:
            sys.setsandboxlimits(
                max_int_digits=50,
                max_str_length=10_000,
                max_bytes_length=10_000,
                max_list_size=10_000,
                max_dict_size=5_000,
                max_set_size=5_000,
                max_tuple_size=10_000,
                scope_max_statements=self.max_statements,
                scope_max_iterations=self.max_statements * 10,
                scope_max_allocations=self.max_allocations,
                allow_dunder_access=False,
            )

            sys.addsandboxfilename(filename)
            sys.resetsandboxcounters()
            sys.setsandboxfrozenmode(True)

            namespace = {"__builtins__": __builtins__}
            sys.sandboxsetobjectmutable(namespace)

            code = compile(source, filename, "exec")
            exec(code, namespace)

            counts = sys.getsandboxcounts()
            return {
                "success": True,
                "namespace": {k: v for k, v in namespace.items()
                             if not k.startswith("_")},
                "statements": counts["scope_statement_count"],
                "allocations": counts["scope_allocation_count"],
            }

        except SandboxError as e:
            counts = sys.getsandboxcounts()
            return {
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "statements": counts["scope_statement_count"],
                "allocations": counts["scope_allocation_count"],
            }

        finally:
            sys.setsandboxfrozenmode(False)
            sys.clearsandboxfilenames()
            sys.setsandboxlimits(**original)
            sys.resetsandboxcounters()


# Usage
runner = SandboxRunner()

result = runner.run("alice", "x = [i**2 for i in range(10)]")
print(result)
# {'success': True, 'namespace': {'x': [0, 1, 4, 9, 16, 25, 36, 49, 64, 81]},
#  'statements': ..., 'allocations': ...}

result = runner.run("bob", "while True: pass")
print(result)
# {'success': False, 'error': 'SandboxRuntimeError: ...', ...}
```

---

## Best Practices

### 1. Always Use Scope Tracking

Without scope tracking, scoped limits (statements, iterations, scoped allocations) are not enforced. Always register filenames:

```python
# Good
sys.addsandboxfilename("<sandbox>")
code = compile(source, "<sandbox>", "exec")

# Bad - scoped limits won't apply
code = compile(source, "<string>", "exec")
# ("<string>" is not registered, so no scoped enforcement)
```

### 2. Reset Counters Before Each Execution

```python
sys.resetsandboxcounters()  # Always reset before running untrusted code
exec(code)
```

### 3. Clean Up in Finally Blocks

Always restore sandbox state, even if execution fails:

```python
original = sys.getsandboxlimits()
try:
    sys.setsandboxlimits(...)
    sys.addsandboxfilename("<sandbox>")
    exec(code)
finally:
    sys.setsandboxfrozenmode(False)
    sys.setsandboxopcoderestrictmode(False)
    sys.setsandboxbannedopcodes(None)
    sys.clearsandboxfilenames()
    sys.setsandboxlimits(**original)
    sys.resetsandboxcounters()
```

### 4. Use Both Statement and Iteration Limits

Statement limits catch Python-level loops, but C builtins like `sum()`, `list()`, `sorted()` bypass the statement counter. Use iteration limits to catch these:

```python
sys.setsandboxlimits(
    scope_max_statements=100_000,   # Catches: while True: pass
    scope_max_iterations=1_000_000, # Catches: sum(range(10**9))
)
```

### 5. Combine Multiple Protections

No single limit is sufficient. Use multiple layers:

```python
sys.setsandboxlimits(
    # Data size limits
    max_list_size=100_000,
    max_str_length=100_000,

    # Execution limits
    scope_max_statements=100_000,
    scope_max_iterations=1_000_000,

    # Memory limits
    scope_max_allocations=10_000,
    global_max_allocations=100_000,

    # Access control
    allow_dunder_access=False,
)

# Plus frozen mode for shared state protection
sys.setsandboxfrozenmode(True)

# Plus opcode restrictions for import blocking
sys.setsandboxbannedopcodes({dis.opmap['IMPORT_NAME'], ...})
sys.setsandboxopcoderestrictmode(True)
```

### 6. Use Mutable Objects for Output

When frozen mode is active, mark output containers as mutable:

```python
output = {}
sys.sandboxsetobjectmutable(output)
# Sandboxed code can write to output even in frozen mode
```

### 7. Security Warning

The sandbox limits are designed for resource protection, not as a complete security boundary. Code with access to C extensions, `ctypes`, or other low-level APIs can bypass these limits. For maximum restriction:

- Ban import opcodes
- Remove dangerous builtins from the namespace
- Block dunder access
- Use frozen mode
- Consider running in a subprocess with OS-level sandboxing

---

## API Quick Reference

### Limit Configuration

| Function | Description |
|----------|-------------|
| `sys.setsandboxlimits(**kwargs)` | Set resource limits |
| `sys.getsandboxlimits() -> dict` | Get current limits |
| `sys.getsandboxcounts() -> dict` | Get current counters |
| `sys.resetsandboxcounters()` | Reset all counters to 0 |

### Scope Management

| Function | Description |
|----------|-------------|
| `sys.entersandboxscope()` | Register current frame + reset counters |
| `sys.exitsandboxscope()` | Clear all registered filenames |
| `sys.issandboxinscope() -> bool` | Check if current code is in scope |
| `sys.addsandboxframe()` | Register current frame's filename |
| `sys.addsandboxfilename(name)` | Register a filename |
| `sys.removesandboxfilename(name)` | Remove a filename |
| `sys.clearsandboxfilenames()` | Clear all filenames |

### Frozen Mode

| Function | Description |
|----------|-------------|
| `sys.setsandboxfrozenmode(bool)` | Enable/disable global freeze |
| `sys.getsandboxfrozenmode() -> bool` | Check global freeze status |
| `sys.sandboxfreezeobject(obj)` | Freeze a specific object |
| `sys.sandboxisobjectfrozen(obj) -> bool` | Check if object is frozen |
| `sys.sandboxsetobjectmutable(obj, bool)` | Set/clear mutable flag |

### Opcode Restrictions

| Function | Description |
|----------|-------------|
| `sys.setsandboxopcoderestrictmode(bool)` | Enable/disable opcode checking |
| `sys.getsandboxopcoderestrictmode() -> bool` | Check mode status |
| `sys.setsandboxbannedopcodes(set/None)` | Set banned opcodes |
| `sys.getsandboxbannedopcodes() -> frozenset` | Get banned opcodes |

### Object Creation Hook

| Function | Description |
|----------|-------------|
| `sys.setobjectcreationhook(callable/None)` | Set/remove creation hook |
| `sys.getobjectcreationhook() -> callable` | Get current hook |

### Suspend/Resume

| Function | Description |
|----------|-------------|
| `sys.suspendsandboxlimits() -> int` | Suspend limits |
| `sys.resumesandboxlimits() -> int` | Resume limits |
| `sys.issandboxsuspended() -> bool` | Check suspend status |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `SandboxError` | Base class for all sandbox violations |
| `SandboxOverflowError` | Size/length limit exceeded |
| `SandboxMemoryError` | Allocation limit exceeded |
| `SandboxRuntimeError` | Statement/iteration limit or banned opcode |
| `SandboxTypeError` | Forbidden type creation |
| `SandboxAttributeError` | Frozen mode or dunder access blocked |

### `setsandboxlimits` Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_int_digits` | int | 0 | Max internal integer digits |
| `max_str_length` | int | 0 | Max string characters |
| `max_bytes_length` | int | 0 | Max bytes length |
| `max_list_size` | int | 0 | Max list items |
| `max_dict_size` | int | 0 | Max dict entries |
| `max_set_size` | int | 0 | Max set members |
| `max_tuple_size` | int | 0 | Max tuple items |
| `global_max_allocations` | int | 0 | Max total GC-tracked allocations |
| `scope_max_statements` | int | 0 | Max statements in scope |
| `scope_max_allocations` | int | 0 | Max allocations in scope |
| `scope_max_iterations` | int | 0 | Max iterator steps in scope |
| `allow_float` | bool | True | Allow float creation |
| `allow_complex` | bool | True | Allow complex creation |
| `allow_dunder_access` | bool | True | Allow `__dunder__` attributes |
