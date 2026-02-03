- Feature Name: sandbox-limits
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox limits module provides size limits for Python objects (integers, strings, containers), type restrictions (float, complex), and scoped execution counters (iterations, operations). These limits prevent denial-of-service attacks through resource exhaustion.

# Motivation
[motivation]: #motivation

Untrusted code can cause denial-of-service through:

1. **Memory Exhaustion**: Creating huge integers (`2**10000000`), strings (`"x" * 10**9`), or containers
2. **CPU Exhaustion**: Infinite loops, excessive computation

The limits module addresses each attack vector:
- **Size limits**: Cap the maximum size of individual objects
- **Type restrictions**: Block creation of specific types entirely
- **Scoped counters**: Limit total iterations or operations

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Setting Size Limits

```python
import sys

# Set individual limits
sys.sandbox.max_int_digits = 100      # ~10^900 max
sys.sandbox.max_str_length = 100_000  # 100KB strings
sys.sandbox.max_list_size = 1_000_000 # 1M items

# Or use set_config() for bulk configuration
sys.sandbox.set_config(
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

PyCF_SANDBOX_COUNT = 0x8000

# Configure limits
sys.sandbox.set_config(
    max_iterations=100000,  # Limit iterator steps
    max_operations=50000,   # Limit AST operations (requires PyCF_SANDBOX_COUNT)
    max_recursion_depth=100, # Limit sandbox frame recursion
)

# Register scope and compile code with operation counting
sys.sandbox.add_filename("<sandbox>")
code = compile(source, "<sandbox>", "exec", flags=PyCF_SANDBOX_COUNT)

# Reset counters before each execution
sys.sandbox.reset_counts()

try:
    exec(code)
except SandboxRuntimeError as e:
    print(e)  # "Sandbox operation limit exceeded" (or iteration)
except SandboxRecursionError as e:
    print(e)  # "Sandbox recursion limit exceeded"
```

## Reading Counters

```python
counts = sys.sandbox.get_counts()
print(f"Iterations: {counts['iteration_count']}")
print(f"Operations: {counts['operation_count']}")
```

## Adding to Counters Programmatically

Increment counters by specified amounts:

```python
sys.sandbox.enable()
sys.sandbox.reset_counts()

# Add to counters
sys.sandbox.add_counts(operation_count=100, iteration_count=50)

counts = sys.sandbox.get_counts()
print(f"Operations: {counts['operation_count']}")  # 100
print(f"Iterations: {counts['iteration_count']}")  # 50
```

**Behaviors:**
- Requires sandbox to be enabled (raises `RuntimeError` if disabled)
- Rejects negative values (raises `ValueError`)
- Checks limits AFTER incrementing (raises `SandboxOverflowError` if exceeded)
- Handles overflow: raises `SandboxOverflowError` if addition would exceed `UINT64_MAX`

```python
# Example: Pre-charge for external API calls
sys.sandbox.max_operations = 10000
sys.sandbox.add_counts(operation_count=1000)  # Reserve budget

# Example: Limit check
sys.sandbox.max_operations = 100
sys.sandbox.reset_counts()
try:
    sys.sandbox.add_counts(operation_count=200)  # Exceeds limit
except SandboxOverflowError as e:
    print(e)  # "operation_count exceeds sandbox limit"
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

### `_PySandboxConfig`

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
    uint64_t max_iterations;        /* Iterator yields */
    uint64_t max_operations;        /* SANDBOX_COUNT opcodes */
    uint64_t max_recursion_depth;   /* Sandbox frame recursion depth */

    /* Type/access restrictions */
    int allow_float;                /* 1 = allowed, 0 = forbidden */
    int allow_complex;              /* 1 = allowed, 0 = forbidden */
    int allow_dunder_access;        /* 0 = blocked (default), 1 = allowed */
    int allow_class_creation;       /* 1 = allow class creation with whitelisted dunders (default) */
    int allow_magic_methods;        /* 1 = allow magic method definitions in class body (default) */
    int allow_metaclasses;          /* 1 = allow all metaclasses (default), 0 = check whitelist */
    int allow_unsafe;               /* 1 = allowed, 0 = blocked */
    int allow_io;                   /* 1 = allowed, 0 = blocked (default) */
    int count_iterations_as_operations;  /* 1 = count iterations as ops */
} _PySandboxConfig;
```

### `_PySandboxCounters`

```c
typedef struct {
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

    if (ndigits > config->max_int_digits) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Integer size (%zd digits) exceeds sandbox limit (%zd digits)",
                     ndigits, config->max_int_digits);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}
```

