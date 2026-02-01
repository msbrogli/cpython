- Feature Name: sandbox-module-access-restriction
- Start Date: 2025-01-30
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox module access restriction feature provides an allowlist-based mechanism to control which modules can be accessed from within sandbox scope. By default, **all modules are blocked** unless explicitly allowed. This complements the import restrictions (RFC-005) by providing defense in depth: while import restrictions block new imports, module access restrictions prevent usage of modules that may have been imported before sandbox activation or obtained through other means like `sys.modules`.

# Motivation
[motivation]: #motivation

Import restrictions alone are insufficient for complete module isolation:

```python
import os  # Imported BEFORE sandbox activation

sys.sandbox.import_restrict_mode = True
sys.sandbox.allowed_imports = frozenset()  # Block all imports
sys.sandbox.add_filename("<sandbox>")

# Attack 1: Use pre-imported module reference
exec(compile("os.system('id')", "<sandbox>", "exec"), {"os": os})  # WORKS!

# Attack 2: Access via sys.modules (if sys is allowed)
exec(compile("sys.modules['os'].system('id')", "<sandbox>", "exec"), {"sys": sys})
```

The module access restriction feature solves this by intercepting attribute access on module objects:

```python
# By default, module_access_restrict_mode=True and allowed_modules=None
# This means ALL modules are blocked
sys.sandbox.add_filename("<sandbox>")

# Even with a reference, the module cannot be used
exec(compile("os.system('id')", "<sandbox>", "exec"), {"os": os})
# Raises: SandboxSecurityError: access to module 'os' is not allowed in sandbox
```

To allow specific safe modules:

```python
sys.sandbox.allowed_modules = {'json', 'math', 'datetime'}
sys.sandbox.add_filename("<sandbox>")

# json works
exec(compile("json.dumps({'a': 1})", "<sandbox>", "exec"), {"json": json})  # OK

# os still blocked
exec(compile("os.getcwd()", "<sandbox>", "exec"), {"os": os})  # Raises error
```

Key benefits:

1. **Default-deny security**: All modules blocked by default (allowlist approach)
2. **Defense in depth**: Complements import restrictions
3. **Blocks pre-imported modules**: Modules imported before sandbox activation are blocked
4. **Blocks sys.modules access**: Even if `sys` is allowed, `sys.modules['os']` returns a blocked module
5. **Reference-agnostic**: Blocks usage regardless of how the module reference was obtained

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Basic Usage

By default, `module_access_restrict_mode=True` and `allowed_modules=None`, which means **all modules are blocked**:

```python
import sys
import os
import json

# Register sandbox scope
sys.sandbox.add_filename("<sandbox>")

# ALL modules are blocked by default
code = compile("result = os.getcwd()", "<sandbox>", "exec")

try:
    exec(code, {"os": os})
except SandboxSecurityError as e:
    print(e)  # "access to module 'os' is not allowed in sandbox (no modules allowed)"
```

## Allowing Specific Modules

To allow certain modules, set `allowed_modules`:

```python
# Allow only json and math
sys.sandbox.allowed_modules = {'json', 'math'}
sys.sandbox.add_filename("<sandbox>")

# json works
code = compile("result = json.dumps({'a': 1})", "<sandbox>", "exec")
ns = {"json": json}
exec(code, ns)  # OK
print(ns["result"])  # '{"a": 1}'

# os is blocked
code = compile("result = os.getcwd()", "<sandbox>", "exec")
try:
    exec(code, {"os": os})
except SandboxSecurityError as e:
    print(e)  # "access to module 'os' is not allowed in sandbox"
```

## Using Default Safe Modules

For convenience, use `use_default_allowed_modules()` to set a predefined list of safe modules:

```python
sys.sandbox.use_default_allowed_modules()
sys.sandbox.add_filename("<sandbox>")

# Safe modules work
exec(compile("json.dumps({'a': 1})", "<sandbox>", "exec"), {"json": json})  # OK
exec(compile("math.sqrt(16)", "<sandbox>", "exec"), {"math": math})  # OK

# Dangerous modules are blocked
exec(compile("os.getcwd()", "<sandbox>", "exec"), {"os": os})  # Raises error
```

The default safe modules include:
- Data: `json`, `csv`, `struct`, `base64`, `binascii`
- Math: `math`, `decimal`, `fractions`, `statistics`
- Text: `string`, `re`, `textwrap`, `unicodedata`
- Collections: `collections`, `bisect`, `heapq`, `array`
- Date/Time: `datetime`, `calendar`, `zoneinfo`
- Utilities: `functools`, `itertools`, `operator`, `contextlib`, `copy`, `enum`, `dataclasses`, `typing`, `abc`
- Other safe: `hashlib`, `hmac`, `zlib`, `html`, `errno`, `stat`, `weakref`, `graphlib`, `pprint`, `reprlib`

**Excluded dangerous modules**: `os`, `subprocess`, `socket`, `ctypes`, `gc`, `sys`, `threading`, `pickle`, `marshal`, `random`, `importlib`, `builtins`, `signal`, etc.

## Submodule Handling

By default, allowing a parent module also allows its submodules:

```python
import html.parser

sys.sandbox.allowed_modules = {'html'}  # Allows html and all html.* submodules
sys.sandbox.add_filename("<sandbox>")

code = compile("parser = html_parser.HTMLParser()", "<sandbox>", "exec")
ns = {"html_parser": html.parser}
exec(code, ns)  # Works because 'html' is allowed
```

### Disabling Submodule Allowance

Set `allow_submodules=False` to require exact module name matches:

```python
sys.sandbox.allowed_modules = {'html'}
sys.sandbox.allow_submodules = False  # Only exact matches
sys.sandbox.add_filename("<sandbox>")

# html.parser is NOT allowed (not an exact match)
code = compile("parser = html_parser.HTMLParser()", "<sandbox>", "exec")
try:
    exec(code, {"html_parser": html.parser})
except SandboxSecurityError as e:
    print(e)  # "access to module 'html.parser' is not allowed in sandbox"

# To allow it, must list explicitly:
sys.sandbox.allowed_modules = {'html', 'html.parser'}
```

## Disabling Module Access Restriction

To disable the feature entirely (allow all modules):

```python
sys.sandbox.module_access_restrict_mode = False
sys.sandbox.add_filename("<sandbox>")

# Now all modules are accessible (NOT RECOMMENDED for untrusted code)
exec(compile("os.getcwd()", "<sandbox>", "exec"), {"os": os})  # Works
```

## Checking Configuration

```python
# Get current allowed modules
allowed = sys.sandbox.allowed_modules
print(allowed)  # frozenset({'json', 'math', ...}) or None

# Check restriction mode
print(sys.sandbox.module_access_restrict_mode)  # True (default)

# Check submodule allowance
print(sys.sandbox.allow_submodules)  # True (default)

# Clear allowed modules (blocks everything)
sys.sandbox.allowed_modules = None
# or
sys.sandbox.reset()
```

## Combining with Import Restrictions

For defense in depth, use both import restrictions and module access restrictions:

```python
import sys

# Layer 1: Block new imports (allowlist)
sys.sandbox.import_restrict_mode = True
sys.sandbox.allowed_imports = frozenset([
    ('json', ''),
    ('math', ''),
    ('re', ''),
])

# Layer 2: Block module usage even if reference exists (allowlist)
sys.sandbox.allowed_modules = {'json', 'math', 're'}

# Register scope
sys.sandbox.add_filename("<sandbox>")
```

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## Data Structures

The allowed modules set is stored in the sandbox state:

```c
typedef struct {
    /* ... other fields ... */

    /* Allowed modules - Python frozenset of module names (strings).
     * When set (non-NULL), only modules in this set can be accessed in sandbox scope.
     * NULL = all modules blocked when module_access_restrict_mode is enabled.
     * Stored as frozenset for O(1) getter performance. */
    PyObject *allowed_modules;
} _PySandboxState;
```

