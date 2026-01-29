- Feature Name: sandbox-exceptions
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox exceptions module defines a dedicated exception hierarchy for sandbox violations. All sandbox-related errors inherit from `SandboxError`, allowing callers to catch all violations with a single `except SandboxError` clause while still distinguishing specific violation types.

# Motivation
[motivation]: #motivation

Without dedicated exceptions, sandbox violations would use generic Python exceptions:

```python
# Confusing: what caused this OverflowError?
except OverflowError:
    # Integer too large? Stack overflow? Sandbox limit?
    pass
```

Dedicated exceptions provide:

1. **Clear identification**: Know exactly that a sandbox limit was hit
2. **Catch-all capability**: `except SandboxError` catches all sandbox issues
3. **Specific handling**: Can handle different violation types differently
4. **Better error messages**: Context-specific messages for each violation type

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Exception Hierarchy

```
Exception
 └── SandboxError (base class for all sandbox violations)
      ├── SandboxOverflowError    (size/length limit exceeded)
      ├── SandboxMemoryError      (allocation limit exceeded)
      ├── SandboxRuntimeError     (statement/iteration/operation limit, banned opcode)
      ├── SandboxTypeError        (forbidden type creation)
      ├── SandboxAttributeError   (frozen mode, dunder access blocked)
      ├── SandboxSecurityError    (unsafe operation blocked)
      └── SandboxImportError      (import not allowed)
```

## Catching All Sandbox Errors

```python
import sys

sys.sandbox.set_limits(
    max_int_digits=100,
    max_list_size=1000,
    max_statements=10000,
)
sys.sandbox.add_filename("<sandbox>")

code = compile(untrusted_source, "<sandbox>", "exec")

try:
    exec(code)
except SandboxError as e:
    # Catches any sandbox violation
    print(f"Sandbox violation: {e}")
```

## Catching Specific Error Types

```python
try:
    exec(sandboxed_code)
except SandboxOverflowError:
    print("Object too large (int, string, or container)")
except SandboxMemoryError:
    print("Too many allocations")
except SandboxRuntimeError:
    print("Execution limit exceeded (statements, iterations, or operations)")
except SandboxTypeError:
    print("Forbidden type (float or complex)")
except SandboxAttributeError:
    print("Attribute access blocked (frozen or dunder)")
except SandboxSecurityError:
    print("Unsafe operation blocked")
except SandboxImportError:
    print("Import not allowed")
except SandboxError:
    print("Other sandbox error")
```

## Error Messages

Each exception type has specific error message formats:

| Exception | Example Message |
|-----------|-----------------|
| `SandboxOverflowError` | `"Integer size (150 digits) exceeds sandbox limit (100 digits)"` |
| `SandboxOverflowError` | `"String length (50000) exceeds sandbox limit (10000)"` |
| `SandboxOverflowError` | `"List size (2000) exceeds sandbox limit (1000)"` |
| `SandboxMemoryError` | `"Sandbox allocation limit exceeded"` |
| `SandboxRuntimeError` | `"Sandbox statement limit exceeded"` |
| `SandboxRuntimeError` | `"Sandbox iteration limit exceeded"` |
| `SandboxRuntimeError` | `"Sandbox operation limit exceeded"` |
| `SandboxRuntimeError` | `"Opcode 108 is not allowed in sandbox scope"` |
| `SandboxTypeError` | `"float type is forbidden in sandbox"` |
| `SandboxAttributeError` | `"cannot modify frozen object 'dict'"` |
| `SandboxAttributeError` | `"cannot modify 'type' object: sandbox frozen mode is active"` |
| `SandboxAttributeError` | `"dunder attribute access blocked in sandbox: '__class__'"` |
| `SandboxSecurityError` | `"compile() is not allowed in sandbox"` |
| `SandboxSecurityError` | `"Cannot modify sandbox configuration from within sandbox scope"` |
| `SandboxImportError` | `"Import of 'os' is not allowed in sandbox"` |

## Checking Exception Type

```python
try:
    exec(sandboxed_code)
except SandboxError as e:
    if isinstance(e, SandboxOverflowError):
        # Handle size limit
        pass
    elif isinstance(e, SandboxRuntimeError):
        # Handle execution limit
        pass
```

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## Exception Definitions