The `_PYSANDBOX_CHECK_PROLOGUE` macro provides fast exits:

```c
#define _PYSANDBOX_CHECK_PROLOGUE(config_field) \
    _PySandboxState *sandbox = get_sandbox_state(); \
    if (sandbox == NULL || sandbox->config.config_field == 0 || \
        sandbox->suppress_checks || sandbox->suspend_depth) { \
        return 0; \
    } \
    _PySandboxConfig *config = &sandbox->config;
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
    if (sandbox == NULL || sandbox->suspend_depth) {
        return 0;
    }
    _PySandboxConfig *config = &sandbox->config;

    if (!config->allow_float && type == &PyFloat_Type) {
        PyErr_SetString(PyExc_SandboxTypeError,
                        "float type is forbidden in sandbox");
        return -1;
    }

    if (!config->allow_complex && type == &PyComplex_Type) {
        PyErr_SetString(PyExc_SandboxTypeError,
                        "complex type is forbidden in sandbox");
        return -1;
    }

    return 0;
}
```

## Scoped Counter Functions

### Operation Counting

Called from `Python/ceval.c` when `SANDBOX_COUNT` opcode executes:

```c
int
_PySandbox_CheckScopeOperation(void)
{
    /* ... get sandbox state ... */
    if (config->max_operations == 0 ||
        sandbox->suppress_checks || sandbox->suspend_depth) {
        return 0;
    }

    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return 0;
    }

    counters->operation_count++;

    /* Single-raise: only at exactly max+1 */
    if (counters->operation_count == config->max_operations + 1) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxRuntimeError,
                        "Sandbox operation limit exceeded");
        sandbox->suppress_checks = 0;
        return -1;
    }

    return 0;
}
```

Called from iterator wrapper's `tp_iternext`:

```c
int
_PySandbox_CheckIteration(void)
{
    /* ... similar pattern ... */
    counters->iteration_count++;

    /* Optionally count as operations too */
    if (config->count_iterations_as_operations && config->max_operations > 0) {
        counters->operation_count++;
        if (counters->operation_count == config->max_operations + 1) {
            /* ... raise SandboxRuntimeError ... */
        }
    }

    if (counters->iteration_count == config->max_iterations + 1) {
        /* ... raise SandboxRuntimeError ... */
    }

    return 0;
}

    if (counters->operation_count == config->max_operations + 1) {
        /* ... raise SandboxRuntimeError ... */
    }

    return 0;
}
```

## Dunder Access Check

```c
/* Class body mode constants */
#define DUNDER_CLASS_NEVER     0  /* Never allow in class body */
#define DUNDER_CLASS_WHITELIST 1  /* Allow whitelisted dunders in class body */
#define DUNDER_CLASS_ALL       2  /* Allow ALL dunders in class body */

int
_PySandbox_CheckDunderAccess(PyObject *name, int class_body_mode)
{
    /* ... get sandbox state ... */
    if (sandbox->config.allow_dunder_access ||
        sandbox->suppress_checks || sandbox->suspend_depth) {
        return 0;
    }

    if (!is_dunder_name(name)) {
        return 0;
    }

    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return 0;
    }

    /* Class body exception handling based on mode.
     * When allow_class_creation=1 and in a class body (CO_CLASS_BODY flag):
     * - DUNDER_CLASS_ALL (2): Allow ALL dunders (STORE_NAME)
     * - DUNDER_CLASS_WHITELIST (1): Allow whitelisted dunders (LOAD_NAME)
     * - DUNDER_CLASS_NEVER (0): No exceptions (LOAD_ATTR, etc.) */
    if (sandbox->config.allow_class_creation) {
        PyCodeObject *code = frame->f_code;
        if (code->co_flags & CO_CLASS_BODY) {
            if (class_body_mode == DUNDER_CLASS_ALL) {
                return 0;  /* Allow ALL dunders (STORE_NAME) */
            }
            if (class_body_mode == DUNDER_CLASS_WHITELIST) {
                if (is_class_body_safe_dunder(name)) {
                    return 0;  /* Allowed in class body context */
                }
            }
            /* DUNDER_CLASS_NEVER: fall through to block */
        }
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

/* Whitelist of dunders allowed in class body context */
static int
is_class_body_safe_dunder(PyObject *name)
{
    return (_PyUnicode_EqualToASCIIString(name, "__name__") ||
            _PyUnicode_EqualToASCIIString(name, "__module__") ||
            _PyUnicode_EqualToASCIIString(name, "__qualname__") ||
            _PyUnicode_EqualToASCIIString(name, "__annotations__") ||
            _PyUnicode_EqualToASCIIString(name, "__doc__") ||
            _PyUnicode_EqualToASCIIString(name, "__classcell__") ||
            _PyUnicode_EqualToASCIIString(name, "__slots__"));
}
```

