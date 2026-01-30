- Feature Name: sandbox-limits
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox limits module provides size limits for Python objects (integers, strings, containers), type restrictions (float, complex), and scoped execution counters (statements, allocations, iterations, operations). These limits prevent denial-of-service attacks through resource exhaustion.

# Motivation
[motivation]: #motivation

Untrusted code can cause denial-of-service through:

1. **Memory Exhaustion**: Creating huge integers (`2**10000000`), strings (`"x" * 10**9`), or containers
2. **CPU Exhaustion**: Infinite loops, excessive computation
3. **Allocation Bombs**: Creating millions of small objects

The limits module addresses each attack vector:
- **Size limits**: Cap the maximum size of individual objects
- **Type restrictions**: Block creation of specific types entirely
- **Scoped counters**: Limit total statements, allocations, iterations, or operations

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Setting Size Limits

```python
import sys

# Set individual limits
sys.sandbox.max_int_digits = 100      # ~10^900 max
sys.sandbox.max_str_length = 100_000  # 100KB strings
sys.sandbox.max_list_size = 1_000_000 # 1M items

# Or use set_limits() for bulk configuration
sys.sandbox.set_limits(
    max_int_digits=100,
    max_str_length=100_000,
    max_bytes_length=100_000,
    max_list_size=1_000_000,
    max_dict_size=1_000_000,
    max_set_size=1_000_000,
    max_tuple_size=1_000_000,
)
```

When a limit is exceeded, a `SandboxOverflowError` is raised:

```python
sys.sandbox.max_int_digits = 10
try:
    x = 2 ** 1000  # Exceeds 10 internal digits
except SandboxOverflowError as e:
    print(e)  # "Integer size (34 digits) exceeds sandbox limit (10 digits)"
```

## Type Restrictions

Block creation of specific types:

```python
sys.sandbox.allow_float = False
sys.sandbox.allow_complex = False

try:
    x = 3.14  # Raises SandboxTypeError
except SandboxTypeError as e:
    print(e)  # "float type is forbidden in sandbox"
```

## Scoped Execution Limits

Scoped limits only count operations within sandbox scope:

```python
import sys

# Configure limits
sys.sandbox.set_limits(
    max_statements=1000,    # Limit line executions
    max_allocations=10000,  # Limit object allocations
    max_iterations=100000,  # Limit iterator steps
    max_operations=50000,   # Limit AST operations (requires PyCF_SANDBOX_COUNT)
)

# Register scope and compile code
sys.sandbox.add_filename("<sandbox>")
code = compile(source, "<sandbox>", "exec")

# Reset counters before each execution
sys.sandbox.reset_counts()

try:
    exec(code)
except SandboxRuntimeError as e:
    print(e)  # "Sandbox statement limit exceeded" (or iteration/operation)
except SandboxMemoryError as e:
    print(e)  # "Sandbox allocation limit exceeded"
```

## Reading Counters

```python
counts = sys.sandbox.get_counts()
print(f"Statements: {counts['statement_count']}")
print(f"Allocations: {counts['allocation_count']}")
print(f"Iterations: {counts['iteration_count']}")
print(f"Operations: {counts['operation_count']}")
```

## Dunder Access Control

Block `__dunder__` attribute access to prevent introspection escapes:

```python
sys.sandbox.allow_dunder_access = False

class Foo:
    pass

try:
    Foo.__class__  # Raises SandboxAttributeError
except SandboxAttributeError as e:
    print(e)  # "dunder attribute access blocked in sandbox: '__class__'"
```

## Unsafe Operation Blocking

Block dangerous operations when `allow_unsafe=False` (default):

```python
sys.sandbox.allow_unsafe = False

try:
    compile("x = 1", "<string>", "exec")  # Raises SandboxSecurityError
except SandboxSecurityError as e:
    print(e)  # "compile() is not allowed in sandbox"
```

When `allow_unsafe=False`, the following operations are blocked in sandbox scope:
- `compile()` - Blocks dynamic code compilation
- `eval()` - Blocks all eval calls (strings AND code objects)
- `exec()` - Blocks all exec calls (strings AND code objects)
- `gc.get_objects()`, `gc.get_referrers()`, `gc.get_referents()` - Blocks GC introspection