The restriction flags are in the limits structure:

```c
typedef struct {
    /* ... other fields ... */

    /* Module access restriction mode.
     * When module_access_restrict_mode=1 (default), only modules in allowed_modules
     * can be accessed in sandbox scope.
     * When module_access_restrict_mode=0, all modules can be accessed. */
    int module_access_restrict_mode;

    /* Allow submodules when parent is allowed.
     * When allow_submodules=1 (default), allowing 'xml' also allows 'xml.etree.ElementTree'.
     * When allow_submodules=0, only exact module names in allowed_modules are allowed. */
    int allow_submodules;
} _PySandboxConfig;
```

## Module Access Check Function

The check is implemented in `Python/sandbox_limits.c`:

```c
int
_PySandbox_CheckModuleAccess(PyObject *module)
{
    _PySandboxState *sandbox = get_sandbox_state();

    /* Fast exits */
    if (sandbox == NULL || sandbox->suspend_depth || sandbox->suppress_checks) {
        return 0;
    }

    /* Fast exit if module access restriction is not enabled */
    if (!sandbox->config.module_access_restrict_mode) {
        return 0;
    }

    /* Check if in sandbox scope */
    if (sandbox->registered_filenames == NULL) {
        return 0;
    }
    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return 0;
    }

    /* Get module name */
    PyObject *mod_name = PyModule_GetNameObject(module);
    if (mod_name == NULL) {
        PyErr_Clear();
        return 0;  /* Can't determine name, allow */
    }

    /* If no allowlist is set, block everything */
    if (sandbox->allowed_modules == NULL ||
        PySet_GET_SIZE(sandbox->allowed_modules) == 0) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxSecurityError,
                     "access to module '%U' is not allowed in sandbox (no modules allowed)",
                     mod_name);
        sandbox->suppress_checks = 0;
        Py_DECREF(mod_name);
        return -1;
    }

    /* Check if module is in allowlist */
    int allowed = PySet_Contains(sandbox->allowed_modules, mod_name);

    /* Check base module name for submodules if enabled */
    if (!allowed && sandbox->config.allow_submodules) {
        const char *name_str = PyUnicode_AsUTF8(mod_name);
        if (name_str) {
            const char *dot = strchr(name_str, '.');
            if (dot) {
                PyObject *base = PyUnicode_FromStringAndSize(name_str, dot - name_str);
                if (base) {
                    allowed = PySet_Contains(sandbox->allowed_modules, base);
                    Py_DECREF(base);
                }
            }
        }
    }

    if (!allowed) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxSecurityError,
                     "access to module '%U' is not allowed in sandbox", mod_name);
        sandbox->suppress_checks = 0;
        Py_DECREF(mod_name);
        return -1;
    }

    Py_DECREF(mod_name);
    return 0;
}
```

## Integration Point

The check is called from `module_getattro()` in `Objects/moduleobject.c`:

```c
static PyObject*
module_getattro(PyModuleObject *m, PyObject *name)
{
    /* Check if this module is allowed in sandbox scope */
    if (_PySandbox_CheckModuleAccess((PyObject *)m) < 0) {
        return NULL;
    }

    /* ... proceed with normal attribute access ... */
}
```

This intercepts ALL attribute access on module objects, including:
- `os.system`
- `os.path`
- `sys.modules`
- `module.__dict__`

## Python API

### Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `module_access_restrict_mode` | bool | `True` | Enable module access restriction |
| `allowed_modules` | frozenset or None | `None` | Set of allowed module names |
| `allow_submodules` | bool | `True` | Allow submodules when parent is allowed |

### Methods

| Method | Description |
|--------|-------------|
| `use_default_allowed_modules()` | Set allowed_modules to predefined safe list |

### Setting Allowed Modules

