# CPython Sandbox Implementation Guide

This comprehensive document describes the complete implementation of the sandbox system for CPython. It provides all details needed to port this feature to Python 3.12, 3.13, 3.14, or other versions.

## Table of Contents

1. [Overview](#overview)
2. [Feature Summary](#feature-summary)
3. [Architecture](#architecture)
4. [Data Structures](#data-structures)
5. [Limit Types and Enforcement](#limit-types-and-enforcement)
6. [Scope Tracking](#scope-tracking)
7. [Object Creation Hooks](#object-creation-hooks)
8. [Suspend/Resume](#suspendresume)
9. [Integration Points](#integration-points)
10. [Python API Reference](#python-api-reference)
11. [C API Reference](#c-api-reference)
12. [Implementation Files](#implementation-files)
13. [Porting Guide](#porting-guide)
14. [Testing](#testing)

---

## Overview

The CPython sandbox provides mechanisms for limiting resource usage and monitoring object creation in Python code. It's designed for executing untrusted code with controlled resource limits.

### Key Capabilities

- **Resource Limits**: Restrict size of integers, strings, bytes, lists, dicts, sets, tuples
- **Type Restrictions**: Forbid creation of float or complex types
- **Allocation Limits**: Limit total object allocations (global and scoped)
- **Statement Limits**: Limit number of statements executed (prevents infinite loops)
- **Scope Tracking**: Track limits only for specific code (by filename)
- **Object Creation Hooks**: Intercept and optionally replace objects at creation time
- **Suspend/Resume**: Temporarily bypass limits for trusted code

---

## Feature Summary

| Feature | Description | Exception Type |
|---------|-------------|----------------|
| `max_int_digits` | Max internal digits (~30 bits each) for integers | `OverflowError` |
| `max_str_length` | Max characters in strings | `OverflowError` |
| `max_bytes_length` | Max bytes in bytes/bytearray | `OverflowError` |
| `max_list_size` | Max items in lists | `OverflowError` |
| `max_dict_size` | Max entries in dicts | `OverflowError` |
| `max_set_size` | Max members in sets | `OverflowError` |
| `max_tuple_size` | Max items in tuples | `OverflowError` |
| `allow_float` | Allow/forbid float creation | `TypeError` |
| `allow_complex` | Allow/forbid complex creation | `TypeError` |
| `global_max_allocations` | Max GC-tracked allocations total | `MemoryError` |
| `scope_max_allocations` | Max allocations in sandbox scope | `MemoryError` |
| `scope_max_statements` | Max statements in sandbox scope | `RuntimeError` |

---

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Python Code                               │
│   sys.setsandboxlimits(...)  sys.addsandboxfilename(...)        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Python/sysmodule.c                          │
│   sys_setsandboxlimits()  sys_addsandboxfilename()  etc.        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Python/sandbox.c                            │
│   _PySandbox_CheckIntSize()  _PySandbox_AddFilename()  etc.     │
└─────────────────────────────────────────────────────────────────┘
                                │
            ┌───────────────────┼───────────────────┐
            ▼                   ▼                   ▼
┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐
│ Objects/          │ │ Python/ceval.c    │ │ Modules/          │
│ longobject.c      │ │ Statement tracing │ │ gcmodule.c        │
│ listobject.c      │ │                   │ │ Allocation count  │
│ dictobject.c      │ │                   │ │                   │
│ etc.              │ │                   │ │                   │
└───────────────────┘ └───────────────────┘ └───────────────────┘
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

---

## Data Structures

### File: `Include/internal/pycore_sandbox.h`

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

    /* Sandbox scope tracking - set of registered filenames */
    _PySandboxFilenameSet registered_filenames;

    /* Type restrictions */
    int allow_float;         /* 0 = forbidden, 1 = allowed (default) */
    int allow_complex;       /* 0 = forbidden, 1 = allowed (default) */

    /* Recursion prevention */
    int in_check;

    /* Suspend counter */
    int suspended;
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
    .registered_filenames = {.filenames = NULL, .capacity = 0, .count = 0}, \
    .allow_float = 1,               \
    .allow_complex = 1,             \
    .in_check = 0,                  \
    .suspended = 0,                 \
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
}
```

---

## Limit Types and Enforcement

### Integer Size Limit (`max_int_digits`)

**Purpose**: Prevent denial-of-service via extremely large integers.

**Unit**: Internal digits (each ~30 bits, roughly 9 decimal digits).

**Enforcement Point**: `Objects/longobject.c` in `_PyLong_New()`

```c
/* In Objects/longobject.c */
#include "pycore_sandbox.h"

PyLongObject *
_PyLong_New(Py_ssize_t size)
{
    /* ... allocation code ... */

    /* Check sandbox limits before allocation */
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
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->max_int_digits == 0 ||
        limits->in_check || limits->suspended) {
        return 0;  /* No limit, already checking, or suspended */
    }

    if (ndigits > limits->max_int_digits) {
        limits->in_check = 1;
        PyErr_Format(PyExc_OverflowError,
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

```c
/* In Objects/unicodeobject.c */
#include "pycore_sandbox.h"

PyObject *
PyUnicode_New(Py_ssize_t size, Py_UCS4 maxchar)
{
    /* Check sandbox limits */
    if (_PySandbox_CheckStrLength(size) < 0) {
        return NULL;
    }
    /* ... rest of function ... */
}
```

**Check Function**:

```c
int
_PySandbox_CheckStrLength(Py_ssize_t length)
{
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->max_str_length == 0 ||
        limits->in_check || limits->suspended) {
        return 0;
    }

    if (length > limits->max_str_length) {
        limits->in_check = 1;
        PyErr_SetString(PyExc_OverflowError,
                        "String length exceeds sandbox limit");
        limits->in_check = 0;
        return -1;
    }
    return 0;
}
```

### Bytes Length Limit (`max_bytes_length`)

**Purpose**: Prevent memory exhaustion via huge byte strings.

**Enforcement Point**: `Objects/bytesobject.c` in `PyBytes_FromStringAndSize()` and related functions.

```c
/* In Objects/bytesobject.c */
#include "pycore_sandbox.h"

PyObject *
PyBytes_FromStringAndSize(const char *str, Py_ssize_t size)
{
    /* Check sandbox limits */
    if (_PySandbox_CheckBytesLength(size) < 0) {
        return NULL;
    }
    /* ... rest of function ... */
}
```

### List Size Limit (`max_list_size`)

**Purpose**: Prevent memory exhaustion via huge lists.

**Enforcement Point**: `Objects/listobject.c` in `list_resize()` and other growth functions.

```c
/* In Objects/listobject.c */
#include "pycore_sandbox.h"

static int
list_resize(PyListObject *self, Py_ssize_t newsize)
{
    /* Check sandbox limits */
    if (_PySandbox_CheckListSize(newsize) < 0) {
        return -1;
    }
    /* ... rest of function ... */
}
```

### Dict Size Limit (`max_dict_size`)

**Purpose**: Prevent memory exhaustion via huge dicts.

**Enforcement Point**: `Objects/dictobject.c` in dict insertion/growth functions.

```c
/* In Objects/dictobject.c */
#include "pycore_sandbox.h"

static int
insertdict(PyDictObject *mp, PyObject *key, Py_hash_t hash, PyObject *value)
{
    /* ... lookup code ... */

    /* Check sandbox limits before growing */
    Py_ssize_t new_size = mp->ma_used + 1;
    if (_PySandbox_CheckDictSize(new_size) < 0) {
        return -1;
    }
    /* ... rest of function ... */
}
```

### Set Size Limit (`max_set_size`)

**Purpose**: Prevent memory exhaustion via huge sets.

**Enforcement Point**: `Objects/setobject.c` in set addition functions.

```c
/* In Objects/setobject.c */
#include "pycore_sandbox.h"

static int
set_add_key(PySetObject *so, PyObject *key)
{
    /* Check sandbox limits */
    if (_PySandbox_CheckSetSize(so->used + 1) < 0) {
        return -1;
    }
    /* ... rest of function ... */
}
```

### Tuple Size Limit (`max_tuple_size`)

**Purpose**: Prevent memory exhaustion via huge tuples.

**Enforcement Point**: `Objects/tupleobject.c` in `PyTuple_New()`.

```c
/* In Objects/tupleobject.c */
#include "pycore_sandbox.h"

PyObject *
PyTuple_New(Py_ssize_t size)
{
    /* Check sandbox limits */
    if (_PySandbox_CheckTupleSize(size) < 0) {
        return NULL;
    }
    /* ... rest of function ... */
}
```

### Type Restrictions (`allow_float`, `allow_complex`)

**Purpose**: Forbid creation of specific types.

**Enforcement Point**: `Objects/typeobject.c` in `type_call()` or `Objects/floatobject.c` and `Objects/complexobject.c`.

```c
int
_PySandbox_CheckTypeAllowed(PyTypeObject *type)
{
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->suspended) {
        return 0;
    }

    if (!limits->allow_float && type == &PyFloat_Type) {
        PyErr_SetString(PyExc_TypeError,
                        "float type is forbidden in sandbox");
        return -1;
    }

    if (!limits->allow_complex && type == &PyComplex_Type) {
        PyErr_SetString(PyExc_TypeError,
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

1. User registers a filename: `sys.addsandboxfilename("<my-sandbox>")`
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
/* In Python/ceval.c - simplified */
static int
maybe_call_line_trace(...)
{
    /* ... other tracing code ... */

    /* Check sandbox statement limit */
    if (_PySandbox_CheckScopeStatement() < 0) {
        return -1;
    }

    /* ... rest of function ... */
}
```

**Check Function**:

```c
int
_PySandbox_CheckScopeStatement(void)
{
    _PySandboxLimits *limits = get_sandbox_limits();

    /* Skip if no limit, suspended, or in_check */
    if (limits == NULL || limits->scope_max_statements == 0 ||
        limits->in_check || limits->suspended) {
        return 0;
    }

    /* Skip if no registered filenames */
    if (limits->registered_filenames.count == 0) {
        return 0;
    }

    /* Check if current frame is in scope */
    _PyInterpreterFrame *current = get_current_interpreter_frame();
    if (!frame_in_sandbox_scope(&limits->registered_filenames, current)) {
        return 0;
    }

    /* Increment and check */
    limits->scope_statement_count++;

    if (limits->scope_statement_count == limits->scope_max_statements + 1) {
        limits->in_check = 1;
        PyErr_SetString(PyExc_RuntimeError,
                        "Sandbox statement limit exceeded");
        limits->in_check = 0;
        return -1;
    }

    return 0;
}
```

### Allocation Counting

**Enforcement Point**: `Modules/gcmodule.c` in `_PyObject_GC_Alloc()`.

```c
/* In Modules/gcmodule.c */
#include "pycore_sandbox.h"

static PyObject *
_PyObject_GC_Alloc(int use_calloc, size_t basicsize)
{
    /* Check sandbox allocation limits */
    if (_PySandbox_CheckAllocation() < 0) {
        return NULL;
    }
    /* ... rest of allocation ... */
}
```

**Check Function**:

```c
int
_PySandbox_CheckAllocation(void)
{
    _PySandboxLimits *limits = get_sandbox_limits();

    if (limits == NULL || limits->in_check || limits->suspended) {
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

    /* Check global limit */
    if (limits->global_max_allocations > 0) {
        if (limits->global_allocation_count > limits->global_max_allocations + GRACE_HEADROOM) {
            PyErr_NoMemory();
            return -1;
        }
        if (limits->global_allocation_count == limits->global_max_allocations + 1) {
            PyErr_NoMemory();
            return -1;
        }
    }

    /* Check scoped limit */
    if (in_scope && limits->scope_max_allocations > 0) {
        if (limits->scope_allocation_count > limits->scope_max_allocations + GRACE_HEADROOM) {
            PyErr_NoMemory();
            return -1;
        }
        if (limits->scope_allocation_count == limits->scope_max_allocations + 1) {
            PyErr_NoMemory();
            return -1;
        }
    }

    return 0;
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

    /* Call creation hook */
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

sys.setobjectcreationhook(my_hook)

class Foo:
    pass

instance = Foo()  # Prints: Created Foo

sys.setobjectcreationhook(None)  # Remove hook
```

---

## Suspend/Resume

### Purpose

Temporarily bypass all limits for trusted code (e.g., during syscalls or stdlib operations).

### API

```python
# Suspend limits (returns new suspend count)
count = sys.suspendsandboxlimits()  # count = 1

# Nested suspend
count = sys.suspendsandboxlimits()  # count = 2

# Resume (returns new suspend count)
count = sys.resumesandboxlimits()   # count = 1
count = sys.resumesandboxlimits()   # count = 0, limits active again

# Check if suspended
if sys.issandboxsuspended():
    # Limits are bypassed
```

### Implementation

```c
int
PySandbox_Suspend(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;
    limits->suspended++;
    return limits->suspended;
}

int
PySandbox_Resume(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

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

---

## Integration Points

### Files Modified

| File | Purpose |
|------|---------|
| `Include/internal/pycore_sandbox.h` | Data structures and API declarations |
| `Include/internal/pycore_interp.h` | Add `_PySandboxState sandbox` to `PyInterpreterState` |
| `Python/sandbox.c` | Core implementation |
| `Python/sysmodule.c` | Python API (sys module functions) |
| `Python/pylifecycle.c` | Call `_PySandbox_Init()` / `_PySandbox_Fini()` |
| `Python/ceval.c` | Statement tracing integration |
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
| `Objects/typeobject.c` | Type check and creation hook |

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

In `Python/pylifecycle.c`:

```c
static PyStatus
new_interpreter(...)
{
    /* ... other initialization ... */

    _PySandbox_Init(interp);

    /* ... */
}

static void
finalize_interp_clear(...)
{
    /* ... */

    _PySandbox_Fini(interp);

    /* ... */
}
```

---

## Python API Reference

### Limit Configuration

| Function | Description |
|----------|-------------|
| `sys.setsandboxlimits(**kwargs)` | Set all limit values |
| `sys.getsandboxlimits() -> dict` | Get current limit values |
| `sys.getsandboxcounts() -> dict` | Get current counter values |

### Counter Reset

| Function | Description |
|----------|-------------|
| `sys.resetsandboxglobalallocationcount()` | Reset global allocation counter |
| `sys.resetsandboxscopestatementcount()` | Reset scope statement counter |
| `sys.resetsandboxscopeallocationcount()` | Reset scope allocation counter |

### Scope Management

| Function | Description |
|----------|-------------|
| `sys.entersandboxscope()` | Add current frame's filename + reset counters |
| `sys.exitsandboxscope()` | Clear all registered filenames |
| `sys.addsandboxframe()` | Add current frame's filename |
| `sys.issandboxinscope() -> bool` | Check if current code is in scope |
| `sys.addsandboxfilename(filename)` | Register a filename for tracking |
| `sys.removesandboxfilename(filename)` | Remove a filename from tracking |
| `sys.clearsandboxfilenames()` | Clear all registered filenames |

### Object Creation Hook

| Function | Description |
|----------|-------------|
| `sys.setobjectcreationhook(callback)` | Set hook callback (or None) |
| `sys.getobjectcreationhook() -> callable` | Get current hook |

### Suspend/Resume

| Function | Description |
|----------|-------------|
| `sys.suspendsandboxlimits() -> int` | Suspend limits, return count |
| `sys.resumesandboxlimits() -> int` | Resume limits, return count |
| `sys.issandboxsuspended() -> bool` | Check if suspended |

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
PyAPI_FUNC(void) _PySandbox_ResetScopeStatementCount(void);
PyAPI_FUNC(void) _PySandbox_ResetScopeAllocationCount(void);
PyAPI_FUNC(void) _PySandbox_ResetGlobalAllocationCount(void);
```

### Initialization

```c
PyAPI_FUNC(void) _PySandbox_Init(PyInterpreterState *interp);
PyAPI_FUNC(void) _PySandbox_Fini(PyInterpreterState *interp);
```

### Object Creation Hook

```c
PyAPI_FUNC(PyObject *) _PySandbox_CallCreationHook(
    PyObject *obj, PyTypeObject *type, int flags);
```

### Suspend/Resume

```c
PyAPI_FUNC(int) PySandbox_Suspend(void);
PyAPI_FUNC(int) PySandbox_Resume(void);
PyAPI_FUNC(int) PySandbox_IsSuspended(void);
```

---

## Implementation Files

### Complete File Listing

```
Include/internal/
├── pycore_sandbox.h      # Data structures, API declarations
└── pycore_interp.h       # Modified: add sandbox field

Python/
├── sandbox.c             # Core implementation (NEW FILE)
├── sysmodule.c           # Modified: add sys.* functions
├── pylifecycle.c         # Modified: init/fini calls
└── ceval.c               # Modified: statement tracing

Modules/
└── gcmodule.c            # Modified: allocation counting

Objects/
├── longobject.c          # Modified: int size check
├── unicodeobject.c       # Modified: string length check
├── bytesobject.c         # Modified: bytes length check
├── listobject.c          # Modified: list size check
├── dictobject.c          # Modified: dict size check
├── setobject.c           # Modified: set size check
├── tupleobject.c         # Modified: tuple size check
├── floatobject.c         # Modified: type check
├── complexobject.c       # Modified: type check
└── typeobject.c          # Modified: type check, creation hook

Lib/test/
└── test_sandbox.py       # Test suite (NEW FILE)
```

---

## Porting Guide

### Step-by-Step Checklist

1. **Add header file**
   - [ ] Create `Include/internal/pycore_sandbox.h`
   - [ ] Define all data structures
   - [ ] Define API function declarations

2. **Modify interpreter state**
   - [ ] Add `_PySandboxState sandbox` to `PyInterpreterState` in `pycore_interp.h`

3. **Create implementation**
   - [ ] Create `Python/sandbox.c`
   - [ ] Implement all check functions
   - [ ] Implement scope management
   - [ ] Implement hooks
   - [ ] Implement suspend/resume

4. **Add Python API**
   - [ ] Add all `sys.*` functions to `Python/sysmodule.c`
   - [ ] Add method table entries

5. **Add initialization**
   - [ ] Call `_PySandbox_Init()` in `Python/pylifecycle.c`
   - [ ] Call `_PySandbox_Fini()` in finalization

6. **Integrate limit checks**
   - [ ] `Objects/longobject.c`: `_PySandbox_CheckIntSize()`
   - [ ] `Objects/unicodeobject.c`: `_PySandbox_CheckStrLength()`
   - [ ] `Objects/bytesobject.c`: `_PySandbox_CheckBytesLength()`
   - [ ] `Objects/listobject.c`: `_PySandbox_CheckListSize()`
   - [ ] `Objects/dictobject.c`: `_PySandbox_CheckDictSize()`
   - [ ] `Objects/setobject.c`: `_PySandbox_CheckSetSize()`
   - [ ] `Objects/tupleobject.c`: `_PySandbox_CheckTupleSize()`
   - [ ] `Objects/typeobject.c`: `_PySandbox_CheckTypeAllowed()`, hook

7. **Integrate allocation counting**
   - [ ] `Modules/gcmodule.c`: `_PySandbox_CheckAllocation()`

8. **Integrate statement tracing**
   - [ ] `Python/ceval.c`: `_PySandbox_CheckScopeStatement()`

9. **Add tests**
   - [ ] Create `Lib/test/test_sandbox.py`
   - [ ] Test all limit types
   - [ ] Test scope management
   - [ ] Test hooks
   - [ ] Test suspend/resume

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

---

## Testing

### Test File

`Lib/test/test_sandbox.py`

### Test Categories

1. **Limit Tests**
   - `SandboxLimitsTests`: Basic get/set
   - `IntegerLimitsTests`: Integer size limits
   - `StringLimitsTests`: String length limits
   - `ListLimitsTests`: List size limits
   - `DictLimitsTests`: Dict size limits
   - `SetLimitsTests`: Set size limits
   - `TupleLimitsTests`: Tuple size limits
   - `TypeRestrictionTests`: Float/complex restrictions

2. **Allocation Tests**
   - `GlobalAllocationCountLimitsTests`: Global allocation limits
   - `ScopedAllocationCountTests`: Scoped allocation limits

3. **Statement Tests**
   - `ScopedStatementCountTests`: Statement counting and limits

4. **Scope Tests**
   - `SandboxScopeTests`: Basic scope enter/exit
   - `SelectedFramesScopeTests`: Frame-based scope (legacy)
   - `FilenameBasedScopeTests`: Filename-based scope

5. **Hook Tests**
   - `ObjectCreationHookTests`: Creation hook functionality

6. **Suspend Tests**
   - `SuspendResumeLimitsTests`: Suspend/resume behavior

7. **Integration Tests**
   - `IntegrationTests`: Combined functionality
   - `MinimalSafeLimitsTests`: Recommended limits

### Running Tests

```bash
./python -m unittest test.test_sandbox -v
```

### Expected Results

All 70+ tests should pass:

```
----------------------------------------------------------------------
Ran 70 tests in 0.XXXs

OK
```

---

## Usage Examples

### Basic Sandboxing

```python
import sys

# Set conservative limits
sys.setsandboxlimits(
    max_int_digits=100,           # ~10^900
    max_str_length=100000,        # 100KB
    max_bytes_length=100000,      # 100KB
    max_list_size=10000,
    max_dict_size=10000,
    max_set_size=10000,
    max_tuple_size=10000,
    scope_max_statements=100000,  # 100K statements
    scope_max_allocations=10000,  # 10K allocations
)

# Register sandbox filename
sys.addsandboxfilename("<user-code>")

# Execute user code
user_code = """
result = []
for i in range(100):
    result.append(i * 2)
"""

try:
    exec(compile(user_code, "<user-code>", "exec"))
except (OverflowError, MemoryError, RuntimeError) as e:
    print(f"Limit exceeded: {e}")
finally:
    sys.clearsandboxfilenames()
```

### Multi-Module Sandbox

```python
import sys

sys.setsandboxlimits(scope_max_statements=50000)

# Register multiple modules
sys.addsandboxfilename("<sandbox-core>")
sys.addsandboxfilename("<sandbox-utils>")

# Core module
exec(compile("""
class Processor:
    def process(self, data):
        return [x * 2 for x in data]
""", "<sandbox-core>", "exec"))

# Utils module
exec(compile("""
def helper(x):
    return x + 1
""", "<sandbox-utils>", "exec"))

# Main code
exec(compile("""
p = Processor()
result = p.process([helper(i) for i in range(10)])
""", "<sandbox-core>", "exec"))

print(sys.getsandboxcounts())
sys.clearsandboxfilenames()
```

### Monitoring Object Creation

```python
import sys

created_types = {}

def monitor_hook(obj, type_, frame, context):
    name = type_.__name__
    created_types[name] = created_types.get(name, 0) + 1
    return obj

sys.setobjectcreationhook(monitor_hook)

# Run some code
exec("""
class Foo:
    pass
class Bar:
    pass
x = Foo()
y = Bar()
z = Foo()
""")

sys.setobjectcreationhook(None)
print(created_types)  # {'Foo': 2, 'Bar': 1, ...}
```

---

## Appendix: Recommended Limits

For executing untrusted code, these limits provide protection while allowing reasonable operations:

```python
sys.setsandboxlimits(
    # Data size limits
    max_int_digits=100,           # Integers up to ~10^900
    max_str_length=1_000_000,     # 1MB strings
    max_bytes_length=1_000_000,   # 1MB bytes
    max_list_size=100_000,        # 100K list items
    max_dict_size=100_000,        # 100K dict entries
    max_set_size=100_000,         # 100K set members
    max_tuple_size=100_000,       # 100K tuple items

    # Execution limits (scoped)
    scope_max_statements=1_000_000,   # 1M statements
    scope_max_allocations=100_000,    # 100K allocations

    # Type restrictions (optional)
    allow_float=True,
    allow_complex=True,
)
```

Adjust based on your specific requirements and available resources.
