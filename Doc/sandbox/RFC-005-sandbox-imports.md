- Feature Name: sandbox-imports
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox imports module provides import restriction through an allowlist mechanism. When enabled, only explicitly allowed modules and names can be imported from sandbox scope. This prevents sandboxed code from accessing dangerous modules like `os`, `subprocess`, `socket`, etc.

# Motivation
[motivation]: #motivation

Python's import system gives access to powerful capabilities:

```python
import os; os.system("rm -rf /")
import subprocess; subprocess.run(["malware"])
import socket; socket.socket().connect(("evil.com", 80))
import ctypes; ctypes.CDLL(None).system(b"whoami")
```

Restricting imports is essential for sandboxing. The allowlist approach is safer than a blocklist because:

1. **Default deny**: New dangerous modules are blocked by default
2. **Explicit intent**: Only specifically allowed modules are accessible
3. **Fine-grained control**: Can allow specific names from a module

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Enabling Import Restrictions

```python
import sys

# Enable import restriction mode
sys.sandbox.import_restrict_mode = True

# Set allowed imports (list of (module, name) tuples)
sys.sandbox.allowed_imports = [
    ("json", ""),       # Allow 'import json' and all 'from json import X'
    ("math", ""),       # Allow 'import math' and all 'from math import X'
    ("re", ""),         # Allow 'import re' and all 'from re import X'
]

sys.sandbox.add_filename("<sandbox>")

code = compile("""
import json    # Allowed
import os      # Raises SandboxImportError
""", "<sandbox>", "exec")

try:
    exec(code)
except SandboxImportError as e:
    print(e)  # "Import of 'os' is not allowed in sandbox"
```

## Allowlist Format

The allowlist is a set of `(module_name, import_name)` tuples:

```python
sys.sandbox.allowed_imports = [
    # Allow entire module
    ("json", ""),           # import json; from json import X

    # Allow specific name only
    ("json", "loads"),      # from json import loads
    ("json", "dumps"),      # from json import dumps

    # Allow star import
    ("constants", "*"),     # from constants import *
]
```

### Module-Level Allow (`name=""`)

```python
("json", "")  # Allows:
              #   import json
              #   from json import loads
              #   from json import dumps, loads
              #   from json import *
```

### Name-Specific Allow

```python
("json", "loads")  # Allows ONLY:
                   #   from json import loads
                   # Does NOT allow:
                   #   import json
                   #   from json import dumps
```

### Star Import Allow

```python
("mymodule", "*")  # Allows:
                   #   from mymodule import *
                   # Does NOT allow:
                   #   import mymodule
                   #   from mymodule import specific_name
```

## Submodule Support

By default, submodule imports are checked against the parent:

```python
sys.sandbox.allowed_imports = [("json", "")]
sys.sandbox.import_allow_submodules = True  # Default

# This works because 'json' is allowed:
import json.decoder  # Allowed (submodule of allowed 'json')
```

Disable submodule allowance:

```python
sys.sandbox.import_allow_submodules = False

# Now submodules must be explicitly listed:
sys.sandbox.allowed_imports = [
    ("json", ""),
    ("json.decoder", ""),  # Must explicitly allow
]
```

## Checking Current Configuration

```python
# Get current allowlist
allowed = sys.sandbox.allowed_imports
print(allowed)  # frozenset({('json', ''), ('math', '')})

# Check mode
print(sys.sandbox.import_restrict_mode)  # True/False
print(sys.sandbox.import_allow_submodules)  # True/False
```

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## Data Structures

The allowlist is stored as a Python `set` of tuples:

```c
typedef struct {
    /* ... other fields ... */
    PyObject *allowed_imports;  /* Python set of (module, name) tuples */
    /* ... */
} _PySandboxState;
```

## Import Check Function

```c
int
_PySandbox_CheckImport(PyObject *abs_name, PyObject *fromlist)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return 0;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    /* Fast exit if not in restrict mode */
    if (!sandbox->limits.import_restrict_mode) {
        return 0;
    }

    if (sandbox->suppress_checks || sandbox->suspended) {
        return 0;
    }

    /* Check if in sandbox scope */
    _PyInterpreterFrame *frame = get_current_interpreter_frame();
    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return 0;
    }

    /* No allowlist means nothing is allowed */
    if (sandbox->allowed_imports == NULL) {
        PyErr_Format(PyExc_SandboxImportError,
                     "Import of '%U' is not allowed in sandbox", abs_name);
        return -1;
    }

    /* Check if import is allowed */
    if (!import_is_allowed(sandbox, abs_name, fromlist)) {
        PyErr_Format(PyExc_SandboxImportError,
                     "Import of '%U' is not allowed in sandbox", abs_name);
        return -1;
    }

    return 0;
}
```

## Allowlist Checking Logic