**Note:** Both `eval()` and `exec()` are blocked even with pre-compiled code objects
to prevent scope escape attacks where code compiled with an unregistered filename
could bypass sandbox limits.

## I/O Operation Blocking

Block all I/O operations (file, socket, raw fd) to prevent data exfiltration:

```python
sys.sandbox.allow_io = False  # This is the default

try:
    open("/tmp/test.txt", "w")  # Raises SandboxSecurityError
except SandboxSecurityError as e:
    print(e)  # "open() is not allowed in sandbox scope (I/O blocked)"
```

When `allow_io=False` (default), the following operations are blocked in sandbox scope:
- `open()`, `FileIO()`
- `socket()` (low-level `_socket.socket`)
- `os.open()`, `os.close()`, `os.closerange()`
- `os.read()`, `os.write()`
- `os.dup()`, `os.dup2()`, `os.pipe()`

In-memory I/O (`StringIO`, `BytesIO`) remains allowed as it doesn't access external resources.

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## Data Structures

### `_PySandboxLimits`

```c
typedef struct {
    /* Size limits (0 = no limit) */
    Py_ssize_t max_int_digits;      /* Internal digits (~30 bits each) */
    Py_ssize_t max_str_length;      /* Unicode code points */
    Py_ssize_t max_bytes_length;    /* Bytes */
    Py_ssize_t max_list_size;       /* List items */
    Py_ssize_t max_dict_size;       /* Dict entries */
    Py_ssize_t max_set_size;        /* Set members */
    Py_ssize_t max_tuple_size;      /* Tuple items */

    /* Scoped limits (0 = no limit) */
    uint64_t max_statements;        /* Line executions */
    uint64_t max_allocations;       /* GC-tracked allocations */
    uint64_t max_iterations;        /* Iterator yields */
    uint64_t max_operations;        /* SANDBOX_COUNT opcodes */

    /* Type/access restrictions */
    int allow_float;                /* 1 = allowed, 0 = forbidden */
    int allow_complex;              /* 1 = allowed, 0 = forbidden */
    int allow_dunder_access;        /* 1 = allowed, 0 = blocked */
    int allow_unsafe;               /* 1 = allowed, 0 = blocked */
    int allow_io;                   /* 1 = allowed, 0 = blocked (default) */
    int count_iterations_as_operations;  /* 1 = count iterations as ops */
} _PySandboxLimits;
```

### `_PySandboxCounters`

```c
typedef struct {
    uint64_t statement_count;   /* Statements executed in scope */
    uint64_t allocation_count;  /* Objects allocated in scope */
    uint64_t iteration_count;   /* Iterator yields in scope */
    uint64_t operation_count;   /* SANDBOX_COUNT opcodes in scope */
} _PySandboxCounters;
```

## Size Limit Check Functions

All check functions follow this pattern:

```c
int
_PySandbox_CheckIntSize(Py_ssize_t ndigits)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_int_digits)

    if (ndigits > limits->max_int_digits) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Integer size (%zd digits) exceeds sandbox limit (%zd digits)",
                     ndigits, limits->max_int_digits);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}
```

The `_PYSANDBOX_CHECK_PROLOGUE` macro provides fast exits:

```c
#define _PYSANDBOX_CHECK_PROLOGUE(limit_field) \
    _PySandboxState *sandbox = get_sandbox_state(); \
    if (sandbox == NULL || sandbox->limits.limit_field == 0 || \
        sandbox->suppress_checks || sandbox->suspended) { \
        return 0; \
    } \
    _PySandboxLimits *limits = &sandbox->limits;
```

### Size Check Functions

```c
int _PySandbox_CheckIntSize(Py_ssize_t ndigits);      /* longobject.c */
int _PySandbox_CheckStrLength(Py_ssize_t length);     /* unicodeobject.c */
int _PySandbox_CheckBytesLength(Py_ssize_t length);   /* bytesobject.c */
int _PySandbox_CheckListSize(Py_ssize_t size);        /* listobject.c */
int _PySandbox_CheckDictSize(Py_ssize_t size);        /* dictobject.c */
int _PySandbox_CheckSetSize(Py_ssize_t size);         /* setobject.c */
int _PySandbox_CheckTupleSize(Py_ssize_t size);       /* tupleobject.c */
```

