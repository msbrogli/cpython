- Feature Name: sandbox-imports
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox imports module provides import restriction through an allowlist mechanism. When enabled, only explicitly allowed modules can be imported from sandbox scope. This prevents sandboxed code from accessing dangerous modules like `os`, `subprocess`, `socket`, etc.

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
3. **Submodule control**: Entry "X" allows X and X.*, entry "X.Y" only allows X.Y and X.Y.*

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Enabling Import Restrictions

```python
import sys

# Enable import restriction mode (enabled by default)
sys.sandbox.import_restrict_mode = True

# Set allowed imports (set of module path strings)
sys.sandbox.allowed_imports = {"json", "math", "re"}

sys.sandbox.enable()
sys.sandbox.add_filename("<sandbox>")

code = compile("""
import json    # Allowed
import os      # Raises SandboxImportError
""", "<sandbox>", "exec")

try:
    exec(code)
except SandboxImportError as e:
    print(e)  # "Import of 'os' is not allowed in sandbox scope"
```

## Allowlist Format

The allowlist is a set of **module path strings**. Paths can be as broad or as restrictive as needed - from top-level modules like `"json"` to deeply nested paths like `"mypackage.submodule.specific.component"`.

```python
sys.sandbox.allowed_imports = {
    # Broad: allow entire module and ALL submodules
    "json",              # import json; import json.decoder; import json.encoder

    # Restrictive: allow only specific submodule (and its children)
    "xml.etree",         # import xml.etree; import xml.etree.ElementTree
                         # Also allows: import xml (as dependency)
                         # Does NOT allow: import xml.dom (sibling)

    # Very restrictive: allow only a specific deeply-nested path
    "myapp.utils.safe",  # Only myapp.utils.safe and myapp.utils.safe.*
                         # Does NOT allow: myapp.utils.dangerous
}
```

### Granular Control

The string format supports **arbitrary nesting depth**, allowing fine-grained control:

| Entry | Restrictiveness | What It Allows |
|-------|-----------------|----------------|
| `"json"` | Broad | All of json: `json`, `json.decoder`, `json.encoder`, etc. |
| `"json.decoder"` | Moderate | Only `json.decoder` and `json` (parent), NOT `json.encoder` |
| `"urllib.parse"` | Moderate | Only `urllib.parse` and `urllib`, NOT `urllib.request` |
| `"a.b.c.d.e"` | Very restrictive | Only `a.b.c.d.e`, `a.b.c.d.e.*`, and parents `a`, `a.b`, `a.b.c`, `a.b.c.d` |

### Entry Semantics

Each entry `"X"` in the allowlist:

1. **Allows X itself**: `import X` is allowed
2. **Allows all submodules of X**: `import X.Y`, `import X.Y.Z`, etc. are allowed
3. **Auto-computes parent dependencies**: Parent modules are allowed as needed for Python's import system

### Examples

```python
# Entry: "json" (BROAD - allows everything under json)
# Allows:
#   import json           (exact match)
#   import json.decoder   (submodule)
#   import json.encoder   (submodule)
#   from json import loads, dumps  (from-import)

# Entry: "json.decoder" (RESTRICTIVE - only decoder, not encoder)
# Allows:
#   import json.decoder           (exact match)
#   import json                   (parent dependency)
# Does NOT allow:
#   import json.encoder           (sibling - NOT allowed)
#   from json import encoder      (sibling via from-import - NOT allowed)

# Entry: "xml.etree.ElementTree" (RESTRICTIVE - only ElementTree)
# Allows:
#   import xml.etree.ElementTree  (exact match)
#   import xml.etree              (parent dependency)
#   import xml                    (grandparent dependency)
# Does NOT allow:
#   import xml.dom                (sibling of xml.etree - NOT allowed)
#   import xml.sax                (sibling of xml.etree - NOT allowed)

# Entry: "myapp.plugins.safe.validator" (VERY RESTRICTIVE)
# Allows:
#   import myapp.plugins.safe.validator       (exact match)
#   import myapp.plugins.safe.validator.core  (child - allowed)
#   import myapp.plugins.safe                 (parent dependency)
#   import myapp.plugins                      (grandparent dependency)
#   import myapp                              (great-grandparent dependency)
# Does NOT allow:
#   import myapp.plugins.safe.executor        (sibling - NOT allowed)
#   import myapp.plugins.dangerous            (uncle - NOT allowed)
#   import myapp.core                         (unrelated - NOT allowed)
```

## Checking Current Configuration

```python
# Get current allowlist
allowed = sys.sandbox.allowed_imports
print(allowed)  # frozenset({'json', 'math', 're'})

# Check mode
print(sys.sandbox.import_restrict_mode)  # True/False
```

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## Data Structures

The allowlist is stored as a Python `frozenset` of strings, with a pre-computed `allowed_ancestors` set:

```c
typedef struct {
    /* ... other fields ... */

    /* Import allowlist - Python frozenset of module path strings.
     * Entry "X" allows: X itself, all submodules X.*, and parent dependencies. */
    PyObject *allowed_imports;

    /* Pre-computed ancestors of allowed_imports entries.
     * Used for O(1) dependency checks. Auto-computed when allowed_imports changes.
     * Example: if allowed_imports={"json.decoder"}, then allowed_ancestors={"json"} */
    PyObject *allowed_ancestors;
} _PySandboxState;
```