```python
# From set
sys.sandbox.allowed_modules = {'json', 'math'}

# From list
sys.sandbox.allowed_modules = ['json', 'math']

# From frozenset
sys.sandbox.allowed_modules = frozenset(['json', 'math'])

# Clear (blocks all modules when restriction mode is on)
sys.sandbox.allowed_modules = None
```

### Getter Returns Frozenset

The getter returns a `frozenset` for immutability, or `None` if not set:

```python
allowed = sys.sandbox.allowed_modules
print(type(allowed))  # <class 'frozenset'> or <class 'NoneType'>

# Stored as frozenset for O(1) operation
sys.sandbox.allowed_modules = {'json', 'math'}
a = sys.sandbox.allowed_modules
b = sys.sandbox.allowed_modules
assert a is b  # True (same object)
```

## Default Allowed Modules

The `use_default_allowed_modules()` method sets these safe modules:

```python
DEFAULT_ALLOWED_MODULES = frozenset({
    # Data serialization (safe)
    'json', 'csv', 'struct', 'base64', 'binascii', 'quopri', 'uu',

    # Math and numbers
    'math', 'decimal', 'fractions', 'statistics',

    # Text processing
    'string', 're', 'textwrap', 'unicodedata',

    # Collections
    'collections', 'bisect', 'heapq', 'array', 'graphlib',

    # Date and time
    'datetime', 'calendar', 'zoneinfo',

    # Functional programming
    'functools', 'itertools', 'operator',

    # Type system
    'typing', 'types', 'enum', 'dataclasses', 'abc',

    # Utilities
    'contextlib', 'copy', 'pprint', 'reprlib', 'weakref',

    # Cryptographic hashing (no secrets, just hashing)
    'hashlib', 'hmac',

    # Compression (in-memory only, no file I/O)
    'zlib',

    # HTML (parsing/escaping, no network)
    'html', 'html.parser', 'html.entities',

    # System constants (read-only)
    'errno', 'stat',
})
```

**Explicitly excluded**: `os`, `subprocess`, `socket`, `ssl`, `ctypes`, `gc`, `sys`, `threading`, `multiprocessing`, `pickle`, `marshal`, `random`, `importlib`, `builtins`, `signal`, `resource`, `fcntl`, `mmap`, `pty`, `tty`, `inspect`, `traceback`, `code`, `codeop`, `ast`, `compile`, `io`, `shutil`, `pathlib`, `tempfile`, `http`, `urllib`, `ftplib`, `smtplib`, etc.

## Exception Type

`SandboxSecurityError` is raised when accessing a non-allowed module:

```
SandboxSecurityError: access to module 'os' is not allowed in sandbox
```

Or when no modules are allowed:

```
SandboxSecurityError: access to module 'os' is not allowed in sandbox (no modules allowed)
```

## Scope Awareness

The check only applies to code running in sandbox scope:

```python
import os

sys.sandbox.allowed_modules = {'json'}
sys.sandbox.add_filename("<sandbox>")

# Code in sandbox scope - BLOCKED
exec(compile("os.getcwd()", "<sandbox>", "exec"), {"os": os})  # Raises error

# Code outside sandbox scope - ALLOWED
exec(compile("os.getcwd()", "<other>", "exec"), {"os": os})  # Works
```

## Note on os.path

`os.path` is actually an alias to `posixpath` (Linux) or `ntpath` (Windows), not a true submodule:

```python
import os.path
print(os.path.__name__)  # "posixpath" (not "os.path")
```

To allow `os.path` functionality without allowing `os`, add `posixpath` to allowed modules:

```python
sys.sandbox.allowed_modules = {'posixpath', 'json'}  # Allow path manipulation
```

# Drawbacks
[drawbacks]: #drawbacks

1. **Performance overhead**: Every attribute access on a module object triggers the check. The check is optimized with fast-path exits, but there is still some overhead.

2. **Incomplete coverage for aliases**: Some modules like `os.path` are aliases to other modules (`posixpath`/`ntpath`). Users must understand these relationships.