```c
static int
import_is_allowed(_PySandboxState *sandbox, PyObject *abs_name, PyObject *fromlist)
{
    PyObject *empty_str = PyUnicode_FromString("");

    /* Check if module-level import is allowed: (module, "") */
    PyObject *module_key = PyTuple_Pack(2, abs_name, empty_str);
    int allowed = PySet_Contains(sandbox->allowed_imports, module_key);
    Py_DECREF(module_key);

    if (allowed > 0) {
        Py_DECREF(empty_str);
        return 1;  /* Module-level allow covers all imports */
    }

    /* Check submodule allowance */
    if (sandbox->limits.import_allow_submodules) {
        if (check_parent_module_allowed(sandbox, abs_name)) {
            Py_DECREF(empty_str);
            return 1;
        }
    }

    /* Check specific names in fromlist */
    if (fromlist != NULL && PySequence_Check(fromlist)) {
        Py_ssize_t n = PySequence_Length(fromlist);
        for (Py_ssize_t i = 0; i < n; i++) {
            PyObject *name = PySequence_GetItem(fromlist, i);
            PyObject *name_key = PyTuple_Pack(2, abs_name, name);
            allowed = PySet_Contains(sandbox->allowed_imports, name_key);
            Py_DECREF(name_key);
            Py_DECREF(name);

            if (allowed <= 0) {
                Py_DECREF(empty_str);
                return 0;  /* At least one name not allowed */
            }
        }
        Py_DECREF(empty_str);
        return 1;  /* All names in fromlist are allowed */
    }

    Py_DECREF(empty_str);
    return 0;  /* Not allowed */
}

static int
check_parent_module_allowed(_PySandboxState *sandbox, PyObject *module_name)
{
    /* Check if any parent module is allowed */
    /* e.g., for "json.decoder", check if "json" is allowed */
    const char *name = PyUnicode_AsUTF8(module_name);
    char *dot = strrchr(name, '.');

    while (dot != NULL) {
        PyObject *parent = PyUnicode_FromStringAndSize(name, dot - name);
        PyObject *key = PyTuple_Pack(2, parent, empty_string);
        int allowed = PySet_Contains(sandbox->allowed_imports, key);
        Py_DECREF(key);
        Py_DECREF(parent);

        if (allowed > 0) {
            return 1;
        }

        /* Check next parent level */
        *dot = '\0';
        dot = strrchr(name, '.');
    }

    return 0;
}
```

## C API

```c
/* Set allowed imports (set of (module, name) tuples, or NULL to clear) */
int PySandbox_SetAllowedImports(PyObject *modules);

/* Get current allowed imports (returns new reference to frozenset) */
PyObject *PySandbox_GetAllowedImports(void);
```

## Python API

### Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `import_restrict_mode` | bool | False | Enable import restrictions |
| `import_allow_submodules` | bool | True | Allow submodules of allowed modules |
| `allowed_imports` | frozenset | None | Set of `(module, name)` tuples |

### Setting Allowed Imports

```python
# From list of tuples
sys.sandbox.allowed_imports = [("json", ""), ("math", "")]

# From set
sys.sandbox.allowed_imports = {("json", ""), ("math", "")}

# Clear (disallow all imports)
sys.sandbox.allowed_imports = None
```

## Integration Point

The check is called from the import machinery in `Python/import.c`:

```c
PyObject *
PyImport_ImportModuleLevelObject(PyObject *name, PyObject *globals,
                                  PyObject *locals, PyObject *fromlist,
                                  int level)
{
    /* ... resolve absolute name ... */

    /* Check sandbox import restrictions */
    if (_PySandbox_CheckImport(abs_name, fromlist) < 0) {
        return NULL;
    }

    /* ... proceed with import ... */
}
```

## Exception Type

`SandboxImportError` is raised for blocked imports:

```
SandboxImportError: Import of 'os' is not allowed in sandbox
```

# Drawbacks
[drawbacks]: #drawbacks

1. **Allowlist Maintenance**: Must explicitly list all allowed modules; easy to miss legitimate needs.

2. **Transitive Imports**: If allowed module `A` imports blocked module `B`, the import may fail unexpectedly.

3. **Dynamic Imports**: `importlib.import_module()` and `__import__()` are also restricted, which may break some patterns.

4. **Standard Library Dependencies**: Many stdlib modules import others; allowing one may require allowing its dependencies.

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why Allowlist vs. Blocklist?

**Blocklist approach**:
```python
blocked_imports = {"os", "subprocess", "socket", ...}
```
- Rejected: Must enumerate all dangerous modules; new dangerous modules are allowed by default; easy to miss one.

**Allowlist approach** (chosen):
```python
allowed_imports = {("json", ""), ("math", "")}
```
- Default-deny: only explicitly allowed modules work
- Safer against unknown threats
- Clear intent

## Why Tuple Format `(module, name)`?

Allows fine-grained control:

```python
# Module-level: allow all from json
("json", "")

# Name-specific: only allow json.loads
("json", "loads")
```

Alternative single-string format couldn't express both use cases cleanly.

## Why Default `import_allow_submodules=True`?

Pragmatic choice: most users expect `import json` to also allow `import json.decoder`. Requiring explicit submodule listing would be tedious.

# Prior art
[prior-art]: #prior-art

1. **RestrictedPython**: Uses a similar allowlist approach for imports.

2. **Java SecurityManager**: Can restrict class loading by package name.

3. **Node.js `--experimental-permission`**: Uses allowlist for module access.

4. **Browser CSP**: Uses allowlists for script sources.

# Unresolved questions
[unresolved-questions]: #unresolved-questions

1. Should there be a "safe stdlib" preset that allows known-safe modules?

2. How should `importlib` machinery itself be handled?

3. Should relative imports be treated differently?

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Import Hooks**: Custom hooks to transform or proxy imported modules.

2. **Lazy Restriction**: Allow import but restrict what can be accessed from the module.

3. **Dependency Resolution**: Automatically allow transitive dependencies of allowed modules.

4. **Import Auditing**: Log all import attempts for analysis.
