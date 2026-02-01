- Feature Name: sandbox-iter
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox iterator module provides iteration limit enforcement through automatic iterator wrapping. When code in sandbox scope creates an iterator, the iterator is wrapped in a `_PySandboxIteratorWrapper` that checks limits on every `tp_iternext` call. This covers all 26+ direct `tp_iternext` call sites in CPython.

# Motivation
[motivation]: #motivation

Many C-level builtins consume iterators directly without executing Python bytecode:

```python
list(range(10**9))      # Calls tp_iternext 10^9 times
sum(range(10**9))       # Same
sorted(huge_iterable)   # Same
min(huge_iterable)      # Same
max(huge_iterable)      # Same
''.join(huge_list)      # Same
```

Statement counting (line tracing) doesn't catch these because no Python statements execute during the iteration. Without iterator wrapping, sandboxed code could cause denial-of-service by:

1. Consuming infinite iterators
2. Processing huge iterables through builtins
3. Bypassing statement limits via C-level iteration

The iterator wrapper provides a single enforcement point that covers all iteration paths.

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Setting Iteration Limits

```python
import sys

sys.sandbox.max_iterations = 1_000_000  # Limit iterator steps
sys.sandbox.add_filename("<sandbox>")
sys.sandbox.reset_counts()

code = compile("""
# This will hit the iteration limit
result = sum(range(10**9))
""", "<sandbox>", "exec")

try:
    exec(code)
except SandboxRuntimeError as e:
    print(e)  # "Sandbox iteration limit exceeded"
```

## How Wrapping Works

Iterator wrapping is automatic and transparent:

```python
import sys

sys.sandbox.max_iterations = 100
sys.sandbox.add_filename("<sandbox>")

code = compile("""
data = [1, 2, 3, 4, 5]

# All of these are protected by the iterator wrapper:
for x in data:           # for-loop iteration
    pass
list(iter(data))         # list() consuming iterator
sum(data)                # sum() consuming iterator
sorted(data)             # sorted() consuming iterator
""", "<sandbox>", "exec")

exec(code)
print(sys.sandbox.iteration_count)  # Shows total yields
```

## Counting Iterations as Operations

You can unify iteration and operation counting:

```python
sys.sandbox.set_config(
    max_operations=100_000,
    count_iterations_as_operations=True,
)

# Now each iterator yield increments operation_count
# Useful when you want a single "cost" budget
```

## Checking Iteration Count

```python
counts = sys.sandbox.get_counts()
print(f"Iterations: {counts['iteration_count']}")

# Or via property
print(f"Iterations: {sys.sandbox.iteration_count}")
```

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## Iterator Wrapper Type

The wrapper is a simple object that delegates to the wrapped iterator:

```c
typedef struct {
    PyObject_HEAD
    PyObject *wrapped;  /* The wrapped iterator (strong ref) */
} _PySandboxIteratorWrapper;

static PyTypeObject _PySandboxIteratorWrapper_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "_sandbox_iterator_wrapper",
    .tp_basicsize = sizeof(_PySandboxIteratorWrapper),
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .tp_dealloc = sandbox_iter_wrapper_dealloc,
    .tp_traverse = sandbox_iter_wrapper_traverse,
    .tp_clear = sandbox_iter_wrapper_clear,
    .tp_iter = PyObject_SelfIter,
    .tp_iternext = sandbox_iter_wrapper_iternext,
};
```

## Wrapper iternext

The core logic checks limits before delegating:

```c
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

## Wrap Function

Called from `PyObject_GetIter()` when in sandbox scope:

```c
PyObject *
_PySandbox_WrapIterator(PyObject *iter)
{
    if (iter == NULL) {
        return NULL;
    }

    /* Don't wrap if not in sandbox scope */
    if (!_PySandbox_IsInScope()) {
        return iter;  /* Return unwrapped (caller already holds ref) */
    }

    /* Avoid wrapping an already-wrapped iterator */
    if (Py_TYPE(iter) == &_PySandboxIteratorWrapper_Type) {
        return iter;
    }

    /* Create wrapper */
    _PySandboxIteratorWrapper *wrapper = PyObject_GC_New(
        _PySandboxIteratorWrapper, &_PySandboxIteratorWrapper_Type);
    if (wrapper == NULL) {
        Py_DECREF(iter);
        return NULL;
    }

    wrapper->wrapped = iter;  /* Steals reference */
    PyObject_GC_Track(wrapper);
    return (PyObject *)wrapper;
}
```

## Iteration Check Function

```c
int
_PySandbox_CheckIteration(void)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        return 0;
    }

    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        return 0;
    }

    _PySandboxState *sandbox = &interp->sandbox;
    _PySandboxConfig *config = &sandbox->config;
    _PySandboxCounters *counters = &sandbox->counters;

    if (sandbox->suppress_checks || sandbox->suspend_depth) {
        return 0;
    }

    /* Check if in scope */
    _PyInterpreterFrame *frame = tstate->cframe->current_frame;
    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return 0;
    }

    /* Increment iteration counter */
    counters->iteration_count++;

    /* Optionally count as operations too */
    if (limits->count_iterations_as_operations && limits->max_operations > 0) {
        counters->operation_count++;
        if (counters->operation_count == limits->max_operations + 1) {
            sandbox->suppress_checks = 1;
            PyErr_SetString(PyExc_SandboxRuntimeError,
                            "Sandbox operation limit exceeded");
            sandbox->suppress_checks = 0;
            return -1;
        }
    }

    /* Check iteration limit */
    if (limits->max_iterations > 0 &&
        counters->iteration_count == limits->max_iterations + 1) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxRuntimeError,
                        "Sandbox iteration limit exceeded");
        sandbox->suppress_checks = 0;
        return -1;
    }

    return 0;
}
```

## Lazy Type Initialization

The wrapper type is initialized lazily because `PyType_Ready()` requires a valid thread state:

```c
int
_PySandbox_InitWrapperType(void)
{
    if (_PySandboxIteratorWrapper_Type.tp_flags & Py_TPFLAGS_READY) {
        return 0;  /* Already initialized */
    }

    if (PyType_Ready(&_PySandboxIteratorWrapper_Type) < 0) {
        return -1;
    }

    return 0;
}
```

Called from `_PySandbox_WrapIterator()` on first use.

## C API

```c
/* Iterator wrapper type (exported for type checking) */
PyAPI_DATA(PyTypeObject) _PySandboxIteratorWrapper_Type;