### Type Check Function

```c
int
_PySandbox_CheckTypeAllowed(PyTypeObject *type)
{
    _PySandboxState *sandbox = get_sandbox_state();
    if (sandbox == NULL || sandbox->suspended) {
        return 0;
    }
    _PySandboxLimits *limits = &sandbox->limits;

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

## Scoped Counter Functions

### Statement Counting

Called from `Python/ceval.c` during line tracing:

```c
int
_PySandbox_CheckScopeStatement(void)
{
    /* ... get sandbox state ... */
    if (limits->max_statements == 0 ||
        sandbox->suppress_checks || sandbox->suspended) {
        return 0;
    }

    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return 0;
    }

    counters->statement_count++;

    /* Single-raise: only at exactly max+1 */
    if (counters->statement_count == limits->max_statements + 1) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxRuntimeError,
                        "Sandbox statement limit exceeded");
        sandbox->suppress_checks = 0;
        return -1;
    }

    return 0;
}
```

### Allocation Counting

Called from `Modules/gcmodule.c`:

```c
int
_PySandbox_CheckAllocation(void)
{
    /* ... get sandbox state ... */
    if (limits->max_allocations == 0 ||
        sandbox->suppress_checks || sandbox->suspended) {
        return 0;
    }

    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return 0;
    }

    counters->allocation_count++;

    /* Grace headroom allows error handling to allocate */
    if (counters->allocation_count > limits->max_allocations + ALLOCATION_GRACE_HEADROOM) {
        PyErr_SetString(PyExc_SandboxMemoryError,
                        "Sandbox allocation limit exceeded");
        return -1;
    }
    if (counters->allocation_count == limits->max_allocations + 1) {
        PyErr_SetString(PyExc_SandboxMemoryError,
                        "Sandbox allocation limit exceeded");
        return -1;
    }

    return 0;
}
```

`ALLOCATION_GRACE_HEADROOM` is 1000, allowing error handling to allocate objects.

### Iteration Counting

Called from iterator wrapper's `tp_iternext`:

```c
int
_PySandbox_CheckIteration(void)
{
    /* ... similar pattern ... */
    counters->iteration_count++;

    /* Optionally count as operations too */
    if (limits->count_iterations_as_operations && limits->max_operations > 0) {
        counters->operation_count++;
        if (counters->operation_count == limits->max_operations + 1) {
            /* ... raise SandboxRuntimeError ... */
        }
    }

    if (counters->iteration_count == limits->max_iterations + 1) {
        /* ... raise SandboxRuntimeError ... */
    }

    return 0;
}
```

### Operation Counting

Called from `Python/ceval.c` for `SANDBOX_COUNT` opcode:

```c
int
_PySandbox_CheckScopeOperation(void)
{
    /* ... similar pattern ... */
    counters->operation_count++;

    if (counters->operation_count == limits->max_operations + 1) {
        /* ... raise SandboxRuntimeError ... */
    }

    return 0;
}
```

## Dunder Access Check

```c
int
_PySandbox_CheckDunderAccess(PyObject *name)
{
    /* ... get sandbox state ... */
    if (sandbox->limits.allow_dunder_access ||
        sandbox->suppress_checks || sandbox->suspended) {
        return 0;
    }

    if (!is_dunder_name(name)) {
        return 0;
    }

    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return 0;
    }

    PyErr_Format(PyExc_SandboxAttributeError,
                 "dunder attribute access blocked in sandbox: '%U'", name);
    return -1;
}