### Class Body Mode

The `class_body_mode` parameter controls dunder access exception handling within class bodies:

| Mode | Constant | Effect in Class Body | Used By |
|------|----------|---------------------|---------|
| 0 | `DUNDER_CLASS_NEVER` | Block all dunders | `LOAD_ATTR`, `STORE_ATTR`, `DELETE_ATTR`, `LOAD_METHOD`, `LOAD_GLOBAL`, `getattr()`, `hasattr()` |
| 1 | `DUNDER_CLASS_WHITELIST` | Allow 7 whitelisted dunders | `LOAD_NAME` |
| 2 | `DUNDER_CLASS_ALL` | Allow ALL dunders | `STORE_NAME` |

### Class Body Whitelist (DUNDER_CLASS_WHITELIST)

When `allow_class_creation=True` (default) and dunder access is blocked, certain dunders are whitelisted within class body execution for `LOAD_NAME` operations (identified by `CO_CLASS_BODY` flag):

| Dunder | Purpose |
|--------|---------|
| `__name__` | Class name (injected by compiler) |
| `__module__` | Module where class is defined |
| `__qualname__` | Qualified name |
| `__annotations__` | Type annotations |
| `__doc__` | Docstrings |
| `__classcell__` | For `super()` support |
| `__slots__` | Slot definitions |

This allows class definitions to work while still blocking introspection dunders like `__class__`, `__bases__`, `__dict__`, etc.

### All Dunders in Class Body (DUNDER_CLASS_ALL)

The `STORE_NAME` opcode's behavior depends on the `allow_magic_methods` config:
- When `allow_magic_methods=True` (default): Uses `DUNDER_CLASS_ALL` mode, allowing ALL dunders in class body
- When `allow_magic_methods=False`: Uses `DUNDER_CLASS_WHITELIST` mode, only allowing whitelisted dunders

This enables defining magic methods like `__init__`, `__str__`, `__add__`, etc. when `allow_magic_methods=True`:

```python
class MyClass:
    def __init__(self):  # STORE_NAME __init__ - allowed with DUNDER_CLASS_ALL
        pass

    def __str__(self):   # STORE_NAME __str__ - allowed with DUNDER_CLASS_ALL
        return "MyClass"
```

When `allow_magic_methods=False`, only basic class definitions work:

```python
class Point:
    __slots__ = ('x', 'y')  # STORE_NAME __slots__ - allowed (whitelisted)
    x: int
    y: int

    def __init__(self):  # STORE_NAME __init__ - BLOCKED (not whitelisted)
        pass
```

**Limitation:** The whitelist only applies during class body execution. Method dunders like `__init__` accessed as attributes (e.g., `super().__init__()`) are blocked. Use `allow_dunder_access=True` if such patterns are needed.

## Metaclass Creation and Usage Check

The `allow_metaclasses` config flag controls both metaclass creation and usage:

**When `allow_metaclasses=True` (default):**
- All metaclass creation and usage is allowed (backward compatible)

**When `allow_metaclasses=False`:**
- Metaclass **creation** (subclassing `type`) is blocked
- Metaclass **usage** is only allowed if the metaclass is in `allowed_metaclasses` set
- If `allowed_metaclasses` is empty/NULL, only `type` is allowed

```c
int
_PySandbox_CheckMetaclassAllowed(PyObject *meta, PyObject *bases)
{
    /* ... get sandbox state ... */
    if (!_PySandbox_IsEnforced(sandbox)) {
        return 0;
    }

    /* When allow_metaclasses=True, allow everything */
    if (config->allow_metaclasses) {
        return 0;
    }

    /* ... scope check ... */

    /* Check 1: Block metaclass CREATION (subclassing type) */
    int creating_metaclass = is_metaclass_creation(bases);
    if (creating_metaclass) {
        PyErr_SetString(PyExc_SandboxSecurityError,
            "creating metaclasses (subclassing type) is not allowed in sandbox");
        return -1;
    }

    /* Check 2: Block metaclass USAGE unless whitelisted */
    if (meta != (PyObject *)&PyType_Type) {
        PyObject *allowed = sandbox->allowed_metaclasses;
        if (allowed == NULL || !PySet_Contains(allowed, meta)) {
            PyErr_Format(PyExc_SandboxSecurityError,
                "metaclass '%.200s' is not in allowed_metaclasses",
                ((PyTypeObject *)meta)->tp_name);
            return -1;
        }
    }

    return 0;
}
```