3. **Does not block cached references**: If code caches a function before sandbox activation (e.g., `func = os.system`), calling `func()` later won't be blocked. The check only intercepts module attribute access, not function calls.

4. **Requires careful allowlist construction**: Users must ensure their allowlist includes all modules needed by their code, including dependencies.

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why Allowlist Instead of Blocklist?

An **allowlist** (default-deny) approach was chosen over a **blocklist** (default-allow) for several reasons:

1. **Security by default**: New/unknown modules are automatically blocked
2. **Fail-safe**: If a new dangerous module is added to Python, it's blocked by default
3. **Explicit trust**: Users must consciously decide which modules to allow
4. **Smaller attack surface**: Most sandboxed code needs only a few safe modules

A blocklist approach would require maintaining an ever-growing list of dangerous modules and could miss newly added dangerous modules.

## Why Intercept `module_getattro()`?

**Intercepting `module_getattro()`** is the most effective approach because:

1. It catches ALL attribute access on modules
2. It's a single integration point (low implementation complexity)
3. It works regardless of how the module reference was obtained
4. It's scope-aware (only affects sandbox code)

## Alternatives Considered

### Alternative 1: Proxy Modules

Replace dangerous modules in `sys.modules` with proxy objects that block access.

**Rejected because:**
- Requires modifying `sys.modules` at runtime
- Doesn't help if code already has a direct reference
- Complex to implement correctly for all module types

### Alternative 2: Frozen sys.modules

Add frozen checks to dict operations to prevent `sys.modules` modification.

**Partially implemented:** This is complementary and could be added later. However, it only prevents injection, not access to pre-imported modules.

### Alternative 3: Clean sys.modules Before Sandbox

Remove dangerous modules from `sys.modules` before running sandbox code.

**Rejected because:**
- Must be done at harness level (not enforced by CPython)
- Modules might be re-imported outside sandbox scope
- Doesn't prevent usage of cached references

## Why `allow_submodules` Flag?

The flag provides flexibility:

- **True (default)**: Convenient for users who allow package hierarchies
- **False**: Explicit control for users who need fine-grained control

# Prior art
[prior-art]: #prior-art

## Python RestrictedPython

RestrictedPython uses AST transformation to restrict module access. It blocks imports at compile time rather than runtime.

**Our approach differs:** We block at runtime, which handles pre-imported modules and references obtained through non-import means.

## Java SecurityManager

Java's SecurityManager (deprecated in Java 17) used permission checks for various operations including class loading.

**Similar concept:** Both use runtime checks to enforce security policies.

## JavaScript Realms Proposal

The JavaScript Realms proposal provides isolated execution contexts with controlled access to globals.

**Similar concept:** Both provide mechanism to control access to dangerous functionality.

# Unresolved questions
[unresolved-questions]: #unresolved-questions

1. **Should we block cached function references?** Blocking `os.system` doesn't prevent calling a cached reference `func = os.system; func()`. This would require tracking function origins, which is complex.

2. **Should submodule allowance check all parent levels?** Currently only the immediate parent is checked (e.g., `xml` for `xml.etree.ElementTree`). Should we also check `xml.etree`?

3. **Should there be security presets?** Methods like `use_strict_allowed_modules()` or `use_minimal_allowed_modules()` could provide different security levels.

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Security presets**: Add `sys.sandbox.use_security_preset("strict")` with different allowed module sets.

2. **Module-level granularity**: Allow specific attributes rather than entire modules (e.g., allow `os.path` but not `os.system`).

3. **Audit logging**: Log blocked access attempts for security monitoring.

4. **Frozen dict operations**: Add frozen checks to `PyDict_SetItem()` to protect `sys.modules` from injection attacks.

5. **Integration with import restrictions**: Automatically sync allowed_modules with allowed_imports for consistency.

6. **Per-scope allowlists**: Different sandbox scopes could have different allowed module sets.
