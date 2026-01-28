# CPython Sandbox Implementation Guide

This comprehensive document describes the complete implementation of the sandbox system for CPython. It provides all details needed to port this feature to Python 3.12, 3.13, 3.14, or other versions.

## Table of Contents

1. [Overview](#overview)
2. [Feature Summary](#feature-summary)
3. [Sandbox Exceptions](#sandbox-exceptions)
4. [Architecture](#architecture)
5. [Data Structures](#data-structures)
6. [Limit Types and Enforcement](#limit-types-and-enforcement)
7. [Scope Tracking](#scope-tracking)
8. [Iteration Limits and Iterator Wrapper](#iteration-limits-and-iterator-wrapper)
9. [Operation Counting](#operation-counting)
10. [Dunder Access Control](#dunder-access-control)
11. [Frozen Mode](#frozen-mode)
12. [Auto-Mutable Mode](#auto-mutable-mode)
13. [Opcode Restrictions](#opcode-restrictions)
14. [Object Creation Hooks](#object-creation-hooks)
15. [Suspend/Resume](#suspendresume)
16. [Integration Points](#integration-points)
17. [Python API Reference](#python-api-reference)
18. [C API Reference](#c-api-reference)
19. [Implementation Files](#implementation-files)
20. [Porting Guide](#porting-guide)
21. [Testing](#testing)

---

## Overview

The CPython sandbox provides mechanisms for limiting resource usage, monitoring object creation, and restricting operations in Python code. It is designed for executing untrusted code with controlled resource limits.

### Key Capabilities

- **Resource Limits**: Restrict size of integers, strings, bytes, lists, dicts, sets, tuples
- **Type Restrictions**: Forbid creation of float or complex types
- **Allocation Limits**: Limit total object allocations (global and scoped)
- **Statement Limits**: Limit number of statements executed (prevents infinite loops)
- **Iteration Limits**: Limit number of iterator steps (prevents abuse via C builtins)
- **Operation Counting**: Limit AST-level operations via compiler-emitted `SANDBOX_COUNT` opcodes
- **Dunder Access Control**: Block access to double-underscore attributes in sandbox scope
- **Frozen Mode**: Prevent attribute mutations globally or per-object
- **Auto-Mutable Mode**: Automatically mark newly created objects as mutable in sandbox scope
- **Opcode Restrictions**: Ban specific bytecode opcodes from executing in sandbox scope
- **Scope Tracking**: Track limits only for specific code (by filename)
- **Object Creation Hooks**: Intercept and optionally replace objects at creation time
- **Suspend/Resume**: Temporarily bypass limits for trusted code
- **Sandbox Exceptions**: Dedicated exception hierarchy for sandbox violations

---

## Feature Summary

| Feature | Description | Exception Type |
|---------|-------------|----------------|
| `max_int_digits` | Max internal digits (~30 bits each) for integers | `SandboxOverflowError` |
| `max_str_length` | Max characters in strings | `SandboxOverflowError` |
| `max_bytes_length` | Max bytes in bytes/bytearray | `SandboxOverflowError` |
| `max_list_size` | Max items in lists | `SandboxOverflowError` |
| `max_dict_size` | Max entries in dicts | `SandboxOverflowError` |
| `max_set_size` | Max members in sets | `SandboxOverflowError` |
| `max_tuple_size` | Max items in tuples | `SandboxOverflowError` |
| `allow_float` | Allow/forbid float creation | `SandboxTypeError` |
| `allow_complex` | Allow/forbid complex creation | `SandboxTypeError` |
| `allow_dunder_access` | Allow/block `__dunder__` attributes | `SandboxAttributeError` |
| `max_allocations` | Max GC-tracked allocations total | `SandboxMemoryError` |
| `max_scope_allocations` | Max allocations in sandbox scope | `SandboxMemoryError` |
| `max_scope_statements` | Max statements in sandbox scope | `SandboxRuntimeError` |
| `max_scope_iterations` | Max iterator steps in sandbox scope | `SandboxRuntimeError` |
| `max_scope_operations` | Max AST operations via `SANDBOX_COUNT` opcode | `SandboxRuntimeError` |
| Frozen mode (global) | Block all attribute mutations | `SandboxAttributeError` |
| Frozen mode (per-object) | Block mutations on specific objects | `SandboxAttributeError` |
| Opcode restrictions | Ban specific bytecode opcodes | `SandboxRuntimeError` |

---

## Sandbox Exceptions

All sandbox violations raise exceptions from a dedicated hierarchy rooted at `SandboxError`. This allows callers to catch all sandbox-related errors with a single `except SandboxError` clause while still distinguishing specific violation types.

### Exception Hierarchy

```
Exception
 +-- SandboxError
      +-- SandboxOverflowError    (size/length limit exceeded)
      +-- SandboxMemoryError      (allocation limit exceeded)
      +-- SandboxRuntimeError     (statement/iteration/operation limit, banned opcode)
      +-- SandboxTypeError        (forbidden type creation)
      +-- SandboxAttributeError   (frozen mode, dunder access blocked)
```

### Exception Types and Error Messages

| Limit | Exception | Error Message |
|-------|-----------|---------------|
| `max_int_digits` | `SandboxOverflowError` | "Integer size (N digits) exceeds sandbox limit (M digits)" |
| `max_str_length` | `SandboxOverflowError` | "String length (N) exceeds sandbox limit (M)" |
| `max_bytes_length` | `SandboxOverflowError` | "Bytes length (N) exceeds sandbox limit (M)" |
| `max_list_size` | `SandboxOverflowError` | "List size (N) exceeds sandbox limit (M)" |
| `max_dict_size` | `SandboxOverflowError` | "Dict size (N) exceeds sandbox limit (M)" |
| `max_set_size` | `SandboxOverflowError` | "Set size (N) exceeds sandbox limit (M)" |
| `max_tuple_size` | `SandboxOverflowError` | "Tuple size (N) exceeds sandbox limit (M)" |
| `allow_float=False` | `SandboxTypeError` | "float type is forbidden in sandbox" |
| `allow_complex=False` | `SandboxTypeError` | "complex type is forbidden in sandbox" |
| `allow_dunder_access=False` | `SandboxAttributeError` | "dunder attribute access blocked in sandbox: 'name'" |
| `max_allocations` | `SandboxMemoryError` | "Sandbox global allocation limit exceeded" |
| `max_scope_allocations` | `SandboxMemoryError` | "Sandbox scoped allocation limit exceeded" |
| `max_scope_statements` | `SandboxRuntimeError` | "Sandbox statement limit exceeded" |
| `max_scope_iterations` | `SandboxRuntimeError` | "Sandbox iteration limit exceeded" |
| `max_scope_operations` | `SandboxRuntimeError` | "Sandbox operation limit exceeded" |
| Frozen mode (global) | `SandboxAttributeError` | "cannot modify 'type' object: sandbox frozen mode is active" |
| Frozen mode (per-object) | `SandboxAttributeError` | "cannot modify frozen object 'type'" |
| Banned opcode | `SandboxRuntimeError` | "Opcode N is not allowed in sandbox scope" |

### Exception Registration

The exceptions are defined in `Objects/exceptions.c` using the `SimpleExtendsException` macro:

```c
SimpleExtendsException(PyExc_Exception, SandboxError,
                       "Base class for sandbox violations");
SimpleExtendsException(PyExc_SandboxError, SandboxOverflowError,
                       "Sandbox size/length limit exceeded");
SimpleExtendsException(PyExc_SandboxError, SandboxMemoryError,
                       "Sandbox allocation limit exceeded");
SimpleExtendsException(PyExc_SandboxError, SandboxRuntimeError,
                       "Sandbox runtime limit exceeded");
SimpleExtendsException(PyExc_SandboxError, SandboxTypeError,
                       "Sandbox type restriction violated");
SimpleExtendsException(PyExc_SandboxError, SandboxAttributeError,
                       "Sandbox attribute access violation");
```

They are declared in `Include/pyerrors.h`:

```c
PyAPI_DATA(PyObject *) PyExc_SandboxError;
PyAPI_DATA(PyObject *) PyExc_SandboxOverflowError;
PyAPI_DATA(PyObject *) PyExc_SandboxMemoryError;
PyAPI_DATA(PyObject *) PyExc_SandboxRuntimeError;
PyAPI_DATA(PyObject *) PyExc_SandboxTypeError;
PyAPI_DATA(PyObject *) PyExc_SandboxAttributeError;
```

All sandbox exceptions are available as builtins (e.g. `except SandboxError:`).

### Memory Allocation Grace Behavior

When `max_allocations` or `max_scope_allocations` limits are reached, the sandbox allows a small number of additional "grace" allocations before raising `SandboxMemoryError`. This grace period exists because:

1. **Error object creation**: Python needs to allocate objects to create and raise the `SandboxMemoryError` exception itself
2. **Exception handling**: The code catching the exception may need to allocate objects for logging, cleanup, or error reporting

The implementation uses a `ALLOCATION_GRACE_HEADROOM` constant (1000 allocations) to allow error handling to proceed after the limit is first hit.

### Statement/Iteration Limit Single-Raise Behavior

The `max_scope_statements` and `max_scope_iterations` limits have special behavior: the `SandboxRuntimeError` is raised **exactly once**, on the first call that exceeds the limit. Subsequent calls do not raise additional exceptions.

This design allows:
1. **Exception handlers to execute**: The `except` and `finally` blocks need to run statements to handle the error
2. **Cleanup code to complete**: Resource cleanup and logging can proceed normally
3. **Stack unwinding**: Python can properly unwind the call stack

---

## Architecture

### Component Diagram

```
+-------------------------------------------------------------------+
|                        Python Code                                |
|   sys.sandbox.set_limits(...)  sys.sandbox.add_filename(...)          |
|   sys.sandbox.frozen_mode = ...  sys.sandbox.banned_opcodes = ... |
+-------------------------------------------------------------------+
                                |
                                v
+-------------------------------------------------------------------+
|                      Python/sysmodule.c                           |
|   sys_setsandboxlimits()  sys_addsandboxfilename()  etc.          |
+-------------------------------------------------------------------+
                                |
                                v
+-------------------------------------------------------------------+
|                      Python/sandbox.c                             |
|   _PySandbox_CheckIntSize()  _PySandbox_AddFilename()             |
|   _PySandbox_CheckFrozen()   _PySandbox_CheckOpcode()             |
|   _PySandbox_CheckIteration()  _PySandbox_WrapIterator()          |
+-------------------------------------------------------------------+
                                |
            +-------------------+-------------------+
            v                   v                   v
+-------------------+ +-------------------+ +-------------------+
| Objects/          | | Python/ceval.c    | | Modules/          |
| longobject.c      | | Statement tracing | | gcmodule.c        |
| listobject.c      | | Opcode checking   | | Allocation count  |
| dictobject.c      | | Dunder access     | |                   |
| abstract.c        | |                   | |                   |
| object.c          | |                   | |                   |
| descrobject.c     | |                   | |                   |
| etc.              | |                   | |                   |
+-------------------+ +-------------------+ +-------------------+
```

### State Storage

Sandbox state is stored in `PyInterpreterState`:

```c
typedef struct _is {
    /* ... other fields ... */
    _PySandboxState sandbox;
    /* ... other fields ... */
} PyInterpreterState;
```

### Object-Level State

Per-object frozen/mutable flags are stored in `ob_flags` (a new `uint32_t` field added to `PyObject`):

```c
typedef struct _object {
    Py_ssize_t ob_refcnt;
    uint32_t ob_flags;      /* Per-instance sandbox flags */
    PyTypeObject *ob_type;
} PyObject;

#define Py_OBJFLAGS_FROZEN    (1U << 0)  /* Object is individually frozen */
#define Py_OBJFLAGS_MUTABLE   (1U << 1)  /* Override: allow mutation even in frozen mode */

#define Py_IS_FROZEN(op) (((PyObject*)(op))->ob_flags & Py_OBJFLAGS_FROZEN)
#define Py_IS_MUTABLE(op) (((PyObject*)(op))->ob_flags & Py_OBJFLAGS_MUTABLE)
```

---

## Data Structures

### File: `Include/internal/pycore_sandbox.h`

#### `_PySandboxOpcodeSet`

256-bit bitmap for opcode restriction:

```c
typedef struct {
    uint32_t bits[8];  /* 8 * 32 = 256 bits */
} _PySandboxOpcodeSet;

#define _PySandbox_OpcodeSet_HAS(set, op)   ((set)->bits[(op) >> 5] & (1U << ((op) & 31)))
#define _PySandbox_OpcodeSet_SET(set, op)   ((set)->bits[(op) >> 5] |= (1U << ((op) & 31)))
#define _PySandbox_OpcodeSet_CLEAR(set, op) ((set)->bits[(op) >> 5] &= ~(1U << ((op) & 31)))
#define _PySandbox_OpcodeSet_ZERO(set)      memset((set)->bits, 0, sizeof((set)->bits))
```

#### `_PySandboxFilenameSet`

Stores registered filenames for scope tracking:

```c
typedef struct {
    PyObject **filenames;    /* Array of filename strings (strong refs) */
    size_t capacity;         /* Array capacity */
    size_t count;            /* Number of registered filenames */
} _PySandboxFilenameSet;
```

#### `_PySandboxLimits`

Main structure holding all limit values and counters:

```c
typedef struct {
    /* Integer limits: max number of internal digits (each ~30 bits) */
    Py_ssize_t max_int_digits;

    /* String/bytes limits: max length in characters/bytes */
    Py_ssize_t max_str_length;
    Py_ssize_t max_bytes_length;

    /* Container limits: max number of items */
    Py_ssize_t max_list_size;
    Py_ssize_t max_dict_size;
    Py_ssize_t max_set_size;
    Py_ssize_t max_tuple_size;

    /* Global allocation limits (apply to all allocations) */
    uint64_t global_max_allocations;   /* 0 = no limit */
    uint64_t global_allocation_count;  /* Current count */

    /* Scoped limits - only enforced within sandbox scope */
    uint64_t scope_max_statements;      /* 0 = no limit */
    uint64_t scope_statement_count;     /* Statement executions in scope */
    uint64_t scope_max_allocations;     /* 0 = no limit */
    uint64_t scope_allocation_count;    /* Allocations in scope */
    uint64_t scope_max_iterations;      /* 0 = no limit */
    uint64_t scope_iteration_count;     /* Iterator calls in scope */
    uint64_t scope_max_operations;      /* 0 = no limit */
    uint64_t scope_operation_count;     /* Counted operations (SANDBOX_COUNT opcode) in scope */

    /* Sandbox scope tracking - set of registered filenames */
    _PySandboxFilenameSet registered_filenames;

    /* Type restrictions */
    int allow_float;         /* 0 = forbidden, 1 = allowed (default) */
    int allow_complex;       /* 0 = forbidden, 1 = allowed (default) */

    /* Recursion prevention */
    int in_check;

    /* Suspend counter */
    int suspended;

    /* Dunder access control */
    int allow_dunder_access;     /* 1 = allowed (default), 0 = block __ attributes */
} _PySandboxLimits;
```

#### `_PyObjectCreationHook`

State for object creation hooks:

```c
typedef struct {
    Py_ObjectCreationHookFunc hook_func;  /* C-level hook */
    void *hook_userdata;                   /* Userdata for C hook */
    PyObject *hook_callback;               /* Python-level callback */
    int in_hook;                           /* Recursion prevention */
} _PyObjectCreationHook;
```

#### `_PySandboxState`

Combined state:

```c
typedef struct {
    _PySandboxLimits limits;
    _PyObjectCreationHook creation_hook;
    int frozen_mode;                     /* 1 = global freeze active, 0 = normal */
    int auto_mutable_mode;               /* 1 = auto-mark created objects as mutable, 0 = off */
    int opcode_restrict_mode;            /* 1 = active, 0 = off */
    _PySandboxOpcodeSet banned_opcodes;  /* bitmap of banned opcodes */
} _PySandboxState;
```

#### Initializer Macros

```c
#define _PySandboxLimits_INIT { \
    .max_int_digits = 0,            \
    .max_str_length = 0,            \
    .max_bytes_length = 0,          \
    .max_list_size = 0,             \
    .max_dict_size = 0,             \
    .max_set_size = 0,              \
    .max_tuple_size = 0,            \
    .global_max_allocations = 0,    \
    .global_allocation_count = 0,   \
    .scope_max_statements = 0,      \
    .scope_statement_count = 0,     \
    .scope_max_allocations = 0,     \
    .scope_allocation_count = 0,    \
    .scope_max_iterations = 0,      \
    .scope_iteration_count = 0,     \
    .scope_max_operations = 0,      \
    .scope_operation_count = 0,     \
    .registered_filenames = {.filenames = NULL, .capacity = 0, .count = 0}, \
    .allow_float = 1,               \
    .allow_complex = 1,             \
    .in_check = 0,                  \
    .suspended = 0,                 \
    .allow_dunder_access = 1,       \
}

#define _PyObjectCreationHook_INIT { \
    .hook_func = NULL,               \
    .hook_userdata = NULL,           \
    .hook_callback = NULL,           \
    .in_hook = 0,                    \
}

#define _PySandboxState_INIT {              \
    .limits = _PySandboxLimits_INIT,        \
    .creation_hook = _PyObjectCreationHook_INIT, \
    .frozen_mode = 0,                       \
    .auto_mutable_mode = 0,                 \
    .opcode_restrict_mode = 0,              \
    .banned_opcodes = {{0}},                \
}
```

---

## Limit Types and Enforcement

### Integer Size Limit (`max_int_digits`)

**Purpose**: Prevent denial-of-service via extremely large integers.

**Unit**: Internal digits (each ~30 bits, roughly 9 decimal digits).

**Enforcement Point**: `Objects/longobject.c` in `_PyLong_New()`

```c
PyLongObject *
_PyLong_New(Py_ssize_t size)
{
    if (_PySandbox_CheckIntSize(size) < 0) {
        return NULL;
    }
    /* ... rest of allocation ... */
}
```

**Check Function** (`Python/sandbox.c`):

```c
int
_PySandbox_CheckIntSize(Py_ssize_t ndigits)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_int_digits)

    if (ndigits > limits->max_int_digits) {
        limits->in_check = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Integer size (%zd digits) exceeds sandbox limit (%zd digits)",
                     ndigits, limits->max_int_digits);
        limits->in_check = 0;
        return -1;
    }
    return 0;
}
```

### String Length Limit (`max_str_length`)

**Purpose**: Prevent memory exhaustion via huge strings.

**Unit**: Characters (Unicode code points).

**Enforcement Point**: `Objects/unicodeobject.c` in `PyUnicode_New()`

### Bytes Length Limit (`max_bytes_length`)

**Purpose**: Prevent memory exhaustion via huge byte strings.

**Enforcement Point**: `Objects/bytesobject.c` in `PyBytes_FromStringAndSize()` and related functions.

### Container Size Limits (`max_list_size`, `max_dict_size`, `max_set_size`, `max_tuple_size`)

**Purpose**: Prevent memory exhaustion via huge containers.

**Enforcement Points**:
- `Objects/listobject.c` in `list_resize()` and other growth functions
- `Objects/dictobject.c` in dict insertion/growth functions
- `Objects/setobject.c` in set addition functions
- `Objects/tupleobject.c` in `PyTuple_New()`

All size limit checks follow the same pattern using the `_PYSANDBOX_CHECK_PROLOGUE` macro for early exits:

```c
#define _PYSANDBOX_CHECK_PROLOGUE(limit_field) \
    _PySandboxLimits *limits = get_sandbox_limits(); \
    if (limits == NULL || limits->limit_field == 0 || \
        limits->in_check || limits->suspended) { \
        return 0; \
    }
```

### Type Restrictions (`allow_float`, `allow_complex`)

**Purpose**: Forbid creation of specific types.

**Enforcement Point**: `Objects/typeobject.c` in `type_call()`, `Objects/floatobject.c`, and `Objects/complexobject.c`.

```c
int
_PySandbox_CheckTypeAllowed(PyTypeObject *type)
{
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->suspended) {
        return 0;
    }

    if (!limits->allow_float && type == &PyFloat_Type) {
        PyErr_SetString(PyExc_SandboxTypeError,
                        "float type is forbidden in sandbox");
        return -1;
    }

    if (!limits->allow_complex && type == &PyComplex_Type) {
        PyErr_SetString(PyExc_SandboxTypeError,
                        "complex type is forbidden in sandbox");
        return -1;
    }

    return 0;
}
```

---

## Scope Tracking

### Filename-Based Tracking

Scope is tracked by registering `co_filename` values. All code compiled with a registered filename counts toward scoped limits.

### How It Works

1. User registers a filename: `sys.sandbox.add_filename("<my-sandbox>")`
2. User compiles code with that filename: `compile(source, "<my-sandbox>", "exec")`
3. All code objects (functions, classes, etc.) in that compilation share the filename
4. When executing, if current frame's `co_filename` is registered, counts increment

### Key Functions

#### `filename_is_registered()`

```c
static int
filename_is_registered(_PySandboxFilenameSet *set, PyObject *filename)
{
    if (set->filenames == NULL || set->count == 0 || filename == NULL) {
        return 0;
    }

    for (size_t i = 0; i < set->count; i++) {
        PyObject *registered = set->filenames[i];
        if (registered == filename) {
            return 1;  /* Pointer equality - quick match */
        }
        /* String comparison fallback */
        int cmp = PyUnicode_Compare(filename, registered);
        if (cmp == 0 && !PyErr_Occurred()) {
            return 1;
        }
        PyErr_Clear();
    }
    return 0;
}
```

#### `frame_in_sandbox_scope()`

```c
static int
frame_in_sandbox_scope(_PySandboxFilenameSet *set, _PyInterpreterFrame *frame)
{
    if (set->filenames == NULL || set->count == 0 || frame == NULL) {
        return 0;
    }

    /* Skip incomplete frames */
    while (frame && _PyFrame_IsIncomplete(frame)) {
        frame = frame->previous;
    }
    if (frame == NULL) {
        return 0;
    }

    return filename_is_registered(set, frame->f_code->co_filename);
}
```

### Statement Counting

**Enforcement Point**: `Python/ceval.c` via line tracing.

When `scope_max_statements > 0`, Python enables line tracing. Each line execution calls `_PySandbox_CheckScopeStatement()`.

```c
int
_PySandbox_CheckScopeStatement(void)
{
    /* ... thread state checks ... */
    _PySandboxLimits *limits = &interp->sandbox.limits;

    if (limits->scope_max_statements == 0 ||
        limits->in_check || limits->suspended) {
        return 0;
    }

    if (limits->registered_filenames.count == 0) {
        return 0;
    }

    _PyInterpreterFrame *current = get_current_interpreter_frame();
    if (!frame_in_sandbox_scope(&limits->registered_filenames, current)) {
        return 0;
    }

    limits->scope_statement_count++;

    /* Only raise error ONCE at exactly max+1 to allow error handling */
    if (limits->scope_statement_count == limits->scope_max_statements + 1) {
        limits->in_check = 1;
        PyErr_SetString(PyExc_SandboxRuntimeError,
                        "Sandbox statement limit exceeded");
        limits->in_check = 0;
        return -1;
    }

    return 0;
}
```

#### Statement Counting Exception Behavior

The statement limit uses a deliberate "single-raise" pattern. The key is the use of `==` (equals) rather than `>=` (greater-than-or-equal):

```c
if (limits->scope_statement_count == limits->scope_max_statements + 1)
```

1. **First violation (count == limit + 1)**: Raises `SandboxRuntimeError`
2. **Subsequent statements (count > limit + 1)**: No exception raised, execution continues

This allows `except` and `finally` blocks to run, enables proper stack unwinding, and avoids cascading failures during error handling.

### Allocation Counting

**Enforcement Point**: `Modules/gcmodule.c` in `_PyObject_GC_Alloc()`.

```c
int
_PySandbox_CheckAllocation(void)
{
    /* ... thread/interpreter state checks ... */
    _PySandboxLimits *limits = &interp->sandbox.limits;

    if (limits->in_check || limits->suspended) {
        return 0;
    }

    /* Always increment global count */
    limits->global_allocation_count++;

    /* Check if in scope for scoped counting */
    int in_scope = 0;
    if (limits->registered_filenames.count > 0) {
        _PyInterpreterFrame *current = get_current_interpreter_frame();
        if (current != NULL) {
            in_scope = frame_in_sandbox_scope(&limits->registered_filenames, current);
        }
    }

    if (in_scope) {
        limits->scope_allocation_count++;
    }

    /* Skip raising if error already set */
    if (PyErr_Occurred()) {
        return 0;
    }

    /* Check global limit with grace headroom */
    if (limits->global_max_allocations > 0) {
        if (limits->global_allocation_count > limits->global_max_allocations + ALLOCATION_GRACE_HEADROOM) {
            PyErr_SetString(PyExc_SandboxMemoryError, "Sandbox global allocation limit exceeded");
            return -1;
        }
        if (limits->global_allocation_count == limits->global_max_allocations + 1) {
            PyErr_SetString(PyExc_SandboxMemoryError, "Sandbox global allocation limit exceeded");
            return -1;
        }
    }

    /* Check scoped limit with grace headroom */
    if (in_scope && limits->scope_max_allocations > 0) {
        if (limits->scope_allocation_count > limits->scope_max_allocations + ALLOCATION_GRACE_HEADROOM) {
            PyErr_SetString(PyExc_SandboxMemoryError, "Sandbox scoped allocation limit exceeded");
            return -1;
        }
        if (limits->scope_allocation_count == limits->scope_max_allocations + 1) {
            PyErr_SetString(PyExc_SandboxMemoryError, "Sandbox scoped allocation limit exceeded");
            return -1;
        }
    }

    return 0;
}
```

---

## Iteration Limits and Iterator Wrapper

### Purpose

Prevent infinite or excessive iteration in sandboxed code. This is critical because many C-level builtins (e.g., `list()`, `sum()`, `sorted()`, `min()`, `max()`) call `tp_iternext` directly, bypassing the Python-level statement counter. The iteration limit covers all these cases.

### How It Works

1. **Iterator Wrapping**: When an iterator is created via `PyObject_GetIter()` while in sandbox scope, the returned iterator is wrapped in a `_PySandboxIteratorWrapper` object.
2. **Per-Step Checking**: Each call to the wrapper's `tp_iternext` checks `_PySandbox_CheckIteration()` before delegating to the wrapped iterator.
3. **Single Wrap Point**: By wrapping at `PyObject_GetIter()`, all 26+ direct `tp_iternext` call sites in CPython are automatically protected.

### Iterator Wrapper Implementation

```c
typedef struct {
    PyObject_HEAD
    PyObject *wrapped;  /* The wrapped iterator (strong ref) */
} _PySandboxIteratorWrapper;

static PyObject *
sandbox_iter_wrapper_iternext(_PySandboxIteratorWrapper *self)
{
    /* Check iteration limits BEFORE delegating */
    if (_PySandbox_CheckIteration() < 0) {
        return NULL;  /* Exception already set */
    }

    /* Delegate to wrapped iterator's tp_iternext */
    PyTypeObject *type = Py_TYPE(self->wrapped);
    return (*type->tp_iternext)(self->wrapped);
}
```

### Wrap Function

```c
PyObject *
_PySandbox_WrapIterator(PyObject *iter)
{
    if (iter == NULL) return NULL;

    /* Don't wrap if not in sandbox scope */
    if (!_PySandbox_IsInScope()) {
        Py_INCREF(iter);
        return iter;
    }

    /* Avoid wrapping an already-wrapped iterator */
    if (Py_TYPE(iter) == &_PySandboxIteratorWrapper_Type) {
        Py_INCREF(iter);
        return iter;
    }

    /* Create and return wrapper */
    _PySandboxIteratorWrapper *wrapper = PyObject_GC_New(
        _PySandboxIteratorWrapper, &_PySandboxIteratorWrapper_Type);
    Py_INCREF(iter);
    wrapper->wrapped = iter;
    PyObject_GC_Track(wrapper);
    return (PyObject *)wrapper;
}
```

### Iteration Check Function

```c
int
_PySandbox_CheckIteration(void)
{
    /* ... thread/interpreter state checks ... */
    _PySandboxLimits *limits = &interp->sandbox.limits;

    if (limits->scope_max_iterations == 0 ||
        limits->in_check || limits->suspended) {
        return 0;
    }

    if (limits->registered_filenames.count == 0) {
        return 0;
    }

    _PyInterpreterFrame *current = get_current_interpreter_frame();
    if (!frame_in_sandbox_scope(&limits->registered_filenames, current)) {
        return 0;
    }

    limits->scope_iteration_count++;

    /* Only raise error ONCE at exactly max+1 */
    if (limits->scope_iteration_count == limits->scope_max_iterations + 1) {
        limits->in_check = 1;
        PyErr_SetString(PyExc_SandboxRuntimeError,
                        "Sandbox iteration limit exceeded");
        limits->in_check = 0;
        return -1;
    }

    return 0;
}
```

### Lazy Type Initialization

The wrapper type (`_PySandboxIteratorWrapper_Type`) is initialized lazily on first use rather than during `_PySandbox_Init()`, because `PyType_Ready()` requires a valid thread state which isn't available during early interpreter initialization.

---

## Operation Counting

### Purpose

Provide precise AST-level operation counting with zero tracing overhead. Unlike statement counting (which relies on line tracing and counts every line execution), operation counting uses a dedicated `SANDBOX_COUNT` opcode emitted by the compiler at specific AST nodes. This counts only semantically meaningful operations (calls, arithmetic, attribute access, etc.).

### How It Works

1. **Compile Flag**: Code must be compiled with `PyCF_SANDBOX_COUNT` (0x8000). Without this flag, no `SANDBOX_COUNT` opcodes are emitted, so there is zero overhead.
2. **Compiler Emission**: During compilation, `ADDOP_SANDBOX_COUNT(c)` is inserted at each counted AST node.
3. **Runtime Check**: Each `SANDBOX_COUNT` opcode calls `_PySandbox_CheckScopeOperation()`, which increments `scope_operation_count` and checks against `max_scope_operations`.

### Compile Flag

Defined in `Include/cpython/compile.h`:

```c
#define PyCF_SANDBOX_COUNT 0x8000
```

Added to `PyCF_MASK` so the compiler accepts it:

```c
#define PyCF_MASK (... | PyCF_SANDBOX_COUNT)
```

### Compiler Integration

In `Python/compile.c`, a macro emits the opcode conditionally:

```c
#define ADDOP_SANDBOX_COUNT(C) { \
    if ((C)->c_flags->cf_flags & PyCF_SANDBOX_COUNT) { \
        ADDOP((C), SANDBOX_COUNT); \
    } \
}
```

This macro is placed at the start of each counted AST node visitor:

**Counted Statements**: `Assign`, `AugAssign`, `Delete`, `Pass`, `Break`, `Continue`, `Return`, `If`, `For`, `While`, `Try`, `Import`, `ImportFrom`, `Assert`, `FunctionDef`, `ClassDef`

**Counted Expressions**: `Call`, `BinOp`, `UnaryOp`, `Compare`, `BoolOp`, `Attribute`, `Subscript`

**Not Counted**: `Expr` (statement wrapper), `Global`, `Nonlocal` (compile-time directives), literal values, `Name` loads

### Opcode Definition

In `Lib/opcode.py` and `Include/opcode.h`:

```c
#define SANDBOX_COUNT  181
```

### Runtime Handler

In `Python/ceval.c`:

```c
TARGET(SANDBOX_COUNT) {
    PyInterpreterState *interp = tstate->interp;
    if (interp->sandbox.limits.scope_max_operations > 0 &&
        !interp->sandbox.limits.suspended) {
        if (_PySandbox_CheckScopeOperation() < 0) {
            goto error;
        }
    }
    DISPATCH();
}
```

### Check Function

In `Python/sandbox.c`:

```c
int
_PySandbox_CheckScopeOperation(void)
{
    /* ... thread/interpreter state checks ... */
    _PySandboxLimits *limits = &interp->sandbox.limits;

    if (limits->scope_max_operations == 0 ||
        limits->in_check || limits->suspended) {
        return 0;
    }

    if (limits->registered_filenames.count == 0) {
        return 0;
    }

    _PyInterpreterFrame *current = get_current_interpreter_frame();
    if (!frame_in_sandbox_scope(&limits->registered_filenames, current)) {
        return 0;
    }

    limits->scope_operation_count++;

    /* Only raise error ONCE at exactly max+1 */
    if (limits->scope_operation_count == limits->scope_max_operations + 1) {
        limits->in_check = 1;
        PyErr_SetString(PyExc_SandboxRuntimeError,
                        "Sandbox operation limit exceeded");
        limits->in_check = 0;
        return -1;
    }

    return 0;
}
```

### Performance

- Code compiled **without** `PyCF_SANDBOX_COUNT`: zero overhead (no `SANDBOX_COUNT` opcodes present).
- Code compiled **with** the flag but no operation limit set (`scope_max_operations == 0`): one pointer dereference + comparison per counted node (predicted not-taken branch).
- Code with the flag and an active limit: one scope check + counter increment per counted node.

### Independence from Statement Counting

Operation counting is fully independent from statement counting:
- Different counters: `scope_operation_count` vs `scope_statement_count`
- Different limits: `max_scope_operations` vs `max_scope_statements`
- Different mechanisms: compiler-emitted opcode vs line tracing
- Both can be used simultaneously

---

## Dunder Access Control

### Purpose

Block access to double-underscore (`__dunder__`) attributes from sandboxed code, preventing introspection-based sandbox escapes (e.g., `obj.__class__.__subclasses__()`, `obj.__globals__`).

### Configuration

Set via `sys.sandbox.set_limits(allow_dunder_access=False)`. Default is `True` (allowed).

### Scope-Aware

Dunder blocking is only enforced within sandbox scope. Code outside the scope (e.g., the test framework, stdlib) can access dunder attributes freely.

### Enforcement Point

`Objects/abstract.c` and `Objects/descrobject.c` for attribute access operations (LOAD_ATTR, STORE_ATTR, DELETE_ATTR).

### Check Function

```c
int
_PySandbox_CheckDunderAccess(PyObject *name)
{
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->allow_dunder_access ||
        limits->in_check || limits->suspended) {
        return 0;
    }

    if (!is_dunder_name(name)) {
        return 0;
    }

    /* Check if in sandbox scope */
    if (limits->registered_filenames.count == 0) {
        return 0;
    }

    _PyInterpreterFrame *frame = get_current_interpreter_frame();
    if (frame == NULL || !frame_in_sandbox_scope(&limits->registered_filenames, frame)) {
        return 0;
    }

    limits->in_check = 1;
    PyErr_Format(PyExc_SandboxAttributeError,
                 "dunder attribute access blocked in sandbox: '%U'", name);
    limits->in_check = 0;
    return -1;
}
```

### Dunder Name Detection

A name is considered a "dunder" if it contains `__` anywhere (using `strstr`):

```c
static int
is_dunder_name(PyObject *name)
{
    const char *str = PyUnicode_AsUTF8(name);
    return strstr(str, "__") != NULL;
}
```

---

## Frozen Mode

### Purpose

Prevent all attribute mutations on objects, useful for ensuring sandboxed code cannot modify shared state. Supports both a global flag and per-object freeze/mutable overrides.

### Global Frozen Mode

When enabled via `sys.sandbox.frozen_mode = True`, all attribute set/delete operations are blocked within sandbox scope unless the target object has the `Py_OBJFLAGS_MUTABLE` flag.

### Per-Object Freezing

Individual objects can be frozen with `sys.sandbox.freeze(obj)`, which sets `Py_OBJFLAGS_FROZEN` in `ob_flags`. This works independently of global frozen mode.

### Mutable Override

Objects can be marked as mutable with `sys.sandbox.set_mutable(obj)`, which sets `Py_OBJFLAGS_MUTABLE`. This overrides both global frozen mode and per-object freeze.

### Priority Order

1. **Mutable flag** (`Py_OBJFLAGS_MUTABLE`): If set, always allow mutations (fast exit)
2. **Suspend state**: If sandbox is suspended, allow all mutations
3. **Scope check**: Only enforce within sandbox scope
4. **Per-instance frozen** (`Py_OBJFLAGS_FROZEN`): If set, block mutations
5. **Global frozen mode**: If active, block mutations

### Enforcement Points

- `Objects/object.c` in `PyObject_GenericSetAttr()` and `PyObject_GenericSetDict()`
- `Objects/typeobject.c` in `type_setattro()`
- `Objects/descrobject.c` in descriptor set/delete

### Check Function

```c
int
_PySandbox_CheckFrozen(PyObject *obj)
{
    /* Fast path: mutable objects are always allowed */
    if (Py_IS_MUTABLE(obj)) {
        return 0;
    }

    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL || interp->sandbox.limits.suspended) {
        return 0;
    }

    int obj_frozen = Py_IS_FROZEN(obj);
    if (!obj_frozen && !interp->sandbox.frozen_mode) {
        return 0;  /* No frozen restrictions exist */
    }

    /* Only enforce within sandbox scope */
    _PySandboxLimits *limits = &interp->sandbox.limits;
    _PyInterpreterFrame *frame = get_current_interpreter_frame();
    if (!frame_in_sandbox_scope(&limits->registered_filenames, frame)) {
        return 0;
    }

    if (obj_frozen) {
        PyErr_Format(PyExc_SandboxAttributeError,
                     "cannot modify frozen object '%.100s'",
                     Py_TYPE(obj)->tp_name);
        return -1;
    }

    PyErr_Format(PyExc_SandboxAttributeError,
                 "cannot modify '%.100s' object: sandbox frozen mode is active",
                 Py_TYPE(obj)->tp_name);
    return -1;
}
```

---

## Auto-Mutable Mode

### Purpose

When frozen mode is active, sandboxed code cannot modify any objects -- including ones it creates itself (classes, instances, functions). Auto-mutable mode solves this by automatically marking newly created objects with `Py_OBJFLAGS_MUTABLE` when created within sandbox scope.

### Configuration

- Enable: `sys.sandbox.auto_mutable = True`
- Disable: `sys.sandbox.auto_mutable = False`
- Check: `sys.sandbox.auto_mutable -> bool`

Both `auto_mutable_mode` and `frozen_mode` must be active for auto-marking to occur.

### Implementation

In `Python/sandbox.c`:

```c
void
_PySandbox_MaybeMarkMutable(PyObject *obj)
{
    assert(obj != NULL);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return;
    }
    /* Fast path: both flags must be on */
    if (!interp->sandbox.auto_mutable_mode || !interp->sandbox.frozen_mode) {
        return;
    }
    if (interp->sandbox.limits.suspended) {
        return;
    }

    /* Check if current frame is in sandbox scope */
    /* ... frame scope check ... */

    /* Mark the object as mutable */
    ((PyObject *)obj)->ob_flags |= Py_OBJFLAGS_MUTABLE;
}
```

### Enforcement Points

`_PySandbox_MaybeMarkMutable()` is called from:
- `Objects/typeobject.c` in `type_call()` -- marks newly created instances and classes
- `Python/ceval.c` in `MAKE_FUNCTION` -- marks newly created function objects

### C API

```c
PyAPI_FUNC(void) PySandbox_SetAutoMutableMode(int mode);
PyAPI_FUNC(int) PySandbox_GetAutoMutableMode(void);
PyAPI_FUNC(void) _PySandbox_MaybeMarkMutable(PyObject *obj);
```

---

## Opcode Restrictions

### Purpose

Ban specific bytecode opcodes from executing within sandbox scope. This allows fine-grained control over what operations sandboxed code can perform (e.g., blocking `IMPORT_NAME`, `IMPORT_FROM`, `IMPORT_STAR` to prevent imports).

### Configuration

1. Set the banned opcodes: `sys.sandbox.banned_opcodes = {opcode_int, ...}`
2. Enable restriction mode: `sys.sandbox.opcode_restrict_mode = True`

### Bitmap-Based Checking

Banned opcodes are stored in a 256-bit bitmap (`_PySandboxOpcodeSet`) for O(1) lookup:

```c
typedef struct {
    uint32_t bits[8];  /* 8 * 32 = 256 bits */
} _PySandboxOpcodeSet;
```

### Enforcement Point

`Python/ceval.c` in the `DO_TRACING` handler. The check runs for every opcode dispatch when tracing is active.

### Fast Exits

The check function has multiple fast exits to minimize overhead:

```c
int
_PySandbox_CheckOpcode(int opcode)
{
    /* ... thread/interpreter state checks ... */

    /* Fast exit: mode not active */
    if (!sandbox->opcode_restrict_mode) return 0;

    /* Fast exit: suspended or in recursive check */
    if (limits->suspended || limits->in_check) return 0;

    /* Fast exit: opcode not banned */
    if (!_PySandbox_OpcodeSet_HAS(&sandbox->banned_opcodes, opcode)) return 0;

    /* Check if in sandbox scope */
    if (!frame_in_sandbox_scope(&limits->registered_filenames, frame)) return 0;

    /* Banned opcode in sandbox scope - raise error */
    limits->in_check = 1;
    PyErr_Format(PyExc_SandboxRuntimeError,
                 "Opcode %d is not allowed in sandbox scope", opcode);
    limits->in_check = 0;
    return -1;
}
```

---

## Object Creation Hooks

### Purpose

Allow interception of object creation for monitoring or replacement.

### Hook Function Signature

```c
typedef PyObject* (*Py_ObjectCreationHookFunc)(
    PyObject *obj,          /* The object being created */
    PyTypeObject *type,     /* The type of the object */
    struct _frame *frame,   /* Current frame (may be NULL) */
    int flags,              /* Py_OBJHOOK_TYPE_CALL or Py_OBJHOOK_INIT */
    void *userdata          /* User-provided data pointer */
);
```

### Flags

```c
#define Py_OBJHOOK_TYPE_CALL  0x01  /* Called from type_call - can replace */
#define Py_OBJHOOK_INIT       0x02  /* Called from _PyObject_Init - observe only */
```

### Enforcement Point

`Objects/typeobject.c` in `type_call()`:

```c
static PyObject *
type_call(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    /* ... create object ... */

    obj = _PySandbox_CallCreationHook(obj, type, Py_OBJHOOK_TYPE_CALL);
    if (obj == NULL) {
        return NULL;  /* Hook raised exception */
    }

    return obj;
}
```

### Python API

```python
def my_hook(obj, type_, frame, context):
    print(f"Created {type_.__name__}")
    return obj  # Return original or replacement

sys.sandbox.creation_hook = my_hook

class Foo:
    pass

instance = Foo()  # Prints: Created Foo

sys.sandbox.creation_hook = None  # Remove hook
```

---

## Suspend/Resume

### Purpose

Temporarily bypass all limits for trusted code (e.g., during syscalls or stdlib operations).

### API

```python
count = sys.sandbox.suspend()  # count = 1
count = sys.sandbox.suspend()  # count = 2 (nested)
count = sys.sandbox.resume()   # count = 1
count = sys.sandbox.resume()   # count = 0, limits active again

if sys.sandbox.suspended:
    # Limits are bypassed
```

### Implementation

```c
int
PySandbox_Suspend(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    _PySandboxLimits *limits = &interp->sandbox.limits;
    limits->suspended++;
    return limits->suspended;
}

int
PySandbox_Resume(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    _PySandboxLimits *limits = &interp->sandbox.limits;
    if (limits->suspended > 0) {
        limits->suspended--;
    }
    return limits->suspended;
}
```

All check functions test `limits->suspended` early:

```c
if (limits->suspended) {
    return 0;  /* Limits bypassed */
}
```

Suspend also bypasses frozen mode checks and opcode restrictions.

---

## Integration Points

### Files Modified

| File | Purpose |
|------|---------|
| `Include/internal/pycore_sandbox.h` | Data structures and API declarations |
| `Include/internal/pycore_interp.h` | Add `_PySandboxState sandbox` to `PyInterpreterState` |
| `Include/cpython/compile.h` | Add `PyCF_SANDBOX_COUNT` flag |
| `Include/opcode.h` | Add `SANDBOX_COUNT` opcode (181) |
| `Include/object.h` | Add `ob_flags` field, `Py_OBJFLAGS_*` macros |
| `Include/pyerrors.h` | Declare `PyExc_Sandbox*` exception types |
| `Include/patchlevel.h` | Version string update (`3.11.14+sandbox`) |
| `Python/sandbox.c` | Core implementation |
| `Python/sysmodule.c` | Python API (sys module functions) |
| `Python/pystate.c` | State initialization |
| `Python/ceval.c` | Statement tracing, opcode checking, `SANDBOX_COUNT` handler |
| `Python/compile.c` | Emit `SANDBOX_COUNT` at AST nodes (`PyCF_SANDBOX_COUNT`) |
| `Modules/gcmodule.c` | Allocation counting |
| `Objects/longobject.c` | Integer size check |
| `Objects/unicodeobject.c` | String length check |
| `Objects/bytesobject.c` | Bytes length check |
| `Objects/listobject.c` | List size check |
| `Objects/dictobject.c` | Dict size check |
| `Objects/setobject.c` | Set size check |
| `Objects/tupleobject.c` | Tuple size check |
| `Objects/floatobject.c` | Float type check |
| `Objects/complexobject.c` | Complex type check |
| `Objects/typeobject.c` | Type check, creation hook, frozen mode |
| `Objects/object.c` | Frozen mode check on `GenericSetAttr` |
| `Objects/abstract.c` | Dunder access check, iterator wrapping |
| `Objects/descrobject.c` | Dunder access check, frozen mode |
| `Objects/sliceobject.c` | Minor adjustment |
| `Objects/exceptions.c` | Sandbox exception classes |
| `Makefile.pre.in` | Build system (sandbox.c) |
| `PCbuild/_freeze_module.vcxproj` | Windows build |
| `PCbuild/pythoncore.vcxproj` | Windows build |

### PyInterpreterState Integration

In `Include/internal/pycore_interp.h`:

```c
struct _is {
    /* ... other fields ... */
    _PySandboxState sandbox;
    /* ... other fields ... */
};
```

### Initialization

In `Python/pystate.c` / `Python/pylifecycle.c`:

```c
_PySandbox_Init(interp);   /* During interpreter creation */
_PySandbox_Fini(interp);   /* During interpreter finalization */
```

---

## Python API Reference

### Limit Configuration

| Function | Description |
|----------|-------------|
| `sys.sandbox.set_limits(**kwargs)` | Set all limit values (see parameters below) |
| `sys.sandbox.get_limits() -> dict` | Get current limit values |
| `sys.sandbox.get_counts() -> dict` | Get current counter values |

**`set_limits()` parameters:**
- `max_int_digits` (int): Max internal integer digits. Default: 0 (no limit)
- `max_str_length` (int): Max string length. Default: 0
- `max_bytes_length` (int): Max bytes length. Default: 0
- `max_list_size` (int): Max list size. Default: 0
- `max_dict_size` (int): Max dict size. Default: 0
- `max_set_size` (int): Max set size. Default: 0
- `max_tuple_size` (int): Max tuple size. Default: 0
- `max_allocations` (int): Max GC-tracked allocations total. Default: 0
- `max_scope_statements` (int): Max statements in sandbox scope. Default: 0
- `max_scope_allocations` (int): Max allocations in sandbox scope. Default: 0
- `max_scope_iterations` (int): Max iterator steps in sandbox scope. Default: 0
- `max_scope_operations` (int): Max AST operations (requires `PyCF_SANDBOX_COUNT`). Default: 0
- `allow_float` (bool): Allow float creation. Default: True
- `allow_complex` (bool): Allow complex creation. Default: True
- `allow_dunder_access` (bool): Allow `__dunder__` attribute access. Default: True

**`getsandboxcounts` returns:**
- `allocation_count`: Total GC-tracked allocations
- `scope_allocation_count`: Allocations within sandbox scope
- `scope_statement_count`: Statements executed within sandbox scope
- `scope_iteration_count`: Iterator steps within sandbox scope
- `scope_operation_count`: Operations counted via `SANDBOX_COUNT` opcode

### Counter Reset

| Function | Description |
|----------|-------------|
| `sys.sandbox.reset_counts()` | Reset all counters (global and scope) to 0 |

### Scope Management

| Function | Description |
|----------|-------------|
| `sys.sandbox.enter_scope()` | Add current frame's filename + reset scope counters |
| `sys.sandbox.exit_scope()` | Clear all registered filenames |
| `sys.sandbox.add_frame()` | Add current frame's filename to registered set |
| `sys.sandbox.in_scope() -> bool` | Check if current code is in scope |
| `sys.sandbox.add_filename(filename)` | Register a filename for tracking |
| `sys.sandbox.remove_filename(filename)` | Remove a filename from tracking |
| `sys.sandbox.clear_filenames()` | Clear all registered filenames |

### Object Creation Hook

| Function | Description |
|----------|-------------|
| `sys.sandbox.creation_hook = callback` | Set hook callback (or None) |
| `sys.sandbox.creation_hook -> callable` | Get current hook |

### Suspend/Resume

| Function | Description |
|----------|-------------|
| `sys.sandbox.suspend() -> int` | Suspend limits, return count |
| `sys.sandbox.resume() -> int` | Resume limits, return count |
| `sys.sandbox.suspended -> bool` | Check if suspended |

### Frozen Mode

| Function | Description |
|----------|-------------|
| `sys.sandbox.frozen_mode = enabled` | Enable/disable global frozen mode |
| `sys.sandbox.frozen_mode -> bool` | Check if global frozen mode is active |
| `sys.sandbox.freeze(obj)` | Freeze a specific object |
| `sys.sandbox.is_frozen(obj) -> bool` | Check if object is individually frozen |
| `sys.sandbox.set_mutable(obj, mutable=True)` | Mark object as mutable (overrides freeze) |
| `sys.sandbox.auto_mutable = enabled` | Enable/disable auto-mutable mode |
| `sys.sandbox.auto_mutable -> bool` | Check if auto-mutable mode is active |

### Opcode Restrictions

| Function | Description |
|----------|-------------|
| `sys.sandbox.opcode_restrict_mode = enabled` | Enable/disable opcode restriction mode |
| `sys.sandbox.opcode_restrict_mode -> bool` | Check if opcode restriction mode is active |
| `sys.sandbox.banned_opcodes = opcode_set` | Set banned opcodes (iterable of ints, or None) |
| `sys.sandbox.banned_opcodes -> frozenset` | Get currently banned opcodes |

---

## C API Reference

### Limit Checks

```c
PyAPI_FUNC(int) _PySandbox_CheckIntSize(Py_ssize_t ndigits);
PyAPI_FUNC(int) _PySandbox_CheckStrLength(Py_ssize_t length);
PyAPI_FUNC(int) _PySandbox_CheckBytesLength(Py_ssize_t length);
PyAPI_FUNC(int) _PySandbox_CheckListSize(Py_ssize_t size);
PyAPI_FUNC(int) _PySandbox_CheckDictSize(Py_ssize_t size);
PyAPI_FUNC(int) _PySandbox_CheckSetSize(Py_ssize_t size);
PyAPI_FUNC(int) _PySandbox_CheckTupleSize(Py_ssize_t size);
PyAPI_FUNC(int) _PySandbox_CheckTypeAllowed(PyTypeObject *type);
PyAPI_FUNC(int) _PySandbox_CheckAllocation(void);
PyAPI_FUNC(int) _PySandbox_CheckScopeStatement(void);
PyAPI_FUNC(int) _PySandbox_CheckIteration(void);
PyAPI_FUNC(int) _PySandbox_CheckScopeOperation(void);
PyAPI_FUNC(int) _PySandbox_CheckDunderAccess(PyObject *name);
PyAPI_FUNC(int) _PySandbox_CheckFrozen(PyObject *obj);
PyAPI_FUNC(int) _PySandbox_CheckOpcode(int opcode);
```

### Scope Management

```c
PyAPI_FUNC(int) _PySandbox_EnterScope(void);
PyAPI_FUNC(int) _PySandbox_ExitScope(void);
PyAPI_FUNC(int) _PySandbox_IsInScope(void);
PyAPI_FUNC(int) _PySandbox_AddFrameToScope(void);
PyAPI_FUNC(int) _PySandbox_AddFilename(PyObject *filename);
PyAPI_FUNC(int) _PySandbox_RemoveFilename(PyObject *filename);
PyAPI_FUNC(void) _PySandbox_ClearFilenames(void);
```

### Counter Reset

```c
PyAPI_FUNC(void) _PySandbox_ResetCounters(void);
```

### Iterator Wrapper

```c
PyAPI_DATA(PyTypeObject) _PySandboxIteratorWrapper_Type;
PyAPI_FUNC(PyObject *) _PySandbox_WrapIterator(PyObject *iter);
```

### Object Creation Hook

```c
PyAPI_FUNC(PyObject *) _PySandbox_CallCreationHook(
    PyObject *obj, PyTypeObject *type, int flags);
```

### Initialization

```c
PyAPI_FUNC(void) _PySandbox_Init(PyInterpreterState *interp);
PyAPI_FUNC(void) _PySandbox_Fini(PyInterpreterState *interp);
```

### Suspend/Resume

```c
PyAPI_FUNC(int) PySandbox_Suspend(void);
PyAPI_FUNC(int) PySandbox_Resume(void);
PyAPI_FUNC(int) PySandbox_IsSuspended(void);
```

### Frozen Mode

```c
PyAPI_FUNC(void) PySandbox_SetFrozenMode(int mode);
PyAPI_FUNC(int) PySandbox_GetFrozenMode(void);
PyAPI_FUNC(void) PySandbox_FreezeObject(PyObject *obj);
PyAPI_FUNC(int) PySandbox_IsObjectFrozen(PyObject *obj);
PyAPI_FUNC(void) PySandbox_SetObjectMutable(PyObject *obj, int mutable);

/* Auto-mutable mode */
PyAPI_FUNC(void) PySandbox_SetAutoMutableMode(int mode);
PyAPI_FUNC(int) PySandbox_GetAutoMutableMode(void);
PyAPI_FUNC(void) _PySandbox_MaybeMarkMutable(PyObject *obj);
```

### Opcode Restrictions

```c
PyAPI_FUNC(void) PySandbox_SetOpcodeRestrictMode(int mode);
PyAPI_FUNC(int) PySandbox_GetOpcodeRestrictMode(void);
PyAPI_FUNC(int) PySandbox_SetBannedOpcodes(PyObject *opcode_set);
PyAPI_FUNC(PyObject *) PySandbox_GetBannedOpcodes(void);
```

---

## Implementation Files

### Complete File Listing

```
Include/
  object.h                  # Modified: add ob_flags, Py_OBJFLAGS_* macros
  opcode.h                  # Modified: add SANDBOX_COUNT (181)
  pyerrors.h                # Modified: declare PyExc_Sandbox* exceptions
  patchlevel.h              # Modified: version string
  cpython/
    compile.h               # Modified: add PyCF_SANDBOX_COUNT flag
  internal/
    pycore_sandbox.h        # Data structures, API declarations (NEW FILE)
    pycore_interp.h         # Modified: add sandbox field
    pycore_pystate.h        # Modified: tracing state
    pycore_opcode.h         # Modified: SANDBOX_COUNT opcode metadata

Python/
  sandbox.c                 # Core implementation (NEW FILE, ~1700 lines)
  sysmodule.c               # Modified: add sys.* functions (~700 lines added)
  pystate.c                 # Modified: initialization
  ceval.c                   # Modified: statement tracing, opcode checking, SANDBOX_COUNT handler
  compile.c                 # Modified: emit SANDBOX_COUNT at AST nodes
  opcode_targets.h          # Modified: add SANDBOX_COUNT target

Modules/
  gcmodule.c                # Modified: allocation counting

Objects/
  longobject.c              # Modified: int size check
  unicodeobject.c           # Modified: string length check
  bytesobject.c             # Modified: bytes length check
  listobject.c              # Modified: list size check
  dictobject.c              # Modified: dict size check
  setobject.c               # Modified: set size check
  tupleobject.c             # Modified: tuple size check
  floatobject.c             # Modified: type check
  complexobject.c           # Modified: type check (NEW FILE for check)
  typeobject.c              # Modified: type check, creation hook, frozen mode
  object.c                  # Modified: frozen mode check
  abstract.c                # Modified: dunder access check, iterator wrapping
  descrobject.c             # Modified: dunder access check, frozen mode
  sliceobject.c             # Modified: minor adjustment
  exceptions.c              # Modified: sandbox exception classes

Build System/
  Makefile.pre.in           # Modified: add sandbox.c
  PCbuild/_freeze_module.vcxproj    # Modified: Windows build
  PCbuild/pythoncore.vcxproj        # Modified: Windows build

Lib/test/test_sandbox/     # Test package (NEW)
  __init__.py               # Package init, shared helpers
  test_limits.py            # API basics, type/size limits, suspend/resume
  test_hooks.py             # Object creation hooks
  test_allocations.py       # Global and scoped allocation counting
  test_scope.py             # Scope management and statement counting
  test_iterations.py        # Iteration counting and iterator wrapper
  test_dunder_access.py     # Dunder attribute blocking
  test_frozen_mode.py       # Frozen mode, auto-mutable mode (global and per-object)
  test_integration.py       # Integration tests
  test_opcodes.py           # Opcode restrictions
  test_operations.py        # Operation counting (SANDBOX_COUNT opcode)

Lib/
  opcode.py                 # Modified: add SANDBOX_COUNT opcode
```

---

## Porting Guide

### Step-by-Step Checklist

1. **Add header file**
   - [ ] Create `Include/internal/pycore_sandbox.h`
   - [ ] Define all data structures (`_PySandboxLimits`, `_PySandboxState`, `_PySandboxOpcodeSet`, etc.)
   - [ ] Define API function declarations

2. **Add object flags**
   - [ ] Add `uint32_t ob_flags` to `PyObject` in `Include/object.h`
   - [ ] Define `Py_OBJFLAGS_FROZEN` and `Py_OBJFLAGS_MUTABLE` macros

3. **Add sandbox exceptions**
   - [ ] Declare `PyExc_Sandbox*` in `Include/pyerrors.h`
   - [ ] Define exception classes in `Objects/exceptions.c`
   - [ ] Register in the exception hierarchy (Level 3 under Exception)

4. **Modify interpreter state**
   - [ ] Add `_PySandboxState sandbox` to `PyInterpreterState` in `pycore_interp.h`

5. **Create implementation**
   - [ ] Create `Python/sandbox.c` (~1600 lines)
   - [ ] Implement all check functions
   - [ ] Implement scope management
   - [ ] Implement iterator wrapper
   - [ ] Implement frozen mode checks
   - [ ] Implement opcode restriction checks
   - [ ] Implement hooks
   - [ ] Implement suspend/resume

6. **Add Python API**
   - [ ] Add all `sys.*` functions to `Python/sysmodule.c` (~600 lines)
   - [ ] Add method table entries

7. **Add initialization**
   - [ ] Call `_PySandbox_Init()` in interpreter creation
   - [ ] Call `_PySandbox_Fini()` in finalization

8. **Integrate limit checks**
   - [ ] `Objects/longobject.c`: `_PySandbox_CheckIntSize()`
   - [ ] `Objects/unicodeobject.c`: `_PySandbox_CheckStrLength()`
   - [ ] `Objects/bytesobject.c`: `_PySandbox_CheckBytesLength()`
   - [ ] `Objects/listobject.c`: `_PySandbox_CheckListSize()`
   - [ ] `Objects/dictobject.c`: `_PySandbox_CheckDictSize()`
   - [ ] `Objects/setobject.c`: `_PySandbox_CheckSetSize()`
   - [ ] `Objects/tupleobject.c`: `_PySandbox_CheckTupleSize()`
   - [ ] `Objects/typeobject.c`: `_PySandbox_CheckTypeAllowed()`, hook, frozen
   - [ ] `Objects/floatobject.c`: `_PySandbox_CheckTypeAllowed()`
   - [ ] `Objects/complexobject.c`: `_PySandbox_CheckTypeAllowed()`
   - [ ] `Objects/object.c`: `_PySandbox_CheckFrozen()`
   - [ ] `Objects/abstract.c`: `_PySandbox_CheckDunderAccess()`, `_PySandbox_WrapIterator()`
   - [ ] `Objects/descrobject.c`: `_PySandbox_CheckDunderAccess()`, `_PySandbox_CheckFrozen()`

9. **Integrate allocation counting**
   - [ ] `Modules/gcmodule.c`: `_PySandbox_CheckAllocation()`

10. **Integrate statement tracing, opcode checking, and operation counting**
    - [ ] `Python/ceval.c`: `_PySandbox_CheckScopeStatement()`, `_PySandbox_CheckOpcode()`, `SANDBOX_COUNT` handler
    - [ ] `Python/compile.c`: Add `ADDOP_SANDBOX_COUNT(c)` macro and emit at AST nodes
    - [ ] `Include/cpython/compile.h`: Add `PyCF_SANDBOX_COUNT` flag to `PyCF_MASK`
    - [ ] `Include/opcode.h`, `Lib/opcode.py`: Define `SANDBOX_COUNT` opcode

11. **Update build system**
    - [ ] `Makefile.pre.in`: Add `sandbox.c` to PYTHON_OBJS
    - [ ] `PCbuild/pythoncore.vcxproj`: Add sandbox.c
    - [ ] `PCbuild/_freeze_module.vcxproj`: Add pycore_sandbox.h

12. **Add tests**
    - [ ] Create `Lib/test/test_sandbox/` package
    - [ ] Test all limit types
    - [ ] Test scope management
    - [ ] Test iteration limits
    - [ ] Test dunder access control
    - [ ] Test frozen mode
    - [ ] Test opcode restrictions
    - [ ] Test hooks
    - [ ] Test suspend/resume
    - [ ] Test operation counting (`SANDBOX_COUNT` opcode)
    - [ ] Test auto-mutable mode
    - [ ] Test exception hierarchy

### Version-Specific Changes

#### Python 3.12+

Frame structure changed:
- Use `tstate->current_frame` instead of `tstate->cframe->current_frame`

```c
/* Python 3.11 */
_PyInterpreterFrame *frame = tstate->cframe->current_frame;

/* Python 3.12+ */
_PyInterpreterFrame *frame = tstate->current_frame;
```

#### Python 3.13+

Verify:
- Frame structure field names
- Interpreter state structure
- GC module allocation paths
- Line tracing mechanism
- `_PyFrame_IsIncomplete` availability

---

## Testing

### Test Package

`Lib/test/test_sandbox/` -- tests split by feature domain.

### Test Modules

| Module | Description |
|--------|-------------|
| `test_limits.py` | API basics, type/size limits, suspend/resume |
| `test_hooks.py` | Object creation hook functionality |
| `test_allocations.py` | Global and scoped allocation counting |
| `test_scope.py` | Scope management, statement counting, filename tracking |
| `test_iterations.py` | Iteration counting and iterator wrapper protection |
| `test_dunder_access.py` | Dunder attribute blocking |
| `test_frozen_mode.py` | Global and per-object frozen mode, auto-mutable mode |
| `test_integration.py` | Combined functionality |
| `test_opcodes.py` | Opcode restriction mode |
| `test_operations.py` | Operation counting (`SANDBOX_COUNT` opcode, `PyCF_SANDBOX_COUNT`) |

### Shared Test Infrastructure

`__init__.py` provides shared helpers:
- `_run_sandboxed_code(code)`: Run code in a subprocess with sandbox limits
- `_get_settable_limits()`: Get current limits for restoring in tearDown
- `SUBPROCESS_TIMEOUT`: Default timeout for subprocess tests (10 seconds)
- Test limit constants (`TEST_LIST_LIMIT`, `TEST_STR_LIMIT`, etc.)

### Running Tests

```bash
# Run all sandbox tests
./python -m pytest Lib/test/test_sandbox/ -v

# Run with unittest
./python -m unittest discover -s Lib/test/test_sandbox -v

# Run a specific test module
./python -m unittest test.test_sandbox.test_limits -v
./python -m unittest test.test_sandbox.test_frozen_mode -v
./python -m unittest test.test_sandbox.test_opcodes -v
```

---

## Appendix: Recommended Limits

For executing untrusted code, these limits provide protection while allowing reasonable operations:

```python
sys.sandbox.set_limits(
    # Data size limits
    max_int_digits=100,           # Integers up to ~10^900
    max_str_length=100_000,       # 100KB strings
    max_bytes_length=100_000,     # 100KB bytes
    max_list_size=1_000_000,      # 1M list items
    max_dict_size=1_000_000,      # 1M dict entries
    max_set_size=1_000_000,       # 1M set members
    max_tuple_size=1_000_000,     # 1M tuple items

    # Execution limits (scoped)
    max_scope_statements=100_000,     # 100K statements
    max_scope_allocations=10_000,     # 10K allocations
    max_scope_iterations=1_000_000,   # 1M iterator steps
    max_scope_operations=100_000,     # 100K AST operations (requires PyCF_SANDBOX_COUNT)

    # Global limits
    max_allocations=1_000_000,        # 1M total allocations

    # Type restrictions (optional)
    allow_float=True,
    allow_complex=True,
    allow_dunder_access=False,    # Block introspection escapes
)
```

Adjust based on your specific requirements and available resources.
