# CPython Sandbox Usage Guide

A practical guide for using the CPython sandbox to safely execute untrusted Python code with resource limits and restrictions.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Core Concepts](#core-concepts)
3. [Setting Resource Limits](#setting-resource-limits)
4. [Scope Management](#scope-management)
5. [Execution Limits](#execution-limits)
6. [Operation Counting](#operation-counting)
7. [Frozen Mode](#frozen-mode)
8. [Dunder Access Control](#dunder-access-control)
9. [Unsafe Operations](#unsafe-operations)
10. [I/O Restrictions](#io-restrictions)
11. [Import Restrictions](#import-restrictions)
12. [Module Access Restrictions](#module-access-restrictions)
13. [Opcode Restrictions](#opcode-restrictions)
14. [Object Creation Hooks](#object-creation-hooks)
15. [Suspend/Resume for Trusted Code](#suspendresume-for-trusted-code)
16. [Context Managers](#context-managers)
17. [Exception Handling](#exception-handling)
18. [Complete Examples](#complete-examples)
19. [Best Practices](#best-practices)
20. [Do's and Don'ts](#dos-and-donts)
21. [Security Considerations](#security-considerations)
22. [API Quick Reference](#api-quick-reference)

---

## Quick Start

The sandbox is accessed through the `sys` module. Here is a minimal example that sets up limits and runs untrusted code:

```python
import sys

# 1. Set resource limits
sys.sandbox.set_config(
    max_list_size=10_000,
    max_str_length=10_000,
    max_iterations=100_000,
    max_operations=50_000,  # AST-level operation counting
    allow_dunder_access=False,
)

# 2. Register a filename for scope tracking
sys.sandbox.add_filename("<sandbox>")

# 3. Reset counters before each execution
sys.sandbox.reset_counts()

# 4. Compile with operation counting flag and execute untrusted code
untrusted_code = """
result = sum(range(100))
"""

PyCF_SANDBOX_COUNT = 0x8000  # Flag for operation counting
code = compile(untrusted_code, "<sandbox>", "exec", flags=PyCF_SANDBOX_COUNT)
namespace = {}
try:
    exec(code, namespace)
    print("Result:", namespace.get("result"))
except SandboxError as e:
    print(f"Sandbox violation: {e}")
finally:
    sys.sandbox.clear_filenames()
```

---

## Core Concepts

### Sandbox State

The sandbox state is global to the interpreter. All limits, counters, and configuration are shared across all threads within the same interpreter.

### Scoped Limits

All sandbox limits are scoped -- they only apply to code whose `co_filename` is registered in the sandbox. This includes:

- Size limits (`max_list_size`, `max_str_length`, etc.)
- Type restrictions (`allow_float`, `allow_complex`)
- `max_iterations` -- limits iterator steps
- `max_operations` -- limits AST-level operations (requires `PyCF_SANDBOX_COUNT` compile flag)
- `max_recursion_depth` -- limits sandbox frame recursion depth

Code outside the registered filenames (e.g., stdlib, builtins, your harness) is not affected by any sandbox limits.

### Scope Tracking

The sandbox determines which code is "sandboxed" by tracking filenames. When you compile code with `compile(source, "<sandbox>", "exec")` and register `"<sandbox>"` as a sandbox filename, all scoped limits apply to that code.

### Zero Means No Limit

All numeric limit values default to `0`, which means no limit. You must explicitly set non-zero values to enable enforcement.

---

## Setting Resource Limits

### Data Size Limits

Control the maximum size of built-in data types:

```python
sys.sandbox.set_config(
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
sys.sandbox.set_config(max_list_size=10)
try:
    big_list = list(range(100))
except SandboxOverflowError as e:
    print(e)  # "List size (100) exceeds sandbox limit (10)"
```

### Type Restrictions

Forbid creation of specific types:

```python
sys.sandbox.set_config(
    allow_float=False,    # Forbid float creation
    allow_complex=False,  # Forbid complex creation
)
```

Attempting to create a forbidden type raises `SandboxTypeError`:

```python
sys.sandbox.set_config(allow_float=False)
try:
    x = 1.0  # SandboxTypeError: float type is forbidden in sandbox
except SandboxTypeError:
    pass
```

### Reading Current Limits

```python
limits = sys.sandbox.get_config()
# Returns dict with all current limit values:
# {'max_int_digits': 100, 'max_str_length': 100000, ...,
#  'allow_float': True, 'allow_complex': True, 'allow_dunder_access': True}
```

### Resetting All State

Reset all limits, counters, modes, scope, and hooks to defaults:

```python
sys.sandbox.reset()  # All limits to 0, modes to defaults, counters to 0
```

---

## Scope Management

All sandbox limits require registering filenames to determine which code is "in scope".

### Method 1: Using `enter_scope()` (Simple)

For executing code in the current frame's context:

```python
sys.sandbox.set_config(max_iterations=10_000)

sys.sandbox.enter_scope()  # Registers current frame's filename + resets counters
try:
    # Code executed here and below is in scope
    exec(some_code)
finally:
    sys.sandbox.exit_scope()  # Clears all registered filenames
```

### Method 2: Using Filenames (Recommended)

For explicit control over what code is tracked:

```python
PyCF_SANDBOX_COUNT = 0x8000

sys.sandbox.set_config(max_operations=10_000)

# Register a virtual filename
sys.sandbox.add_filename("<user-code>")
sys.sandbox.reset_counts()

# Compile untrusted code with that filename and operation counting flag
code = compile(user_source, "<user-code>", "exec", flags=PyCF_SANDBOX_COUNT)
try:
    exec(code)
except SandboxRuntimeError:
    print("Operation limit exceeded")
finally:
    sys.sandbox.clear_filenames()
```

This approach is preferred because:
- Only the user's code counts toward limits (not your harness code)
- The stdlib and builtins don't count toward scoped limits
- You have fine-grained control over what is tracked

### Method 3: Using `add_frame()`

Register the current frame's filename without resetting counters:

```python
sys.sandbox.add_frame()  # Adds current frame's co_filename to tracked set
```

### Checking Scope Status

```python
if sys.sandbox.in_scope():
    print("Currently executing in sandbox scope")
```

### Managing Filenames

```python
sys.sandbox.add_filename("<module-a>")
sys.sandbox.add_filename("<module-b>")
sys.sandbox.remove_filename("<module-a>")  # Remove specific filename
sys.sandbox.clear_filenames()               # Remove all filenames
```

---

## Execution Limits

### Operation Limit

Prevents infinite loops and long-running code by counting AST-level operations within scope. Operations are counted via `SANDBOX_COUNT` opcodes emitted by the compiler when `PyCF_SANDBOX_COUNT` flag is used:

```python
PyCF_SANDBOX_COUNT = 0x8000

sys.sandbox.set_config(max_operations=1000)
sys.sandbox.add_filename("<sandbox>")
sys.sandbox.reset_counts()

code = compile("""
x = 0
while True:
    x += 1  # Each iteration counts operations (While, AugAssign, BinOp)
""", "<sandbox>", "exec", flags=PyCF_SANDBOX_COUNT)

try:
    exec(code)
except SandboxRuntimeError as e:
    print(e)  # "Sandbox operation limit exceeded"
```

### Iteration Limit

Prevents excessive iteration even through C builtins like `sum()`, `list()`, `sorted()`:

```python
sys.sandbox.set_config(max_iterations=10_000)
sys.sandbox.add_filename("<sandbox>")
sys.sandbox.reset_counts()

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

### Recursion Limit

Limits the depth of sandbox-scoped frames in the call stack to prevent stack exhaustion:

```python
sys.sandbox.set_config(max_recursion_depth=100)
sys.sandbox.add_filename("<sandbox>")

code = compile("""
def recurse(n):
    return recurse(n + 1)
recurse(0)
""", "<sandbox>", "exec")

try:
    exec(code)
except SandboxRecursionError:
    print("Recursion limit reached")
```

### Reading Counters

Check current counter values at any time:

```python
counts = sys.sandbox.get_counts()
print(f"Iterator steps: {counts['iteration_count']}")
print(f"Operations counted: {counts['operation_count']}")
```

### Resetting Counters

Reset all counters to 0 before each execution:

```python
sys.sandbox.reset_counts()
```

---

## Operation Counting

Operation counting provides an alternative to statement counting that works at the AST level. Instead of counting source lines via tracing, the compiler emits `SANDBOX_COUNT` opcodes at specific AST nodes. This has zero overhead for non-sandbox code and does not depend on the tracing mechanism.

### How It Works

1. **Compile with `PyCF_SANDBOX_COUNT` flag**: Code must be compiled with `flags=0x8000` to enable operation counting.
2. **Set `max_operations`**: Configure the maximum number of counted operations.
3. **Register filenames and reset counters**: Same as with statement counting.

### Basic Usage

```python
import sys

PyCF_SANDBOX_COUNT = 0x8000

sys.sandbox.set_config(max_operations=1000)
sys.sandbox.add_filename("<sandbox>")
sys.sandbox.reset_counts()

# Compile with the SANDBOX_COUNT flag
code = compile(user_source, "<sandbox>", "exec", flags=PyCF_SANDBOX_COUNT)

try:
    exec(code, {"__builtins__": __builtins__})
except SandboxRuntimeError as e:
    print(e)  # "Sandbox operation limit exceeded"
finally:
    sys.sandbox.clear_filenames()
```

### What Gets Counted

Each `SANDBOX_COUNT` opcode increments the `operation_count` counter. The compiler emits one opcode per AST node for:

**Counted Statements:**
- `Assign`, `AugAssign`, `Delete`
- `Pass`, `Break`, `Continue`, `Return`
- `If`, `For`, `While`, `Try`
- `Import`, `ImportFrom`
- `Assert`
- `FunctionDef`, `ClassDef`

**Counted Expressions:**
- `Call` (function/method calls)
- `BinOp` (e.g., `a + b`)
- `UnaryOp` (e.g., `-a`)
- `Compare` (e.g., `a < b`)
- `BoolOp` (e.g., `a and b`)
- `Attribute` (e.g., `obj.attr`)
- `Subscript` (e.g., `a[0]`)

**Not Counted:**
- `Expr` statement wrapper (the inner expression is counted instead)
- `Global`, `Nonlocal` (compile-time directives)
- Literal values, `Name` loads, `Starred`

### Counting Examples

```python
# a = 1          -> Assign(1) = 1 operation
# a = len([])    -> Assign(1) + Call(1) = 2 operations
# a = len([]) + 1 -> Assign(1) + Call(1) + BinOp(1) = 3 operations
# for i in range(3): a = i -> For(1) + Call(1) + Assign*3 = 5 operations
```

### Reading the Operation Counter

```python
counts = sys.sandbox.get_counts()
print(f"Operations: {counts['operation_count']}")
```

### Zero Overhead When Disabled

Code compiled **without** `PyCF_SANDBOX_COUNT` has zero operation counting overhead. Code compiled **with** the flag but without `max_operations` set has minimal overhead (one pointer dereference + comparison per counted node).

### Counting Iterations as Operations

By default, iterator steps only increment `iteration_count`. When `count_iterations_as_operations` is enabled, each iterator yield also increments `operation_count`, allowing you to enforce a single unified limit via `max_operations` for both AST-level operations and iterator steps:

```python
sys.sandbox.set_config(
    max_operations=10_000,
    count_iterations_as_operations=True,
)
sys.sandbox.add_filename("<sandbox>")
sys.sandbox.reset_counts()

code = compile("""
total = sum(range(1_000_000))  # Each iterator step counts as an operation
""", "<sandbox>", "exec", flags=0x8000)

try:
    exec(code)
except SandboxRuntimeError:
    print("Operation limit exceeded (includes iteration steps)")
finally:
    sys.sandbox.clear_filenames()
```

The flag can also be set as a property:

```python
sys.sandbox.count_iterations_as_operations = True
```

### No-Flag Code Is Not Counted

Code compiled without `PyCF_SANDBOX_COUNT` does not contain `SANDBOX_COUNT` opcodes, so operations are never counted regardless of limits:

```python
# This code will NOT count operations (no flag)
code = compile("a = 1\nb = 2", "<sandbox>", "exec")

# This code WILL count operations (flag set)
code = compile("a = 1\nb = 2", "<sandbox>", "exec", flags=0x8000)
```

---

## Frozen Mode

Frozen mode prevents attribute modifications (set/delete) on objects. This is useful for protecting shared state from sandboxed code.

### Global Frozen Mode

Block all attribute mutations within sandbox scope:

```python
# Set up scope first
sys.sandbox.add_filename("<sandbox>")

# Enable frozen mode
sys.sandbox.frozen_mode = True

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
    sys.sandbox.frozen_mode = False
    sys.sandbox.clear_filenames()
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
sys.sandbox.freeze(config)

# Now even without global frozen mode:
try:
    config.api_key = "hacked"  # SandboxAttributeError
except SandboxAttributeError:
    print("Cannot modify frozen config")

# Check if frozen
print(sys.sandbox.is_frozen(config))  # True
```

### Mutable Override

Mark specific objects as always mutable, even when global frozen mode is active:

```python
# Create an output object that sandboxed code CAN modify
output = type('Output', (), {})()
sys.sandbox.set_mutable(output)

sys.sandbox.frozen_mode = True
sys.sandbox.add_filename("<sandbox>")

code = compile("""
output.result = 42  # Allowed because output is marked mutable
""", "<sandbox>", "exec")

exec(code, {"output": output})
print(output.result)  # 42

# Remove mutable flag if needed
sys.sandbox.set_mutable(output, False)
```

### Auto-Mutable Mode

When frozen mode is active, sandboxed code cannot modify any objects -- including objects it creates itself (classes, instances, functions). Auto-mutable mode solves this by automatically marking newly created objects as mutable when they are created within sandbox scope.

```python
# Enable both frozen mode and auto-mutable mode
sys.sandbox.frozen_mode = True
sys.sandbox.auto_mutable = True
sys.sandbox.add_filename("<sandbox>")

code = compile("""
class Foo:
    pass
obj = Foo()
obj.x = 42  # Allowed - obj was created in sandbox scope and auto-marked mutable
""", "<sandbox>", "exec")

exec(code)

# Check the mode
print(sys.sandbox.auto_mutable)  # True

# Clean up
sys.sandbox.auto_mutable = False
sys.sandbox.frozen_mode = False
sys.sandbox.clear_filenames()
```

Auto-mutable mode automatically applies `Py_OBJFLAGS_MUTABLE` to objects created via `type.__call__` (classes and instances) and `MAKE_FUNCTION` (function definitions) when:
- Both `auto_mutable` and `frozen_mode` are active
- The current frame is within sandbox scope
- The sandbox is not suspended

This allows sandboxed code to define and use its own classes and functions naturally while still preventing modification of imported or pre-existing objects.

### Frozen Mode with Scope

Frozen mode is scope-aware. Only code with registered filenames is restricted:

```python
sys.sandbox.add_filename("<sandbox>")
sys.sandbox.frozen_mode = True

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
sys.sandbox.set_config(allow_dunder_access=False)
sys.sandbox.add_filename("<sandbox>")

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

### Implicit Dunder Blocking

When `allow_dunder_access=False`, certain implicit dunder operations are also restricted:

- `__iter__` access is blocked when `allow_unsafe=False` (default), preventing custom iterator protocol abuse
- This helps prevent sandbox escapes through iterator manipulation

### Scope-Aware

Dunder blocking only applies within sandbox scope. Your harness code can freely use dunder attributes:

```python
sys.sandbox.set_config(allow_dunder_access=False)
sys.sandbox.add_filename("<sandbox>")

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

## Unsafe Operations

The `allow_unsafe` setting controls access to operations that could be used to escape the sandbox or inspect internal state.

### Default Behavior

By default, `allow_unsafe=False`, blocking dangerous operations:

```python
import sys

sys.sandbox.add_filename("<sandbox>")

# compile() is blocked by default
code = compile("""
eval(compile('import os', '<x>', 'exec'))
""", "<sandbox>", "exec")

try:
    exec(code)
except SandboxSecurityError as e:
    print(e)  # "compile() is not allowed in sandbox scope"
```

### Blocked Operations

When `allow_unsafe=False` (default), these operations are blocked in sandbox scope:

| Operation | Risk | Description |
|-----------|------|-------------|
| `compile()` | Code injection | Sandboxed code cannot compile new code objects |
| `__iter__` access | Iterator abuse | Blocks direct `__iter__` attribute access |
| `gc` module introspection | Object discovery | Blocks `gc.get_objects()`, `gc.get_referrers()`, etc. |
| `frame.f_code` | Code inspection | Blocks access to frame code objects |

### Enabling Unsafe Operations

Only enable if you trust the code or have other mitigations:

```python
sys.sandbox.set_config(allow_unsafe=True)
sys.sandbox.add_filename("<sandbox>")

# Now compile() works
code = compile("result = compile('1+1', '<x>', 'eval')", "<sandbox>", "exec")
exec(code)  # Works
```

### Why Block These?

- **`compile()`**: Allows generating code that bypasses sandbox restrictions or constructs escape payloads dynamically
- **`gc` introspection**: `gc.get_objects()` can find references to sensitive objects (modules, frames, etc.)
- **`frame.f_code`**: Allows inspecting local variables and code structure of calling frames
- **`__iter__`**: Can be used in complex sandbox escape chains

---

## I/O Restrictions

Block all I/O operations (file, socket, raw fd) in sandbox scope to prevent data exfiltration and unauthorized system access.

### Default Behavior

By default, `allow_io` is `False`, meaning all I/O operations are blocked in sandbox scope:

```python
import sys

sys.sandbox.add_filename("<sandbox>")

# In sandbox scope - I/O is blocked by default
code = compile('open("/tmp/test.txt", "w")', "<sandbox>", "exec")
try:
    exec(code)
except SandboxSecurityError as e:
    print(e)  # "open() is not allowed in sandbox scope (I/O blocked)"
```

### Blocked Operations

When `allow_io=False` (default), the following operations are blocked in sandbox scope:

| Operation | Description |
|-----------|-------------|
| `open()` | High-level file open |
| `FileIO()` | Low-level file I/O |
| `socket()` | Socket creation |
| `os.open()` | Raw file descriptor open |
| `os.read()` | Raw fd read |
| `os.write()` | Raw fd write |
| `os.close()` | Raw fd close |
| `os.closerange()` | Batch fd close |
| `os.dup()` | fd duplication |
| `os.dup2()` | fd duplication to specific fd |
| `os.pipe()` | Pipe creation |

### Allowed Operations

In-memory I/O remains allowed even with `allow_io=False`:

```python
from io import StringIO, BytesIO

# These work even with allow_io=False
s = StringIO()
s.write("hello")

b = BytesIO()
b.write(b"world")
```

### Enabling I/O

If your sandbox needs I/O access (less secure), enable it explicitly:

```python
sys.sandbox.allow_io = True
sys.sandbox.add_filename("<sandbox>")

# Now I/O operations are allowed
code = compile('open("/tmp/test.txt", "w").close()', "<sandbox>", "exec")
exec(code)  # Works
```

### Scope Behavior

The I/O check uses the sandbox's scope mechanism. Operations called from code whose `co_filename` is registered in the sandbox are blocked. Operations called from unregistered code (stdlib, your harness) are allowed.

```python
# If socket.py is NOT registered, high-level socket.socket() may not be blocked
# because the actual C init is called from socket.py, not <sandbox>

# For complete I/O blocking, register wrapper modules too:
import socket
sys.sandbox.add_filename(socket.__file__)
sys.sandbox.add_filename("<sandbox>")
```

---

## Import Restrictions

Control which modules can be imported within sandbox scope using an import allowlist.

### Default Behavior

By default, `import_restrict_mode=True` with an empty allowlist, meaning **all imports are blocked** in sandbox scope:

```python
import sys

sys.sandbox.add_filename("<sandbox>")

code = compile("import json", "<sandbox>", "exec")
try:
    exec(code)
except SandboxImportError as e:
    print(e)  # "Import of 'json' is not allowed in sandbox"
```

### Setting Up an Import Allowlist

Use the `allowed_imports` property to specify which imports are permitted:

```python
# Allow specific imports
sys.sandbox.allowed_imports = {
    ("json", ""),           # Allow: import json, from json import *
    ("json", "loads"),      # Allow: from json import loads
    ("json", "dumps"),      # Allow: from json import dumps
    ("math", ""),           # Allow: import math, from math import *
    ("datetime", "date"),   # Allow: from datetime import date
}

sys.sandbox.add_filename("<sandbox>")

code = compile("""
import json           # OK - ("json", "") allows it
from json import loads  # OK - ("json", "loads") allows it
from math import sqrt   # OK - ("math", "") allows all from math
import os              # SandboxImportError - not in allowlist
""", "<sandbox>", "exec")
```

### Allowlist Format

The allowlist is a set of `(module_name, import_name)` tuples:

| Entry | What It Allows |
|-------|----------------|
| `("json", "")` | `import json` and `from json import *` (any name) |
| `("json", "loads")` | Only `from json import loads` |
| `("json", "*")` | `from json import *` |
| `("os.path", "")` | `import os.path` and `from os.path import *` |

### Submodule Access

Control whether importing a parent allows access to submodules:

```python
# Allow submodule access (parent import grants child access)
sys.sandbox.import_allow_submodules = True
sys.sandbox.allowed_imports = {("os", "")}

# Now "import os.path" works because "os" is allowed
# and submodules are permitted
```

By default, `import_allow_submodules=False`, requiring explicit allowlist entries for each submodule.

### Using Default Safe Modules

For convenience, load a curated set of safe modules:

```python
sys.sandbox.use_default_allowed_modules()

# This enables module_access_restrict_mode and sets allowed_modules to:
# - Data: json, collections, enum, dataclasses, typing, types, copy, pprint, reprlib
# - Math: math, decimal, fractions, statistics
# - Strings: string, re, textwrap, unicodedata
# - Date/Time: datetime, calendar, zoneinfo
# - Binary: struct, base64, binascii, quopri, uu
# - Crypto: hashlib, hmac
# - Functional: functools, itertools, operator
# - Context: contextlib
# - ABC: abc
# - File formats: csv, html, html.parser, html.entities
# - Utilities: bisect, heapq, array, weakref, graphlib
# - Constants: errno, stat
# - Compression: zlib
```

### Disabling Import Restrictions

To allow all imports (less secure):

```python
sys.sandbox.import_restrict_mode = False
```

### Reading Current Settings

```python
print(sys.sandbox.import_restrict_mode)       # True/False
print(sys.sandbox.import_allow_submodules)    # True/False
print(sys.sandbox.allowed_imports)            # Set of (module, name) tuples
```

---

## Module Access Restrictions

Even if sandboxed code has a reference to a module (e.g., passed in via the namespace), module access restrictions can block its use.

### Purpose

Import restrictions prevent `import` statements, but code might receive module references through the namespace:

```python
import os
namespace = {"os": os, "__builtins__": __builtins__}
exec(sandboxed_code, namespace)  # Code has access to os module!
```

Module access restrictions add a second layer of defense by restricting which modules can be used, even if already imported.

### Enabling Module Access Restrictions

```python
sys.sandbox.module_access_restrict_mode = True
sys.sandbox.allowed_modules = frozenset({"json", "math"})
sys.sandbox.add_filename("<sandbox>")

import os
code = compile("os.getcwd()", "<sandbox>", "exec")

try:
    exec(code, {"os": os})
except SandboxSecurityError as e:
    print(e)  # "Access to module 'os' is not allowed in sandbox"
```

### Submodule Access

Control whether allowing a parent module grants access to its submodules:

```python
sys.sandbox.module_access_restrict_mode = True
sys.sandbox.allow_submodules = True  # Default
sys.sandbox.allowed_modules = frozenset({"os"})

# With allow_submodules=True, os.path is accessible because os is allowed
```

### Combined with Import Restrictions

For maximum security, use both:

```python
# Block imports
sys.sandbox.import_restrict_mode = True
sys.sandbox.allowed_imports = {("json", "")}

# Block module usage even if passed in
sys.sandbox.module_access_restrict_mode = True
sys.sandbox.allowed_modules = frozenset({"json"})
```

### Using Default Safe Modules

```python
sys.sandbox.use_default_allowed_modules()
# Sets both allowed_imports for import statements
# AND allowed_modules for module access
# with the same curated safe module list
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

sys.sandbox.banned_opcodes = banned
sys.sandbox.opcode_restrict_mode = True
sys.sandbox.add_filename("<sandbox>")

code = compile("""
import os  # SandboxRuntimeError: Opcode N is not allowed in sandbox scope
""", "<sandbox>", "exec")

try:
    exec(code)
except SandboxRuntimeError as e:
    print(e)
finally:
    sys.sandbox.opcode_restrict_mode = False
    sys.sandbox.banned_opcodes = None  # Clear all banned opcodes
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
banned = sys.sandbox.banned_opcodes  # Returns frozenset of ints
print(f"Banned opcodes: {banned}")

mode = sys.sandbox.opcode_restrict_mode
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

sys.sandbox.creation_hook = creation_hook

class Foo:
    pass

instance = Foo()  # Prints: Created Foo

sys.sandbox.creation_hook = None  # Remove hook
```

### Blocking Object Creation

```python
def block_types(obj, type_, frame, context):
    """Block creation of specific types."""
    if type_.__name__ in ('socket', 'Process'):
        raise SandboxTypeError(f"Cannot create {type_.__name__} in sandbox")
    return obj

sys.sandbox.creation_hook = block_types
```

### Replacing Objects

```python
def replace_hook(obj, type_, frame, context):
    """Replace objects at creation time."""
    if type_.__name__ == 'dict':
        # Replace with a read-only wrapper (hypothetical)
        return ReadOnlyDict(obj)
    return obj

sys.sandbox.creation_hook = replace_hook
```

### Reading Current Hook

```python
hook = sys.sandbox.creation_hook
if hook is not None:
    print(f"Hook active: {hook}")
```

---

## Suspend/Resume for Trusted Code

Temporarily bypass all sandbox limits when executing trusted code.

### Basic Usage

```python
sys.sandbox.set_config(max_list_size=10)

# Create a large list in trusted code
count = sys.sandbox.suspend()  # Returns 1
large_list = list(range(1000))       # Works - limits suspended
sys.sandbox.resume()            # Limits active again

# Now this would fail
try:
    another_list = list(range(100))  # SandboxOverflowError
except SandboxOverflowError:
    pass
```

### Nested Suspend/Resume

Suspend calls nest. Limits resume only when the count reaches 0:

```python
sys.sandbox.suspend()  # count = 1
sys.sandbox.suspend()  # count = 2
sys.sandbox.resume()   # count = 1 (still suspended)
sys.sandbox.resume()   # count = 0 (limits active again)
```

### Check Suspend Status

```python
if sys.sandbox.suspended:
    print("Limits are currently suspended")
```

### Context Manager Pattern

For cleaner code, wrap suspend/resume in a context manager:

```python
from contextlib import contextmanager

@contextmanager
def sandbox_suspended():
    sys.sandbox.suspend()
    try:
        yield
    finally:
        sys.sandbox.resume()

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
- Operation counting
- Frozen mode (including auto-mutable marking)
- Dunder access blocking
- Opcode restrictions
- Import restrictions
- Module access restrictions

---

## Context Managers

The sandbox provides built-in context managers for cleaner scope and suspend/resume handling.

### Scope Context Manager

Use `sys.sandbox.scope()` for automatic scope entry/exit:

```python
import sys

sys.sandbox.set_config(max_iterations=1000)

# Using the context manager
with sys.sandbox.scope():
    # Automatically calls enter_scope() on entry
    # Automatically calls exit_scope() on exit
    code = compile("x = sum(range(10))", "<sandbox>", "exec")
    exec(code)
# Scope automatically cleared here

# Equivalent manual code:
sys.sandbox.enter_scope()
try:
    code = compile("x = sum(range(10))", "<sandbox>", "exec")
    exec(code)
finally:
    sys.sandbox.exit_scope()
```

### Suspended Limits Context Manager

Use `sys.sandbox.suspended_limits()` for automatic suspend/resume:

```python
import sys

sys.sandbox.set_config(max_list_size=10)
sys.sandbox.add_filename("<sandbox>")

# Need to create large data structure in trusted code
with sys.sandbox.suspended_limits():
    # Automatically calls suspend() on entry
    # Automatically calls resume() on exit
    large_list = list(range(10000))  # Works - limits suspended
# Limits automatically restored here

# Equivalent manual code:
sys.sandbox.suspend()
try:
    large_list = list(range(10000))
finally:
    sys.sandbox.resume()
```

### Combining Context Managers

Context managers can be nested:

```python
import sys

sys.sandbox.set_config(
    max_iterations=1000,
    max_list_size=100,
)

with sys.sandbox.scope():
    # In sandbox scope
    code = compile("x = [1, 2, 3]", "<sandbox>", "exec")
    exec(code)

    with sys.sandbox.suspended_limits():
        # Temporarily bypass all limits
        big_data = prepare_large_dataset()

    # Back in scope with limits
    code2 = compile("y = x + [4, 5]", "<sandbox>", "exec")
    exec(code2)
```

### Exception Safety

Both context managers are exception-safe. Cleanup happens even if exceptions occur:

```python
try:
    with sys.sandbox.scope():
        exec(malicious_code)  # Raises SandboxError
except SandboxError:
    pass
# Scope is still properly cleared
assert not sys.sandbox.in_scope()
```

---

## Exception Handling

All sandbox violations raise exceptions from a dedicated hierarchy.

### Exception Hierarchy

```
Exception
 +-- SandboxError                    # Base class for all sandbox violations
      +-- SandboxOverflowError       # Size/length limit exceeded
      +-- SandboxMemoryError         # Allocation limit exceeded
      +-- SandboxRuntimeError        # Statement/iteration/operation limit, banned opcode
      +-- SandboxTypeError           # Forbidden type creation
      +-- SandboxAttributeError      # Frozen mode or dunder access blocked
      +-- SandboxSecurityError       # Security violation (I/O, unsafe ops, frame access, module access)
      +-- SandboxImportError         # Import not in allowlist
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
    print("Execution limit exceeded (statements, iterations, operations, or banned opcode)")
except SandboxTypeError:
    print("Forbidden type creation attempted")
except SandboxAttributeError:
    print("Attribute access blocked (frozen mode or dunder)")
except SandboxSecurityError:
    print("Security violation (I/O blocked, unsafe operation, frame access, module access)")
except SandboxImportError:
    print("Import not in allowlist")
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

Iteration and operation limits raise their exception **exactly once** on first violation. This allows `except` and `finally` blocks to execute normally:

```python
PyCF_SANDBOX_COUNT = 0x8000
sys.sandbox.set_config(max_operations=100)
sys.sandbox.add_filename("<sandbox>")
sys.sandbox.reset_counts()

code = compile("""
try:
    while True:
        pass  # Will hit operation limit
except SandboxRuntimeError:
    # This except block runs normally (no second exception)
    result = "caught"
""", "<sandbox>", "exec", flags=PyCF_SANDBOX_COUNT)

ns = {}
exec(code, ns)
print(ns["result"])  # "caught"
```

---

## Complete Examples

### Example 1: Safe Code Evaluation

```python
import sys

PyCF_SANDBOX_COUNT = 0x8000

def safe_eval(source, allowed_globals=None, max_ops=100_000):
    """Safely evaluate Python code with sandbox limits."""
    # Save original limits
    original = sys.sandbox.get_config()

    try:
        # Configure sandbox
        sys.sandbox.set_config(
            max_int_digits=50,
            max_str_length=50_000,
            max_bytes_length=50_000,
            max_list_size=50_000,
            max_dict_size=10_000,
            max_set_size=10_000,
            max_tuple_size=50_000,
            max_operations=max_ops,
            max_iterations=500_000,
            allow_dunder_access=False,
        )

        # Set up scope
        sys.sandbox.add_filename("<safe-eval>")
        sys.sandbox.reset_counts()

        # Enable frozen mode to protect shared state
        sys.sandbox.frozen_mode = True

        # Enable auto-mutable so sandboxed code can define and use its own
        # classes, functions, and instances without manual mutable marking
        sys.sandbox.auto_mutable = True

        # Prepare namespace
        namespace = {"__builtins__": __builtins__}
        if allowed_globals:
            namespace.update(allowed_globals)

        # Mark namespace as mutable so sandboxed code can write results
        sys.sandbox.set_mutable(namespace)

        # Compile with operation counting and execute
        code = compile(source, "<safe-eval>", "exec", flags=PyCF_SANDBOX_COUNT)
        exec(code, namespace)

        return namespace

    except SandboxError as e:
        return {"error": f"{type(e).__name__}: {e}"}

    finally:
        sys.sandbox.auto_mutable = False
        sys.sandbox.frozen_mode = False
        sys.sandbox.clear_filenames()
        sys.sandbox.set_config(**original)
        sys.sandbox.reset_counts()


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
    original = sys.sandbox.get_config()

    try:
        # Strict limits for expressions
        sys.sandbox.set_config(
            max_int_digits=20,
            max_str_length=1000,
            allow_float=True,
            allow_complex=False,
            allow_dunder_access=False,
            max_operations=100,
            max_iterations=1000,
        )

        # Ban imports
        banned = {
            dis.opmap['IMPORT_NAME'],
            dis.opmap['IMPORT_FROM'],
            dis.opmap['IMPORT_STAR'],
        }
        sys.sandbox.banned_opcodes = banned
        sys.sandbox.opcode_restrict_mode = True

        # Set up scope
        sys.sandbox.add_filename("<expr>")
        sys.sandbox.reset_counts()

        # Compile as eval (expression only, no statements)
        code = compile(expr, "<expr>", "eval")
        result = eval(code, {"__builtins__": {}})
        return result

    except SandboxError as e:
        raise ValueError(f"Expression error: {e}") from e

    finally:
        sys.sandbox.opcode_restrict_mode = False
        sys.sandbox.banned_opcodes = None
        sys.sandbox.clear_filenames()
        sys.sandbox.set_config(**original)
        sys.sandbox.reset_counts()


# Usage
print(eval_expression("2 + 3 * 4"))    # 14
print(eval_expression("2 ** 10"))       # 1024
```

### Example 3: Multi-Tenant Code Runner

```python
import sys

PyCF_SANDBOX_COUNT = 0x8000

class SandboxRunner:
    """Run code for multiple tenants with per-tenant limits."""

    def __init__(self, max_operations=50_000):
        self.max_operations = max_operations

    def run(self, tenant_id, source):
        """Run source code for a tenant, return results or error."""
        filename = f"<tenant-{tenant_id}>"
        original = sys.sandbox.get_config()

        try:
            sys.sandbox.set_config(
                max_int_digits=50,
                max_str_length=10_000,
                max_bytes_length=10_000,
                max_list_size=10_000,
                max_dict_size=5_000,
                max_set_size=5_000,
                max_tuple_size=10_000,
                max_operations=self.max_operations,
                max_iterations=self.max_operations * 10,
                allow_dunder_access=False,
            )

            sys.sandbox.add_filename(filename)
            sys.sandbox.reset_counts()
            sys.sandbox.frozen_mode = True

            namespace = {"__builtins__": __builtins__}
            sys.sandbox.set_mutable(namespace)

            # Compile with operation counting flag
            code = compile(source, filename, "exec", flags=PyCF_SANDBOX_COUNT)
            exec(code, namespace)

            counts = sys.sandbox.get_counts()
            return {
                "success": True,
                "namespace": {k: v for k, v in namespace.items()
                             if not k.startswith("_")},
                "operations": counts["operation_count"],
                "iterations": counts["iteration_count"],
            }

        except SandboxError as e:
            counts = sys.sandbox.get_counts()
            return {
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "operations": counts["operation_count"],
                "iterations": counts["iteration_count"],
            }

        finally:
            sys.sandbox.frozen_mode = False
            sys.sandbox.clear_filenames()
            sys.sandbox.set_config(**original)
            sys.sandbox.reset_counts()


# Usage
runner = SandboxRunner()

result = runner.run("alice", "x = [i**2 for i in range(10)]")
print(result)
# {'success': True, 'namespace': {'x': [0, 1, 4, 9, 16, 25, 36, 49, 64, 81]},
#  'operations': ..., 'iterations': ...}

result = runner.run("bob", "while True: pass")
print(result)
# {'success': False, 'error': 'SandboxRuntimeError: ...', ...}
```

---

## Best Practices

### 1. Always Use Scope Tracking

Without scope tracking, limits (statements, iterations, allocations) are not enforced. Always register filenames:

```python
# Good
sys.sandbox.add_filename("<sandbox>")
code = compile(source, "<sandbox>", "exec")

# Bad - scoped limits won't apply
code = compile(source, "<string>", "exec")
# ("<string>" is not registered, so no scoped enforcement)
```

### 2. Reset Counters Before Each Execution

```python
sys.sandbox.reset_counts()  # Always reset before running untrusted code
exec(code)
```

### 3. Clean Up in Finally Blocks

Always restore sandbox state, even if execution fails:

```python
original = sys.sandbox.get_config()
try:
    sys.sandbox.set_config(...)
    sys.sandbox.add_filename("<sandbox>")
    exec(code)
finally:
    sys.sandbox.auto_mutable = False
    sys.sandbox.frozen_mode = False
    sys.sandbox.opcode_restrict_mode = False
    sys.sandbox.banned_opcodes = None
    sys.sandbox.clear_filenames()
    sys.sandbox.set_config(**original)
    sys.sandbox.reset_counts()
```

### 4. Use Multiple Execution Limits

C builtins like `sum()`, `list()`, `sorted()` iterate internally in C code. Use iteration limits to catch these. Operation limits provide precise AST-level counting with zero tracing overhead:

```python
sys.sandbox.set_config(
    max_operations=100_000,   # AST-level counting (requires PyCF_SANDBOX_COUNT)
    max_iterations=1_000_000, # Catches: sum(range(10**9))
)
```

### 5. Combine Multiple Protections

No single limit is sufficient. Use multiple layers:

```python
sys.sandbox.set_config(
    # Data size limits
    max_list_size=100_000,
    max_str_length=100_000,

    # Execution limits
    max_operations=100_000,  # Requires PyCF_SANDBOX_COUNT at compile time
    max_iterations=1_000_000,
    max_recursion_depth=100,

    # Access control
    allow_dunder_access=False,
)

# Plus frozen mode for shared state protection
sys.sandbox.frozen_mode = True

# Plus opcode restrictions for import blocking
sys.sandbox.banned_opcodes = {dis.opmap['IMPORT_NAME'], ...}
sys.sandbox.opcode_restrict_mode = True
```

### 6. Use Mutable Objects for Output

When frozen mode is active, mark output containers as mutable:

```python
output = {}
sys.sandbox.set_mutable(output)
# Sandboxed code can write to output even in frozen mode
```

### 7. Generator/Coroutine Frame Access is Blocked

The sandbox automatically blocks access to generator, coroutine, and async generator frames from within sandbox scope. This prevents information leakage when generators/coroutines created outside the sandbox are passed to sandboxed code.

```python
# Outside sandbox
def gen_with_secret():
    api_key = "SECRET_KEY"
    yield 1

gen = gen_with_secret()
next(gen)

# Inside sandbox
sys.sandbox.add_filename("<sandbox>")
code = compile("frame = gen.gi_frame", "<sandbox>", "exec")  # Raises SandboxSecurityError
```

Blocked attributes:
- `generator.gi_frame`
- `coroutine.cr_frame`
- `async_generator.ag_frame`

Note: These attributes work normally outside sandbox scope.

### 8. Allocation Limit Grace Headroom

The allocation limit includes a 1000-unit "grace headroom" for error handling. When the limit is exceeded:

1. First violation: `SandboxMemoryError` raised at `count == max + 1`
2. Grace period: Additional 1000 allocations allowed for exception handling
3. Hard limit: Error raised again at `count > max + 1000`

This prevents cascading failures during exception handling.

### 9. Security Warning

The sandbox limits are designed for resource protection, not as a complete security boundary. Code with access to C extensions, `ctypes`, or other low-level APIs can bypass these limits. For maximum restriction:

- Ban import opcodes
- Remove dangerous builtins from the namespace
- Block dunder access
- Use frozen mode
- Consider running in a subprocess with OS-level sandboxing

---

## Do's and Don'ts

### Do's

| Do | Why |
|----|-----|
| **Always register filenames** | Scoped limits only apply to registered filenames |
| **Always reset counters** | `reset_counts()` before each execution prevents limit carry-over |
| **Always clean up in finally** | Ensures sandbox state is restored on exceptions |
| **Use multiple limit types** | Statements, iterations, operations, and allocations each catch different attacks |
| **Set `allow_dunder_access=False`** | Prevents `__class__.__subclasses__()` escape chains |
| **Set `allow_unsafe=False`** (default) | Blocks `compile()`, gc introspection |
| **Use frozen mode + auto_mutable** | Protects shared state while allowing sandboxed code to create its own objects |
| **Use context managers** | `scope()` and `suspended_limits()` are cleaner and exception-safe |
| **Mark output objects as mutable** | `set_mutable(output)` allows writing results in frozen mode |
| **Use import restrictions** | Explicitly allow only safe modules |
| **Save and restore config** | `original = get_config()` ... `set_config(**original)` |

### Don'ts

| Don't | Why |
|-------|-----|
| **Don't forget scope registration** | Without it, no scoped limits are enforced |
| **Don't use `allow_io=True`** | Enables file/socket access - major security hole |
| **Don't use `allow_unsafe=True`** | Enables `compile()` and gc introspection |
| **Don't pass dangerous modules** | Even with import restrictions, passed modules can be used if `module_access_restrict_mode` is off |
| **Don't trust `__builtins__` as-is** | Contains `eval`, `exec`, `compile`, `open`, etc. |
| **Don't rely on a single limit** | Attackers find ways around individual limits |
| **Don't share mutable state** | Either freeze it or create copies for the sandbox |
| **Don't forget to resume after suspend** | Leaves limits bypassed for all subsequent code |
| **Don't set limits too low** | Legitimate code may fail; test with real workloads |
| **Don't set limits too high** | Defeats the purpose of resource protection |
| **Don't use sandbox in multi-threaded code without care** | State is per-interpreter, shared across threads |

### Common Mistakes

```python
# MISTAKE 1: Forgetting to register filename
sys.sandbox.set_config(max_operations=100)
code = compile(source, "<sandbox>", "exec", flags=0x8000)
exec(code)  # Limits NOT enforced - filename not registered!

# FIX: Register the filename
sys.sandbox.add_filename("<sandbox>")
code = compile(source, "<sandbox>", "exec", flags=0x8000)
exec(code)  # Now limits are enforced
```

```python
# MISTAKE 2: Mismatched filename
sys.sandbox.add_filename("<sandbox>")
code = compile(source, "<user>", "exec")  # Different filename!
exec(code)  # Limits NOT enforced

# FIX: Match the filename
sys.sandbox.add_filename("<user>")
code = compile(source, "<user>", "exec")
exec(code)  # Now limits are enforced
```

```python
# MISTAKE 3: Not resetting counters between runs
sys.sandbox.add_filename("<sandbox>")
exec(code1)  # Uses 500 statements
exec(code2)  # Starts at 500, not 0!

# FIX: Reset before each execution
sys.sandbox.reset_counts()
exec(code1)
sys.sandbox.reset_counts()
exec(code2)
```

```python
# MISTAKE 4: Passing dangerous builtins
namespace = {"__builtins__": __builtins__}  # Includes eval, exec, open!
exec(sandboxed_code, namespace)

# FIX: Create a safe builtins subset
SAFE_BUILTINS = {
    'abs': abs, 'all': all, 'any': any, 'bool': bool,
    'dict': dict, 'enumerate': enumerate, 'filter': filter,
    'float': float, 'int': int, 'len': len, 'list': list,
    'map': map, 'max': max, 'min': min, 'print': print,
    'range': range, 'round': round, 'set': set, 'sorted': sorted,
    'str': str, 'sum': sum, 'tuple': tuple, 'zip': zip,
    # Sandbox exceptions
    'SandboxError': SandboxError,
    'SandboxOverflowError': SandboxOverflowError,
    # ... etc
}
namespace = {"__builtins__": SAFE_BUILTINS}
exec(sandboxed_code, namespace)
```

---

## Security Considerations

### Defense in Depth

The sandbox provides multiple layers of protection. Use them together:

```python
import sys
import dis

# Layer 1: Resource limits
sys.sandbox.set_config(
    max_int_digits=100,
    max_str_length=100_000,
    max_list_size=100_000,
    max_operations=100_000,
    max_iterations=1_000_000,
    max_recursion_depth=100,
)

# Layer 2: Type and access restrictions
sys.sandbox.set_config(
    allow_float=True,
    allow_complex=False,
    allow_dunder_access=False,
    allow_unsafe=False,  # Blocks compile(), gc introspection
    allow_io=False,      # Blocks file, socket, fd operations
)

# Layer 3: Import and module restrictions
sys.sandbox.import_restrict_mode = True
sys.sandbox.allowed_imports = {("math", ""), ("json", "")}
sys.sandbox.module_access_restrict_mode = True
sys.sandbox.allowed_modules = frozenset({"math", "json"})

# Layer 4: Opcode restrictions (extra defense against imports)
sys.sandbox.banned_opcodes = {
    dis.opmap['IMPORT_NAME'],
    dis.opmap['IMPORT_FROM'],
    dis.opmap['IMPORT_STAR'],
}
sys.sandbox.opcode_restrict_mode = True

# Layer 5: Frozen mode
sys.sandbox.frozen_mode = True
sys.sandbox.auto_mutable = True

# Layer 6: Safe builtins
SAFE_BUILTINS = {...}  # Curated safe builtins only
```

### Known Limitations

| Limitation | Mitigation |
|------------|------------|
| C extensions can bypass limits | Use import restrictions, block `ctypes`, `cffi` |
| `__subclasses__()` can find types | Block dunder access |
| `gc.get_objects()` can find objects | Block unsafe operations (default) |
| `compile()` can create escape code | Block unsafe operations (default) |
| File descriptors inherited from parent | Block I/O operations (default) |
| Memory exhaustion before allocation limit | Use OS-level memory limits (ulimit, cgroups) |
| CPU exhaustion before statement limit | Use OS-level CPU limits (timeout, cgroups) |
| Thread spawning | Remove `threading` from allowed modules |
| Signal handlers | Remove `signal` from allowed modules |
| Subprocess spawning | Remove `subprocess`, `os` from allowed modules |

### Escape Vectors to Block

Common sandbox escape techniques and how to block them:

| Escape Vector | How It Works | Blocking Method |
|---------------|--------------|-----------------|
| `().__class__.__bases__[0].__subclasses__()` | Type introspection | `allow_dunder_access=False` |
| `eval(compile(...))` | Dynamic code generation | `allow_unsafe=False` |
| `gc.get_objects()` | Find sensitive objects | `allow_unsafe=False` |
| `import os; os.system()` | Import dangerous module | Import restrictions |
| `open('/etc/passwd')` | File access | `allow_io=False` |
| `socket.socket()` | Network access | `allow_io=False` |
| `ctypes.CDLL()` | Call arbitrary C code | Import restrictions |
| `frame.f_back.f_locals` | Access parent frame | Frame access is blocked in scope |
| `gen.gi_frame.f_locals` | Access generator frame | Frame access blocked |

### Recommended Minimal Configuration

For maximum security with minimal trusted builtins:

```python
import sys
import dis

def create_sandbox():
    """Create a maximally restricted sandbox."""

    # Minimal safe builtins
    SAFE_BUILTINS = {
        # Types
        'bool': bool, 'int': int, 'float': float, 'str': str,
        'list': list, 'dict': dict, 'set': set, 'tuple': tuple,
        'frozenset': frozenset, 'bytes': bytes, 'bytearray': bytearray,

        # Functions
        'abs': abs, 'all': all, 'any': any, 'bin': bin,
        'chr': chr, 'divmod': divmod, 'enumerate': enumerate,
        'filter': filter, 'format': format, 'hash': hash, 'hex': hex,
        'isinstance': isinstance, 'issubclass': issubclass,
        'iter': iter, 'len': len, 'map': map, 'max': max, 'min': min,
        'next': next, 'oct': oct, 'ord': ord, 'pow': pow,
        'print': print, 'range': range, 'repr': repr, 'reversed': reversed,
        'round': round, 'slice': slice, 'sorted': sorted, 'sum': sum,
        'zip': zip,

        # Constants
        'True': True, 'False': False, 'None': None,

        # Sandbox exceptions (for error handling)
        'SandboxError': SandboxError,
        'SandboxOverflowError': SandboxOverflowError,
        'SandboxMemoryError': SandboxMemoryError,
        'SandboxRuntimeError': SandboxRuntimeError,
        'SandboxTypeError': SandboxTypeError,
        'SandboxAttributeError': SandboxAttributeError,
        'SandboxSecurityError': SandboxSecurityError,
        'SandboxImportError': SandboxImportError,

        # Standard exceptions (for except clauses)
        'Exception': Exception,
        'ValueError': ValueError,
        'TypeError': TypeError,
        'KeyError': KeyError,
        'IndexError': IndexError,
        'AttributeError': AttributeError,
        'ZeroDivisionError': ZeroDivisionError,
        'StopIteration': StopIteration,
    }

    # Configure all limits
    sys.sandbox.set_config(
        max_int_digits=50,
        max_str_length=50_000,
        max_bytes_length=50_000,
        max_list_size=10_000,
        max_dict_size=5_000,
        max_set_size=5_000,
        max_tuple_size=10_000,
        max_operations=50_000,
        max_iterations=500_000,
        max_recursion_depth=100,
        allow_float=True,
        allow_complex=False,
        allow_dunder_access=False,
        allow_unsafe=False,
        allow_io=False,
    )

    # Block imports
    sys.sandbox.import_restrict_mode = True
    sys.sandbox.allowed_imports = set()  # No imports allowed

    # Block module access
    sys.sandbox.module_access_restrict_mode = True
    sys.sandbox.allowed_modules = frozenset()  # No modules allowed

    # Block import opcodes as extra defense
    sys.sandbox.banned_opcodes = {
        dis.opmap['IMPORT_NAME'],
        dis.opmap['IMPORT_FROM'],
        dis.opmap['IMPORT_STAR'],
    }
    sys.sandbox.opcode_restrict_mode = True

    # Enable frozen mode
    sys.sandbox.frozen_mode = True
    sys.sandbox.auto_mutable = True

    return SAFE_BUILTINS


PyCF_SANDBOX_COUNT = 0x8000

def run_sandboxed(source, safe_builtins):
    """Run code in the sandbox."""
    sys.sandbox.add_filename("<sandbox>")
    sys.sandbox.reset_counts()

    output = {}
    sys.sandbox.set_mutable(output)

    namespace = {
        "__builtins__": safe_builtins,
        "output": output,
    }
    sys.sandbox.set_mutable(namespace)

    try:
        # Compile with operation counting flag
        code = compile(source, "<sandbox>", "exec", flags=PyCF_SANDBOX_COUNT)
        exec(code, namespace)
        return {"success": True, "output": dict(output)}
    except SandboxError as e:
        return {"success": False, "error": str(e)}
    finally:
        sys.sandbox.clear_filenames()


# Usage
safe_builtins = create_sandbox()
result = run_sandboxed("output['result'] = sum(range(100))", safe_builtins)
print(result)  # {'success': True, 'output': {'result': 4950}}
```

### When the Sandbox Is Not Enough

The CPython sandbox provides resource limits and access control within the Python interpreter. For truly untrusted code, combine with OS-level isolation:

1. **Process isolation**: Run sandboxed code in a subprocess with restricted privileges
2. **Container isolation**: Use Docker/Podman with security profiles
3. **seccomp/landlock**: Restrict system calls at the kernel level
4. **cgroups**: Limit memory, CPU, and other resources at the OS level
5. **Network namespaces**: Isolate network access
6. **Read-only filesystems**: Prevent file modifications

Example subprocess pattern:

```python
import subprocess
import json

def run_in_subprocess(source, timeout=5.0):
    """Run sandboxed code in an isolated subprocess."""
    wrapper = f'''
import sys
import json

sys.sandbox.set_config(
    max_iterations=100000,
    allow_dunder_access=False,
)
sys.sandbox.add_filename("<sandbox>")
sys.sandbox.reset_counts()

try:
    code = compile({source!r}, "<sandbox>", "exec")
    ns = {{"__builtins__": {{}}}  # Empty builtins
    exec(code, ns)
    print(json.dumps({{"success": True}}))
except SandboxError as e:
    print(json.dumps({{"success": False, "error": str(e)}}))
'''

    result = subprocess.run(
        ["python", "-c", wrapper],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return json.loads(result.stdout)
```

---

## API Quick Reference

### Limit Configuration

| Function | Description |
|----------|-------------|
| `sys.sandbox.set_config(**kwargs)` | Set resource limits |
| `sys.sandbox.get_config() -> dict` | Get current limits |
| `sys.sandbox.get_counts() -> dict` | Get current counters |
| `sys.sandbox.reset_counts()` | Reset all counters to 0 |

### Scope Management

| Function | Description |
|----------|-------------|
| `sys.sandbox.enter_scope()` | Register current frame + reset counters |
| `sys.sandbox.exit_scope()` | Clear all registered filenames |
| `sys.sandbox.in_scope() -> bool` | Check if current code is in scope |
| `sys.sandbox.add_frame()` | Register current frame's filename |
| `sys.sandbox.add_filename(name)` | Register a filename |
| `sys.sandbox.remove_filename(name)` | Remove a filename |
| `sys.sandbox.clear_filenames()` | Clear all filenames |
| `sys.sandbox.scope()` | Context manager for enter/exit scope |

### Frozen Mode

| Function | Description |
|----------|-------------|
| `sys.sandbox.frozen_mode = bool` | Enable/disable global freeze |
| `sys.sandbox.frozen_mode -> bool` | Check global freeze status |
| `sys.sandbox.freeze(obj)` | Freeze a specific object |
| `sys.sandbox.is_frozen(obj) -> bool` | Check if object is frozen |
| `sys.sandbox.set_mutable(obj, bool)` | Set/clear mutable flag |
| `sys.sandbox.auto_mutable = bool` | Enable/disable auto-mutable mode |
| `sys.sandbox.auto_mutable -> bool` | Check auto-mutable mode status |

### Opcode Restrictions

| Function | Description |
|----------|-------------|
| `sys.sandbox.opcode_restrict_mode = bool` | Enable/disable opcode checking |
| `sys.sandbox.opcode_restrict_mode -> bool` | Check mode status |
| `sys.sandbox.banned_opcodes = set/None` | Set banned opcodes |
| `sys.sandbox.banned_opcodes -> frozenset` | Get banned opcodes |

### Object Creation Hook

| Function | Description |
|----------|-------------|
| `sys.sandbox.creation_hook = callable/None` | Set/remove creation hook |
| `sys.sandbox.creation_hook -> callable` | Get current hook |

### Suspend/Resume

| Function | Description |
|----------|-------------|
| `sys.sandbox.suspend() -> int` | Suspend limits |
| `sys.sandbox.resume() -> int` | Resume limits |
| `sys.sandbox.suspended -> bool` | Check suspend status |
| `sys.sandbox.suspended_limits()` | Context manager for suspend/resume |

### Import Restrictions

| Function | Description |
|----------|-------------|
| `sys.sandbox.import_restrict_mode = bool` | Enable/disable import allowlist |
| `sys.sandbox.import_restrict_mode -> bool` | Check import restriction status |
| `sys.sandbox.import_allow_submodules = bool` | Allow submodule imports |
| `sys.sandbox.import_allow_submodules -> bool` | Check submodule setting |
| `sys.sandbox.allowed_imports = set` | Set allowed (module, name) tuples |
| `sys.sandbox.allowed_imports -> set` | Get allowed imports |

### Module Access Restrictions

| Function | Description |
|----------|-------------|
| `sys.sandbox.module_access_restrict_mode = bool` | Enable/disable module access allowlist |
| `sys.sandbox.module_access_restrict_mode -> bool` | Check module restriction status |
| `sys.sandbox.allow_submodules = bool` | Allow submodule access |
| `sys.sandbox.allow_submodules -> bool` | Check submodule access setting |
| `sys.sandbox.allowed_modules = frozenset` | Set allowed module names |
| `sys.sandbox.allowed_modules -> frozenset` | Get allowed modules |
| `sys.sandbox.use_default_allowed_modules()` | Set safe module defaults |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `SandboxError` | Base class for all sandbox violations |
| `SandboxOverflowError` | Size/length limit exceeded |
| `SandboxMemoryError` | Allocation limit exceeded |
| `SandboxRuntimeError` | Statement/iteration/operation limit or banned opcode |
| `SandboxTypeError` | Forbidden type creation |
| `SandboxAttributeError` | Frozen mode or dunder access blocked |
| `SandboxSecurityError` | Security violation (I/O, unsafe ops, frame access, module access) |
| `SandboxImportError` | Import not in allowlist |

### `set_config()` Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_int_digits` | int | 0 | Max internal integer digits |
| `max_str_length` | int | 0 | Max string characters |
| `max_bytes_length` | int | 0 | Max bytes length |
| `max_list_size` | int | 0 | Max list items |
| `max_dict_size` | int | 0 | Max dict entries |
| `max_set_size` | int | 0 | Max set members |
| `max_tuple_size` | int | 0 | Max tuple items |
| `max_iterations` | int | 0 | Max iterator steps in scope |
| `max_operations` | int | 0 | Max AST operations in scope (requires `PyCF_SANDBOX_COUNT`) |
| `max_recursion_depth` | int | 0 | Max sandbox-scoped recursion depth |
| `allow_float` | bool | True | Allow float creation |
| `allow_complex` | bool | True | Allow complex creation |
| `allow_dunder_access` | bool | True | Allow `__dunder__` attributes |
| `allow_unsafe` | bool | False | Allow unsafe operations (compile, gc introspection) |
| `allow_io` | bool | False | Allow I/O operations (file, socket, fd) |
| `count_iterations_as_operations` | bool | False | Count iterator yields toward `operation_count` |
| `import_restrict_mode` | bool | True | Enforce import allowlist |
| `import_allow_submodules` | bool | False | Allow submodule imports when parent allowed |
| `module_access_restrict_mode` | bool | False | Enforce module access allowlist |
| `allow_submodules` | bool | True | Allow submodule access when parent allowed |