static int
is_dunder_name(PyObject *name)
{
    const char *str = PyUnicode_AsUTF8(name);
    return strstr(str, "__") != NULL;
}
```

## Unsafe Operation Check

```c
int
_PySandbox_CheckUnsafeBlocked(const char *operation)
{
    /* ... get sandbox state ... */
    if (sandbox->limits.allow_unsafe ||
        sandbox->suppress_checks || sandbox->suspended) {
        return 0;
    }

    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return 0;
    }

    PyErr_Format(PyExc_SandboxSecurityError,
                 "%s is not allowed in sandbox", operation);
    return -1;
}
```

## I/O Operation Check

```c
int
_PySandbox_CheckIOAllowed(const char *operation)
{
    /* ... get sandbox state ... */
    if (sandbox->limits.allow_io ||
        sandbox->suppress_checks || sandbox->suspended) {
        return 0;
    }

    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return 0;
    }

    PyErr_Format(PyExc_SandboxSecurityError,
                 "%s is not allowed in sandbox scope (I/O blocked)", operation);
    return -1;
}
```

Called from:
- `Modules/_io/_iomodule.c` - `_io_open_impl()` (high-level `open()`)
- `Modules/_io/fileio.c` - `_io_FileIO___init___impl()` (FileIO)
- `Modules/socketmodule.c` - `sock_initobj_impl()` (socket creation)
- `Modules/posixmodule.c` - `os_open_impl()`, `os_close_impl()`, `os_read_impl()`, `os_write_impl()`, `os_dup_impl()`, `os_dup2_impl()`, `os_pipe_impl()`, `os_closerange_impl()`

## Python API

### Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `max_int_digits` | int | 0 | Max internal integer digits |
| `max_str_length` | int | 0 | Max string length |
| `max_bytes_length` | int | 0 | Max bytes length |
| `max_list_size` | int | 0 | Max list size |
| `max_dict_size` | int | 0 | Max dict size |
| `max_set_size` | int | 0 | Max set size |
| `max_tuple_size` | int | 0 | Max tuple size |
| `max_statements` | int | 0 | Max statements in scope |
| `max_allocations` | int | 0 | Max allocations in scope |
| `max_iterations` | int | 0 | Max iterations in scope |
| `max_operations` | int | 0 | Max operations in scope |
| `allow_float` | bool | True | Allow float creation |
| `allow_complex` | bool | True | Allow complex creation |
| `allow_dunder_access` | bool | True | Allow `__dunder__` access |
| `allow_unsafe` | bool | False | Allow unsafe operations |
| `allow_io` | bool | False | Allow I/O operations (file, socket, fd) |
| `count_iterations_as_operations` | bool | False | Count iterations as operations |

### Read-Only Counter Properties

| Property | Type | Description |
|----------|------|-------------|
| `statement_count` | int | Statements executed in scope |
| `allocation_count` | int | Allocations in scope |
| `iteration_count` | int | Iterator yields in scope |
| `operation_count` | int | Operations in scope |

### Methods

| Method | Description |
|--------|-------------|
| `set_limits(**kwargs)` | Bulk update limits |
| `get_limits()` | Return dict of all limits |
| `get_counts()` | Return dict of all counters |
| `reset_counts()` | Reset counters to 0 |

## Integration Points

| File | Function | Check Called |
|------|----------|--------------|
| `Objects/longobject.c` | `_PyLong_New()` | `_PySandbox_CheckIntSize()` |
| `Objects/unicodeobject.c` | `PyUnicode_New()` | `_PySandbox_CheckStrLength()` |
| `Objects/bytesobject.c` | `PyBytes_FromStringAndSize()` | `_PySandbox_CheckBytesLength()` |
| `Objects/listobject.c` | `list_resize()`, others | `_PySandbox_CheckListSize()` |
| `Objects/dictobject.c` | insertion functions, `PyDict_Copy()`, `dict_merge()` | `_PySandbox_CheckDictSize()` |
| `Objects/setobject.c` | `set_add_entry()`, `set_merge()` | `_PySandbox_CheckSetSize()` |
| `Objects/tupleobject.c` | `PyTuple_New()` | `_PySandbox_CheckTupleSize()` |
| `Objects/floatobject.c` | `PyFloat_FromDouble()` | `_PySandbox_CheckTypeAllowed()` |
| `Objects/complexobject.c` | `PyComplex_FromCComplex()` | `_PySandbox_CheckTypeAllowed()` |
| `Python/ceval.c` | `LOAD_CONST` (type checks) | `_PySandbox_CheckTypeAllowed()` (float/complex) |
| `Python/ceval.c` | `LOAD_CONST` (size checks) | `_PySandbox_CheckStrLength()`, `_PySandbox_CheckBytesLength()`, `_PySandbox_CheckTupleSize()`, `_PySandbox_CheckIntSize()` |
| `Objects/typeobject.c` | `type_call()` | `_PySandbox_CheckTypeAllowed()` |
| `Modules/gcmodule.c` | `_PyObject_GC_Alloc()` | `_PySandbox_CheckAllocation()` |
| `Python/ceval.c` | line tracing | `_PySandbox_CheckScopeStatement()` |
| `Python/ceval.c` | `SANDBOX_COUNT` | `_PySandbox_CheckScopeOperation()` |
| `Python/ceval.c` | `LOAD_ATTR`, etc. | `_PySandbox_CheckDunderAccess()` |
| `Python/ceval.c` | `LOAD_NAME` (dunder variables) | `_PySandbox_CheckDunderAccess()` |
| `Python/ceval.c` | `LOAD_GLOBAL` (dunder variables) | `_PySandbox_CheckDunderAccess()` |
| `Modules/_io/_iomodule.c` | `_io_open_impl()` | `_PySandbox_CheckIOAllowed()` |
| `Modules/_io/fileio.c` | `_io_FileIO___init___impl()` | `_PySandbox_CheckIOAllowed()` |
| `Modules/socketmodule.c` | `sock_initobj_impl()` | `_PySandbox_CheckIOAllowed()` |
| `Modules/posixmodule.c` | `os_open_impl()`, etc. | `_PySandbox_CheckIOAllowed()` |

## Exception Types

| Exception | Trigger |
|-----------|---------|
| `SandboxOverflowError` | Size limit exceeded |
| `SandboxMemoryError` | Allocation limit exceeded |
| `SandboxRuntimeError` | Statement/iteration/operation limit exceeded |
| `SandboxTypeError` | Forbidden type creation |
| `SandboxAttributeError` | Dunder access blocked |
| `SandboxSecurityError` | Unsafe operation blocked |

## Single-Raise Behavior

Statement, iteration, and operation limits raise exactly once (at `count == max + 1`). This allows exception handlers to execute without triggering additional errors:

```python
try:
    # ... code that exceeds limit ...