In `Objects/exceptions.c`:

```c
/* Base exception */
SimpleExtendsException(PyExc_Exception, SandboxError,
                       "Base class for sandbox violations");

/* Size/length limit exceeded */
SimpleExtendsException(PyExc_SandboxError, SandboxOverflowError,
                       "Sandbox size/length limit exceeded");

/* Allocation limit exceeded */
SimpleExtendsException(PyExc_SandboxError, SandboxMemoryError,
                       "Sandbox allocation limit exceeded");

/* Statement/iteration/operation limit exceeded */
SimpleExtendsException(PyExc_SandboxError, SandboxRuntimeError,
                       "Sandbox runtime limit exceeded");

/* Forbidden type creation */
SimpleExtendsException(PyExc_SandboxError, SandboxTypeError,
                       "Sandbox type restriction violated");

/* Frozen object or dunder access */
SimpleExtendsException(PyExc_SandboxError, SandboxAttributeError,
                       "Sandbox attribute access violation");

/* Unsafe operation (compile, gc, etc.) */
SimpleExtendsException(PyExc_SandboxError, SandboxSecurityError,
                       "Sandbox security violation");

/* Import not allowed */
SimpleExtendsException(PyExc_SandboxError, SandboxImportError,
                       "Sandbox import restriction violated");
```

## Exception Declarations

In `Include/pyerrors.h`:

```c
PyAPI_DATA(PyObject *) PyExc_SandboxError;
PyAPI_DATA(PyObject *) PyExc_SandboxOverflowError;
PyAPI_DATA(PyObject *) PyExc_SandboxMemoryError;
PyAPI_DATA(PyObject *) PyExc_SandboxRuntimeError;
PyAPI_DATA(PyObject *) PyExc_SandboxTypeError;
PyAPI_DATA(PyObject *) PyExc_SandboxAttributeError;
PyAPI_DATA(PyObject *) PyExc_SandboxSecurityError;
PyAPI_DATA(PyObject *) PyExc_SandboxImportError;
```

## Exception Usage in Check Functions

### Size Overflow

```c
int
_PySandbox_CheckListSize(Py_ssize_t size)
{
    /* ... checks ... */
    PyErr_Format(PyExc_SandboxOverflowError,
                 "List size (%zd) exceeds sandbox limit (%zd)",
                 size, limits->max_list_size);
    return -1;
}
```

### Allocation Limit

```c
int
_PySandbox_CheckAllocation(void)
{
    /* ... checks ... */
    PyErr_SetString(PyExc_SandboxMemoryError,
                    "Sandbox allocation limit exceeded");
    return -1;
}
```

### Runtime Limits

```c
int
_PySandbox_CheckScopeStatement(void)
{
    /* ... checks ... */
    PyErr_SetString(PyExc_SandboxRuntimeError,
                    "Sandbox statement limit exceeded");
    return -1;
}

int
_PySandbox_CheckOpcode(int opcode)
{
    /* ... checks ... */
    PyErr_Format(PyExc_SandboxRuntimeError,
                 "Opcode %d is not allowed in sandbox scope", opcode);
    return -1;
}
```

### Type Restriction

```c
int
_PySandbox_CheckTypeAllowed(PyTypeObject *type)
{
    /* ... checks ... */
    PyErr_SetString(PyExc_SandboxTypeError,
                    "float type is forbidden in sandbox");
    return -1;
}
```

### Attribute Violations

```c
int
_PySandbox_CheckFrozen(PyObject *obj)
{
    /* ... checks ... */
    if (Py_IS_FROZEN(obj)) {
        PyErr_Format(PyExc_SandboxAttributeError,
                     "cannot modify frozen object '%.100s'",
                     Py_TYPE(obj)->tp_name);
    } else {
        PyErr_Format(PyExc_SandboxAttributeError,
                     "cannot modify '%.100s' object: sandbox frozen mode is active",
                     Py_TYPE(obj)->tp_name);
    }
    return -1;
}

int
_PySandbox_CheckDunderAccess(PyObject *name)
{
    /* ... checks ... */
    PyErr_Format(PyExc_SandboxAttributeError,
                 "dunder attribute access blocked in sandbox: '%U'", name);
    return -1;
}
```