This prevents sandbox code from:
1. Creating custom metaclasses that could override `__new__` or `__call__`
2. Using arbitrary metaclasses that might have security implications

### Inheriting from Trusted Classes with Custom Metaclasses

When `allow_metaclasses=False`, sandbox code can inherit from a trusted base class (created outside the sandbox) that has a custom metaclass, **provided the metaclass is whitelisted** in `allowed_metaclasses`:

```python
# Outside sandbox (trusted code)
class TrustedMeta(type):
    pass

class TrustedBase(metaclass=TrustedMeta):
    x = 1

# Configure sandbox
sys.sandbox.set_config(allow_metaclasses=False)
sys.sandbox.allowed_metaclasses = frozenset({TrustedMeta})
sys.sandbox.add_filename("<sandbox>")

# Sandbox code inherits the metaclass from the trusted base
code = compile("""
class Derived(Base):  # OK - TrustedMeta is whitelisted
    y = 2
""", "<sandbox>", "exec")
exec(code, {"Base": TrustedBase})
```

If the metaclass is NOT whitelisted, inheritance is blocked:

```python
sys.sandbox.set_config(allow_metaclasses=False)
# TrustedMeta NOT in allowed_metaclasses
sys.sandbox.add_filename("<sandbox>")

code = compile("""
class Derived(Base):  # SandboxSecurityError!
    pass
""", "<sandbox>", "exec")
# Error: "metaclass 'TrustedMeta' is not in allowed_metaclasses"
```

This ensures that even when inheriting from trusted classes, the metaclass must be explicitly approved

## Unsafe Operation Check

```c
int
_PySandbox_CheckUnsafeBlocked(const char *operation)
{
    /* ... get sandbox state ... */
    if (sandbox->config.allow_unsafe ||
        sandbox->suppress_checks || sandbox->suspend_depth) {
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
    if (sandbox->config.allow_io ||
        sandbox->suppress_checks || sandbox->suspend_depth) {
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
| `max_iterations` | int | 0 | Max iterations in scope |
| `max_operations` | int | 0 | Max operations in scope |
| `max_recursion_depth` | int | 0 | Max sandbox frame recursion depth |
| `allow_float` | bool | True | Allow float creation |
| `allow_complex` | bool | True | Allow complex creation |
| `allow_dunder_access` | bool | False | Allow `__dunder__` access |
| `allow_class_creation` | bool | True | Allow class creation with whitelisted dunders |
| `allow_magic_methods` | bool | True | Allow magic method definitions in class body |
| `allow_metaclasses` | bool | True | Allow metaclass creation and usage |
| `allow_unsafe` | bool | False | Allow unsafe operations |
| `allow_io` | bool | False | Allow I/O operations (file, socket, fd) |
| `count_iterations_as_operations` | bool | False | Count iterations as operations |

### Read-Only Counter Properties

| Property | Type | Description |
|----------|------|-------------|
| `iteration_count` | int | Iterator yields in scope |
| `operation_count` | int | Operations in scope |
| `recursion_depth` | int | Current sandbox frame recursion depth |

### Methods

| Method | Description |
|--------|-------------|
| `set_config(**kwargs)` | Bulk update config |
| `get_config()` | Return dict of all limits |
| `get_counts()` | Return dict of all counters |
| `reset_counts()` | Reset counters to 0 |
| `add_counts(operation_count=0, iteration_count=0)` | Increment counters by specified amounts |

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
| `Python/ceval.c` | `SANDBOX_COUNT` | `_PySandbox_CheckScopeOperation()` |
| `Python/ceval.c` | `start_frame` | `_PySandbox_EnterFrame()` |
| `Python/ceval.c` | `LOAD_ATTR`, `STORE_ATTR`, `DELETE_ATTR`, `LOAD_METHOD` | `_PySandbox_CheckDunderAccess(name, DUNDER_CLASS_NEVER)` |
| `Python/ceval.c` | `LOAD_NAME` | `_PySandbox_CheckDunderAccess(name, DUNDER_CLASS_WHITELIST)` |
| `Python/ceval.c` | `STORE_NAME` | `_PySandbox_CheckDunderAccess(name, DUNDER_CLASS_ALL)` |
| `Python/ceval.c` | `LOAD_GLOBAL` | `_PySandbox_CheckDunderAccess(name, DUNDER_CLASS_NEVER)` |
| `Python/bltinmodule.c` | `getattr()`, `hasattr()` | `_PySandbox_CheckDunderAccess(name, DUNDER_CLASS_NEVER)` |
| `Python/bltinmodule.c` | `__build_class__` (metaclass) | `_PySandbox_CheckMetaclassAllowed()` |
| `Python/compile.c` | `compute_code_flags()` | Sets `CO_CLASS_BODY` flag for class bodies |
| `Modules/_io/_iomodule.c` | `_io_open_impl()` | `_PySandbox_CheckIOAllowed()` |
| `Modules/_io/fileio.c` | `_io_FileIO___init___impl()` | `_PySandbox_CheckIOAllowed()` |
| `Modules/socketmodule.c` | `sock_initobj_impl()` | `_PySandbox_CheckIOAllowed()` |
| `Modules/posixmodule.c` | `os_open_impl()`, etc. | `_PySandbox_CheckIOAllowed()` |

## Exception Types

| Exception | Trigger |
|-----------|---------|
| `SandboxOverflowError` | Size limit exceeded |
| `SandboxRuntimeError` | Iteration/operation limit exceeded |
| `SandboxRecursionError` | Recursion depth limit exceeded |
| `SandboxTypeError` | Forbidden type creation |
| `SandboxAttributeError` | Dunder access blocked |
| `SandboxSecurityError` | Unsafe operation blocked |

## Single-Raise Behavior

Iteration and operation limits raise exactly once (at `count == max + 1`). This allows exception handlers to execute without triggering additional errors:

```python
try:
    # ... code that exceeds limit ...