## Import Check Algorithm

The check runs in O(p) time where p = number of parts in the module path:

```c
static int
is_module_allowed(_PySandboxState *sandbox, const char *module_str)
{
    if (sandbox->allowed_imports == NULL) {
        return 0;
    }

    size_t module_len = strlen(module_str);

    /* Check each prefix of the module (including the full module) */
    for (size_t i = 0; i <= module_len; i++) {
        if (i == module_len || module_str[i] == '.') {
            /* Build prefix string */
            PyObject *prefix = PyUnicode_FromStringAndSize(module_str, i);
            if (prefix == NULL) {
                return -1;
            }

            /* Check if prefix is in allowed_imports */
            int result = PySet_Contains(sandbox->allowed_imports, prefix);
            Py_DECREF(prefix);

            if (result < 0) {
                return -1;
            }
            if (result) {
                return 1;  /* Found: module or ancestor is directly allowed */
            }
        }
    }

    /* Check if module is a required dependency (in allowed_ancestors) */
    if (sandbox->allowed_ancestors != NULL) {
        PyObject *module_obj = PyUnicode_FromString(module_str);
        if (module_obj == NULL) {
            return -1;
        }

        int result = PySet_Contains(sandbox->allowed_ancestors, module_obj);
        Py_DECREF(module_obj);

        if (result < 0) {
            return -1;
        }
        if (result) {
            return 1;  /* Module is a required dependency */
        }
    }

    return 0;  /* Not allowed */
}
```

## Ancestor Computation

When `allowed_imports` is set, ancestors are computed automatically:

```c
/* For each entry in allowed_imports, add all its parent prefixes to allowed_ancestors.
 * Example: "json.decoder.JSONDecoder" adds "json" and "json.decoder" to ancestors. */
static int
compute_ancestors(_PySandboxState *sandbox)
{
    /* Clear existing ancestors */
    Py_CLEAR(sandbox->allowed_ancestors);

    if (sandbox->allowed_imports == NULL) {
        return 0;
    }

    /* Create new ancestors set */
    PyObject *ancestors = PySet_New(NULL);

    /* For each entry, add all parent prefixes */
    PyObject *iter = PyObject_GetIter(sandbox->allowed_imports);
    PyObject *entry;
    while ((entry = PyIter_Next(iter)) != NULL) {
        const char *entry_str = PyUnicode_AsUTF8(entry);
        size_t len = strlen(entry_str);

        for (size_t i = 0; i < len; i++) {
            if (entry_str[i] == '.') {
                PyObject *prefix = PyUnicode_FromStringAndSize(entry_str, i);
                PySet_Add(ancestors, prefix);
                Py_DECREF(prefix);
            }
        }
        Py_DECREF(entry);
    }
    Py_DECREF(iter);

    sandbox->allowed_ancestors = ancestors;
    return 0;
}
```

## C API

```c
/* Set allowed imports (set of module path strings, or None to clear) */
int PySandbox_SetAllowedImports(PyObject *modules);

/* Get current allowed imports (returns new reference to frozenset) */
PyObject *PySandbox_GetAllowedImports(void);
```

## Python API

### Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `import_restrict_mode` | bool | True | Enable import restrictions |
| `allowed_imports` | frozenset | empty | Set of module path strings |

### Setting Allowed Imports

```python
# From list of strings
sys.sandbox.allowed_imports = ["json", "math", "xml.etree.ElementTree"]

# From set
sys.sandbox.allowed_imports = {"json", "math"}

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
SandboxImportError: Import of 'os' is not allowed in sandbox scope
```

# Drawbacks
[drawbacks]: #drawbacks

1. **Allowlist Maintenance**: Must explicitly list all allowed modules; easy to miss legitimate needs.

2. **Transitive Imports**: If allowed module `A` internally imports blocked module `B`, the import may fail unexpectedly.

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
allowed_imports = {"json", "math"}
```
- Default-deny: only explicitly allowed modules work
- Safer against unknown threats
- Clear intent

## Why String Format vs. Tuple Format?

**Old tuple format** (rejected):
```python
allowed_imports = {("json", ""), ("json", "loads")}
```
- Complex semantics for `("module", "")` vs `("module", "name")`
- Submodule handling was complex and error-prone

**New string format** (chosen):
```python
allowed_imports = {"json", "json.decoder"}
```
- Simple: entry "X" allows X and X.*
- Parent dependencies computed automatically
- O(p) check where p = number of path parts

## Why Auto-Compute Ancestors?

When you allow `"json.decoder"`, you need `import json` to work (Python requires loading parent modules first). Rather than forcing users to list all parents, ancestors are computed automatically:

```python
# User writes:
allowed_imports = {"json.decoder"}

# System computes:
allowed_ancestors = {"json"}

# Result: both 'import json' and 'import json.decoder' work
# But 'import json.encoder' is blocked (sibling, not ancestor)
```

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