### Security Violations

```c
int
_PySandbox_CheckUnsafeBlocked(const char *operation)
{
    /* ... checks ... */
    PyErr_Format(PyExc_SandboxSecurityError,
                 "%s is not allowed in sandbox", operation);
    return -1;
}

int
_PySandbox_CheckConfigModification(void)
{
    /* ... checks ... */
    PyErr_SetString(PyExc_SandboxSecurityError,
                    "Cannot modify sandbox configuration from within sandbox scope");
    return -1;
}
```

### Import Violations

```c
int
_PySandbox_CheckImport(PyObject *abs_name, PyObject *fromlist)
{
    /* ... checks ... */
    PyErr_Format(PyExc_SandboxImportError,
                 "Import of '%U' is not allowed in sandbox", abs_name);
    return -1;
}
```

## Builtin Availability

All sandbox exceptions are available as builtins:

```python
# These work without import
try:
    ...
except SandboxError:
    pass

except SandboxOverflowError:
    pass

# etc.
```

## Grace Behavior

### Allocation Grace Headroom

When allocation limit is hit, 1000 additional allocations are allowed before hard failure. This allows the exception itself to be created and handled:

```python
try:
    exec(sandboxed_code)
except SandboxMemoryError:
    # This handler can allocate objects for logging, etc.
    error_message = f"Allocation failed"  # Creates string
    log_error(error_message)              # May allocate
```

### Single-Raise Behavior

Statement, iteration, and operation limits raise exactly once (at `count == max + 1`). Subsequent violations don't raise additional exceptions:

```python
try:
    exec(sandboxed_code)
except SandboxRuntimeError:
    # This handler's statements don't trigger more SandboxRuntimeError
    cleanup()
    log_error()
```

# Drawbacks
[drawbacks]: #drawbacks

1. **New Exception Types**: Users must learn new exception classes.

2. **Not Standard**: These exceptions don't map to standard Python exceptions like `OverflowError`, `MemoryError`.

3. **Catch-All Risk**: `except SandboxError` might catch errors user wanted to handle specifically.

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why Not Use Standard Exceptions?

**Alternative**: Reuse `OverflowError`, `MemoryError`, `RuntimeError`, etc.

- Rejected: Ambiguous (can't tell sandbox error from legitimate error)
- Rejected: No common base class for catch-all
- Rejected: Different semantics (standard exceptions may propagate differently)

## Why Single Base Class?

Allows catch-all pattern:
```python
except SandboxError:
    # Handle any sandbox issue
```

Without common base:
```python
except (SandboxOverflowError, SandboxMemoryError, SandboxRuntimeError, ...):
    # Verbose and error-prone
```

## Why Not Exception Chaining?

**Alternative**: Wrap original exception
```python
except OverflowError as e:
    raise SandboxOverflowError("Sandbox limit") from e
```

- Rejected: No original exception to wrap (limit check happens before failure)
- Rejected: Added complexity for no benefit

# Prior art
[prior-art]: #prior-art

1. **OSError Subclasses**: Python 3.3+ has `FileNotFoundError`, `PermissionError`, etc. Similar pattern of specific subclasses.

2. **Django Exceptions**: Django has `ValidationError`, `PermissionDenied`, etc. with common base.

3. **requests Exceptions**: `RequestException` base with `HTTPError`, `ConnectionError`, etc.

# Unresolved questions
[unresolved-questions]: #unresolved-questions

1. Should there be additional exception types for more specific violations?

2. Should exceptions include structured data (limit value, actual value)?

3. Should there be warning-level violations that don't raise but log?

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Structured Exception Data**: Add attributes like `limit_value`, `actual_value`, `operation_type`.

2. **Exception Policies**: Configure whether violations raise, warn, or are silently ignored.

3. **Exception Hooks**: Callback when exceptions are raised for logging/monitoring.

4. **Recovery Hints**: Include suggestions for how to fix the violation.