except SandboxRuntimeError:
    # This handler can execute statements without raising again
    log_error()
    cleanup()
```

## Programmatic Counter Addition

The `add_counts()` method allows incrementing counters from Python code:

```c
static PyObject *
sandbox_add_counts(_PySandboxObject *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"operation_count", "iteration_count", NULL};

    long long operation_count = 0;
    long long iteration_count = 0;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|LL:add_counts", kwlist,
                                     &operation_count, &iteration_count)) {
        return NULL;
    }

    /* Validate: only non-negative values allowed */
    if (operation_count < 0 || iteration_count < 0) {
        PyErr_SetString(PyExc_ValueError, "count values must be non-negative");
        return NULL;
    }

    /* Fail if sandbox is disabled */
    if (!sandbox->enabled) {
        PyErr_SetString(PyExc_RuntimeError, "sandbox is disabled");
        return NULL;
    }

    /* Safe add with overflow and limit checks */
    if (_PySandbox_CounterSafeAdd(&sandbox->counters.operation_count,
                                  (uint64_t)operation_count,
                                  config->max_operations,
                                  "operation_count") < 0) {
        return NULL;
    }

    if (_PySandbox_CounterSafeAdd(&sandbox->counters.iteration_count,
                                  (uint64_t)iteration_count,
                                  config->max_iterations,
                                  "iteration_count") < 0) {
        return NULL;
    }

    Py_RETURN_NONE;
}
```

### `_PySandbox_CounterSafeAdd` Helper

Safe counter addition with overflow and limit checks:

```c
static inline int
_PySandbox_CounterSafeAdd(uint64_t *counter, uint64_t amount,
                          uint64_t max_limit, const char *counter_name)
{
    if (amount == 0) {
        return 0;
    }

    uint64_t old_val = _PySandbox_CounterLoad(*counter);

    /* Overflow check before adding */
    if (amount > UINT64_MAX - old_val) {
        PyErr_Format(PyExc_SandboxOverflowError,
                     "%s would overflow", counter_name);
        return -1;
    }

    _PySandbox_CounterAdd(*counter, amount);

    /* Check against limit AFTER incrementing */
    if (max_limit > 0 && _PySandbox_CounterLoad(*counter) > max_limit) {
        PyErr_Format(PyExc_SandboxOverflowError,
                     "%s exceeds sandbox limit", counter_name);
        return -1;
    }

    return 0;
}
```

**Design Notes:**
- Uses thread-safe `_PySandbox_CounterAdd` macro (atomic in free-threading builds)
- Overflow check prevents wraparound before adding
- Limit check happens AFTER incrementing (consistent with natural counting)
- Returns `SandboxOverflowError` (not `SandboxRuntimeError`) for limit violations

# Drawbacks
[drawbacks]: #drawbacks

1. **Size Limit Overhead**: Every object creation checks limits, even when disabled (though fast-exit minimizes impact).

2. **Integer Digit Units**: `max_int_digits` uses internal digits (~30 bits each), which is unintuitive for users.

3. **Operation Counting Requires Compile Flag**: `max_operations` only works with code compiled using `PyCF_SANDBOX_COUNT` flag.

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