/* Wrap an iterator if in sandbox scope */
PyAPI_FUNC(PyObject *) _PySandbox_WrapIterator(PyObject *iter);

/* Check iteration limit (called by wrapper's tp_iternext) */
PyAPI_FUNC(int) _PySandbox_CheckIteration(void);
```

## Integration Point

In `Objects/abstract.c`, `PyObject_GetIter()` is modified:

```c
PyObject *
PyObject_GetIter(PyObject *o)
{
    PyTypeObject *t = Py_TYPE(o);
    getiterfunc f;

    f = t->tp_iter;
    if (f == NULL) {
        /* ... error handling ... */
    }

    PyObject *res = (*f)(o);
    if (res != NULL && !PyIter_Check(res)) {
        /* ... error handling ... */
    }

    /* Wrap iterator if in sandbox scope */
    if (res != NULL) {
        res = _PySandbox_WrapIterator(res);
    }

    return res;
}
```

## Python API

### Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `max_iterations` | int | 0 | Max iterator yields (0 = no limit) |
| `iteration_count` | int (read-only) | 0 | Current iteration count |
| `count_iterations_as_operations` | bool | False | Also count iterations toward `operation_count` |

## Covered Call Sites

The iterator wrapper covers these and more:

| Builtin | How it uses iterators |
|---------|----------------------|
| `list()` | `PySequence_List()` → `tp_iternext` |
| `tuple()` | `PySequence_Tuple()` → `tp_iternext` |
| `set()` | `set_update_internal()` → `tp_iternext` |
| `dict()` | `dict_update_arg()` → `tp_iternext` |
| `sum()` | `builtin_sum()` → `tp_iternext` |
| `min()` | `builtin_min_max()` → `tp_iternext` |
| `max()` | `builtin_min_max()` → `tp_iternext` |
| `sorted()` | `list_sort_impl()` → `tp_iternext` |
| `''.join()` | `PyUnicode_Join()` → `tp_iternext` |
| `any()` | `builtin_any()` → `tp_iternext` |
| `all()` | `builtin_all()` → `tp_iternext` |
| `zip()` | `zip_next()` → `tp_iternext` |
| `map()` | `map_next()` → `tp_iternext` |
| `filter()` | `filter_next()` → `tp_iternext` |
| `enumerate()` | `enum_next()` → `tp_iternext` |
| `for` loops | `GET_ITER` + `FOR_ITER` |

## Exception Type

`SandboxRuntimeError` is raised when the iteration limit is exceeded:

```
SandboxRuntimeError: Sandbox iteration limit exceeded
```

# Drawbacks
[drawbacks]: #drawbacks

1. **Wrapper Overhead**: Each `__iter__()` call creates a wrapper object (one allocation).

2. **Type Checking Issues**: `type(wrapped_iter)` returns `_sandbox_iterator_wrapper`, not the original iterator type.

3. **Performance**: Additional function call per iteration step. Measured at ~5-10% overhead for tight loops.

4. **Generator Edge Cases**: Generators created outside scope but consumed inside scope may not be wrapped.

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why Wrap at `PyObject_GetIter()`?

**Alternative 1: Patch each builtin individually**
- Rejected: 26+ call sites to modify; error-prone; doesn't cover C extensions.

**Alternative 2: Wrap at `tp_iternext` dispatch**
- Rejected: No central dispatch point; would require modifying every type.

**Alternative 3: Use signals/timeouts**
- Rejected: Non-deterministic; can't guarantee limit before timeout.

**Chosen**: Single wrap point at `PyObject_GetIter()` covers all paths.

## Why Not Wrap Generators Specially?

Generators are iterators, so they're wrapped like any other iterator. No special handling needed.

## Why Single-Raise Behavior?

Same rationale as statement limits: allows exception handlers to use iteration without triggering additional errors.

# Prior art
[prior-art]: #prior-art

1. **Java Iterator Limits**: Some Java sandboxes limit iterator operations, but typically via bytecode instrumentation.

2. **JavaScript Proxy**: Could wrap iterators with Proxy, but no native support.

3. **Resource Governors**: Database query governors limit row iterations similarly.

# Unresolved questions
[unresolved-questions]: #unresolved-questions

1. Should `iter()` on a wrapper return the wrapper or a new wrapper?

2. Should there be a way to "unwrap" an iterator for trusted code?

3. Should generator send/throw also count as iterations?

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Iteration Cost Weights**: Different iterators cost different amounts (e.g., file iteration costs more).

2. **Yield Value Inspection**: Hook to inspect/replace yielded values.

3. **Async Iterator Support**: Wrap `__anext__` for async iterators.

4. **Iteration Profiling**: Track which iterators consume the most budget.