except SandboxRuntimeError:
    # This handler can execute statements without raising again
    log_error()
    cleanup()
```

# Drawbacks
[drawbacks]: #drawbacks

1. **Statement Counting Non-Determinism**: Statement count depends on bytecode layout, not source structure. Different Python versions may count differently for the same source.

2. **Allocation Counting Non-Determinism**: Allocation count depends on Python internals (interning, caching). Same code may allocate differently across runs.

3. **Size Limit Overhead**: Every object creation checks limits, even when disabled (though fast-exit minimizes impact).

4. **Integer Digit Units**: `max_int_digits` uses internal digits (~30 bits each), which is unintuitive for users.

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why Internal Digit Units for Integers?

**Alternative**: Use decimal digits or bit count.
- Rejected: Conversion overhead on every check; internal digits map directly to memory usage.

## Why Scoped Counters?

**Alternative**: Global counters.
- Rejected: Limits would apply to all code including stdlib, breaking legitimate operations.

## Why Single-Raise?

**Alternative**: Raise on every call after limit.
- Rejected: Exception handlers couldn't execute, causing cascading failures.

## Why Grace Headroom for Allocations?

Error handling requires allocations (exception object, traceback). Without grace, the allocation limit would prevent its own error from being raised.

# Prior art
[prior-art]: #prior-art

1. **sys.set_int_max_str_digits()**: Python 3.11+ limits integer-to-string conversion. Similar concept, narrower scope.

2. **resource.setrlimit()**: OS-level limits. Coarser granularity, process-wide.

3. **cProfile**: Uses similar line-tracing mechanism for statement counting.

# Unresolved questions
[unresolved-questions]: #unresolved-questions

1. Should `max_int_digits` accept decimal digit counts for usability?

2. Should there be separate limits for different container operations (append vs extend)?

3. Should allocation counting include non-GC objects?

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Memory Byte Limits**: Track actual memory usage instead of allocation count.

2. **CPU Time Limits**: Limit wall-clock or CPU time instead of statements.

3. **Custom Type Restrictions**: Block arbitrary types, not just float/complex.

4. **Per-Type Size Limits**: Different limits for user-defined classes.
